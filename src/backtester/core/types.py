"""Core types and data structures for the backtester."""

from typing import NamedTuple, Optional, Literal, Union, Dict, Any
from datetime import datetime
from decimal import Decimal
from enum import Enum
import numpy as np


class OrderType(Enum):
    """Order types supported by the backtester."""
    MARKET = "market"
    LIMIT = "limit"
    STOP = "stop"
    STOP_LIMIT = "stop_limit"


class OrderSide(Enum):
    """Order side (buy/sell)."""
    BUY = "buy"
    SELL = "sell"


class OrderStatus(Enum):
    """Order status."""
    PENDING = "pending"
    FILLED = "filled"
    PARTIALLY_FILLED = "partially_filled"
    CANCELLED = "cancelled"
    REJECTED = "rejected"


class PositionSide(Enum):
    """Position side."""
    LONG = "long"
    SHORT = "short"
    FLAT = "flat"


class RecordType(Enum):
    """Market data record types."""
    L1 = "L1"  # Level 1 (top of book)
    L2 = "L2"  # Level 2 (order book depth)


class TimeInForce(Enum):
    """Time in force for orders."""
    DAY = "day"
    GTC = "gtc"  # Good Till Cancelled
    IOC = "ioc"  # Immediate or Cancel
    FOK = "fok"  # Fill or Kill


# Core data structures
class TickData(NamedTuple):
    """Single tick data point."""
    timestamp: datetime
    price: float
    volume: int
    record_type: RecordType
    market_data_type: int
    timestamp_offset: int
    operation: Optional[int] = None
    position: Optional[int] = None
    market_maker: Optional[str] = None


class OrderBookLevel(NamedTuple):
    """Single order book level."""
    price: float
    volume: int
    market_maker: Optional[str] = None


class OrderBookSnapshot(NamedTuple):
    """Order book snapshot at a point in time."""
    timestamp: datetime
    bids: list[OrderBookLevel]
    asks: list[OrderBookLevel]


class Trade(NamedTuple):
    """Executed trade record."""
    timestamp: datetime
    price: float
    volume: int
    side: OrderSide
    commission: float = 0.0
    slippage: float = 0.0


class Position(NamedTuple):
    """Current position state."""
    side: PositionSide
    size: int
    avg_price: float
    unrealized_pnl: float
    realized_pnl: float


class EquityPoint(NamedTuple):
    """Equity curve data point."""
    timestamp: datetime
    equity: float
    cash: float
    position_value: float
    drawdown: float
    drawdown_pct: float


# Configuration types
class BacktestConfig(NamedTuple):
    """Backtest configuration."""
    start_date: datetime
    end_date: datetime
    initial_capital: float
    commission_per_trade: float
    tick_size: float
    contract_multiplier: int
    slippage_ticks: int = 0


class DataConfig(NamedTuple):
    """Data configuration."""
    data_path: str
    instrument: str
    date_format: str = "%Y%m%d"
    timezone: str = "America/New_York"


# Type aliases for common types
Price = Union[float, Decimal]
Volume = int
Timestamp = datetime
InstrumentId = str
OrderId = str
TradeId = str

# Numpy array types for performance
PriceArray = np.ndarray  # dtype=float64
VolumeArray = np.ndarray  # dtype=int32
TimestampArray = np.ndarray  # dtype=datetime64[ns]