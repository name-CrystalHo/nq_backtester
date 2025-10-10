"""
Core Backtesting Engine - Tick-by-tick replay with order book simulation

Replays historical tick data event-by-event, maintaining order book state
and executing strategy logic with realistic order fills.
"""

import pandas as pd
from datetime import datetime, date
from typing import Dict, List, Optional, Any, Callable
import logging
from pathlib import Path

from ..data.loader import DataLoader
from ..data.order_book import OrderBook
from .order_manager import OrderManager, Order
from .position_tracker import PositionTracker
from ..metrics.performance import PerformanceMetrics

logger = logging.getLogger(__name__)


class BacktestConfig:
    """Configuration for backtesting engine."""
    
    def __init__(self,
                 initial_capital: float = 100000.0,
                 commission_per_contract: float = 2.50,
                 slippage_ticks: int = 0,
                 max_order_book_levels: int = 10,
                 market_hours_only: bool = True,
                 market_open: str = "09:30:00",
                 market_close: str = "16:15:00",
                 allow_partial_fills: bool = True):
        self.initial_capital = initial_capital
        self.commission_per_contract = commission_per_contract
        self.slippage_ticks = slippage_ticks
        self.max_order_book_levels = max_order_book_levels
        self.market_hours_only = market_hours_only
        self.market_open = market_open
        self.market_close = market_close
        self.allow_partial_fills = allow_partial_fills


