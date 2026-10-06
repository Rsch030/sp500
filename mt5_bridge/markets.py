"""Explicit market allowlist shared by signal server and Windows worker."""
def market_symbols(env):
    configured=env.get('MT5_SYMBOLS','').strip()
    if configured:
        symbols=[s.strip() for s in configured.split(',')]
        if not symbols or len(symbols)>2 or len(set(symbols))!=len(symbols):
            raise ValueError('Configure one or two unique FTMO markets')
        if any(s not in ('US500.cash','US500','BTCUSD') for s in symbols):
            raise ValueError('Only verified US500 and BTCUSD markets are supported')
        return symbols
    symbol=env.get('MT5_SYMBOL','').strip()
    if not symbol: raise ValueError('MT5_SYMBOL or MT5_SYMBOLS required')
    return [symbol]
