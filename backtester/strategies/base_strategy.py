"""
Base Strategy - Abstract interface for trading strategies

Similar to NinjaScript's Strategy class, provides required methods
and access to market data, order placement, and position information.
"""

from abc import ABC, abstractmethod
from datetime import datetime
from typing import Dict, List, Optional, Any
import pandas as pd

from ..data.order_book import OrderBook


class BaseStrategy(ABC):
    """
    Abstract base class for all trading strategies.
    
    Similar to NinjaScript's Strategy class, provides standardized interface
    for strategy development with access to market data and order placement.
    """
    
    def __init__(self, **parameters):
        """
        Initialize strategy with parameters.
        
        Args:
            **parameters: Strategy-specific parameters
        """
        self.parameters = parameters
        
        # Market state (injected by backtester)
        self.position: int = 0
        self.avg_price: float = 0.0
        self.unrealized_pnl: float = 0.0
        self.realized_pnl: float = 0.0
        self.last_price: float = 0.0
        self.order_book: Optional[OrderBook] = None
        
        # Order placement methods (injected by backtester)
        self.enter_long = None
        self.enter_short = None
        self.exit_long = None
        self.exit_short = None
        self.cancel_order = None
        
        # Strategy state storage
        self.state: Dict[str, Any] = {}
        
        # Custom indicators/variables can be stored here
        self.indicators: Dict[str, Any] = {}
    
    @abstractmethod
    def on_start(self):
        """
        Called once before backtest begins.
        
        Use this method to:
        - Initialize indicators
        - Set up strategy variables
        - Perform one-time setup
        """
        pass
    
    @abstractmethod
    def on_bar_update(self, timestamp: datetime, last_price: float, order_book: OrderBook):
        """
        Called on every tick/market data update.
        
        This is the main strategy logic method where trading decisions are made.
        
        Args:
            timestamp: Current market timestamp
            last_price: Most recent trade price
            order_book: Current order book state
        """
        pass
    
    def on_end(self):
        """
        Called once after backtest completes.
        
        Use this method to:
        - Clean up resources
        - Log final statistics
        - Perform post-backtest analysis
        """
        pass
    
    def on_order_update(self, order: Any):
        """
        Called when order status changes.
        
        Args:
            order: Order object with updated status
        """
        pass
    
    def on_execution(self, fill: Any):
        """
        Called when order fills.
        
        Args:
            fill: Fill object with execution details
        """
        pass
    
    def on_trade(self, trade: Any):
        """
        Called when a complete trade is closed.
        
        Args:
            trade: Trade object with entry/exit details
        """
        pass
    
    # Utility methods for common strategy operations
    
    def is_long(self) -> bool:
        """Check if currently long."""
        return self.position > 0
    
    def is_short(self) -> bool:
        """Check if currently short."""
        return self.position < 0
    
    def is_flat(self) -> bool:
        """Check if currently flat (no position)."""
        return self.position == 0
    
    def get_spread(self) -> Optional[float]:
        """Get current bid-ask spread."""
        if self.order_book:
            return self.order_book.get_spread()
        return None
    
    def get_mid_price(self) -> Optional[float]:
        """Get current mid-market price."""
        if self.order_book:
            return self.order_book.get_mid_price()
        return None
    
    def get_best_bid(self) -> Optional[float]:
        """Get current best bid price."""
        if self.order_book:
            price, _ = self.order_book.get_best_bid()
            return price
        return None
    
    def get_best_ask(self) -> Optional[float]:
        """Get current best ask price."""
        if self.order_book:
            price, _ = self.order_book.get_best_ask()
            return price
        return None
    
    def log(self, message: str, level: str = 'info'):
        """
        Log strategy message.
        
        Args:
            message: Message to log
            level: Log level ('info', 'debug', 'warning', 'error')
        """
        import logging
        logger = logging.getLogger(f"strategy.{self.__class__.__name__}")
        
        if level == 'debug':
            logger.debug(message)
        elif level == 'warning':
            logger.warning(message)
        elif level == 'error':
            logger.error(message)
        else:
            logger.info(message)


# Example strategy implementations

class BuyAndHoldStrategy(BaseStrategy):
    """Simple buy and hold strategy for testing."""
    
    def __init__(self, quantity: int = 1):
        super().__init__(quantity=quantity)
        self.bought = False
    
    def on_start(self):
        self.log("Buy and Hold strategy started")
    
    def on_bar_update(self, timestamp: datetime, last_price: float, order_book: OrderBook):
        # Buy once at the beginning
        if not self.bought and last_price > 0 and self.is_flat():
            self.enter_long(self.parameters['quantity'])
            self.bought = True
            self.log(f"Bought {self.parameters['quantity']} contracts @ {last_price}")