class Backtester:
    """
    Core backtesting engine with tick-by-tick replay.
    
    Processes historical tick data chronologically, maintains order book state,
    executes strategy logic, and tracks performance metrics.
    """
    
    def __init__(self, strategy: Any, data_loader: DataLoader, 
                 config: Optional[BacktestConfig] = None):
        """
        Initialize backtester.
        
        Args:
            strategy: Strategy instance with required methods
            data_loader: DataLoader instance for tick data
            config: Backtest configuration
        """
        self.strategy = strategy
        self.data_loader = data_loader
        self.config = config or BacktestConfig()
        
        # Core components
        self.order_book = OrderBook(max_levels=self.config.max_order_book_levels)
        self.order_manager = OrderManager(self.order_book, self.config)
        self.position_tracker = PositionTracker(self.config.initial_capital)
        
        # Market state
        self.current_timestamp = None
        self.last_price = 0.0
        self.current_bid = 0.0
        self.current_ask = 0.0
        
        # Strategy interface - inject backtester methods into strategy
        self._setup_strategy_interface()
        
        # Logging
        self.event_log = []
        self.debug_mode = False
        
    def _setup_strategy_interface(self):
        """Inject backtester methods into strategy for order placement."""
        self.strategy.enter_long = self.enter_long
        self.strategy.enter_short = self.enter_short
        self.strategy.exit_long = self.exit_long
        self.strategy.exit_short = self.exit_short
        self.strategy.cancel_order = self.cancel_order
        
        # Provide access to current market state
        self.strategy.position = 0
        self.strategy.avg_price = 0.0
        self.strategy.unrealized_pnl = 0.0
        self.strategy.realized_pnl = 0.0
        self.strategy.order_book = self.order_book
        self.strategy.last_price = 0.0
    
    def run(self, instrument: str, start_date: str, end_date: str) -> PerformanceMetrics:
        """
        Run backtest for specified instrument and date range.
        
        Args:
            instrument: Instrument name (e.g., 'NQ_JUN21')
            start_date: Start date in YYYYMMDD format
            end_date: End date in YYYYMMDD format
            
        Returns:
            PerformanceMetrics with complete backtest results
        """
        logger.info(f"Starting backtest: {instrument} from {start_date} to {end_date}")
        
        # Initialize strategy
        self.strategy.on_start()
        
        # Get available dates in range
        available_dates = self.data_loader.get_available_dates(instrument)
        test_dates = [d for d in available_dates if start_date <= d <= end_date]
        
        if not test_dates:
            logger.warning(f"No data available for {instrument} in date range")
            return PerformanceMetrics()
        
        logger.info(f"Processing {len(test_dates)} days: {test_dates[0]} to {test_dates[-1]}")
        
        # Process each day
        for date_str in test_dates:
            logger.debug(f"Processing {date_str}")
            self.replay_day(instrument, date_str)
        
        # Finalize strategy
        self.strategy.on_end()
        
        # Generate performance metrics
        metrics = PerformanceMetrics()
        metrics.calculate_from_tracker(self.position_tracker)
        
        logger.info(f"Backtest complete. Net P&L: ${metrics.total_net_profit:,.2f}")
        return metrics
    
    def replay_day(self, instrument: str, date_str: str):
        """
        Replay a single day of tick data.
        
        Args:
            instrument: Instrument name
            date_str: Date in YYYYMMDD format
        """
        # Load day's data (both L1 and L2 records)
        time_range = None
        if self.config.market_hours_only:
            time_range = (self.config.market_open, self.config.market_close)
            
        data = self.data_loader.load_day(
            instrument=instrument,
            date_str=date_str,
            time_range=time_range
        )
        
        if data.empty:
            logger.warning(f"No data for {instrument} on {date_str}")
            return
        
        logger.debug(f"Replaying {len(data)} events for {date_str}")
        
        # Reset order book for new day
        self.order_book.clear()
        
        # Process each tick chronologically
        for idx, record in data.iterrows():
            self.current_timestamp = record['timestamp']
            
            # Process L2 events (order book updates)
            if record['record_type'] == 'L2':
                self.order_book.process_l2_event(record)
                
            # Process L1 events (market data updates)
            elif record['record_type'] == 'L1':
                self._process_l1_event(record)
            
            # Check for order fills and update positions
            filled_orders = self.order_manager.check_fills(self.current_timestamp)
            
            # Process any new fills
            if hasattr(self.order_manager, '_new_fills'):
                for fill in self.order_manager._new_fills:
                    # Determine quantity direction (buy = positive, sell = negative)
                    quantity = fill.quantity
                    if fill.order_id in self.order_manager.completed_orders:
                        order = self.order_manager.completed_orders[fill.order_id]
                        if order.direction == 'sell':
                            quantity = -quantity
                    
                    # Update position
                    trade = self.position_tracker.update_position(
                        quantity=quantity,
                        price=fill.price,
                        timestamp=fill.timestamp,
                        commission=fill.commission
                    )
                    
                    # Notify strategy of trade completion
                    if trade and hasattr(self.strategy, 'on_trade'):
                        self.strategy.on_trade(trade)
                
                # Clear processed fills
                self.order_manager._new_fills.clear()
            
            # Update strategy state
            self._update_strategy_state()
            
            # Call strategy
            self.strategy.on_bar_update(
                timestamp=self.current_timestamp,
                last_price=self.last_price,
                order_book=self.order_book
            )
            
            # Update position tracker with current price
            self.position_tracker.update_unrealized_pnl(
                self.current_timestamp, 
                self.last_price
            )
    
    def _process_l1_event(self, record: pd.Series):
        """
        Process L1 market data event.
        
        L1 MarketDataType meanings:
        0 = Ask, 1 = Bid, 2 = Last, 3 = DailyHigh, 4 = DailyLow, etc.
        """
        market_data_type = record['market_data_type']
        price = record['price']
        
        if market_data_type == 2:  # Last price
            self.last_price = price
        elif market_data_type == 1:  # Bid
            self.current_bid = price
        elif market_data_type == 0:  # Ask
            self.current_ask = price
    
    def _update_strategy_state(self):
        """Update strategy properties with current state."""
        position = self.position_tracker.position
        
        self.strategy.position = position.size
        self.strategy.avg_price = position.average_price
        self.strategy.unrealized_pnl = position.unrealized_pnl
        self.strategy.realized_pnl = self.position_tracker.realized_pnl
        self.strategy.last_price = self.last_price
    
    def enter_long(self, quantity: int, order_type: str = 'market', 
                   limit_price: Optional[float] = None,
                   stop_price: Optional[float] = None) -> str:
        """
        Enter long position (strategy interface).
        
        Args:
            quantity: Number of contracts
            order_type: 'market', 'limit', 'stop', 'stop_limit'
            limit_price: Limit price for limit orders
            stop_price: Stop price for stop orders
            
        Returns:
            Order ID
        """
        order = Order(
            order_id=self.order_manager.get_next_order_id(),
            direction='buy',
            quantity=quantity,
            order_type=order_type,
            limit_price=limit_price,
            stop_price=stop_price,
            timestamp=self.current_timestamp
        )
        
        self.order_manager.submit_order(order)
        
        if self.debug_mode:
            self.event_log.append({
                'timestamp': self.current_timestamp,
                'event': 'order_submitted',
                'order': order
            })
        
        return order.order_id
    
    def enter_short(self, quantity: int, order_type: str = 'market',
                    limit_price: Optional[float] = None,
                    stop_price: Optional[float] = None) -> str:
        """Enter short position (strategy interface)."""
        order = Order(
            order_id=self.order_manager.get_next_order_id(),
            direction='sell',
            quantity=quantity,
            order_type=order_type,
            limit_price=limit_price,
            stop_price=stop_price,
            timestamp=self.current_timestamp
        )
        
        self.order_manager.submit_order(order)
        return order.order_id
    
    def exit_long(self, quantity: int) -> str:
        """Exit long position (market order)."""
        return self.enter_short(quantity, 'market')
    
    def exit_short(self, quantity: int) -> str:
        """Exit short position (market order)."""
        return self.enter_long(quantity, 'market')
    
    def cancel_order(self, order_id: str) -> bool:
        """Cancel pending order."""
        return self.order_manager.cancel_order(order_id)
    
    def get_backtest_summary(self) -> Dict:
        """Get summary of backtest execution."""
        return {
            'total_events': len(self.event_log) if self.debug_mode else 'N/A',
            'total_orders': self.order_manager.total_orders_submitted,
            'total_fills': self.order_manager.total_fills,
            'final_position': self.position_tracker.position.size,
            'realized_pnl': self.position_tracker.realized_pnl,
            'unrealized_pnl': self.position_tracker.position.unrealized_pnl,
            'total_pnl': self.position_tracker.get_total_pnl(),
            'final_equity': self.position_tracker.get_current_equity(),
        }