"""FTMO 1-Step Free Trial paper-account ledger. No broker orders."""
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo
import math

PRAGUE = ZoneInfo('Europe/Prague')
INITIAL = 100000.0
TARGET = 5000.0
DAILY_ALLOWANCE = 3000.0
TOTAL_ALLOWANCE = 10000.0
BUFFER = 500.0
SOFT_DAILY_LOSS = 1500.0
RISK_USD = 250.0


def local_day(t):
    return t.astimezone(PRAGUE).date().isoformat()


def account_balance(state, baseline):
    return INITIAL + sum(float(a['balance'])-baseline for a in state['strategies'].values())


def floating(position, price, cost_rate):
    sign = 1 if position['side']=='LONG' else -1
    gross = sign*(price-position['entry_price'])*position['qty']
    costs = (position['notional']+position['qty']*price)*cost_rate
    return gross-costs


def equity(state, balance, price, cost_rate):
    return balance+sum(floating(a['position'], price, cost_rate)
                       for a in state['strategies'].values() if a.get('position'))


def advance(state, now, balance):
    g = state.setdefault('ftmo', {
        'day':local_day(now), 'day_start_balance':INITIAL,
        'eod_peak':INITIAL, 'daily_pnl':{}, 'breach':None,
        'simulation_started':now.isoformat(), 'peak_equity':INITIAL,
        'max_drawdown':0.0, 'last_equity':INITIAL})
    day = local_day(now)
    if day < g['day']:
        raise ValueError('Cannot process FTMO ledger backwards')
    if day != g['day']:
        # balance is the ledger immediately BEFORE processing this day's first bar.
        # With no trades during missing days, all intervening EOD balances are equal.
        g['eod_peak'] = max(g['eod_peak'], balance, INITIAL)
        g['day_start_balance'] = balance
        g['day'] = day
    return g


def record_close(state, now, pnl):
    day = local_day(now)
    g = state['ftmo']
    g['daily_pnl'][day] = float(g['daily_pnl'].get(day,0))+pnl


def snapshot(state, now, balance, eq, open_count):
    g = state['ftmo']
    if not all(math.isfinite(x) for x in (balance, eq)):
        raise ValueError('Invalid account balance/equity')
    g['last_equity'] = eq
    g['peak_equity'] = max(g['peak_equity'], eq)
    g['max_drawdown'] = min(g['max_drawdown'], eq/g['peak_equity']-1)
    daily_floor = g['day_start_balance']-DAILY_ALLOWANCE
    total_floor = g['eod_peak']-TOTAL_ALLOWANCE
    if eq <= daily_floor:
        g['breach'] = g['breach'] or 'MAX_DAILY_LOSS'
    if eq <= total_floor:
        g['breach'] = g['breach'] or 'MAX_TRAILING_LOSS'
    positive = [x for x in g['daily_pnl'].values() if x>0]
    positive_total = sum(positive)
    best = max(positive, default=0.0)
    best_share = best/positive_total if positive_total else None
    best_ok = best_share is not None and best_share <= .5+1e-12
    expired = now >= datetime.fromisoformat(g['simulation_started'])+timedelta(days=14)
    passed = balance >= INITIAL+TARGET and open_count==0 and best_ok and not g['breach'] and not expired
    reason = g['breach'] or ('SIMULATION_EXPIRED' if expired else ('OBJECTIVES_MET' if passed else None))
    if reason is None and eq <= g['day_start_balance']-SOFT_DAILY_LOSS:
        reason = 'SOFT_DAILY_STOP'
    if reason is None and eq <= max(daily_floor, total_floor)+BUFFER:
        reason = 'LOSS_BUFFER'
    return {'profile':'FTMO_100K_1STEP_FREE_TRIAL', 'execution':'PAPER_ONLY',
        'mt5_connected':False, 'balance':balance, 'equity':eq,
        'profit_target_usd':TARGET, 'profit_remaining_usd':max(0,INITIAL+TARGET-balance),
        'daily_loss_floor':daily_floor, 'trailing_loss_floor':total_floor,
        'best_day_share_pct':None if best_share is None else 100*best_share,
        'best_day_ok':best_ok, 'breach':g['breach'], 'objectives_met':passed,
        'new_entries_allowed':reason is None, 'entry_block_reason':reason,
        'risk_per_trade_usd':RISK_USD, 'max_open_positions':1,
        'day_timezone':'Europe/Prague', 'simulation_started':g['simulation_started'],
        'simulation_expires':(datetime.fromisoformat(g['simulation_started'])+timedelta(days=14)).isoformat(),
        'expiry_note':'Local paper simulation dates; actual FTMO trial expiry is not connected.'}


def permission(state, now, balance, eq, open_count, extra_cost):
    view = snapshot(state,now,balance,eq,open_count)
    if not view['new_entries_allowed']:
        return False, view['entry_block_reason']
    if open_count>=1:
        return False,'ACCOUNT_ALREADY_OPEN'
    if eq-(RISK_USD+extra_cost) <= max(view['daily_loss_floor'],view['trailing_loss_floor'])+BUFFER:
        return False,'INSUFFICIENT_LOSS_HEADROOM'
    return True,'FTMO_PAPER_RISK_OK'
