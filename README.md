# S&P 500 Research Bot V1.0

Paper research engine with six independent strategy accounts, adapted from BTC V1.7.5.

Strategies: liquidity sweep/reversal, EMA trend pullback, momentum, breakout/retest, higher-timeframe trend continuation, and mean reversion.

## Railway

Run `python bot.py`. Railway installs requirements automatically. Dashboard: `/`; status: `/api/status`; process health: `/health`. Health reports process availability; consult `market_data.ready` and `market_data.last_candle` for data availability/freshness.

Attach a Railway volume at `/data` to retain strategy balances and CSV logs across redeployments. Without a volume, results can be lost.

## Configuration

`SYMBOL=SPY` (default), `RUN_MODE=RESEARCH`, `POLL_SECONDS=300`, `BOOTSTRAP_DAYS=59`, `START_BALANCE=500`, `DATA_DIR=/data`. Cost assumptions remain configurable via `TAKER_FEE` and `SLIPPAGE_BPS` and are research assumptions, not broker quotes.

Uses Yahoo Finance via yfinance, regular-session five-minute SPY candles, with volume. SPY is an ETF proxy, not an MT5 US500 CFD. Data can be delayed or unavailable; errors are retried and reported. Intraday history is limited to the recent 60 days, so initialization requests 59 days. Only completed candles are processed. The higher-timeframe warmup requires 50 four-hour bars and 130 hourly bars; the volatility window uses approximately seven hourly bars per trading session. No overnight candles are fabricated.

Each strategy retains its own paper positions, balance, trades, decisions and management events. The initial history warms up indicators; strategy entries begin at the latest completed bar. This is forward paper research, not a historical backtest or an out-of-sample evaluation. Stops, shorts, fees, fills and sizing are simulations; results do not reproduce a specific broker account.

No broker connection, API keys, or real orders. Paper account values are in USD; legacy CSV field names ending in `_eur` also contain USD values. FX conversion is not simulated. Profitability is not guaranteed.
