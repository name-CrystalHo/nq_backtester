"""
Main Backtester - Works with ANY Strategy

This is the primary backtesting engine for the entire system. It accepts any strategy
as a parameter and provides the complete trading pipeline:

1. Bar aggregation (configurable timeframes)
2. Signal processing (convert any strategy's signals to orders)  
3. Order management (execute orders with realistic fills)
4. Position tracking (track trades and P&L)

Usage:
    from backtester.engine.backtester import Backtester
    
    backtester = Backtester()
    results = backtester.run_backtest(
        strategy_name="wicktest",
        data_file="path/to/data.parquet",
        config={"initial_capital": 100000}
    )
"""

import logging
import sys
import polars as pl
from pathlib import Path
from typing import Dict, Any, List, Optional, Union, Type
from datetime import datetime, timedelta
import time
import json
import importlib
from tqdm import tqdm
import numpy as np

# Add project root for imports
project_root = Path(__file__).parent.parent.parent
sys.path.append(str(project_root))

# Import with absolute paths to avoid relative import issues
import sys
import os
sys.path.insert(0, str(project_root))

from backtester.strategies.base_strategy import BaseStrategy, Signal
from backtester.data.order_book import OrderBook
from backtester.engine.bar_aggregator import BarAggregator, Bar

# Set up logging (WARNING level to reduce noise, tqdm handles progress)
logging.basicConfig(level=logging.WARNING, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)


class BacktestConfig:
    """Configuration for backtesting parameters."""
    
    def __init__(self, **kwargs):
        # Trading parameters
        self.initial_capital = kwargs.get('initial_capital', 100000.0)
        self.commission_per_contract = kwargs.get('commission_per_contract', 2.50)
        self.slippage_ticks = kwargs.get('slippage_ticks', 1)
        self.max_position_size = kwargs.get('max_position_size', 1)
        
        # Data parameters
        self.max_ticks = kwargs.get('max_ticks', None)
        self.start_date = kwargs.get('start_date', None)
        self.end_date = kwargs.get('end_date', None)
        
        # Bar aggregation (for strategies that need bars)
        self.bar_timeframe = kwargs.get('bar_timeframe', '5T')  # 5-minute bars
        
        # Risk parameters
        self.max_drawdown = kwargs.get('max_drawdown', 0.20)  # 20% max drawdown
        
        # Execution parameters
        self.fill_simulation = kwargs.get('fill_simulation', 'realistic')  # 'instant' or 'realistic'
        
        # Order book simulation (for ultra-realistic fills)
        self.use_order_book = kwargs.get('use_order_book', True)  # Enable L2 order book simulation
        self.max_order_book_levels = kwargs.get('max_order_book_levels', 20)  # Order book depth


