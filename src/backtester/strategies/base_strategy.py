"""
Base Strategy Class - Foundation for All Trading Strategies

Provides standardized interface for:
- Entry/exit signal generation
- Position and risk management
- Strategy parameter handling
- Performance tracking integration
"""

from abc import ABC, abstractmethod
from typing import Dict, List, Optional, Any, Callable, Union, Tuple
from dataclasses import dataclass, field
from datetime import datetime, timedelta
import polars as pl
import numpy as np

from ..engine.bar_aggregator import Bar, BarAggregator
from ..engine.live_market_simulator import LiveMarketSimulator, Order, Fill, Trade, Position, ExitReason


@dataclass
class Signal:
    """Trading signal with entry/exit information"""
    timestamp_ns: int
    signal_type: str  # 'entry_long', 'entry_short', 'exit_long', 'exit_short', 'close_all'
    price: float
    confidence: float = 1.0  # Signal confidence (0.0 to 1.0)
    metadata: Dict[str, Any] = field(default_factory=dict)
    
    @property
    def timestamp(self) -> datetime:
        return datetime.fromtimestamp(self.timestamp_ns / 1_000_000_000)
    
    @property
    def is_entry(self) -> bool:
        return self.signal_type.startswith('entry_')
    
    @property
    def is_exit(self) -> bool:
        return self.signal_type.startswith('exit_') or self.signal_type == 'close_all'
    
    @property
    def side(self) -> Optional[str]:
        if 'long' in self.signal_type:
            return 'long'
        elif 'short' in self.signal_type:
            return 'short'
        return None


