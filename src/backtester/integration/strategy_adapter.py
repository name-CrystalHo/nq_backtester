"""
Universal Strategy Backtester Adapter

This module provides a generic adapter interface that connects any BaseStrategy
implementation to the backtesting engine, enabling universal strategy execution
without strategy-specific modifications.

Key Features:
- Strategy-agnostic interface for any BaseStrategy implementation
- Signal translation and order management
- Performance tracking and analytics
- Position size management and risk controls
- Multi-strategy coordination support

Architecture:
- StrategyBacktesterAdapter: Main adapter class for strategy execution
- OrderSignal: Standardized signal format from strategies
- AdapterConfig: Configuration for adapter behavior and risk management

The adapter acts as a bridge between strategy logic and backtesting execution,
handling signal processing, order placement, position management, and performance
measurement in a unified, reusable manner.
"""

import logging
from typing import Optional, Dict, Any, List, Union, Tuple, Protocol
from dataclasses import dataclass, field
from datetime import datetime
import time

# Import base strategy interface
from ..strategies.base_strategy import BaseStrategy, Signal

logger = logging.getLogger(__name__)


# Protocol interfaces for dependency injection (allows mocking in tests)
class OrderManagerProtocol(Protocol):
    """Protocol for order manager dependencies."""
    def place_order(self, **kwargs) -> str: ...


class PositionTrackerProtocol(Protocol):
    """Protocol for position tracker dependencies."""
    def get_current_position(self) -> int: ...


@dataclass
class OrderSignal:
    """Standardized signal format from strategies to adapter."""
    action: str  # "BUY", "SELL", "EXIT"
    quantity: int
    order_type: str = "MARKET"  # "MARKET", "LIMIT", "STOP"
    price: Optional[float] = None  # For LIMIT orders
    stop_loss: Optional[float] = None
    take_profit: Optional[float] = None
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class AdapterConfig:
    """Configuration for strategy adapter behavior."""
    max_position_size: int = 1000
    risk_per_trade: float = 0.01  # 1% risk per trade
    enable_stop_loss: bool = True
    enable_take_profit: bool = True
    track_performance: bool = True
    log_signals: bool = False
    log_orders: bool = False


