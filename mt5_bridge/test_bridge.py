import os, unittest, time
from types import SimpleNamespace
from unittest.mock import patch
os.environ['BRIDGE_TOKEN']='t'*48
os.environ['MT5_SYMBOL']='US500.test'
from mt5_bridge.worker import volume_for, validate_account, broker_timestamp_utc
from mt5_bridge.server import app
from mt5_bridge.markets import market_symbols
from mt5_bridge.worker import poll_symbol

class Tests(unittest.TestCase):
    def test_sp500_and_btc_use_30m_5m(self):
        client=app.test_client(); now=int(time.time())-10
        bars=[dict(timestamp=now-(599-i)*300,open=5000,high=5002,low=4998,close=5001,volume=100) for i in range(600)]
        with patch.dict(os.environ,{'MT5_SYMBOLS':'US500.cash,BTCUSD','BRIDGE_STRATEGY':'TREND_PULLBACK'}),patch('mt5_bridge.server.bot.signal_for',return_value=None) as signal,patch('mt5_bridge.server.bot.regime_snapshot',return_value={}):
            for symbol,expected in [('US500.cash',True),('BTCUSD',True)]:
                client.post('/bridge/feed',json={'symbol':symbol,'bars':bars},headers={'Authorization':'Bearer '+'t'*48})
                self.assertEqual(signal.call_args.kwargs['pullback_30m_5m'],expected)

    def test_fast_pullback_uses_closed_30m_and_5m(self):
        import pandas as pd
        import bot
        timestamps=pd.date_range(end='2026-10-07T13:25:00Z',periods=4000,freq='5min')
        bars=pd.DataFrame({'timestamp':timestamps,'open':5000.,'high':5002.,'low':4998.,'close':5001.,'volume':100.})
        with patch('bot.detect_trend_pullback',return_value=(None,'WAIT_HTF_PULLBACK_RESUMPTION',None,0)) as detector:
            result=bot.signal_for('TREND_PULLBACK',bars,{},pullback_30m_5m=True)
            confirmation=detector.call_args.args[1]; trend=detector.call_args.args[2]
            self.assertEqual(confirmation.index[-1],pd.Timestamp('2026-10-07T13:25:00Z'))
            self.assertEqual(trend.index[-1],pd.Timestamp('2026-10-07T13:00:00Z'))
            self.assertEqual(result['reason'],'WAIT_M30_M5_PULLBACK_RESUMPTION')

    def test_market_allowlist(self):
        self.assertEqual(market_symbols({'MT5_SYMBOLS':'US500.cash,BTCUSD'}),['US500.cash','BTCUSD'])
        self.assertEqual(market_symbols({'MT5_SYMBOL':'AUTO'}),['AUTO'])
        for value in ['BTCUSD,BTCUSD','US500.cash,ETHUSD','BTCUSD,','US500,US500.cash,BTCUSD']:
            with self.assertRaises(ValueError): market_symbols({'MT5_SYMBOLS':value})

    def test_interleaved_markets_have_distinct_signals_and_freshness(self):
        from mt5_bridge.server import status
        client=app.test_client(); now=int(time.time())-10
        bars=[dict(timestamp=now-(599-i)*300,open=100000,high=100002,low=99998,close=100001,volume=100) for i in range(600)]
        headers={'Authorization':'Bearer '+'t'*48}
        signal={'signal':'LONG','allowed':True,'entry':100001,'stop_distance':1000}
        with patch.dict(os.environ,{'MT5_SYMBOLS':'US500.cash,BTCUSD'}),patch('mt5_bridge.server.bot.signal_for',return_value=signal),patch('mt5_bridge.server.bot.regime_snapshot',return_value={}):
            us=client.post('/bridge/feed',json={'symbol':'US500.cash','bars':bars},headers=headers).json
            btc=client.post('/bridge/feed',json={'symbol':'BTCUSD','bars':bars},headers=headers).json
            again=client.post('/bridge/feed',json={'symbol':'US500.cash','bars':bars},headers=headers).json
            self.assertEqual(us['id'],again['id']); self.assertNotEqual(us['id'],btc['id'])
            self.assertEqual(client.post('/bridge/feed',json={'symbol':'ETHUSD','bars':bars},headers=headers).status_code,409)
            status['markets']['US500.cash']['last_seen']=time.time()-100
            result=client.get('/bridge/status',headers=headers).json
            self.assertFalse(result['markets']['US500.cash']['connected'])
            self.assertTrue(result['markets']['BTCUSD']['connected'])

    def test_malformed_feed_returns_400(self):
        c=app.test_client(); h={'Authorization':'Bearer '+'t'*48}
        self.assertEqual(c.post('/bridge/feed',json=[],headers=h).status_code,400)
        self.assertEqual(c.post('/bridge/feed',json={'symbol':'US500.test','bars':None},headers=h).status_code,400)

    def test_two_markets_share_exposure_and_uncertain_order_guard(self):
        import sqlite3
        from unittest.mock import Mock
        now=int(time.time()); positions=[]
        a=SimpleNamespace(login=123,server='Demo',currency='USD',trade_mode=0,trade_allowed=True,trade_expert=True,balance=100000,equity=100000,margin_free=100000)
        t=SimpleNamespace(connected=True,trade_allowed=True,tradeapi_disabled=False)
        info=SimpleNamespace(trade_tick_size=.01,digits=2,volume_step=.01,volume_min=.01,volume_max=10,filling_mode=1)
        rates=[dict(time=now-300-(599-i)*300,open=100000,high=100002,low=99998,close=100001,tick_volume=100) for i in range(600)]
        m=SimpleNamespace(ACCOUNT_TRADE_MODE_DEMO=0,TIMEFRAME_M5=5,ORDER_TYPE_BUY=0,ORDER_TYPE_SELL=1,ORDER_FILLING_FOK=0,ORDER_FILLING_IOC=1,TRADE_ACTION_DEAL=1,ORDER_TIME_GTC=0,TRADE_RETCODE_DONE=10009,TRADE_RETCODE_DONE_PARTIAL=10010,
            account_info=lambda:a,terminal_info=lambda:t,symbol_select=lambda *args:True,copy_rates_from_pos=lambda *args:rates,symbol_info_tick=lambda s:SimpleNamespace(time=now,ask=100000,bid=99999),positions_get=lambda:positions,orders_get=lambda:[],symbol_info=lambda s:info,order_calc_profit=lambda *args:-1000,order_calc_margin=lambda *args:100,order_check=lambda r:SimpleNamespace(retcode=0))
        def send(req):
            positions.append(req); return SimpleNamespace(retcode=10009)
        m.order_send=Mock(side_effect=send)
        def response(*args,**kwargs):
            symbol=kwargs['json']['symbol']
            return SimpleNamespace(raise_for_status=lambda:None,json=lambda:{'id':symbol,'symbol':symbol,'side':'LONG','reference':100000,'distance':100,'rr':2,'expires_at':time.time()+60})
        db=sqlite3.connect(':memory:'); db.execute('create table sends (id text primary key,state text)');db.execute('create table baselines (day text primary key,balance real)')
        import threading
        guard=SimpleNamespace(lock=threading.RLock(),check=lambda:{'new_entries_allowed':True,'protective_floor':99000},identity=lambda:(a,t))
        with patch('mt5_bridge.worker.requests.post',side_effect=response):
            for symbol in ['US500.cash','BTCUSD']: poll_symbol(m,symbol,123,'Demo','https://example.test',{},'DEMO','UTC',db,set(),guard)
            self.assertEqual(m.order_send.call_count,1)
            self.assertEqual(positions[0]['symbol'],'US500.cash')
            positions.clear(); db.execute("insert into sends values ('unknown','UNCERTAIN')");db.commit()
            with self.assertRaisesRegex(RuntimeError,'Uncertain prior order'):
                poll_symbol(m,'BTCUSD',123,'Demo','https://example.test',{},'DEMO','UTC',db,set(),guard)
            self.assertEqual(m.order_send.call_count,1)
    def test_ftmo_server_time_tracks_us_dst(self):
        from datetime import datetime, timezone
        for day,hours in [('2026-01-06',2),('2026-03-12',3),('2026-10-06',3),('2026-11-06',2)]:
            utc=int(datetime.fromisoformat(day+'T15:00:00').replace(tzinfo=timezone.utc).timestamp())
            self.assertEqual(broker_timestamp_utc(utc+hours*3600,'FTMO_SERVER'),utc)
            self.assertEqual(broker_timestamp_utc(utc,'UTC'),utc)
    def test_ftmo_ambiguous_and_missing_times_blocked(self):
        from datetime import datetime, timezone
        for text in ['2026-11-01T08:30:00','2026-03-08T09:30:00']:
            value=int(datetime.fromisoformat(text).replace(tzinfo=timezone.utc).timestamp())
            with self.assertRaises(ValueError): broker_timestamp_utc(value,'FTMO_SERVER')
    def test_ftmo_conversion_does_not_refresh_old_data(self):
        from datetime import datetime, timezone
        now=int(datetime(2026,10,6,15,tzinfo=timezone.utc).timestamp())
        converted=broker_timestamp_utc(now-3600+10800,'FTMO_SERVER')
        self.assertEqual(now-converted,3600)

    def test_real_or_other_account_blocked(self):
        a=SimpleNamespace(login=123,server='Demo',trade_mode=0,currency='USD')
        validate_account(a,123,'Demo',0)
        for changes in [{'trade_mode':2},{'login':456},{'server':'Other'},{'currency':'EUR'}]:
            b=SimpleNamespace(**{**vars(a),**changes})
            with self.assertRaises(RuntimeError): validate_account(b,123,'Demo',0)
    def test_feed_fresh_stale_and_stable_id(self):
        client=app.test_client(); now=int(time.time())-10
        bars=[dict(timestamp=now-(599-i)*300,open=5000,high=5002,low=4998,close=5001,volume=100) for i in range(600)]
        headers={'Authorization':'Bearer '+'t'*48}
        sig={'signal':'LONG','allowed':True,'entry':5001,'stop_distance':20}
        with patch('mt5_bridge.server.bot.signal_for',return_value=sig), patch('mt5_bridge.server.bot.regime_snapshot',return_value={}):
            one=client.post('/bridge/feed',json={'symbol':'US500.test','bars':bars},headers=headers).json
            two=client.post('/bridge/feed',json={'symbol':'US500.test','bars':bars},headers=headers).json
            self.assertEqual(one['id'],two['id'])
            self.assertEqual(one['distance'],20)
            for b in bars: b['timestamp']-=1000
            stale=client.post('/bridge/feed',json={'symbol':'US500.test','bars':bars},headers=headers).json
            self.assertEqual(stale['reason'],'STALE_OR_FUTURE_CANDLE')
    def test_size_never_rounds_up(self):
        for risk,loss,step in [(100,333,.01),(10,300,.1),(100,17,.01)]:
            self.assertLessEqual(volume_for(risk,loss,step)*loss,risk+1e-8)
    def test_invalid_size(self):
        for value in [0,-1,float('nan')]:
            with self.assertRaises(ValueError): volume_for(100,value,.01)
    def test_auth_and_symbol(self):
        c=app.test_client()
        self.assertEqual(c.post('/bridge/feed',json={}).status_code,401)
        self.assertEqual(c.post('/bridge/feed',json={'symbol':'SPY'},headers={'Authorization':'Bearer '+'t'*48}).status_code,409)
    def test_health_is_not_connection(self):
        from mt5_bridge.server import status
        status.update(last_seen=None)
        c=app.test_client()
        self.assertEqual(c.get('/health').status_code,200)
        self.assertFalse(c.get('/bridge/status',headers={'Authorization':'Bearer '+'t'*48}).json['connected'])

if __name__=='__main__': unittest.main()
