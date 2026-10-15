# Asset-specific trading bots

No single strategy works on every market. Each bot here is written for one
asset: its own setup, sessions, stop placement, targets and risk. They all share
one backtest engine that enforces the ICC risk rules (risk per trade, a cap on
signals per session, one trade per direction, done after the daily loss limit,
stop to breakeven at TP1).

| Bot | Asset | Setup | Sessions (UTC) | Exit |
|---|---|---|---|---|
| Gold Sweep | XAUUSD | ICC continuation, only after a liquidity sweep + reclaim, with the 200-EMA trend | London 7-11, NY 12:30-16 | 50% at 1R, rest at 3R |
| Fiber Deep Pullback | EURUSD | ICC on deep 50-79% retracements, trend EMA slope filter | London 7-10:30, overlap 12:30-15 | 50% at 1R, rest at 2R |
| Dragon Asian-Range Retest | GBPJPY | London break of the Tokyo range, entry on the retest | London 7-11 | 50% at 1R, rest at range-height projection |
| BTC Trend Rider | BTCUSD | Stacked-EMA trend, pullback into 21-50 EMA band | 24/7 (half risk on weekends) | 33% at 1.5R, trail rest 3 ATR |
| NAS Opening Drive | NAS100 | NY opening-range break, pullback to range edge/VWAP | NY 14:00-17:00 | 50% at 1R, rest 2.5R, flat by 19:45 |

Run `python -m bots list` to see each bot's reasoning.

## Usage

Needs Python 3.10+ with `pandas` and `numpy`.

```bash
python -m bots list                                # what each bot does and why
python -m bots backtest all                        # every bot on synthetic data
python -m bots backtest XAUUSD --csv data/xau_15m.csv --trades   # real data
python -m unittest tests.test_bots                 # engine + bot rule tests
```

`--csv` accepts TradingView, MT5 or exchange exports (time, open, high,
low, close, optional volume). Timestamps are treated as **UTC**, and bars are
resampled to `--timeframe` (default 15min).

## Important

- **Synthetic results mean nothing.** The built-in data is a random walk, so it
  only proves the mechanics work. Judge a bot only on real historical data, and
  across more than one period.
- **No live trading is wired in.** These bots backtest only. Before connecting
  one to a broker, backtest it on real data, then paper trade it.
- NAS100 times assume US summer time (EDT). Shift them by one hour in winter.
- Fills are modelled conservatively: entry at the next bar's open, the stop
  is assumed hit first if a bar touches both stop and target, and the spread
  is charged on every trade. Slippage beyond that isn't modelled.

## Adding a bot for another asset

Subclass `Strategy` in `bots/assets/<symbol>.py`. Set `sessions`, `risk`
and `spread`, add indicators in `prepare()`, and return a `Signal` from
`on_bar()`. Then register it in `bots/assets/__init__.py`. `bots/core/icc.py`
has a reusable Indication -> Correction -> Continuation detector.
