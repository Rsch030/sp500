"""FTMO 100k 1-Step demo guard. Rebuild midnight balances from broker deals.

Rules: https://ftmo.com/en/trading-objectives/ (checked 2026-10-07).
Only the authorized demo and bot-owned positions may be acted on. No guarantee
against gaps, disconnections, broker rejection or breaches before installation.
"""
import json
import math
import threading
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

PRAGUE = ZoneInfo('Europe/Prague')
INITIAL = 100000.0
MAGIC = 530006
BUFFER = 500.0


def day_of(stamp):
    return datetime.fromtimestamp(stamp, timezone.utc).astimezone(PRAGUE).date().isoformat()


def ledger(deals, balance, now, convert):
    if deals is None or not deals:
        raise ValueError('Complete broker history including initial funding required')
    rows = sorted(deals, key=lambda d: (d.time_msc, d.ticket))
    if len({d.ticket for d in rows}) != len(rows):
        raise ValueError('Duplicate history tickets')
    funding = rows[0]
    net = lambda d: sum(float(getattr(d, k, 0)) for k in ('profit', 'commission', 'swap', 'fee'))
    if funding.type != 2 or abs(net(funding)-INITIAL) > .005:
        raise ValueError('Initial USD 100000 funding not verified')
    cash_days = {}; closed_days = {}; entries = {}
    for d in rows:
        amount = net(d)
        stamp = convert(d.time)
        if not math.isfinite(amount) or stamp > now+5:
            raise ValueError('Invalid or future broker deal')
        day = day_of(stamp)
        if d.ticket == funding.ticket:
            continue
        if d.type not in (0, 1):
            if abs(amount) > .005:
                raise ValueError('Unsupported account adjustment: reconcile with FTMO')
            continue
        cash_days[day] = cash_days.get(day, 0)+amount
        # Attribute entry commission to the closing day, including partial closes.
        pid = d.position_id
        volume = float(d.volume)
        if volume <= 0:
            raise ValueError('Invalid deal volume')
        if d.entry == 0:
            v, cost = entries.get(pid, (0., 0.))
            entries[pid] = (v+volume, cost+amount)
        elif d.entry in (1, 3):
            v, cost = entries.get(pid, (0., 0.))
            if volume > v+1e-7 or v <= 0:
                raise ValueError('Missing opening deal for closed position')
            allocation = cost*volume/v
            closed_days[day] = closed_days.get(day, 0)+amount+allocation
            entries[pid] = (max(0., v-volume), cost-allocation)
        else:
            raise ValueError('Netting reversal requires ledger reconciliation')
    computed = INITIAL+sum(cash_days.values())
    if not math.isfinite(balance) or abs(computed-balance) > .02:
        raise ValueError('Broker history does not reconcile to current balance')
    today = day_of(now)
    midnight = INITIAL; peak = INITIAL
    for day, amount in sorted(cash_days.items()):
        if day < today:
            midnight += amount
            peak = max(peak, midnight)
    positives = [max(0., x) for x in closed_days.values()]
    total = sum(positives); best = max(positives, default=0.)
    return dict(day=today, midnight_balance=round(midnight, 2), eod_peak=round(peak, 2),
                daily_floor=round(midnight-3000, 2), trailing_floor=round(peak-10000, 2),
                best_day_profit=round(best, 2), positive_days_profit=round(total, 2),
                best_day_pct=round(100*best/total, 4) if total else None,
                best_day_ok=bool(total and best <= total*.5+.005),
                extra_positive_profit_needed=round(max(0., 2*best-total), 2),
                closed_daily_pnl={k:round(v, 2) for k,v in closed_days.items()})


class LockedTerminal:
    """Serialize the MT5 C API; release the lock during HTTP signal requests."""
    def __init__(self, api):
        self.api = api
        self.lock = threading.RLock()
    def __getattr__(self, name):
        value = getattr(self.api, name)
        if not callable(value):
            return value
        def call(*args, **kwargs):
            with self.lock:
                return value(*args, **kwargs)
        return call


