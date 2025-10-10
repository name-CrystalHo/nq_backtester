"""
Order Manager - Realistic order execution simulation using order book depth

Simulates market order fills by walking through order book levels,
limit order fills with queue position tracking, and market impact modeling.
"""

import pandas as pd
from datetime import datetime
from typing import Dict, List, Optional, Tuple, Any
from enum import Enum
from dataclasses import dataclass
import logging
import uuid

from ..data.order_book import OrderBook

logger = logging.getLogger(__name__)


class OrderStatus(Enum):
    """Order status enumeration."""
    PENDING = "pending"
    FILLED = "filled"
    PARTIALLY_FILLED = "partially_filled"
    CANCELLED = "cancelled"
    REJECTED = "rejected"


class OrderType(Enum):
    """Order type enumeration."""
    MARKET = "market"
    LIMIT = "limit"
    STOP = "stop"
    STOP_LIMIT = "stop_limit"


@dataclass
class Fill:
    """Represents an order fill."""
    fill_id: str
    order_id: str
    price: float
    quantity: int
    timestamp: datetime
    commission: float = 0.0


@dataclass
class Order:
    """Represents a trading order."""
    order_id: str
    direction: str  # 'buy' or 'sell'
    quantity: int
    order_type: str
    timestamp: datetime
    limit_price: Optional[float] = None
    stop_price: Optional[float] = None
    filled_quantity: int = 0
    average_fill_price: float = 0.0
    status: OrderStatus = OrderStatus.PENDING
    fills: List[Fill] = None
    
    def __post_init__(self):
        if self.fills is None:
            self.fills = []
    
    @property
    def remaining_quantity(self) -> int:
        """Get remaining unfilled quantity."""
        return self.quantity - self.filled_quantity
    
    @property
    def is_filled(self) -> bool:
        """Check if order is completely filled."""
        return self.filled_quantity >= self.quantity
    
    @property
    def is_active(self) -> bool:
        """Check if order is active (pending or partially filled)."""
        return self.status in [OrderStatus.PENDING, OrderStatus.PARTIALLY_FILLED]


