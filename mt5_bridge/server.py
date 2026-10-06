"""Broker-feed signal adapter. No passwords or order execution on Railway."""
import os, time, hmac, math, hashlib
import json
from pathlib import Path
import pandas as pd
from flask import Flask, request, jsonify
import bot

app = Flask(__name__)
app.config['MAX_CONTENT_LENGTH'] = 4 * 1024 * 1024
status = {'connected': False, 'last_seen': None}

def authorized():
    token = os.environ.get('BRIDGE_TOKEN', '')
    return len(token) >= 32 and hmac.compare_digest(request.headers.get('Authorization', ''), 'Bearer ' + token)

@app.get('/health')
def health():
    return {'service': 'MT5 bridge', 'status': 'ok', 'execution': 'worker', 'mt5_connected':bool(status['last_seen'] and time.time()-status['last_seen']<90)}

@app.get('/runtime/status')
def runtime_status():
    if not authorized(): return {'error':'unauthorized'},401
    path=Path(os.getenv('RUNTIME_STATE','/data/runtime-state.json'))
    try: runtime=json.loads(path.read_text())
    except (OSError,ValueError): runtime={'stage':'EXTERNAL_WORKER'}
    return {**runtime, 'mt5_connected':bool(status['last_seen'] and time.time()-status['last_seen']<90)}

@app.get('/bridge/status')
def bridge_status():
    if not authorized(): return {'error': 'unauthorized'}, 401
    return {**status, 'connected': bool(status['last_seen'] and time.time()-status['last_seen'] < 90)}

@app.post('/bridge/feed')
def feed():
    if not authorized(): return {'error': 'unauthorized'}, 401
    d = request.get_json()
    symbol = os.environ.get('MT5_SYMBOL', '')
    if symbol=='AUTO':
        import re
        received=d.get('symbol','')
        if not re.fullmatch(r'US500(?:\.cash)?',received,re.I): return {'error':'symbol mismatch'},409
        if status.get('symbol') and status['symbol']!=received: return {'error':'symbol changed'},409
        symbol=received
    if not symbol or d.get('symbol') != symbol: return {'error': 'symbol mismatch'}, 409
    rows = d.get('bars', [])
    if not 600 <= len(rows) <= 20000: return {'error': 'Need 600-20000 closed M5 bars'}, 400
    c = pd.DataFrame(rows)
    try:
        c = c[['timestamp', 'open', 'high', 'low', 'close', 'volume']].copy()
        c['timestamp'] = pd.to_datetime(c.timestamp, unit='s', utc=True)
        for k in ['open','high','low','close','volume']: c[k] = pd.to_numeric(c[k], errors='raise')
        if not all(math.isfinite(float(x)) for x in c[['open','high','low','close','volume']].to_numpy().flat): raise ValueError()
        if not c.timestamp.is_monotonic_increasing or c.timestamp.duplicated().any(): raise ValueError()
        if (c.low <= 0).any() or (c.high < c.low).any(): raise ValueError()
        age = time.time() - c.timestamp.iloc[-1].timestamp()
        if not 0 <= age <= 360: return {'signal': None, 'reason': 'STALE_OR_FUTURE_CANDLE'}
    except (ValueError, KeyError, TypeError): return {'error': 'Invalid candles'}, 400
    key = os.environ.get('BRIDGE_STRATEGY', 'TREND_PULLBACK')
    if key not in bot.STRATEGIES: return {'error': 'Invalid BRIDGE_STRATEGY'}, 500
    sig = bot.signal_for(key, c, bot.regime_snapshot(c))
    status.update(connected=True, last_seen=time.time(), symbol=symbol,
                  account=d.get('account', {}), mode=d.get('mode'), strategy=key)
    if not sig: return {'signal': None, 'reason': 'WARMUP_LOAD_MORE_HISTORY'}
    if not sig.get('signal') or not sig.get('allowed'): return {'signal': None, 'reason': sig.get('router_reason', sig.get('reason'))}
    stamp = c.timestamp.iloc[-1].timestamp()
    cid = hashlib.sha256(f'{symbol}:{key}:{stamp}'.encode()).hexdigest()[:24]
    return jsonify(id=cid, symbol=symbol, strategy=key, side=sig['signal'],
                   reference=float(sig['entry']), distance=float(sig['stop_distance']),
                   rr=float(bot.STRATEGIES[key]['rr']), candle_time=stamp, expires_at=stamp+120)

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=int(os.getenv('PORT','8080')), threaded=False)