class AccountGuard:
    def __init__(self, mt5, login, server, directory, convert, mode='DEMO'):
        self.mt5=mt5; self.login=login; self.server=server; self.convert=convert; self.mode=mode
        self.path=Path(directory)/'ftmo-risk.json'
        self.lock=mt5.lock; self.stop_event=threading.Event(); self.view=None
        self.last_log=None; self.last_write=0.; self.state={}
        if self.path.exists():
            try: self.state=json.loads(self.path.read_text())
            except (OSError, ValueError): raise RuntimeError('Unreadable persistent FTMO guard state')
            if self.state.get('login') != login or self.state.get('server') != server:
                raise RuntimeError('FTMO guard state belongs to another account')

    def identity(self):
        a=self.mt5.account_info(); t=self.mt5.terminal_info()
        if not a or not t or not t.connected:
            raise RuntimeError('MT5 disconnected')
        if a.login!=self.login or a.server!=self.server or a.trade_mode!=self.mt5.ACCOUNT_TRADE_MODE_DEMO or a.currency!='USD':
            raise RuntimeError('FTMO guard account identity blocked')
        if not all(math.isfinite(float(x)) for x in (a.balance,a.equity)) or getattr(a,'credit',0):
            raise RuntimeError('Invalid account equity or unsupported credit')
        return a,t

    def save(self, view, force=False):
        view.update(login=self.login,server=self.server,profile='FTMO_100K_1STEP_FREE_TRIAL',updated_at=time.time(),
                    historical_intraday_breaches_verified=False)
        changed = any(self.state.get(k)!=view.get(k) for k in ('breach','stop_day','eod_peak','day','objectives_met','reason'))
        if force or changed or time.monotonic()-self.last_write >= 10:
            tmp=self.path.with_suffix('.tmp')
            tmp.write_text(json.dumps(view,allow_nan=False)); tmp.replace(self.path)
            self.state=dict(view); self.last_write=time.monotonic()
        self.view=view
        summary={k:view.get(k) for k in ('day','midnight_balance','daily_floor','trailing_floor','protective_floor','best_day_pct','new_entries_allowed','reason')}
        if summary != self.last_log:
            print('FTMO GUARD:',json.dumps(summary),flush=True); self.last_log=summary

    def check(self, liquidate=True):
        with self.lock:
            try:
                a,t=self.identity()
                now=time.time()
                deals=self.mt5.history_deals_get(datetime(2000,1,1,tzinfo=timezone.utc),datetime.now(timezone.utc)+timedelta(days=1))
                # Read balance again after history to catch a concurrent broker fill.
                a,t=self.identity()
                v=ledger(deals,float(a.balance),now,self.convert)
                v['eod_peak']=max(v['eod_peak'],float(self.state.get('eod_peak',INITIAL)))
                v['trailing_floor']=v['eod_peak']-10000
                positions=self.mt5.positions_get(); orders=self.mt5.orders_get()
                if positions is None or orders is None: raise RuntimeError('Account exposure unavailable')
                foreign=any(p.magic!=MAGIC for p in (*positions,*orders))
                breach=self.state.get('breach')
                if a.equity <= v['daily_floor']: breach=breach or 'MAX_DAILY_LOSS'
                if a.equity <= v['trailing_floor']: breach=breach or 'MAX_TRAILING_LOSS'
                # Preserve the earlier tighter $1000 daily / $95000 absolute guard.
                floor=max(v['daily_floor']+BUFFER,v['trailing_floor']+BUFFER,v['midnight_balance']-1000,95000.)
                stop_day=self.state.get('stop_day')
                if a.equity <= floor: stop_day=v['day']
                reason=breach or ('DAILY_PROTECTIVE_STOP' if stop_day==v['day'] else None)
                objective=a.balance>=105000 and not positions and not orders and v['best_day_ok'] and not breach
                if not reason and objective: reason='FREE_TRIAL_OBJECTIVES_MET'
                if not reason and foreign: reason='EXTERNAL_EXPOSURE'
                ready=bool(t.trade_allowed and not t.tradeapi_disabled and a.trade_allowed and a.trade_expert)
                if not reason and not ready: reason='TRADING_DISABLED'
                v.update(balance=a.balance,equity=a.equity,protective_floor=floor,breach=breach,stop_day=stop_day,
                         objectives_met=objective,profit_target=5000,open_positions=len(positions),pending_orders=len(orders),
                         new_entries_allowed=not reason,reason=reason or 'READY',history_reconciled=True)
                self.save(v)
                if liquidate and (breach or stop_day==v['day']) and self.mode=='DEMO':
                    if not ready: raise RuntimeError('Protective close required but trading disabled')
                    self.close_owned(positions,orders)
                return v
            except Exception as exc:
                self.view=None
                try:
                    self.save({**self.state,'history_reconciled':False,'new_entries_allowed':False,
                               'reason':'GUARD_UNAVAILABLE','error':str(exc)})
                except OSError: pass
                print('FTMO GUARD BLOCKED:',type(exc).__name__,str(exc),flush=True)
                raise

    def close_owned(self, positions, orders):
        m=self.mt5
        for order in orders:
            if order.magic==MAGIC:
                self.identity()
                result=m.order_send({'action':m.TRADE_ACTION_REMOVE,'order':order.ticket})
                print('FTMO GUARD cancel:',order.ticket,getattr(result,'retcode','UNCERTAIN'),flush=True)
        for pos in positions:
            if pos.magic!=MAGIC: continue
            self.identity()
            # Re-read before each ticket-specific close, including retries/partial fills.
            current=m.positions_get(ticket=pos.ticket)
            if current is None: raise RuntimeError('Cannot reconcile close ticket')
            if not current: continue
            pos=current[0]
            if pos.magic!=MAGIC: continue
            info=m.symbol_info(pos.symbol); tick=m.symbol_info_tick(pos.symbol)
            if not info or not tick or not 0 <= time.time()-self.convert(tick.time) <= 30:
                raise RuntimeError('No fresh quote for protective close')
            filling=m.ORDER_FILLING_FOK if info.filling_mode&1 else m.ORDER_FILLING_IOC if info.filling_mode&2 else None
            if filling is None: raise RuntimeError('Unsupported close filling mode')
            buy=pos.type==m.ORDER_TYPE_BUY
            result=m.order_send({'action':m.TRADE_ACTION_DEAL,'position':pos.ticket,'symbol':pos.symbol,
                                 'volume':pos.volume,'type':m.ORDER_TYPE_SELL if buy else m.ORDER_TYPE_BUY,
                                 'price':tick.bid if buy else tick.ask,'deviation':20,'magic':MAGIC,
                                 'comment':'FTMO protective close','type_time':m.ORDER_TIME_GTC,'type_filling':filling})
            print('FTMO GUARD close:',pos.ticket,getattr(result,'retcode','UNCERTAIN'),flush=True)

    def run(self):
        while not self.stop_event.is_set():
            try: self.check()
            except Exception: pass # Entry checks fail closed; retry broker visibility next second.
            self.stop_event.wait(1)

    def start(self):
        thread=threading.Thread(target=self.run,name='ftmo-equity-guard',daemon=True)
        thread.start(); return thread
