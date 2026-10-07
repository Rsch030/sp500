"""Read-only MT5 connectivity probe. Contains no order placement functions."""
import os, json, time
from pathlib import Path
import MetaTrader5 as mt5
state=Path('Z:/data/ultima-probe.json')
def record(status, **fields):
    payload={'status':status,'updated_at':time.time(),'live_orders_enabled':False,**fields}
    tmp=state.with_suffix('.tmp'); tmp.write_text(json.dumps(payload)); tmp.replace(state)
    print('Ultima probe:',status,flush=True)
while True:
    if not mt5.initialize(os.environ['MT5_PATH'],login=int(os.environ['ULTIMA_LOGIN']),password=os.environ['ULTIMA_PASSWORD'],server=os.environ['ULTIMA_SERVER'],portable=True):
        record('CONNECTION_FAILED',error_code=mt5.last_error()[0]); mt5.shutdown(); time.sleep(30); continue
    account=mt5.account_info()
    if account is None or account.login!=int(os.environ['ULTIMA_LOGIN']) or account.server!=os.environ['ULTIMA_SERVER']:
        record('ACCOUNT_MISMATCH'); mt5.shutdown(); time.sleep(30); continue
    symbols=mt5.symbols_get() or []
    gold=[{'name':s.name,'minimum_lot':s.volume_min,'lot_step':s.volume_step,'contract_size':s.trade_contract_size} for s in symbols if s.currency_base=='XAU' and s.currency_profit=='USD']
    record('CONNECTED_READ_ONLY',currency=account.currency,gold_symbols=gold)
    mt5.shutdown(); time.sleep(60)