class TradingEngine:
    """Generic trading engine that works with any strategy."""
    
    def __init__(self, config: BacktestConfig, max_equity_points: int = 100000):
        self.config = config
        self.order_book = OrderBook()
        
        # Trading state
        self.current_position = 0
        self.current_avg_price = 0.0
        self.unrealized_pnl = 0.0
        self.realized_pnl = 0.0
        
        # Pre-allocated equity curve arrays (HUGE PERFORMANCE WIN)
        self.max_equity_points = max_equity_points
        self.equity_timestamps = np.zeros(max_equity_points, dtype=np.int64)
        self.equity_realized_pnl = np.zeros(max_equity_points, dtype=np.float64)
        self.equity_unrealized_pnl = np.zeros(max_equity_points, dtype=np.float64)
        self.equity_total = np.zeros(max_equity_points, dtype=np.float64)
        self.equity_position = np.zeros(max_equity_points, dtype=np.int32)
        self.equity_idx = 0  # Current index in equity arrays
        
        self.trades = []
        self.active_orders = {}
        
        # Performance tracking
        self.total_signals = 0
        self.executed_trades = 0
        self.current_capital = config.initial_capital
        
        logger.info(f"Trading engine initialized with ${config.initial_capital:,.2f} capital")
        
    def process_signal(self, signal: Signal, current_price: float, timestamp: int) -> Optional[Dict[str, Any]]:
        """
        Process a signal from ANY strategy and convert it to trades.
        
        Args:
            signal: Strategy signal (entry/exit)
            current_price: Current market price
            timestamp: Current timestamp (nanoseconds)
            
        Returns:
            Trade result if executed, None otherwise
        """
        self.total_signals += 1
        
        logger.debug(f"Processing {signal.signal_type} signal at ${signal.price}")
        
        try:
            if signal.signal_type == 'entry_long':
                return self._process_entry_long(signal, current_price, timestamp)
            elif signal.signal_type == 'entry_short':
                return self._process_entry_short(signal, current_price, timestamp)
            elif signal.signal_type == 'exit_long':
                return self._process_exit_long(signal, current_price, timestamp)
            elif signal.signal_type == 'exit_short':
                return self._process_exit_short(signal, current_price, timestamp)
            elif signal.signal_type == 'close_position':
                return self._process_close_position(signal, current_price, timestamp)
            else:
                logger.warning(f"Unknown signal type: {signal.signal_type}")
                return None
                
        except Exception as e:
            logger.error(f"Error processing signal: {e}")
            return None
    
    def _process_entry_long(self, signal: Signal, current_price: float, timestamp: int) -> Optional[Dict[str, Any]]:
        """Process long entry signal."""
        if self.current_position != 0:
            logger.debug("Already in position, ignoring entry signal")
            return None
        
        # Check risk limits
        if not self._check_risk_limits():
            logger.debug("Risk limits exceeded, skipping trade")
            return None
        
        entry_price = self._get_fill_price(signal, current_price, 'buy')
        
        if self._should_fill_order(signal.signal_type, entry_price, current_price):
            self.current_position = 1
            self.current_avg_price = entry_price
            
            trade = self._create_trade_record('entry', 'long', entry_price, 1, timestamp, signal)
            self.trades.append(trade)
            self.executed_trades += 1
            
            logger.info(f"LONG ENTRY at ${entry_price:.2f}")
            return trade
            
        return None
    
    def _process_entry_short(self, signal: Signal, current_price: float, timestamp: int) -> Optional[Dict[str, Any]]:
        """Process short entry signal."""
        if self.current_position != 0:
            logger.debug("Already in position, ignoring entry signal")
            return None
            
        if not self._check_risk_limits():
            logger.debug("Risk limits exceeded, skipping trade")
            return None
        
        entry_price = self._get_fill_price(signal, current_price, 'sell')
        
        if self._should_fill_order(signal.signal_type, entry_price, current_price):
            self.current_position = -1
            self.current_avg_price = entry_price
            
            trade = self._create_trade_record('entry', 'short', entry_price, 1, timestamp, signal)
            self.trades.append(trade)
            self.executed_trades += 1
            
            logger.info(f"SHORT ENTRY at ${entry_price:.2f}")
            return trade
            
        return None
    
    def _process_exit_long(self, signal: Signal, current_price: float, timestamp: int) -> Optional[Dict[str, Any]]:
        """Process long exit signal."""
        if self.current_position <= 0:
            logger.debug("No long position to exit")
            return None
        
        exit_price = self._get_fill_price(signal, current_price, 'sell')
        
        if self._should_fill_order(signal.signal_type, exit_price, current_price):
            pnl = (exit_price - self.current_avg_price) * self.current_position
            self.realized_pnl += pnl
            self.current_capital += pnl
            
            trade = self._create_trade_record('exit', 'long', exit_price, self.current_position, 
                                            timestamp, signal, self.current_avg_price, pnl)
            self.trades.append(trade)
            self.executed_trades += 1
            
            # Reset position
            self.current_position = 0
            self.current_avg_price = 0.0
            
            logger.info(f"LONG EXIT at ${exit_price:.2f}, P&L: ${pnl:.2f}")
            return trade
            
        return None
    
    def _process_exit_short(self, signal: Signal, current_price: float, timestamp: int) -> Optional[Dict[str, Any]]:
        """Process short exit signal."""
        if self.current_position >= 0:
            logger.debug("No short position to exit")
            return None
        
        exit_price = self._get_fill_price(signal, current_price, 'buy')
        
        if self._should_fill_order(signal.signal_type, exit_price, current_price):
            pnl = (self.current_avg_price - exit_price) * abs(self.current_position)
            self.realized_pnl += pnl
            self.current_capital += pnl
            
            trade = self._create_trade_record('exit', 'short', exit_price, abs(self.current_position),
                                            timestamp, signal, self.current_avg_price, pnl)
            self.trades.append(trade)
            self.executed_trades += 1
            
            # Reset position
            self.current_position = 0
            self.current_avg_price = 0.0
            
            logger.info(f"SHORT EXIT at ${exit_price:.2f}, P&L: ${pnl:.2f}")
            return trade
            
        return None
    
    def _process_close_position(self, signal: Signal, current_price: float, timestamp: int) -> Optional[Dict[str, Any]]:
        """Process close position signal (works for any direction)."""
        if self.current_position == 0:
            logger.debug("No position to close")
            return None
        
        if self.current_position > 0:
            return self._process_exit_long(signal, current_price, timestamp)
        else:
            return self._process_exit_short(signal, current_price, timestamp)
    
    def _get_fill_price(self, signal: Signal, current_price: float, side: str) -> float:
        """Calculate realistic fill price with slippage."""
        if self.config.fill_simulation == 'instant':
            return current_price
        
        # Realistic fill with slippage
        slippage = self.config.slippage_ticks * 0.25  # Assume 0.25 per tick
        
        if side == 'buy':
            return signal.price + slippage  # Pay slightly more when buying
        else:
            return signal.price - slippage  # Receive slightly less when selling
    
    def _should_fill_order(self, signal_type: str, order_price: float, current_price: float) -> bool:
        """Determine if an order should be filled."""
        if self.config.fill_simulation == 'instant':
            return True
        
        # Realistic fill logic
        if 'entry' in signal_type:
            if 'long' in signal_type:
                return current_price <= order_price * 1.001  # Allow small tolerance
            else:
                return current_price >= order_price * 0.999
        else:
            # Exit orders are usually more urgent (market orders)
            return True
    
    def _create_trade_record(self, trade_type: str, direction: str, price: float, 
                           quantity: int, timestamp: int, signal: Signal,
                           entry_price: float = None, pnl: float = None) -> Dict[str, Any]:
        """Create standardized trade record."""
        trade = {
            'id': len(self.trades) + 1,
            'type': trade_type,
            'direction': direction,
            'timestamp': timestamp,
            'price': price,
            'quantity': quantity,
            'signal_metadata': signal.metadata,
            'strategy_signal': signal.signal_type
        }
        
        if entry_price is not None:
            trade['entry_price'] = entry_price
        if pnl is not None:
            trade['pnl'] = pnl
            trade['commission'] = self.config.commission_per_contract
            trade['net_pnl'] = pnl - self.config.commission_per_contract
        
        return trade
    
    def _check_risk_limits(self) -> bool:
        """Check if trade passes risk management rules."""
        # Max drawdown check
        peak_capital = max(self.current_capital, self.config.initial_capital)
        current_drawdown = (peak_capital - self.current_capital) / peak_capital
        
        if current_drawdown > self.config.max_drawdown:
            logger.warning(f"Max drawdown exceeded: {current_drawdown:.2%}")
            return False
        
        return True
    
    def update_equity(self, current_price: float, timestamp: int):
        """Update equity curve with current unrealized P&L using pre-allocated arrays."""
        # Check if we need to resize (unlikely with 100k pre-allocated points)
        if self.equity_idx >= self.max_equity_points:
            # Double the array size if needed
            new_size = self.max_equity_points * 2
            self.equity_timestamps = np.resize(self.equity_timestamps, new_size)
            self.equity_realized_pnl = np.resize(self.equity_realized_pnl, new_size)
            self.equity_unrealized_pnl = np.resize(self.equity_unrealized_pnl, new_size)
            self.equity_total = np.resize(self.equity_total, new_size)
            self.equity_position = np.resize(self.equity_position, new_size)
            self.max_equity_points = new_size
        
        # Calculate unrealized P&L
        if self.current_position != 0:
            if self.current_position > 0:
                self.unrealized_pnl = (current_price - self.current_avg_price) * self.current_position
            else:
                self.unrealized_pnl = (self.current_avg_price - current_price) * abs(self.current_position)
        else:
            self.unrealized_pnl = 0.0
        
        total_equity = self.current_capital + self.unrealized_pnl
        
        # Direct array assignment (MUCH faster than append)
        self.equity_timestamps[self.equity_idx] = timestamp
        self.equity_realized_pnl[self.equity_idx] = self.realized_pnl
        self.equity_unrealized_pnl[self.equity_idx] = self.unrealized_pnl
        self.equity_total[self.equity_idx] = total_equity
        self.equity_position[self.equity_idx] = self.current_position
        self.equity_idx += 1
    
    def get_performance_summary(self) -> Dict[str, Any]:
        """Get comprehensive performance summary."""
        completed_trades = [t for t in self.trades if t['type'] == 'exit']
        total_pnl = sum(t.get('pnl', 0) for t in completed_trades)
        
        winning_trades = [t for t in completed_trades if t.get('pnl', 0) > 0]
        losing_trades = [t for t in completed_trades if t.get('pnl', 0) < 0]
        
        win_rate = len(winning_trades) / len(completed_trades) if completed_trades else 0.0
        
        return {
            'total_signals': self.total_signals,
            'total_trades': len(completed_trades),
            'executed_trades': self.executed_trades,
            'total_pnl': total_pnl,
            'realized_pnl': self.realized_pnl,
            'unrealized_pnl': self.unrealized_pnl,
            'current_capital': self.current_capital,
            'win_rate': win_rate,
            'winning_trades': len(winning_trades),
            'losing_trades': len(losing_trades),
            'current_position': self.current_position,
            'avg_win': sum(t['pnl'] for t in winning_trades) / len(winning_trades) if winning_trades else 0.0,
            'avg_loss': sum(t['pnl'] for t in losing_trades) / len(losing_trades) if losing_trades else 0.0,
            'profit_factor': abs(sum(t['pnl'] for t in winning_trades) / sum(t['pnl'] for t in losing_trades)) if losing_trades else float('inf')
        }


