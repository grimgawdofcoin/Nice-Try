"""Live paper trading on real market data.

Every poll it downloads recent 15m candles, drops the bar still forming, and
replays each bot over them with fills only allowed after the run started.
Because the engine is deterministic, a crash or restart rebuilds the exact same
state from the ledger's start time: the log is the memory.

    python -m bots.live --cash 200
"""
import argparse
import json
import time
import urllib.request
from datetime import datetime, timezone

import pandas as pd

from .assets import get_bot
from .core.engine import backtest

# bot symbol -> (Yahoo ticker, spread in price units, max leverage)
MARKETS = {
    "NAS100": ("QQQ", 0.02, 1.0),        # ETF, cash account: no leverage
    "BTCUSD": ("BTC-USD", 15.0, 1.0),    # spot crypto
    "XAUUSD": ("GC=F", 0.30, 20.0),      # gold, CFD/futures-style margin
    "EURUSD": ("EURUSD=X", 0.00008, 20.0),
    "GBPJPY": ("GBPJPY=X", 0.03, 20.0),
}
UA = {"User-Agent": "Mozilla/5.0"}


def fetch_yahoo(ticker: str, rng: str = "1mo") -> pd.DataFrame:
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{ticker}?interval=15m&range={rng}"
    with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=20) as r:
        res = json.load(r)["chart"]["result"][0]
    q = res["indicators"]["quote"][0]
    df = pd.DataFrame(
        {k: q[k] for k in ("open", "high", "low", "close", "volume")},
        index=pd.to_datetime(res["timestamp"], unit="s", utc=True),
    ).dropna(subset=["open", "high", "low", "close"])
    df["volume"] = df["volume"].fillna(0).astype(float).clip(lower=1.0)
    df = df[~df.index.duplicated(keep="last")].sort_index()
    # Drop the bar that hasn't closed yet; bots only act on completed candles.
    return df[df.index + pd.Timedelta(minutes=15) <= pd.Timestamp.now(tz="UTC")]


def run_once(ledger: dict) -> dict:
    start = pd.Timestamp(ledger["started"])
    sleeve = ledger["cash"] / len(ledger["bots"])
    report = {}
    for sym in ledger["bots"]:
        ticker, spread, lev = MARKETS[sym]
        bot = get_bot(sym)
        bot.spread, bot.max_leverage = spread, lev
        try:
            df = fetch_yahoo(ticker)
        except Exception as e:  # one dead feed shouldn't stop the others
            report[sym] = {"error": str(e)}
            continue
        res = backtest(bot, df, sleeve, trade_from=start, close_at_end=False)
        live = [t for t in res.trades if t.entry_time >= start]
        ot = res.open_trade
        last = df["close"].iloc[-1]
        upnl = ((last - ot.entry) * ot.direction * ot.size) if ot else 0.0
        report[sym] = {
            "ticker": ticker,
            "last_bar": str(df.index[-1]),
            "last_price": float(last),
            "equity": float(res.equity.iloc[-1] + upnl),
            "closed": [{"side": "long" if t.direction > 0 else "short", "entry_time": str(t.entry_time),
                        "entry": t.entry, "exit_time": str(t.exit_time), "exit": t.exit_reason,
                        "pnl": round(t.pnl, 4), "r": round(t.r, 2), "why": t.reason} for t in live],
            "open": None if not ot else {
                "side": "long" if ot.direction > 0 else "short", "entry_time": str(ot.entry_time),
                "entry": ot.entry, "stop": ot.stop, "size": ot.size, "tp1_hit": ot.tp1_hit,
                "unrealized": round(upnl, 4), "why": ot.reason},
            "pending": None if not res.pending else {
                "side": "long" if res.pending.direction > 0 else "short",
                "stop": res.pending.stop, "why": res.pending.reason},
        }
    total = sum(r.get("equity", sleeve) for r in report.values())
    ledger.update(updated=datetime.now(timezone.utc).isoformat(), bots_state=report,
                  equity=round(total, 2), pnl=round(total - ledger["cash"], 2))
    return ledger


def main(argv=None):
    ap = argparse.ArgumentParser(prog="bots.live")
    ap.add_argument("--cash", type=float, default=200.0)
    ap.add_argument("--bots", default=",".join(MARKETS))
    ap.add_argument("--ledger", default="data/paper_ledger.json")
    ap.add_argument("--every", type=int, default=60, help="seconds between polls")
    ap.add_argument("--once", action="store_true")
    ap.add_argument("--fresh", action="store_true", help="start a new run instead of resuming")
    args = ap.parse_args(argv)

    import os
    os.makedirs(os.path.dirname(args.ledger) or ".", exist_ok=True)
    if os.path.exists(args.ledger) and not args.fresh:
        ledger = json.load(open(args.ledger))
        print(f"Resuming run started {ledger['started']}")
    else:
        ledger = {"started": datetime.now(timezone.utc).isoformat(), "cash": args.cash,
                  "bots": [b.strip().upper() for b in args.bots.split(",")]}
    while True:
        ledger = run_once(ledger)
        json.dump(ledger, open(args.ledger, "w"), indent=2, default=str)
        stamp = datetime.now(timezone.utc).strftime("%H:%M:%S")
        print(f"[{stamp}] equity ${ledger['equity']:.2f} ({ledger['pnl']:+.2f})")
        for sym, r in ledger["bots_state"].items():
            if "error" in r:
                print(f"   {sym:<7} feed error: {r['error']}")
                continue
            state = (f"OPEN {r['open']['side']} @ {r['open']['entry']:.5g} stop {r['open']['stop']:.5g}"
                     f" uPnL {r['open']['unrealized']:+.2f}") if r["open"] else \
                    (f"signal {r['pending']['side']} next bar" if r["pending"] else "flat")
            print(f"   {sym:<7} {r['ticker']:<9} {r['last_price']:<10.5g} {state}  closed {len(r['closed'])}")
        if args.once:
            return 0
        time.sleep(args.every)


if __name__ == "__main__":
    raise SystemExit(main())
