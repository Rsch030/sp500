"""Windows-only polling bridge. Demo-only, dry-run by default, at-most-once send."""
import os, time, sqlite3, math
from mt5_bridge.account_guard import AccountGuard, LockedTerminal
from datetime import datetime, timezone
from zoneinfo import ZoneInfo
from pathlib import Path
from mt5_bridge.markets import market_symbols
import requests
from dotenv import load_dotenv
load_dotenv(Path(__file__).with_name('.env'))

def broker_timestamp_utc(value, time_format='UTC'):
    """FTMO server time follows GMT+2 plus US DST; reject ambiguous transitions."""
    value=int(value)
    if time_format=='UTC': return value
    if time_format!='FTMO_SERVER': raise ValueError('Unsupported MT5_TIME_FORMAT')
    candidates=[]
    for hours in (2,3):
        utc=value-hours*3600
        dst=datetime.fromtimestamp(utc,timezone.utc).astimezone(ZoneInfo('America/New_York')).dst()
        if hours==2+int(bool(dst and dst.total_seconds())): candidates.append(utc)
    if len(candidates)!=1: raise ValueError('Ambiguous or nonexistent FTMO server timestamp')
    return candidates[0]

def volume_for(risk, loss_one_lot, step):
    if not all(math.isfinite(x) and x > 0 for x in [risk,loss_one_lot,step]): raise ValueError('Invalid sizing')
    return round(math.floor((risk/loss_one_lot)/step + 1e-10)*step, 8)

def validate_account(a, login, server, demo_mode):
    if a.login!=login or a.server!=server or a.trade_mode!=demo_mode:
        raise RuntimeError('Account identity/type blocked: demo only')
    if a.currency!='USD': raise RuntimeError('This profile requires USD account')

def poll_symbol(mt5, symbol, login, server, url, headers, mode, time_format, db, logged_symbols, guard=None):
    # Recheck account for each market; both markets share one journal/exposure cap.
    a=mt5.account_info(); t=mt5.terminal_info()
    if not a or not t or not t.connected: raise RuntimeError('MT5 disconnected')
    validate_account(a,login,server,mt5.ACCOUNT_TRADE_MODE_DEMO)
    if mode=='DEMO' and not (a.trade_allowed and a.trade_expert and t.trade_allowed and not t.tradeapi_disabled):
        raise RuntimeError('MT5 algo/Python trading disabled')
    if not mt5.symbol_select(symbol, True): raise RuntimeError('Unknown broker symbol')
    rates=mt5.copy_rates_from_pos(symbol, mt5.TIMEFRAME_M5, 1, 12000)
    if rates is None or len(rates)<600: raise RuntimeError('Load more M5 history in MT5')
    if symbol not in logged_symbols:
        tick=mt5.symbol_info_tick(symbol)
        print('MT5 connected:',a.login,a.server,symbol,'closed_bar_age_seconds=',round(time.time()-int(rates[-1]['time'])-300),'tick_age_seconds=',round(time.time()-tick.time) if tick else None,'time_format=',time_format,'utc_bar_age_seconds=',round(time.time()-broker_timestamp_utc(rates[-1]['time'],time_format)-300),flush=True)
        logged_symbols.add(symbol)
    bars=[{'timestamp':broker_timestamp_utc(r['time'],time_format)+300, **{k:float(r[k]) for k in ['open','high','low','close']}, 'volume':float(r['tick_volume'])} for r in rates]
    account={'login':a.login,'server':a.server,'balance':a.balance,'equity':a.equity,'currency':a.currency,'demo':True}
    resp=requests.post(url+'/bridge/feed',headers=headers,json={'symbol':symbol,'bars':bars,'account':account,'mode':mode},timeout=45)
    resp.raise_for_status(); sig=resp.json()
    print(datetime.now().isoformat(timespec='seconds'),mode,symbol,sig.get('reason',sig.get('side','WAIT')),flush=True)
    if sig.get('id') and (sig.get('symbol')!=symbol or sig.get('side') not in ('LONG','SHORT')): raise RuntimeError('Signal identity blocked')
    if mode=='DEMO' and sig.get('id') and time.time()<=sig['expires_at']:
        if guard is None: raise RuntimeError('FTMO guard required for entries')
        with guard.lock:
            execute_signal(mt5,symbol,sig,db,guard,time_format)

