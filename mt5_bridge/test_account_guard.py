import tempfile
import time
import unittest
from datetime import datetime, timezone
from types import SimpleNamespace as N
from unittest.mock import Mock
from mt5_bridge.account_guard import ledger, AccountGuard, LockedTerminal, MAGIC, day_of


def stamp(s): return datetime.fromisoformat(s).replace(tzinfo=timezone.utc).timestamp()
def deal(ticket, when, profit=0, entry=1, volume=1, pid=10, typ=0, commission=0, swap=0, fee=0):
    t=stamp(when)
    return N(ticket=ticket,time=t,time_msc=int(t*1000),profit=profit,entry=entry,volume=volume,position_id=pid,type=typ,commission=commission,swap=swap,fee=fee)
def funding(): return deal(1,'2026-10-04T12:00:00',100000,typ=2)
def trade(n, day, profit):
    return [deal(n,day+'T12:00:00',entry=0,pid=n),deal(n+1,day+'T13:00:00',profit,pid=n)]

class LedgerTests(unittest.TestCase):
    def test_midnight_and_trailing_rebuilt_after_restart(self):
        ds=[funding()]+trade(2,'2026-10-04',4000)+trade(4,'2026-10-05',-1000)+trade(6,'2026-10-06',500)
        v=ledger(ds,103500,stamp('2026-10-06T16:00:00'),lambda x:x)
        self.assertEqual(v['midnight_balance'],103000)
        self.assertEqual(v['daily_floor'],100000)
        self.assertEqual(v['eod_peak'],104000)
        self.assertEqual(v['trailing_floor'],94000)
        self.assertFalse(v['best_day_ok'])
        self.assertEqual(v['extra_positive_profit_needed'],3500)
    def test_best_day_exact_half_is_allowed_and_losing_days_excluded(self):
        ds=[funding()]+trade(2,'2026-10-04',2000)+trade(4,'2026-10-05',-500)+trade(6,'2026-10-06',2000)
        v=ledger(ds,103500,stamp('2026-10-07T12:00:00'),lambda x:x)
        self.assertEqual(v['best_day_pct'],50)
        self.assertTrue(v['best_day_ok'])
    def test_prague_midnight_not_utc_midnight(self):
        ds=[funding(),deal(2,'2026-10-06T21:00:00',entry=0),deal(3,'2026-10-06T22:00:00',100)]
        v=ledger(ds,100100,stamp('2026-10-06T22:01:00'),lambda x:x)
        self.assertEqual(v['day'],'2026-10-07')
        self.assertEqual(v['midnight_balance'],100000)
    def test_dst_day_boundaries(self):
        self.assertEqual(day_of(stamp('2026-10-24T22:00:00')),'2026-10-25')
        self.assertEqual(day_of(stamp('2026-10-25T22:30:00')),'2026-10-25')
        self.assertEqual(day_of(stamp('2026-10-25T23:00:00')),'2026-10-26')
    def test_partial_closes_allocate_entry_cost_on_close_day(self):
        ds=[funding(),deal(2,'2026-10-04T13:00:00',entry=0,volume=2,commission=-10),
            deal(3,'2026-10-05T12:00:00',100,commission=-2,swap=-3,fee=-1),
            deal(4,'2026-10-06T12:00:00',50,commission=-2)]
        v=ledger(ds,100132,stamp('2026-10-07T12:00:00'),lambda x:x)
        self.assertEqual(v['closed_daily_pnl'],{'2026-10-05':89,'2026-10-06':43})
        self.assertEqual(v['midnight_balance'],100132)
    def test_missing_or_mismatched_history_fails_closed(self):
        for ds,balance in [(None,100000),([],100000),([funding()],100001),([funding(),funding()],100000),([funding(),deal(3,'2026-10-06T12:00:00',10)],100010)]:
            with self.assertRaises(ValueError): ledger(ds,balance,stamp('2026-10-07T12:00:00'),lambda x:x)
    def test_unverified_funding_or_deposit_blocked(self):
        for ds in [[deal(1,'2026-10-04T12:00:00',50000,typ=2)],[funding(),deal(2,'2026-10-06T12:00:00',100,typ=2)]]:
            with self.assertRaises(ValueError):ledger(ds,100000,stamp('2026-10-07T12:00:00'),lambda x:x)

class RuntimeTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.a=N(login=123,server='FTMO-Demo',trade_mode=0,currency='USD',balance=100000.,equity=100000.,trade_allowed=True,trade_expert=True)
        self.t=N(connected=True,trade_allowed=True,tradeapi_disabled=False)
        self.positions=[];self.orders=[]
        self.api=N(ACCOUNT_TRADE_MODE_DEMO=0,ORDER_TYPE_BUY=0,ORDER_TYPE_SELL=1,ORDER_FILLING_FOK=0,ORDER_FILLING_IOC=1,TRADE_ACTION_DEAL=1,TRADE_ACTION_REMOVE=8,ORDER_TIME_GTC=0,
            account_info=lambda:self.a,terminal_info=lambda:self.t,history_deals_get=lambda *args:[funding()],
            positions_get=lambda **kw:[p for p in self.positions if not kw or p.ticket==kw['ticket']],orders_get=lambda:self.orders,
            symbol_info=lambda s:N(filling_mode=1),symbol_info_tick=lambda s:N(time=time.time(),bid=60000,ask=60001))
        def send(req):
            if 'position' in req: self.positions[:]=[p for p in self.positions if p.ticket!=req['position']]
            if 'order' in req: self.orders[:]=[o for o in self.orders if o.ticket!=req['order']]
            return N(retcode=10009)
        self.api.order_send=Mock(side_effect=send)
        self.m=LockedTerminal(self.api)
        self.g=AccountGuard(self.m,123,'FTMO-Demo',self.temp.name,lambda x:x)
    def tearDown(self): self.temp.cleanup()
    def position(self,magic=MAGIC): return N(ticket=42,symbol='BTCUSD',magic=magic,volume=.1,type=0)
    def test_guard_closes_without_signal_and_daily_stop_survives_restart(self):
        self.positions.append(self.position());self.a.equity=98999
        v=self.g.check()
        self.assertFalse(v['new_entries_allowed']);self.assertEqual(self.api.order_send.call_count,1)
        self.assertEqual(self.api.order_send.call_args.args[0]['position'],42)
        self.a.equity=100000
        restored=AccountGuard(self.m,123,'FTMO-Demo',self.temp.name,lambda x:x)
        self.assertFalse(restored.check()['new_entries_allowed'])
    def test_breach_latches_and_pending_orders_cancel(self):
        self.orders.append(N(ticket=88,magic=MAGIC));self.a.equity=96999
        v=self.g.check();self.assertEqual(v['breach'],'MAX_DAILY_LOSS')
        self.a.equity=100000
        self.assertEqual(AccountGuard(self.m,123,'FTMO-Demo',self.temp.name,lambda x:x).check()['breach'],'MAX_DAILY_LOSS')
        self.assertFalse(self.orders)
    def test_foreign_account_never_traded(self):
        self.positions.append(self.position());self.a.login=456;self.a.equity=90000
        with self.assertRaises(RuntimeError):self.g.check()
        self.api.order_send.assert_not_called()
    def test_manual_position_not_closed(self):
        self.positions.append(self.position(0));self.a.equity=98000
        self.assertFalse(self.g.check()['new_entries_allowed'])
        self.api.order_send.assert_not_called()
    def test_history_error_blocks_entries(self):
        self.api.history_deals_get=lambda *args:None
        with self.assertRaises(ValueError):self.g.check()
        self.assertFalse(self.g.view['new_entries_allowed'])
    def test_best_day_does_not_block_first_profitable_day(self):
        self.api.history_deals_get=lambda *args:[funding()]+trade(2,'2026-10-05',100)
        self.a.balance=100100;self.a.equity=100100
        v=self.g.check();self.assertFalse(v['best_day_ok']);self.assertTrue(v['new_entries_allowed'])
    def test_partial_close_rechecks_ticket_before_retry(self):
        p=self.position();self.positions.append(p);self.a.equity=98000
        self.api.order_send.side_effect=lambda req:(setattr(p,'volume',p.volume/2) or N(retcode=10010))
        self.g.check();self.g.check()
        self.assertEqual(self.api.order_send.call_args.args[0]['volume'],.05)
        self.assertTrue(all(c.args[0]['position']==42 for c in self.api.order_send.call_args_list))

if __name__=='__main__':unittest.main()
