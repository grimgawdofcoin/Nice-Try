"""CLI: python -m bots list | python -m bots backtest <SYMBOL|all> [--csv FILE]"""
import argparse
import sys

from .assets import BOTS, get_bot
from .core.data import load_csv, synthetic
from .core.engine import backtest


def _fmt(s):
    pf = "inf" if s["profit_factor"] == float("inf") else f"{s['profit_factor']:.2f}"
    return (f"{s['symbol']:<8} trades {s['trades']:>4}  win {s['win_rate']:>5.1%}  "
            f"avgR {s['avg_r']:>+5.2f}  totalR {s['total_r']:>+7.1f}  PF {pf:>5}  "
            f"maxDD {s['max_drawdown']:>6.1%}  return {s['return']:>+7.1%}")


def main(argv=None):
    ap = argparse.ArgumentParser(prog="bots")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("list", help="describe every bot")
    bt = sub.add_parser("backtest", help="backtest one bot or all of them")
    bt.add_argument("symbol", help="e.g. XAUUSD, or 'all'")
    bt.add_argument("--csv", help="real OHLC data (UTC). Without it, synthetic data is used")
    bt.add_argument("--timeframe", default="15min")
    bt.add_argument("--days", type=int, default=250, help="synthetic days")
    bt.add_argument("--seed", type=int, default=7)
    bt.add_argument("--equity", type=float, default=10_000)
    bt.add_argument("--trades", action="store_true", help="print every trade")
    args = ap.parse_args(argv)

    if args.cmd == "list":
        for cls in BOTS.values():
            print(cls().describe(), end="\n\n")
        return 0

    symbols = list(BOTS) if args.symbol.lower() == "all" else [args.symbol]
    if args.csv and len(symbols) > 1:
        ap.error("--csv works with a single symbol")
    if not args.csv:
        print("Synthetic data: checks the mechanics only, NOT evidence of an edge.\n")
    for sym in symbols:
        bot = get_bot(sym)
        df = load_csv(args.csv, args.timeframe) if args.csv else \
            synthetic(bot.symbol, args.days, args.seed, args.timeframe)
        res = backtest(bot, df, args.equity)
        print(_fmt(res.stats()))
        if args.trades:
            for t in res.trades:
                side = "LONG " if t.direction > 0 else "SHORT"
                print(f"   {t.entry_time:%Y-%m-%d %H:%M} {side} @ {t.entry:.5g} "
                      f"-> {t.exit_reason:<13} {t.r:+.2f}R  ({t.reason})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
