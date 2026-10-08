"""Read-only MT5 recovery probe: no order placement or account mutation."""
import os, json, time
from pathlib import Path
import MetaTrader5 as mt5

state=Path('Z:/data/ultima-probe.json')
VERSION='ultima-connect-3'

def record(status, **fields):
    payload={'version':VERSION,'status':status,'updated_at':time.time(),
             'live_orders_enabled':False,**fields}
    tmp=state.with_suffix('.tmp'); tmp.write_text(json.dumps(payload)); tmp.replace(state)
    print('Ultima probe:',status,'error_code=',fields.get('error_code'),flush=True)

def diagnostics():
    folder=Path(os.environ['MT5_PATH']).parent
    files=sorted((folder/'Logs').glob('*.log'),key=lambda p:p.stat().st_mtime)
    if not files: return
    raw=files[-1].read_bytes()
    encoding='utf-16' if raw.startswith((b'\xff\xfe',b'\xfe\xff')) else 'utf-16-le'
    lines=raw.decode(encoding,errors='replace').splitlines()[-30:]
    secrets=[os.getenv(k,'') for k in ('ULTIMA_PASSWORD','ULTIMA_LOGIN','MT5_PASSWORD','MT5_LOGIN')]
    for line in lines:
        if not any(k in line.lower() for k in ('terminal','network','python','error','failed','authorization')): continue
        for secret in secrets:
            if secret: line=line.replace(secret,'[REDACTED]')
        print('Ultima terminal diagnostic:',line[-600:],flush=True)

def probe():
    record('ATTACHING_TERMINAL')
    if not mt5.initialize(os.environ['MT5_PATH'],login=int(os.environ['ULTIMA_LOGIN']),password=os.environ['ULTIMA_PASSWORD'],server=os.environ['ULTIMA_SERVER'],timeout=120000,portable=True):
        record('IPC_FAILED',error_code=mt5.last_error()[0]); diagnostics(); return
    record('AUTHENTICATING_BROKER')
    if not mt5.login(int(os.environ['ULTIMA_LOGIN']),password=os.environ['ULTIMA_PASSWORD'],
                     server=os.environ['ULTIMA_SERVER'],timeout=120000):
        record('LOGIN_FAILED',error_code=mt5.last_error()[0]); diagnostics(); return
    account=mt5.account_info(); terminal=mt5.terminal_info()
    if account is None or account.login!=int(os.environ['ULTIMA_LOGIN']) or account.server!=os.environ['ULTIMA_SERVER']:
        record('ACCOUNT_MISMATCH'); return
    if terminal is None or not terminal.connected:
        record('BROKER_DISCONNECTED'); return
    gold=[]
    for s in (mt5.symbols_get() or []):
        if s.currency_base!='XAU' or s.currency_profit!='USD': continue
        selected=mt5.symbol_select(s.name,True)
        q=mt5.symbol_info_tick(s.name) if selected else None
        bars=mt5.copy_rates_from_pos(s.name,mt5.TIMEFRAME_M5,0,120) if selected else None
        gold.append({'name':s.name,'minimum_lot':s.volume_min,'lot_step':s.volume_step,
                     'contract_size':s.trade_contract_size,'tick_size':s.trade_tick_size,
                     'bid':q.bid if q else None,'ask':q.ask if q else None,
                     'tick_time':q.time if q else None,'m5_bars':len(bars) if bars is not None else 0})
    record('CONNECTED_READ_ONLY',currency=account.currency,balance=account.balance,
           equity=account.equity,account_type=account.trade_mode,
           terminal_build=mt5.version()[1],gold_symbols=gold)

def main():
    while True:
        try: probe()
        except Exception as exc: record('PROBE_FAILED',error_type=type(exc).__name__)
        finally: mt5.shutdown()
        time.sleep(60)

if __name__=='__main__': main()
