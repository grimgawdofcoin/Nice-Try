from .btcusd import TrendRider
from .eurusd import FiberPullback
from .gbpjpy import DragonRetest
from .nas100 import OpeningDrive
from .xauusd import GoldSweep

BOTS = {cls.symbol: cls for cls in (GoldSweep, FiberPullback, DragonRetest, TrendRider, OpeningDrive)}


def get_bot(symbol: str):
    key = symbol.upper().replace("/", "")
    if key not in BOTS:
        raise KeyError(f"No bot for {symbol}. Available: {', '.join(BOTS)}")
    return BOTS[key]()