def execute_signal(mt5,symbol,sig,db,guard,time_format):
    if db.execute('select 1 from sends where id=?',(sig['id'],)).fetchone(): return
    if db.execute("select 1 from sends where state='UNCERTAIN'").fetchone(): raise RuntimeError('Uncertain prior order: inspect journal and broker history before continuing')
    limits=guard.check()
    if not limits['new_entries_allowed']: return
    a,t=guard.identity()
    if time.time()>sig['expires_at']: return
    positions=mt5.positions_get(); orders=mt5.orders_get()
    if positions is None or orders is None: raise RuntimeError('Could not inspect account exposure')
    if positions or orders: return
    if not a.trade_allowed or not a.trade_expert or not t.trade_allowed or t.tradeapi_disabled: raise RuntimeError('MT5 algo/Python trading disabled')
    info=mt5.symbol_info(symbol); tick=mt5.symbol_info_tick(symbol)
    if not info or not tick or not 0<=time.time()-broker_timestamp_utc(tick.time,time_format)<=30: return
    buy=sig['side']=='LONG'; typ=mt5.ORDER_TYPE_BUY if buy else mt5.ORDER_TYPE_SELL
    price=tick.ask if buy else tick.bid; dist=float(sig['distance']); rr=float(sig['rr'])
    if not all(math.isfinite(x) and x>0 for x in [price,dist,rr,float(sig['reference'])]): return
    if abs(price-sig['reference'])>dist*.25 or tick.ask-tick.bid>dist*.15: return
    step=info.trade_tick_size
    if step<=0: return
    sl=round(round((price-dist if buy else price+dist)/step)*step,info.digits)
    tp=round(round((price+dist*rr if buy else price-dist*rr)/step)*step,info.digits)
    if (buy and not sl<tick.bid<price<tp) or (not buy and not tp<price<tick.ask<sl): return
    loss=mt5.order_calc_profit(typ,symbol,1.0,price,sl)
    if loss is None or loss>=0: return
    risk=min(100.0,a.equity*.001,a.equity-limits['protective_floor']-100)
    if risk<=0: return
    vol=volume_for(risk,abs(loss),info.volume_step)
    if not info.volume_min<=vol<=info.volume_max: return
    margin=mt5.order_calc_margin(typ,symbol,vol,price)
    if margin is None or margin>a.margin_free*.8: return
    filling=mt5.ORDER_FILLING_FOK if info.filling_mode & 1 else mt5.ORDER_FILLING_IOC if info.filling_mode & 2 else None
    if filling is None: return
    req={'action':mt5.TRADE_ACTION_DEAL,'symbol':symbol,'volume':vol,'type':typ,'price':price,'sl':sl,'tp':tp,'deviation':10,'magic':530006,'comment':'bridge-'+sig['id'][:12],'type_time':mt5.ORDER_TIME_GTC,'type_filling':filling}
    check=mt5.order_check(req)
    if check is None or check.retcode!=0: return
    # Persist before send. A crash/timeout is never retried automatically.
    db.execute('insert into sends values (?,?)',(sig['id'],'UNCERTAIN'));db.commit()
    result=mt5.order_send(req)
    if result is not None and result.retcode in (mt5.TRADE_RETCODE_DONE,mt5.TRADE_RETCODE_DONE_PARTIAL):
        db.execute('update sends set state=? where id=?',('SENT',sig['id']));db.commit()
    print('Order result:',symbol,result.retcode if result else 'UNCERTAIN',flush=True)