class Backtester:
    """
    Main backtester that works with ANY strategy.
    
    This is the primary backtesting engine for the entire system.
    """
    
    def __init__(self):
        self.logger = logger
        
    def load_strategy(self, strategy_name: str, bar_aggregator: BarAggregator = None, config: BacktestConfig = None) -> BaseStrategy:
        """
        Dynamically load any strategy by name.
        
        Args:
            strategy_name: Name of strategy (e.g., 'wicktest', 'moving_average')
            bar_aggregator: Optional bar aggregator
            config: Optional backtest config for commission settings
            
        Returns:
            Instantiated strategy object
        """
        try:
            # Try to import from strategies directory
            module_name = f"backtester.strategies.{strategy_name}"
            strategy_module = importlib.import_module(module_name)
            
            # Look for create function or class
            create_func_name = f"create_{strategy_name}_strategy"
            if hasattr(strategy_module, create_func_name):
                create_func = getattr(strategy_module, create_func_name)
                # Try to pass bar_aggregator if the function accepts it
                try:
                    import inspect
                    sig = inspect.signature(create_func)
                    if 'bar_aggregator' in sig.parameters:
                        strategy = create_func(bar_aggregator=bar_aggregator)
                    else:
                        strategy = create_func()
                    
                    # Apply commission from config if provided
                    if config and hasattr(strategy, 'params'):
                        strategy.params.set_commission(config.commission_per_contract)
                        # Update simulator with new commission
                        if hasattr(strategy, 'simulator'):
                            strategy.simulator.commission_per_trade = config.commission_per_contract
                    
                    return strategy
                except:
                    strategy = create_func()
                    if config and hasattr(strategy, 'params'):
                        strategy.params.set_commission(config.commission_per_contract)
                        if hasattr(strategy, 'simulator'):
                            strategy.simulator.commission_per_trade = config.commission_per_contract
                    return strategy
            
            # Look for strategy class
            class_name = f"{strategy_name.title().replace('_', '')}Strategy"
            if hasattr(strategy_module, class_name):
                strategy_class = getattr(strategy_module, class_name)
                # Try to pass bar_aggregator if the constructor accepts it
                try:
                    import inspect
                    sig = inspect.signature(strategy_class.__init__)
                    if 'bar_aggregator' in sig.parameters:
                        # Need to create proper params first
                        params_class_name = f"{strategy_name.title().replace('_', '')}Params"
                        if hasattr(strategy_module, params_class_name):
                            params_class = getattr(strategy_module, params_class_name)
                            params = params_class()
                            
                            # Apply commission from config
                            if config:
                                params.set_commission(config.commission_per_contract)
                            
                            strategy = strategy_class(params, bar_aggregator=bar_aggregator)
                            return strategy
                    strategy = strategy_class()
                    if config and hasattr(strategy, 'params'):
                        strategy.params.set_commission(config.commission_per_contract)
                        if hasattr(strategy, 'simulator'):
                            strategy.simulator.commission_per_trade = config.commission_per_contract
                    return strategy
                except Exception as e:
                    strategy = strategy_class()
                    if config and hasattr(strategy, 'params'):
                        strategy.params.set_commission(config.commission_per_contract)
                        if hasattr(strategy, 'simulator'):
                            strategy.simulator.commission_per_trade = config.commission_per_contract
                    return strategy
            
            raise ValueError(f"No create function or strategy class found in {module_name}")
            
        except ImportError as e:
            logger.error(f"Could not import strategy '{strategy_name}': {e}")
            raise ValueError(f"Strategy '{strategy_name}' not found")
    
    def run_backtest(self, strategy_name: str, data_file: str, config: Dict[str, Any] = None) -> Dict[str, Any]:
        """
        Run backtest with any strategy on any data.
        
        Args:
            strategy_name: Name of strategy to test
            data_file: Path to parquet data file
            config: Configuration parameters
            
        Returns:
            Complete backtest results
        """
        config = config or {}
        backtest_config = BacktestConfig(**config)
        
        logger.info(f"Starting backtest: {strategy_name}")
        logger.info(f"Data file: {data_file}")
        logger.info(f"Config: {config}")
        
        try:
            # 1. Initialize bar aggregator for strategies that need bars
            bar_period_minutes = 5  # Default to 5-minute bars
            if 'bar_timeframe' in config:
                timeframe = config['bar_timeframe']
                if timeframe.endswith('T'):
                    bar_period_minutes = int(timeframe[:-1])
            
            bar_aggregator = BarAggregator(bar_period_minutes=bar_period_minutes)
            
            # 2. Load strategy with bar aggregator and config for commission
            logger.info(f"Loading strategy: {strategy_name}")
            strategy = self.load_strategy(strategy_name, bar_aggregator, config=backtest_config)
            strategy_info = strategy.get_strategy_info()
            logger.info(f"Strategy loaded: {strategy_info.get('name', strategy_name)}")
            
            # Configure order book simulation in strategy's simulator
            if hasattr(strategy, 'simulator') and backtest_config.use_order_book:
                strategy.simulator.use_order_book = True
                strategy.simulator.order_book = OrderBook(max_levels=backtest_config.max_order_book_levels)
                logger.info(f"Order book configured in strategy simulator (max {backtest_config.max_order_book_levels} levels)")
            
            # 3. Load data with Polars (much faster than pandas)
            logger.info("Loading market data...")
            data = pl.read_parquet(data_file)
            
            # CRITICAL: Separate L1 (trades) and L2 (order book) data
            # If order book simulation is enabled, we'll maintain live order book state
            use_order_book = backtest_config.use_order_book
            l2_data = None
            l2_event_map = {}
            
            if use_order_book and 'record_type' in data.columns:
                # Check if we have L2 data
                l2_count = data.filter(pl.col('record_type') == 'L2').height
                if l2_count > 0:
                    logger.info(f"📚 Order book simulation ENABLED - {l2_count:,} L2 events found")
                    
                    # Separate L1 and L2 data
                    l1_data = data.filter(pl.col('record_type') == 'L1').sort('timestamp')
                    l2_data = data.filter(pl.col('record_type') == 'L2').sort('timestamp')
                    
                    # Build L2 event map: group L2 events by their timestamp
                    # This allows us to batch-process all L2 events that occur before each L1 tick
                    logger.info("Building L2 event map for batch processing...")
                    l2_timestamps = l2_data['timestamp'].to_numpy()
                    l2_types = l2_data['market_data_type'].to_numpy().astype(np.int16)
                    l2_operations = l2_data['operation'].to_numpy().astype(np.int16)
                    l2_positions = l2_data['position'].to_numpy().astype(np.int32)
                    l2_prices = l2_data['price'].to_numpy().astype(np.float64)
                    l2_volumes = l2_data['volume'].to_numpy().astype(np.int32)
                    
                    # Group L2 events by timestamp for efficient lookup
                    from collections import defaultdict
                    l2_event_map = defaultdict(lambda: {'indices': []})
                    for i in range(len(l2_timestamps)):
                        l2_event_map[l2_timestamps[i]]['indices'].append(i)
                    
                    # Pre-build numpy arrays for each timestamp to avoid repeated slicing
                    for ts in l2_event_map:
                        indices = l2_event_map[ts]['indices']
                        l2_event_map[ts] = {
                            'market_data_types': l2_types[indices],
                            'operations': l2_operations[indices],
                            'positions': l2_positions[indices],
                            'prices': l2_prices[indices],
                            'volumes': l2_volumes[indices]
                        }
                    
                    logger.info(f"L2 event map built: {len(l2_event_map)} unique timestamps")
                    
                    # Use L1 data only for tick processing
                    data = l1_data
                else:
                    logger.info("No L2 data found - order book simulation disabled")
                    use_order_book = False
            
            # NOTE: DO NOT filter to trades only! We need bid/ask quotes for limit order simulation
            # Filter to TRADES ONLY (market_data_type == 2) for OHLC bar building ONLY
            # But keep bid/ask quotes (0, 1) for realistic limit order fills
            # This matches production order routing where limit orders fill at bid/ask, not mid
            if 'market_data_type' in data.columns:
                logger.info(f"Loaded {len(data):,} ticks (trades + bid/ask quotes)")
            else:
                logger.warning("No 'market_data_type' column found - using all data (may include bid/ask quotes)")
            
            if backtest_config.max_ticks and len(data) > backtest_config.max_ticks:
                data = data.head(backtest_config.max_ticks)
                logger.info(f"Limited to {backtest_config.max_ticks:,} ticks")
            
            logger.info(f"Loaded {len(data):,} ticks")
            
            # 4. Initialize trading engine
            logger.info("Initializing trading engine...")
            trading_engine = TradingEngine(backtest_config)
            
            # 5. Run backtest
            logger.info("Starting backtest execution...")
            start_time = time.time()
            
            tick_count = 0
            bars_created = 0
            
            # Ensure data has proper columns
            if 'last_price' not in data.columns and 'price' in data.columns:
                data = data.with_columns(pl.col('price').alias('last_price'))
            
            # CRITICAL: Sort data by timestamp to ensure chronological order
            # Market data files may contain out-of-order ticks
            data = data.sort('timestamp')
            
            # OPTIMIZATION: Convert to numpy arrays for fast iteration
            # This is 10-20x faster than iterating over Polars rows
            timestamps = data['timestamp'].to_numpy()
            prices = data['last_price'].to_numpy()
            
            # Extract market_data_type for bid/ask handling (0=ask, 1=bid, 2=trade)
            market_data_types = data['market_data_type'].to_numpy() if 'market_data_type' in data.columns else None
            
            # Convert timestamps to nanoseconds upfront
            # Check if timestamps are datetime objects or already numeric
            if timestamps.dtype.kind == 'M':  # datetime64
                # Convert to int64 (this gives us the value in the original unit)
                timestamps_int = timestamps.astype('int64')
                # Polars datetime is in microseconds, convert to nanoseconds
                timestamps_ns = timestamps_int * 1000
            elif timestamps.dtype.kind in ['i', 'u']:  # integer types
                # Already numeric, assume it's in the right unit
                timestamps_ns = timestamps
            else:
                # Handle other types (float, object)
                timestamps_ns = (timestamps * 1e9).astype('int64')
            
            total_ticks = len(timestamps_ns)
            
            # Pre-allocate variables to avoid lookups in tight loop
            last_log_tick = 0
            log_interval = 100000
            equity_interval = 100000  # Match progress bar interval (was 5000)
            
            # Process ticks with progress bar
            with tqdm(total=total_ticks, desc="🔄 Processing ticks", 
                     unit="ticks", unit_scale=True, 
                     bar_format='{desc}: {percentage:3.0f}%|{bar}| {n_fmt}/{total_fmt} [{elapsed}<{remaining}, {rate_fmt}]') as pbar:
                
                for i in range(total_ticks):
                    tick_count += 1
                    timestamp_ns = timestamps_ns[i]  # Already int64, no conversion needed
                    price = prices[i]  # Already float, no conversion needed
                    
                    # Extract bid/ask from market data type (0=ask, 1=bid, 2=trade)
                    bid = None
                    ask = None
                    if market_data_types is not None:
                        if market_data_types[i] == 0:  # Ask quote
                            ask = price
                        elif market_data_types[i] == 1:  # Bid quote
                            bid = price
                    
                    # Process L2 order book events before this L1 tick (if available)
                    l2_events = None
                    if use_order_book and timestamps[i] in l2_event_map:
                        l2_events = l2_event_map[timestamps[i]]
                    
                    # Process tick through strategy (handles bar aggregation automatically)
                    try:
                        # Pass L2 events AND bid/ask to strategy's simulator via process_tick
                        signals, fills = strategy.process_tick(
                            timestamp_ns, 
                            price,
                            bid=bid,  # Pass bid if this is a bid quote
                            ask=ask,  # Pass ask if this is an ask quote
                            l2_events=l2_events  # Pass L2 batch for order book simulation
                        )
                        
                        # NOTE: Signals are already processed by BaseStrategy._process_signal()
                        # which submits orders to the LiveMarketSimulator. The TradingEngine
                        # is legacy code and would cause double-processing of signals.
                        # if signals:
                        #     for signal in signals:
                        #         trade_result = trading_engine.process_signal(signal, price, timestamp_ns)
                                    
                    except Exception as e:
                        if tick_count % 100000 == 0:  # Only log errors occasionally
                            pbar.write(f"[WARNING] Error at tick {tick_count}: {e}")
                        continue
                    
                    # Update equity curve periodically (less frequently for speed)
                    if tick_count % equity_interval == 0:
                        trading_engine.update_equity(price, timestamp_ns)
                    
                    # Update progress bar (batch updates for performance - every 100k for better speed)
                    if tick_count % 100000 == 0:
                        pbar.update(100000)
                        # Update description with performance metrics (simplified for speed)
                        elapsed = time.time() - start_time
                        rate = tick_count / elapsed if elapsed > 0 else 0
                        # Only update postfix, don't call expensive get_performance_summary()
                        pbar.set_postfix({
                            'Speed': f"{rate/1000:.0f}k/s"
                        })
                
                # Update remaining ticks
                remaining = total_ticks % 100000
                if remaining > 0:
                    pbar.update(remaining)
            
            # Final equity update
            trading_engine.update_equity(price, timestamp_ns)
            
            # 5. Generate results
            end_time = time.time()
            execution_time = end_time - start_time
            throughput = tick_count / execution_time if execution_time > 0 else 0
            
            performance = trading_engine.get_performance_summary()
            
            # Get final strategy info
            final_strategy_info = strategy.get_strategy_info()
            
            # Get simulator trades (the REAL trades)
            simulator_trades = strategy.simulator.get_completed_trades()
            simulator_stats = strategy.simulator.get_stats()
            
            logger.info("=== BACKTEST RESULTS ===")
            logger.info(f"Strategy: {strategy_info['name']}")
            logger.info(f"Execution time: {execution_time:.2f} seconds")
            logger.info(f"Ticks processed: {tick_count:,}")
            logger.info(f"Throughput: {throughput:,.0f} ticks/second")
            logger.info(f"Bars created: {final_strategy_info.get('bars_in_history', 0)}")
            logger.info(f"Signals generated: {performance['total_signals']}")
            logger.info(f"Trades executed (TradingEngine): {performance['total_trades']}")
            logger.info(f"Trades executed (Simulator): {len(simulator_trades)}")
            logger.info(f"Fills (Simulator): {simulator_stats['total_fills']}")
            logger.info(f"Total P&L: ${performance['total_pnl']:.2f}")
            logger.info(f"Win rate: {performance['win_rate']:.1%}")
            
            # Convert equity arrays to list format for compatibility
            equity_curve = [
                {
                    'timestamp': int(trading_engine.equity_timestamps[i]),
                    'realized_pnl': float(trading_engine.equity_realized_pnl[i]),
                    'unrealized_pnl': float(trading_engine.equity_unrealized_pnl[i]),
                    'total_equity': float(trading_engine.equity_total[i]),
                    'position': int(trading_engine.equity_position[i])
                }
                for i in range(trading_engine.equity_idx)
            ]
            
            results = {
                "success": True,
                "strategy_name": strategy_name,
                "data_file": data_file,  # Include data file path for date extraction
                "strategy_info": final_strategy_info,  # Use final state, not initial
                "execution_time": execution_time,
                "ticks_processed": tick_count,
                "throughput_ticks_per_second": throughput,
                "signals_generated": performance['total_signals'],
                "trades_executed": performance['total_trades'],
                "simulator_trades": len(simulator_trades),
                "simulator_fills": simulator_stats['total_fills'],
                "simulator_completed_trades": simulator_trades,  # Include actual trade objects
                "total_pnl": performance['total_pnl'],
                "realized_pnl": performance['realized_pnl'],
                "unrealized_pnl": performance['unrealized_pnl'],
                "win_rate": performance['win_rate'],
                "winning_trades": performance['winning_trades'],
                "losing_trades": performance['losing_trades'],
                "profit_factor": performance['profit_factor'],
                "performance_summary": performance,
                "trades": trading_engine.trades,
                "equity_curve": equity_curve,
                "config": config
            }
            
            logger.info("Backtest completed successfully!")
            return results
            
        except Exception as e:
            logger.error(f"Backtest failed: {e}")
            import traceback
            traceback.print_exc()
            return {"success": False, "error": str(e)}