class OrderManager:
    """
    Manages order execution with realistic fill simulation.
    
    Features:
    - Market orders: Walk through order book levels
    - Limit orders: Fill when market reaches limit price
    - Market impact modeling for large orders
    - Partial fill handling
    """
    
    def __init__(self, order_book: OrderBook, config: Any):
        """
        Initialize order manager.
        
        Args:
            order_book: OrderBook instance for fill simulation
            config: Backtest configuration
        """
        self.order_book = order_book
        self.config = config
        
        # Order tracking
        self.active_orders: Dict[str, Order] = {}
        self.completed_orders: Dict[str, Order] = {}
        self.all_fills: List[Fill] = []
        
        # Statistics
        self.total_orders_submitted = 0
        self.total_fills = 0
        self.total_commission = 0.0
        
        # Track new fills for position updates
        self._new_fills: List[Fill] = []
        
        # Order ID generation
        self._next_order_id = 1
    
    def get_next_order_id(self) -> str:
        """Generate unique order ID."""
        order_id = f"ORD_{self._next_order_id:06d}"
        self._next_order_id += 1
        return order_id
    
    def submit_order(self, order: Order):
        """
        Submit order for execution.
        
        Args:
            order: Order to submit
        """
        self.active_orders[order.order_id] = order
        self.total_orders_submitted += 1
        
        logger.debug(f"Order submitted: {order.order_id} {order.direction} "
                    f"{order.quantity} @ {order.order_type}")
        
        # Try immediate execution for market orders
        if order.order_type == 'market':
            self._try_fill_market_order(order)
    
    def cancel_order(self, order_id: str) -> bool:
        """
        Cancel pending order.
        
        Args:
            order_id: ID of order to cancel
            
        Returns:
            True if order was cancelled successfully
        """
        if order_id in self.active_orders:
            order = self.active_orders[order_id]
            order.status = OrderStatus.CANCELLED
            self.completed_orders[order_id] = self.active_orders.pop(order_id)
            
            logger.debug(f"Order cancelled: {order_id}")
            return True
        
        return False
    
    def check_fills(self, current_timestamp: datetime):
        """
        Check all active orders for potential fills.
        
        Args:
            current_timestamp: Current market timestamp
        """
        orders_to_process = list(self.active_orders.values())
        
        for order in orders_to_process:
            if not order.is_active:
                continue
                
            if order.order_type == 'market':
                self._try_fill_market_order(order)
            elif order.order_type == 'limit':
                self._try_fill_limit_order(order)
            elif order.order_type == 'stop':
                self._try_trigger_stop_order(order, current_timestamp)
            elif order.order_type == 'stop_limit':
                self._try_trigger_stop_limit_order(order, current_timestamp)
    
    def _try_fill_market_order(self, order: Order):
        """
        Simulate market order fill using order book liquidity.
        
        Features:
        - Walk through order book levels
        - Calculate realistic average fill price
        - Handle partial fills if insufficient liquidity
        - Model slippage for large orders
        """
        if order.direction == 'buy':
            levels = self.order_book.get_ask_depth(levels=10)
        else:
            levels = self.order_book.get_bid_depth(levels=10)
        
        if not levels:
            logger.debug(f"No liquidity available for market order {order.order_id}")
            return
        
        remaining_qty = order.remaining_quantity
        total_cost = 0.0
        fills = []
        
        # Walk through order book levels
        for price, volume in levels:
            if remaining_qty <= 0:
                break
            
            # Calculate fill quantity for this level
            fill_qty = min(remaining_qty, volume)
            
            # Apply slippage for large orders
            adjusted_price = self._apply_slippage(price, fill_qty, volume, order.direction)
            
            fills.append({
                'price': adjusted_price,
                'quantity': fill_qty
            })
            
            total_cost += adjusted_price * fill_qty
            remaining_qty -= fill_qty
        
        if not fills:
            return
        
        # Calculate average fill price
        total_filled = sum(f['quantity'] for f in fills)
        avg_price = total_cost / total_filled
        
        # Create fill record
        fill = Fill(
            fill_id=f"FILL_{len(self.all_fills) + 1:06d}",
            order_id=order.order_id,
            price=avg_price,
            quantity=total_filled,
            timestamp=self.order_book.last_update or datetime.now(),
            commission=self.config.commission_per_contract * total_filled
        )
        
        # Update order
        self._execute_fill(order, fill)
        
        # Handle partial fills
        if remaining_qty > 0 and self.config.allow_partial_fills:
            order.status = OrderStatus.PARTIALLY_FILLED
            logger.debug(f"Partial fill: {order.order_id}, filled {total_filled}/{order.quantity}")
        else:
            logger.debug(f"Market order filled: {order.order_id} @ {avg_price:.2f}")
    
    def _try_fill_limit_order(self, order: Order):
        """
        Check if limit order can be filled.
        
        Logic:
        - Buy limit: fill if best ask <= limit price
        - Sell limit: fill if best bid >= limit price
        - Consider available volume at limit price
        """
        if order.direction == 'buy':
            best_ask, ask_volume = self.order_book.get_best_ask()
            if best_ask is not None and best_ask <= order.limit_price:
                # Can fill at or better than limit price
                fill_price = min(order.limit_price, best_ask)
                fill_qty = min(order.remaining_quantity, ask_volume)
                self._create_and_execute_fill(order, fill_price, fill_qty)
                
        else:  # sell
            best_bid, bid_volume = self.order_book.get_best_bid()
            if best_bid is not None and best_bid >= order.limit_price:
                # Can fill at or better than limit price
                fill_price = max(order.limit_price, best_bid)
                fill_qty = min(order.remaining_quantity, bid_volume)
                self._create_and_execute_fill(order, fill_price, fill_qty)
    
    def _try_trigger_stop_order(self, order: Order, current_timestamp: datetime):
        """Check if stop order should be triggered."""
        # Get current market price (use last price or mid price)
        current_price = self._get_current_market_price()
        if current_price is None:
            return
        
        triggered = False
        if order.direction == 'buy' and current_price >= order.stop_price:
            triggered = True
        elif order.direction == 'sell' and current_price <= order.stop_price:
            triggered = True
        
        if triggered:
            # Convert to market order
            order.order_type = 'market'
            order.stop_price = None
            logger.debug(f"Stop order triggered: {order.order_id} @ {current_price}")
            self._try_fill_market_order(order)
    
    def _try_trigger_stop_limit_order(self, order: Order, current_timestamp: datetime):
        """Check if stop-limit order should be triggered."""
        current_price = self._get_current_market_price()
        if current_price is None:
            return
        
        triggered = False
        if order.direction == 'buy' and current_price >= order.stop_price:
            triggered = True
        elif order.direction == 'sell' and current_price <= order.stop_price:
            triggered = True
        
        if triggered:
            # Convert to limit order
            order.order_type = 'limit'
            order.stop_price = None
            logger.debug(f"Stop-limit order triggered: {order.order_id}")
    
    def _apply_slippage(self, price: float, fill_qty: int, level_volume: int, 
                       direction: str) -> float:
        """
        Apply slippage based on order size vs available liquidity.
        
        Args:
            price: Base price
            fill_qty: Quantity being filled
            level_volume: Available volume at this level
            direction: 'buy' or 'sell'
            
        Returns:
            Adjusted price with slippage
        """
        if self.config.slippage_ticks <= 0:
            return price
        
        # Calculate liquidity consumption ratio
        consumption_ratio = fill_qty / level_volume if level_volume > 0 else 1.0
        
        # Apply slippage for large orders (>50% of level volume)
        if consumption_ratio > 0.5:
            slippage_ticks = self.config.slippage_ticks * consumption_ratio
            tick_size = 0.01  # Assume 1 cent tick size (configurable in future)
            
            if direction == 'buy':
                return price + (slippage_ticks * tick_size)
            else:
                return price - (slippage_ticks * tick_size)
        
        return price
    
    def _get_current_market_price(self) -> Optional[float]:
        """Get current market price for stop order evaluation."""
        # Try mid price first
        mid_price = self.order_book.get_mid_price()
        if mid_price is not None:
            return mid_price
        
        # Fall back to best bid/ask
        best_bid, _ = self.order_book.get_best_bid()
        best_ask, _ = self.order_book.get_best_ask()
        
        if best_bid is not None and best_ask is not None:
            return (best_bid + best_ask) / 2.0
        elif best_bid is not None:
            return best_bid
        elif best_ask is not None:
            return best_ask
        
        return None
    
    def _create_and_execute_fill(self, order: Order, price: float, quantity: int):
        """Create and execute a fill."""
        fill = Fill(
            fill_id=f"FILL_{len(self.all_fills) + 1:06d}",
            order_id=order.order_id,
            price=price,
            quantity=quantity,
            timestamp=self.order_book.last_update or datetime.now(),
            commission=self.config.commission_per_contract * quantity
        )
        
        self._execute_fill(order, fill)
    
    def _execute_fill(self, order: Order, fill: Fill):
        """Execute a fill and update order state."""
        # Update order
        old_filled_qty = order.filled_quantity
        old_avg_price = order.average_fill_price
        
        order.filled_quantity += fill.quantity
        order.fills.append(fill)
        
        # Calculate new average fill price
        if old_filled_qty == 0:
            order.average_fill_price = fill.price
        else:
            total_cost = (old_avg_price * old_filled_qty) + (fill.price * fill.quantity)
            order.average_fill_price = total_cost / order.filled_quantity
        
        # Update order status
        if order.is_filled:
            order.status = OrderStatus.FILLED
            self.completed_orders[order.order_id] = self.active_orders.pop(order.order_id)
        else:
            order.status = OrderStatus.PARTIALLY_FILLED
        
        # Track fill globally
        self.all_fills.append(fill)
        self._new_fills.append(fill)  # Track for position updates
        self.total_fills += 1
        self.total_commission += fill.commission
        
        logger.debug(f"Fill executed: {fill.order_id} {fill.quantity} @ {fill.price:.2f}")
    
    def get_order_status(self, order_id: str) -> Optional[OrderStatus]:
        """Get status of specific order."""
        if order_id in self.active_orders:
            return self.active_orders[order_id].status
        elif order_id in self.completed_orders:
            return self.completed_orders[order_id].status
        return None
    
    def get_all_fills(self) -> List[Fill]:
        """Get all fills for analysis."""
        return self.all_fills.copy()
    
    def get_order_history(self) -> List[Order]:
        """Get complete order history."""
        all_orders = list(self.completed_orders.values()) + list(self.active_orders.values())
        return sorted(all_orders, key=lambda o: o.timestamp)
    
    def get_statistics(self) -> Dict:
        """Get order manager statistics."""
        return {
            'total_orders_submitted': self.total_orders_submitted,
            'total_fills': self.total_fills,
            'active_orders': len(self.active_orders),
            'completed_orders': len(self.completed_orders),
            'total_commission': self.total_commission,
            'average_commission_per_fill': self.total_commission / max(1, self.total_fills),
        }