def main():
    import MetaTrader5 as mt5_api
    mt5=LockedTerminal(mt5_api)
    import msvcrt
    state_dir=Path(os.getenv('MT5_STATE_DIR',str(Path(__file__).parent)))
    state_dir.mkdir(parents=True,exist_ok=True)
    lock=open(state_dir/'worker.lock', 'a+b')
    lock.seek(0); lock.write(b'1'); lock.flush(); lock.seek(0)
    try: msvcrt.locking(lock.fileno(), msvcrt.LK_NBLCK, 1)
    except OSError: raise RuntimeError('Another bridge worker is already running')
    url=os.environ['BRIDGE_URL'].rstrip('/')
    if not url.startswith('https://'): raise RuntimeError('HTTPS required')
    mode=os.getenv('BRIDGE_MODE','DRY_RUN')
    if mode not in ('DRY_RUN','DEMO'): raise RuntimeError('Only DRY_RUN or DEMO allowed')
    time_format=os.getenv('MT5_TIME_FORMAT','UTC')
    if time_format not in ('UTC','FTMO_SERVER'): raise RuntimeError('Unsupported MT5_TIME_FORMAT')
    login=int(os.environ['MT5_LOGIN']); server=os.environ['MT5_SERVER']; symbols=market_symbols(os.environ)
    path=os.environ['MT5_PATH']; token=os.environ['BRIDGE_TOKEN']
    if len(token)<32: raise RuntimeError('Token must be >=32 characters')
    db=sqlite3.connect(state_dir/'journal.sqlite')
    db.execute('create table if not exists sends (id text primary key, state text)')
    db.execute('create table if not exists baselines (day text primary key, balance real)')
    headers={'Authorization':'Bearer '+token}
    print('Starting', mode, 'demo accounts only', flush=True)
    guard=AccountGuard(mt5,login,server,state_dir,lambda stamp:broker_timestamp_utc(stamp,time_format),mode)
    guard_thread=None
    logged_connection=False
    logged_symbols=set()
    while True:
        try:
            terminal=mt5.terminal_info()
            if (not terminal or not terminal.connected) and not mt5.initialize(path, login=login, password=os.environ['MT5_PASSWORD'], server=server, timeout=60000, portable=os.getenv('MT5_PORTABLE','0')=='1'):
                try:
                    files=sorted((Path(path).parent/'Logs').glob('*.log'),key=lambda p:p.stat().st_mtime)
                    if files:
                        raw=files[-1].read_bytes()
                        text=raw.decode('utf-16' if raw.startswith(b'\xff\xfe') else 'utf-16-le',errors='replace')
                        for line in text.splitlines()[-25:]:
                            if any(k in line.lower() for k in ('terminal','error','failed','python')):
                                for secret in (os.environ['MT5_PASSWORD'],token): line=line.replace(secret,'[REDACTED]')
                                print('MT5 diagnostic:',line[-600:],flush=True)
                except OSError: pass
                raise RuntimeError('MT5 initialize failed; code='+str(mt5.last_error()[0]))
            a=mt5.account_info(); t=mt5.terminal_info()
            if not a or not t or not t.connected: raise RuntimeError('MT5 disconnected')
            validate_account(a, login, server, mt5.ACCOUNT_TRADE_MODE_DEMO)
            trading_ready=bool(a.trade_allowed and a.trade_expert and t.trade_allowed and not t.tradeapi_disabled)
            if not logged_connection:
                print('MT5 trading permissions:', 'account=',a.trade_allowed,'experts=',a.trade_expert,'terminal=',t.trade_allowed,'python_api_disabled=',t.tradeapi_disabled,'mode=',mode,flush=True)
            if mode=='DEMO' and not trading_ready: raise RuntimeError('MT5 algo/Python trading disabled')
            if guard_thread is None: guard_thread=guard.start()
            if 'AUTO' in symbols:
                import re
                matches=[x.name for x in (mt5.symbols_get() or []) if re.fullmatch(r'US500(?:\.cash)?',x.name,re.I)]
                if len(matches)!=1: raise RuntimeError('US500 symbol is not unique')
                symbols=[matches[0] if x=='AUTO' else x for x in symbols]
            logged_connection=True
            for symbol in symbols:
                try:
                    poll_symbol(mt5,symbol,login,server,url,headers,mode,time_format,db,logged_symbols,guard)
                except Exception as exc:
                    print('BLOCKED:',symbol,type(exc).__name__,str(exc),flush=True)
        except KeyboardInterrupt: break
        except Exception as e: print('BLOCKED:',type(e).__name__,str(e),flush=True)
        finally: time.sleep(30)
    guard.stop_event.set()
    if guard_thread: guard_thread.join(timeout=5)
    mt5.shutdown()

if __name__=='__main__': main()