def main():
    """Example usage of the Backtester."""
    backtester = Backtester()
    
    # Find data file
    project_root = Path(__file__).parent.parent.parent
    storage_path = project_root / 'storage' / 'parquet'
    
    data_file = None
    for dir_path in storage_path.glob('*'):
        if dir_path.is_dir() and 'NQ' in dir_path.name:
            parquet_files = sorted(dir_path.glob('*.parquet'))
            if parquet_files:
                data_file = parquet_files[0]
                break
    
    if not data_file:
        print("No data file found!")
        return
    
    # Test with WickTest strategy
    config = {
        'initial_capital': 100000,
        'max_ticks': 100000,
        'commission_per_contract': 2.50
    }
    
    results = backtester.run_backtest('wicktest', str(data_file), config)
    
    if results['success']:
        print(f"\n{'='*60}")
        print("BACKTESTER RESULTS")
        print(f"{'='*60}")
        print(f"Strategy: {results['strategy_name']}")
        print(f"Execution time: {results['execution_time']:.2f} seconds")
        print(f"Ticks processed: {results['ticks_processed']:,}")
        print(f"Throughput: {results['throughput_ticks_per_second']:,.0f} ticks/second")
        print(f"Signals generated: {results['signals_generated']}")
        print(f"Trades executed: {results['trades_executed']}")
        print(f"Total P&L: ${results['total_pnl']:.2f}")
        print(f"Win rate: {results['win_rate']:.1%}")
        print(f"Profit factor: {results['profit_factor']:.2f}")
        print(f"{'='*60}")
    else:
        print(f"Backtest failed: {results.get('error', 'Unknown error')}")


if __name__ == '__main__':
    main()