class SimpleMovingAverageStrategy(BaseStrategy):
    """Simple moving average crossover strategy."""
    
    def __init__(self, short_window: int = 10, long_window: int = 20, quantity: int = 1):
        super().__init__(
            short_window=short_window,
            long_window=long_window,
            quantity=quantity
        )
        self.prices: List[float] = []
        self.signals: List[str] = []
    
    def on_start(self):
        self.log(f"MA Strategy started: {self.parameters['short_window']}/{self.parameters['long_window']}")
    
    def on_bar_update(self, timestamp: datetime, last_price: float, order_book: OrderBook):
        if last_price <= 0:
            return
        
        # Store price
        self.prices.append(last_price)
        
        # Keep only needed history
        long_window = self.parameters['long_window']
        if len(self.prices) > long_window:
            self.prices = self.prices[-long_window:]
        
        # Need enough data for long MA
        if len(self.prices) < long_window:
            return
        
        # Calculate moving averages
        short_window = self.parameters['short_window']
        short_ma = sum(self.prices[-short_window:]) / short_window
        long_ma = sum(self.prices) / len(self.prices)
        
        quantity = self.parameters['quantity']
        
        # Generate signals
        if short_ma > long_ma and self.is_flat():
            # Golden cross - go long
            self.enter_long(quantity)
            self.log(f"Golden cross signal: MA({short_window})={short_ma:.2f} > MA({long_window})={long_ma:.2f}")
            
        elif short_ma < long_ma and self.is_long():
            # Death cross - exit long
            self.exit_long(quantity)
            self.log(f"Death cross signal: MA({short_window})={short_ma:.2f} < MA({long_window})={long_ma:.2f}")


class MeanReversionStrategy(BaseStrategy):
    """Mean reversion strategy using order book imbalance."""
    
    def __init__(self, lookback: int = 20, entry_threshold: float = 2.0, 
                 exit_threshold: float = 0.5, quantity: int = 1):
        super().__init__(
            lookback=lookback,
            entry_threshold=entry_threshold,
            exit_threshold=exit_threshold,
            quantity=quantity
        )
        self.mid_prices: List[float] = []
        self.imbalances: List[float] = []
    
    def on_start(self):
        self.log("Mean Reversion strategy started")
    
    def on_bar_update(self, timestamp: datetime, last_price: float, order_book: OrderBook):
        # Calculate order book imbalance
        best_bid, bid_vol = order_book.get_best_bid()
        best_ask, ask_vol = order_book.get_best_ask()
        
        if best_bid is None or best_ask is None:
            return
        
        mid_price = (best_bid + best_ask) / 2.0
        self.mid_prices.append(mid_price)
        
        if bid_vol and ask_vol:
            imbalance = (bid_vol - ask_vol) / (bid_vol + ask_vol)
            self.imbalances.append(imbalance)
        
        lookback = self.parameters['lookback']
        if len(self.mid_prices) < lookback:
            return
        
        # Keep only needed history
        self.mid_prices = self.mid_prices[-lookback:]
        self.imbalances = self.imbalances[-lookback:]
        
        # Calculate mean and standard deviation
        mean_price = sum(self.mid_prices) / len(self.mid_prices)
        variance = sum((p - mean_price) ** 2 for p in self.mid_prices) / len(self.mid_prices)
        std_dev = variance ** 0.5
        
        if std_dev == 0:
            return
        
        # Z-score
        z_score = (mid_price - mean_price) / std_dev
        
        entry_threshold = self.parameters['entry_threshold']
        exit_threshold = self.parameters['exit_threshold']
        quantity = self.parameters['quantity']
        
        # Trading logic
        if z_score > entry_threshold and self.is_flat():
            # Price too high, expect reversion down
            self.enter_short(quantity)
            self.log(f"Mean reversion short: z_score={z_score:.2f}")
            
        elif z_score < -entry_threshold and self.is_flat():
            # Price too low, expect reversion up
            self.enter_long(quantity)
            self.log(f"Mean reversion long: z_score={z_score:.2f}")
            
        elif abs(z_score) < exit_threshold:
            # Price back to mean, exit position
            if self.is_long():
                self.exit_long(quantity)
                self.log(f"Exit long at mean: z_score={z_score:.2f}")
            elif self.is_short():
                self.exit_short(quantity)
                self.log(f"Exit short at mean: z_score={z_score:.2f}")