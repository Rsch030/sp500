import os, unittest, time
from types import SimpleNamespace
from unittest.mock import patch
os.environ['BRIDGE_TOKEN']='t'*48
os.environ['MT5_SYMBOL']='US500.test'
from mt5_bridge.worker import volume_for, validate_account, broker_timestamp_utc
from mt5_bridge.server import app

class Tests(unittest.TestCase):
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
