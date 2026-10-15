"""Asset-specific trading bots. One strategy per market, no one-size-fits-all."""
from .assets import BOTS, get_bot
from .core.engine import backtest