@dataclass
class StrategyParams:
    """Base strategy parameters"""
    name: str = "BaseStrategy"
    max_position_size: int = 1
    risk_per_trade: float = 100.0  # Risk per trade in dollars
    max_daily_loss: float = 500.0  # Max daily loss in dollars
    commission_per_trade: float = 0.0  # Round trip commission (set via config, not here)
    point_value: float = 20.0  # Dollar value per point
    tick_size: float = 0.25  # Minimum price increment
    
    # Timing constraints
    start_time: str = "09:30:00"  # Strategy start time
    end_time: str = "16:00:00"    # Strategy end time
    max_trade_duration: int = 300  # Max trade duration in minutes
    
    # Risk management
    use_stops: bool = True
    use_targets: bool = True
    stop_loss_points: float = 4.0  # Stop loss in points
    profit_target_points: float = 8.0  # Profit target in points
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert parameters to dictionary"""
        return {
            'name': self.name,
            'max_position_size': self.max_position_size,
            'risk_per_trade': self.risk_per_trade,
            'max_daily_loss': self.max_daily_loss,
            'commission_per_trade': self.commission_per_trade,
            'point_value': self.point_value,
            'tick_size': self.tick_size,
            'start_time': self.start_time,
            'end_time': self.end_time,
            'max_trade_duration': self.max_trade_duration,
            'use_stops': self.use_stops,
            'use_targets': self.use_targets,
            'stop_loss_points': self.stop_loss_points,
            'profit_target_points': self.profit_target_points
        }
    
    def set_commission(self, commission: float):
        """Set commission (called from config/CLI)"""
        self.commission_per_trade = commission
        return self


class BaseStrategy(ABC):
    """
    Abstract base class for all trading strategies.
    
    Features:
    - Standardized signal generation interface
    - Integrated position and risk management
    - Performance tracking and statistics
    - Live market simulation integration
    - Configurable parameters and constraints
    """
    
    def __init__(
        self,
        params: StrategyParams,
        bar_aggregator: Optional[BarAggregator] = None
    ):
        """
        Initialize strategy.
        
        Args:
            params: Strategy parameters
            bar_aggregator: Optional bar aggregator for OHLC data
        """
        self.params = params
        self.bar_aggregator = bar_aggregator
        
        # Initialize market simulator
        self.simulator = LiveMarketSimulator(
            tick_size=params.tick_size,
            point_value=params.point_value,
            commission_per_trade=params.commission_per_trade,
            verbose=False  # Suppress fill/trade output during backtest
        )
        
        # Strategy state
        self.is_active: bool = False
        self.current_bar: Optional[Bar] = None
        self.bar_history: List[Bar] = []
        self.signals_generated: List[Signal] = []
        
        # Risk management state
        self.daily_pnl: float = 0.0
        self.max_daily_loss_hit: bool = False
        self.active_stop_order: Optional[str] = None
        self.active_target_order: Optional[str] = None
        self.position_entry_time_ns: Optional[int] = None
        
        # Performance tracking
        self.total_signals: int = 0
        self.total_entries: int = 0
        self.total_exits: int = 0
        self.start_time_ns: Optional[int] = None
        self.end_time_ns: Optional[int] = None
        
        # Custom strategy data
        self.custom_data: Dict[str, Any] = {}
        
        # Cache time parsing (CRITICAL OPTIMIZATION: 15-30% speedup)
        self._start_time_sec = self._parse_time_to_seconds(params.start_time)
        self._end_time_sec = self._parse_time_to_seconds(params.end_time)
    
    @abstractmethod
    def generate_signals(self, timestamp_ns: int, price: float, **kwargs) -> List[Signal]:
        """
        Generate trading signals based on market data.
        
        Args:
            timestamp_ns: Current timestamp in nanoseconds
            price: Current market price
            **kwargs: Additional market data (bid, ask, volume, etc.)
            
        Returns:
            List of trading signals
        """
        pass
    
    def process_tick(
        self,
        timestamp_ns: int,
        price: float,
        l2_events: Optional[Dict[str, Any]] = None,
        **kwargs
    ) -> Tuple[List[Signal], List[Fill]]:
        """
        Process a market tick through the strategy.
        
        Args:
            timestamp_ns: Tick timestamp in nanoseconds
            price: Tick price
            l2_events: Optional L2 order book events for realistic fill simulation
            **kwargs: Additional tick data
            
        Returns:
            Tuple of (signals generated, fills executed)
        """
        # Update simulator with tick (including L2 events for order book)
        fills = self.simulator.process_tick(
            timestamp_ns, 
            price, 
            l2_events=l2_events,
            **kwargs
        )
        
        # Update bar aggregator if available
        # IMPORTANT: Build OHLC bars from TRADE ticks only (exclude bid/ask quotes)
        # Heuristic: in the engine, trade ticks are passed with bid=None and ask=None
        if self.bar_aggregator:
            bid = kwargs.get('bid', None)
            ask = kwargs.get('ask', None)
            is_trade_tick = (bid is None and ask is None)
            if is_trade_tick:
                new_bar = self.bar_aggregator.process_tick(timestamp_ns, price)
                if new_bar:
                    self.current_bar = new_bar
                    self.bar_history.append(new_bar)
        
        # Check if strategy should be active
        self._update_active_status(timestamp_ns)
        
        if not self.is_active:
            return [], fills
        
        # Update daily P&L tracking
        self._update_daily_pnl()
        
        # Check risk limits
        if self._check_risk_limits():
            return [], fills
        
        # Generate signals
        signals = self.generate_signals(timestamp_ns, price, **kwargs)
        
        # Process signals
        for signal in signals:
            self._process_signal(signal)
        
        # Update exit orders
        self._update_exit_orders(timestamp_ns, price)
        
        # Track performance
        self.total_signals += len(signals)
        self.signals_generated.extend(signals)
        
        return signals, fills
    
    def _process_signal(self, signal: Signal):
        """Process a generated signal"""
        position = self.simulator.get_position()
        
        if signal.signal_type == 'entry_long' and position.is_flat:
            self._enter_long(signal)
        elif signal.signal_type == 'entry_short' and position.is_flat:
            self._enter_short(signal)
        elif signal.signal_type == 'exit_long' and position.is_long:
            self._exit_position(signal)
        elif signal.signal_type == 'exit_short' and position.is_short:
            self._exit_position(signal)
        elif signal.signal_type == 'close_all' and not position.is_flat:
            self._exit_position(signal)
    
    def _enter_long(self, signal: Signal):
        """Enter long position"""
        # CRITICAL: Cancel any old exit orders before entering new position
        self._cancel_exit_orders()
        
        # If signal has a price, use LIMIT order for exact entry
        # Otherwise use MARKET order for immediate fill
        if signal.price is not None and signal.price > 0:
            from ..engine.live_market_simulator import OrderType
            order_id = self.simulator.submit_order(
                side='buy',
                quantity=self.params.max_position_size,
                order_type=OrderType.LIMIT,
                price=signal.price,
                label=f"{self.params.name}_ENTRY_LONG"
            )
        else:
            order_id = self.simulator.submit_order(
                side='buy',
                quantity=self.params.max_position_size,
                label=f"{self.params.name}_ENTRY_LONG"
            )
        
        self.position_entry_time_ns = signal.timestamp_ns
        self.total_entries += 1
        
        # NOTE: Exit orders will be set in _update_exit_orders after position opens
    
    def _enter_short(self, signal: Signal):
        """Enter short position"""
        # CRITICAL: Cancel any old exit orders before entering new position
        self._cancel_exit_orders()
        
        # If signal has a price, use LIMIT order for exact entry
        # Otherwise use MARKET order for immediate fill
        if signal.price is not None and signal.price > 0:
            from ..engine.live_market_simulator import OrderType
            order_id = self.simulator.submit_order(
                side='sell',
                quantity=self.params.max_position_size,
                order_type=OrderType.LIMIT,
                price=signal.price,
                label=f"{self.params.name}_ENTRY_SHORT"
            )
        else:
            order_id = self.simulator.submit_order(
                side='sell',
                quantity=self.params.max_position_size,
                label=f"{self.params.name}_ENTRY_SHORT"
            )
        
        self.position_entry_time_ns = signal.timestamp_ns
        self.total_entries += 1
        
        # NOTE: Exit orders will be set in _update_exit_orders after position opens
    
    def _exit_position(self, signal: Signal):
        """Exit current position"""
        position = self.simulator.get_position()
        
        if position.is_long:
            order_id = self.simulator.submit_order(
                side='sell',
                quantity=position.size,
                label=f"{self.params.name}_EXIT_LONG"
            )
        elif position.is_short:
            order_id = self.simulator.submit_order(
                side='buy',
                quantity=abs(position.size),
                label=f"{self.params.name}_EXIT_SHORT"
            )
        
        self._cancel_exit_orders()
        self.total_exits += 1
        self.position_entry_time_ns = None
    
    def _set_exit_orders(self, entry_price: float, side: str):
        """Set stop loss and profit target orders"""
        from ..engine.live_market_simulator import OrderType
        
        # CRITICAL: Cancel ALL existing orders first to prevent orphans
        self._cancel_exit_orders()  # Cancel existing orders first
        
        if side == 'long':
            if self.params.use_stops:
                stop_price = entry_price - self.params.stop_loss_points
                self.active_stop_order = self.simulator.submit_order(
                    side='sell',
                    quantity=self.params.max_position_size,
                    order_type=OrderType.STOP,
                    stop_price=stop_price,
                    label=f"{self.params.name}_STOP_LONG"
                )
            
            if self.params.use_targets:
                target_price = entry_price + self.params.profit_target_points
                self.active_target_order = self.simulator.submit_order(
                    side='sell',
                    quantity=self.params.max_position_size,
                    order_type=OrderType.LIMIT,
                    price=target_price,
                    label=f"{self.params.name}_TARGET_LONG"
                )
        
        else:  # short
            if self.params.use_stops:
                stop_price = entry_price + self.params.stop_loss_points
                self.active_stop_order = self.simulator.submit_order(
                    side='buy',
                    quantity=self.params.max_position_size,
                    order_type=OrderType.STOP,
                    stop_price=stop_price,
                    label=f"{self.params.name}_STOP_SHORT"
                )
            
            if self.params.use_targets:
                target_price = entry_price - self.params.profit_target_points
                self.active_target_order = self.simulator.submit_order(
                    side='buy',
                    quantity=self.params.max_position_size,
                    order_type=OrderType.LIMIT,
                    price=target_price,
                    label=f"{self.params.name}_TARGET_SHORT"
                )
    
    def _cancel_exit_orders(self):
        """Cancel active stop and target orders"""
        if self.active_stop_order:
            self.simulator.cancel_order(self.active_stop_order)
            self.active_stop_order = None
        if self.active_target_order:
            self.simulator.cancel_order(self.active_target_order)
            self.active_target_order = None
    
    def _update_exit_orders(self, timestamp_ns: int, price: float):
        """Update exit orders based on current market conditions"""
        position = self.simulator.get_position()
        
        # CRITICAL: When position closes, cancel any remaining exit orders
        # (One of them filled to close the position, but the other is still pending!)
        if position.is_flat and (self.active_stop_order or self.active_target_order):
            self._cancel_exit_orders()  # Cancel orders, not just clear references
        
        # Set exit orders when position first opens (and we don't have exit orders yet)
        if not position.is_flat and self.active_stop_order is None and self.active_target_order is None:
            if self.params.use_stops or self.params.use_targets:
                side = 'long' if position.is_long else 'short'
                # Use actual position entry price, not signal price
                self._set_exit_orders(position.avg_price, side)
        
        # Check for position timeout
        if (self.position_entry_time_ns and 
            self.params.max_trade_duration > 0):
            
            duration_minutes = (timestamp_ns - self.position_entry_time_ns) / (60 * 1_000_000_000)
            if duration_minutes >= self.params.max_trade_duration:
                # Force exit on timeout
                timeout_signal = Signal(
                    timestamp_ns=timestamp_ns,
                    signal_type='close_all',
                    price=price,
                    metadata={'reason': 'timeout'}
                )
                self._process_signal(timeout_signal)
    
    def _update_active_status(self, timestamp_ns: int):
        """Update whether strategy should be active based on time constraints"""
        # CRITICAL OPTIMIZATION: Numeric comparison instead of string parsing (15-30% speedup)
        seconds_since_midnight = (timestamp_ns // 1_000_000_000) % 86400
        self.is_active = (self._start_time_sec <= seconds_since_midnight <= self._end_time_sec 
                          and not self.max_daily_loss_hit)
    
    def _parse_time_to_seconds(self, time_str: str) -> int:
        """Convert HH:MM:SS to seconds since midnight (parsed once, not every tick)"""
        h, m, s = map(int, time_str.split(':'))
        return h * 3600 + m * 60 + s
    
    def _update_daily_pnl(self):
        """Update daily P&L tracking"""
        position = self.simulator.get_position()
        # OPTIMIZATION: Only update if position exists (skip when flat)
        if position.is_flat and self.daily_pnl == 0.0:
            return
        self.daily_pnl = position.realized_pnl + position.unrealized_pnl
    
    def _check_risk_limits(self) -> bool:
        """Check if risk limits have been hit"""
        if self.daily_pnl <= -self.params.max_daily_loss:
            self.max_daily_loss_hit = True
            # Force close all positions
            position = self.simulator.get_position()
            if not position.is_flat:
                close_signal = Signal(
                    timestamp_ns=self.simulator.current_time_ns,
                    signal_type='close_all',
                    price=self.simulator.current_price,
                    metadata={'reason': 'max_daily_loss'}
                )
                self._process_signal(close_signal)
            return True
        
        return False
    
    def get_performance_stats(self) -> Dict[str, Any]:
        """Get strategy performance statistics"""
        trades = self.simulator.get_completed_trades()
        position = self.simulator.get_position()
        
        if not trades:
            return {
                'total_trades': 0,
                'total_pnl': position.realized_pnl + position.unrealized_pnl,
                'win_rate': 0.0,
                'avg_win': 0.0,
                'avg_loss': 0.0,
                'profit_factor': 0.0,
                'max_drawdown': 0.0,
                'sharpe_ratio': 0.0
            }
        
        # Basic statistics
        total_trades = len(trades)
        winning_trades = [t for t in trades if t.pnl > 0]
        losing_trades = [t for t in trades if t.pnl < 0]
        
        total_pnl = sum(t.pnl for t in trades) + position.unrealized_pnl
        win_rate = len(winning_trades) / total_trades if total_trades > 0 else 0.0
        
        avg_win = np.mean([t.pnl for t in winning_trades]) if winning_trades else 0.0
        avg_loss = np.mean([t.pnl for t in losing_trades]) if losing_trades else 0.0
        
        gross_profits = sum(t.pnl for t in winning_trades)
        gross_losses = abs(sum(t.pnl for t in losing_trades))
        profit_factor = gross_profits / gross_losses if gross_losses > 0 else float('inf')
        
        # Calculate drawdown
        cumulative_pnl = np.cumsum([t.pnl for t in trades])
        running_max = np.maximum.accumulate(cumulative_pnl)
        drawdowns = running_max - cumulative_pnl
        max_drawdown = np.max(drawdowns) if len(drawdowns) > 0 else 0.0
        
        # Calculate Sharpe ratio (simplified)
        if len(trades) > 1:
            returns = [t.pnl for t in trades]
            sharpe_ratio = np.mean(returns) / np.std(returns) * np.sqrt(252) if np.std(returns) > 0 else 0.0
        else:
            sharpe_ratio = 0.0
        
        return {
            'strategy_name': self.params.name,
            'total_trades': total_trades,
            'winning_trades': len(winning_trades),
            'losing_trades': len(losing_trades),
            'total_pnl': total_pnl,
            'gross_profits': gross_profits,
            'gross_losses': gross_losses,
            'win_rate': win_rate,
            'avg_win': avg_win,
            'avg_loss': avg_loss,
            'profit_factor': profit_factor,
            'max_drawdown': max_drawdown,
            'sharpe_ratio': sharpe_ratio,
            'total_signals': self.total_signals,
            'total_entries': self.total_entries,
            'total_exits': self.total_exits,
            'daily_pnl': self.daily_pnl,
            'max_daily_loss_hit': self.max_daily_loss_hit,
            'current_position': position.size,
            'unrealized_pnl': position.unrealized_pnl
        }
    
    def reset(self):
        """Reset strategy state for new backtest"""
        self.simulator.reset()
        self.is_active = False
        self.current_bar = None
        self.bar_history.clear()
        self.signals_generated.clear()
        
        self.daily_pnl = 0.0
        self.max_daily_loss_hit = False
        self.active_stop_order = None
        self.active_target_order = None
        self.position_entry_time_ns = None
        
        self.total_signals = 0
        self.total_entries = 0
        self.total_exits = 0
        self.start_time_ns = None
        self.end_time_ns = None
        
        self.custom_data.clear()
        
        if self.bar_aggregator:
            self.bar_aggregator.reset()
    
    def get_trades_df(self):
        """Get completed trades as Polars DataFrame"""
        import polars as pl
        trades = self.simulator.get_completed_trades()
        if not trades:
            return pl.DataFrame([])
        
        data = []
        for trade in trades:
            data.append({
                'entry_time': trade.entry_time,
                'exit_time': trade.exit_time,
                'side': trade.side,
                'quantity': trade.quantity,
                'entry_price': trade.entry_price,
                'exit_price': trade.exit_price,
                'pnl': trade.pnl,
                'commission': trade.commission,
                'exit_reason': trade.exit_reason.value,
                'duration_seconds': trade.duration_seconds
            })
        
        return pl.DataFrame(data)
    
    def get_signals_df(self):
        """Get generated signals as Polars DataFrame"""
        import polars as pl
        if not self.signals_generated:
            return pl.DataFrame([])
        
        data = []
        for signal in self.signals_generated:
            data.append({
                'timestamp': signal.timestamp,
                'signal_type': signal.signal_type,
                'price': signal.price,
                'confidence': signal.confidence,
                'metadata': str(signal.metadata)
            })
        
        return pl.DataFrame(data)

