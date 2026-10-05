# S&P 500 FTMO $100k Free Trial paper bot

One shared simulated USD 100,000 account. Six strategies provide candidates; at most one paper position is allowed account-wide. Strategy subledgers show attributed P/L, not six funded accounts.

## Default profile

- `RUN_MODE=FTMO_PAPER`, `START_BALANCE=100000`, `DATA_DIR=/data/ftmo100k-v1`.
- $250 stop risk per trade, plus estimated costs. Maximum modeled notional 5 times balance.
- Free Trial profit target $5,000 (5%), with all positions closed and Best Day no more than 50% of positive days' realized net profits.
- Daily loss floor: midnight Prague balance minus $3,000.
- EOD trailing floor: highest midnight Prague balance minus $10,000; never decreases.
- Internal daily stop at $1,500 loss, $500 loss-limit buffer, and permanent halt after a detected breach.
- Local paper simulation expires after 14 days from first processed candle. This is not the expiry of an externally connected FTMO account.

Rules verified 2026-10-05: https://ftmo.com/en/trading-objectives/ and https://ftmo.com/en/faq/do-you-offer-a-free-trial/ . Code and risk settings cannot guarantee passing.

## Deployment

`python bot.py`; attach persistent storage at `/data`. Dashboard `/`, API `/api/status`, process health `/health`. Old research files remain in their original directory; this profile starts a separate ledger.

**MT5 NOT CONNECTED.** This Railway Linux service does not execute orders on the screenshot's FTMO demo account. SPY/Yahoo is an ETF proxy, not FTMO's US500 CFD feed. Actual execution requires an always-on supported MT5 desktop terminal/Windows VPS, account validation and broker symbol/contract sizing. The iPhone alone does not run this Python terminal integration. No credentials, personal details or account login numbers are committed.

Market data may be delayed/unavailable. Five-minute candles approximate intrabar loss checks; broker tick-level equity, swaps, CFD commissions, margin and actual order execution are not reproduced. Loss-limit monitoring is simulation, not a compliance guarantee. Fees and slippage remain configurable research assumptions; legacy CSV fields ending `_eur` contain USD.

`RUN_MODE=RESEARCH` retains the previous independent-strategy engine for separate research deployments. Use a separate DATA_DIR and original START_BALANCE as needed.