class StrategyBacktesterAdapter:
    """
    Universal adapter that connects any BaseStrategy to backtesting engines.
    
    This adapter provides a generic interface for:
    - Signal translation to orders
    - Position size management and risk controls
    - Performance tracking
    - Multi-strategy coordination
    """
    
    def __init__(
        self,
        strategy: BaseStrategy,
        order_manager: OrderManagerProtocol,
        position_tracker: PositionTrackerProtocol,
        config: Optional[AdapterConfig] = None
    ):
        """
        Initialize strategy adapter.
        
        Args:
            strategy: Any BaseStrategy implementation
            order_manager: Order management interface
            position_tracker: Position tracking interface
            config: Adapter configuration
        """
        self.strategy = strategy
        self.order_manager = order_manager
        self.position_tracker = position_tracker
        self.config = config or AdapterConfig()
        
        # Performance tracking
        self.total_signals = 0
        self.total_orders = 0
        self.signal_history: List[Dict[str, Any]] = []
        self.order_history: List[Dict[str, Any]] = []
        
        # Timing
        self.start_time = time.time()
        self.first_signal_time: Optional[float] = None
        self.last_signal_time: Optional[float] = None
        
        logger.debug(f"Strategy adapter initialized for {strategy.params.name}")
    
    def process_tick(self, timestamp_ns: int, price: float, **kwargs) -> List[str]:
        """
        Process market tick through the strategy and handle resulting signals.
        
        Args:
            timestamp_ns: Tick timestamp in nanoseconds
            price: Current price
            **kwargs: Additional market data
            
        Returns:
            List of order IDs that were successfully placed
        """
        try:
            # Generate signals from strategy
            signals = self.strategy.generate_signals(timestamp_ns, price, **kwargs)
            
            if not signals:
                return []
            
            # Track timing
            current_time = time.time()
            if self.first_signal_time is None:
                self.first_signal_time = current_time
            self.last_signal_time = current_time
            
            # Process each signal
            order_ids = []
            
            for signal in signals:
                self.total_signals += 1
                
                # Convert Strategy Signal to OrderSignal
                order_signal = self._convert_signal_to_order_signal(signal)
                if not order_signal:
                    continue
                
                # Log signal if enabled
                if self.config.log_signals:
                    self.signal_history.append({
                        'timestamp': timestamp_ns,
                        'price': price,
                        'signal': signal,
                        'order_signal': order_signal
                    })
                
                # Convert signal to order
                order_id = self._process_signal(order_signal, timestamp_ns, price)
                if order_id:
                    order_ids.append(order_id)
            
            return order_ids
            
        except Exception as e:
            logger.error(f"Error processing tick in strategy adapter: {e}")
            return []
    
    def _convert_signal_to_order_signal(self, signal: Signal) -> Optional[OrderSignal]:
        """
        Convert Strategy Signal to OrderSignal format.
        
        Args:
            signal: Signal from strategy
            
        Returns:
            OrderSignal object or None if signal cannot be converted
        """
        try:
            # Map signal types to actions
            action_mapping = {
                "entry_long": "BUY",
                "entry_short": "SELL",
                "exit_long": "SELL",
                "exit_short": "BUY",
                "close_all": "EXIT"
            }
            
            action = action_mapping.get(signal.signal_type)
            if not action:
                logger.warning(f"Unknown signal type: {signal.signal_type}")
                return None
            
            # Default quantity (could be enhanced based on signal metadata)
            quantity = signal.metadata.get("quantity", 1)
            
            # Create OrderSignal
            order_signal = OrderSignal(
                action=action,
                quantity=quantity,
                order_type="MARKET",  # Default to market orders
                price=signal.price if action == "LIMIT" else None,
                metadata={
                    "original_signal_type": signal.signal_type,
                    "confidence": signal.confidence,
                    "timestamp_ns": signal.timestamp_ns,
                    **signal.metadata
                }
            )
            
            return order_signal
            
        except Exception as e:
            logger.error(f"Error converting signal to order signal: {e}")
            return None
    
    def _process_signal(self, signal: OrderSignal, timestamp_ns: int, price: float) -> Optional[str]:
        """
        Convert strategy signal to backtester order.
        
        Args:
            signal: Signal from strategy
            timestamp_ns: Current timestamp
            price: Current price
            
        Returns:
            Order ID if order was placed successfully, None otherwise
        """
        try:
            # Check position limits
            current_position = self.position_tracker.get_current_position()
            adjusted_quantity = self._apply_position_limits(signal, current_position)
            
            if adjusted_quantity <= 0:
                logger.debug(f"Signal filtered out: quantity {adjusted_quantity}")
                return None
            
            # Build order parameters
            order_params = {
                'action': signal.action,
                'quantity': adjusted_quantity,
                'order_type': signal.order_type,
                'timestamp': timestamp_ns
            }
            
            # Add price for limit orders
            if signal.order_type == "LIMIT" and signal.price:
                order_params['price'] = signal.price
            
            # Add risk management parameters if enabled
            if self.config.enable_stop_loss and signal.stop_loss:
                order_params['stop_loss'] = signal.stop_loss
                
            if self.config.enable_take_profit and signal.take_profit:
                order_params['take_profit'] = signal.take_profit
            
            # Add metadata
            if signal.metadata:
                order_params['metadata'] = signal.metadata
            
            # Place order through order manager
            order_id = self.order_manager.place_order(**order_params)
            
            if order_id:
                self.total_orders += 1
                
                # Log order if enabled
                if self.config.log_orders:
                    self.order_history.append({
                        'timestamp': timestamp_ns,
                        'price': price,
                        'order_id': order_id,
                        'order_params': order_params,
                        'original_signal': signal
                    })
                
                logger.debug(f"Order placed: {order_id}")
                return order_id
            
            return None
            
        except Exception as e:
            logger.error(f"Error processing signal: {e}")
            return None
    
    def _apply_position_limits(self, signal: OrderSignal, current_position: int) -> int:
        """
        Apply position size limits and risk management to signal quantity.
        
        Args:
            signal: Original signal
            current_position: Current position size
            
        Returns:
            Adjusted quantity that respects limits
        """
        max_size = self.config.max_position_size
        
        if signal.action.upper() == "BUY":
            # Check how much we can buy without exceeding limits
            available_size = max_size - current_position
            return min(signal.quantity, max(0, available_size))
            
        elif signal.action.upper() == "SELL":
            # Check how much we can sell (limited by current position for shorts)
            if current_position > 0:
                # Selling long position
                return min(signal.quantity, current_position)
            else:
                # Short selling
                available_short = max_size + current_position  # current_position is negative
                return min(signal.quantity, max(0, available_short))
        
        return signal.quantity
    
    def reset(self):
        """Reset adapter state for new backtest run."""
        self.total_signals = 0
        self.total_orders = 0
        self.signal_history.clear()
        self.order_history.clear()
        
        self.start_time = time.time()
        self.first_signal_time = None
        self.last_signal_time = None
        
        # Reset strategy
        if self.strategy:
            self.strategy.reset()
        
        logger.debug("Strategy adapter reset")
    
    def get_performance_stats(self) -> Dict[str, Any]:
        """
        Get performance statistics for the adapter.
        
        Returns:
            Dictionary containing performance metrics
        """
        current_time = time.time()
        
        stats = {
            'total_signals': self.total_signals,
            'total_orders': self.total_orders,
            'signal_to_order_ratio': self.total_orders / max(1, self.total_signals),
            'total_runtime_seconds': current_time - self.start_time
        }
        
        # Timing statistics
        if self.first_signal_time and self.last_signal_time:
            stats['first_signal_time'] = self.first_signal_time
            stats['last_signal_time'] = self.last_signal_time
            stats['signal_duration_seconds'] = self.last_signal_time - self.first_signal_time
        
        # Signal breakdown by action
        if self.signal_history:
            actions = {}
            for entry in self.signal_history:
                action = entry['signal'].action
                actions[action] = actions.get(action, 0) + 1
            stats['signals_by_action'] = actions
        
        # Order breakdown if tracking orders
        if self.order_history:
            stats['order_history_count'] = len(self.order_history)
        
        return stats


# Factory function for easy creation
def create_strategy_adapter(
    strategy: BaseStrategy,
    order_manager: OrderManagerProtocol,
    position_tracker: PositionTrackerProtocol,
    **config_kwargs
) -> StrategyBacktesterAdapter:
    """
    Factory function to create a strategy adapter.
    
    Args:
        strategy: Strategy to adapt
        order_manager: Order management interface
        position_tracker: Position tracking interface
        **config_kwargs: Configuration parameters for AdapterConfig
        
    Returns:
        Configured StrategyBacktesterAdapter
    """
    config = AdapterConfig(**config_kwargs)
    return StrategyBacktesterAdapter(strategy, order_manager, position_tracker, config)