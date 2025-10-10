"""
Position Tracker - Track positions, PnL, and equity curve during backtest

Maintains real-time position state, calculates realized/unrealized P&L,
and tracks equity curve for performance analysis.
"""

from datetime import datetime
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass
import logging

logger = logging.getLogger(__name__)


@dataclass
class Position:
    """Represents current position state."""
    size: int = 0  # Positive = long, negative = short, zero = flat
    average_price: float = 0.0
    entry_timestamp: Optional[datetime] = None
    unrealized_pnl: float = 0.0
    
    @property
    def is_long(self) -> bool:
        return self.size > 0
    
    @property
    def is_short(self) -> bool:
        return self.size < 0
    
    @property
    def is_flat(self) -> bool:
        return self.size == 0
    
    @property
    def abs_size(self) -> int:
        return abs(self.size)


@dataclass  
class Trade:
    """Represents a completed trade (entry to exit)."""
    entry_timestamp: datetime
    exit_timestamp: datetime
    direction: str  # 'long' or 'short'
    quantity: int
    entry_price: float
    exit_price: float
    pnl: float
    commission: float
    bars_held: int = 0
    mae: float = 0.0  # Maximum Adverse Excursion
    mfe: float = 0.0  # Maximum Favorable Excursion


@dataclass
class EquityPoint:
    """Single point on equity curve."""
    timestamp: datetime
    equity: float
    realized_pnl: float
    unrealized_pnl: float
    position_size: int
    drawdown: float = 0.0
    drawdown_pct: float = 0.0


class PositionTracker:
    """
    Tracks position state, P&L, and equity curve in real-time.
    
    Features:
    - Position sizing with average entry price calculation
    - Realized P&L calculation on position changes
    - Unrealized P&L mark-to-market updates
    - Equity curve generation
    - Trade history with detailed metrics
    """
    
    def __init__(self, initial_capital: float = 100000.0):
        """
        Initialize position tracker.
        
        Args:
            initial_capital: Starting capital amount
        """
        self.initial_capital = initial_capital
        self.current_capital = initial_capital
        
        # Position state
        self.position = Position()
        
        # P&L tracking
        self.realized_pnl = 0.0
        self.total_commission = 0.0
        
        # Trade history
        self.completed_trades: List[Trade] = []
        self.equity_curve: List[EquityPoint] = []
        
        # Peak tracking for drawdown
        self.peak_equity = initial_capital
        self.current_drawdown = 0.0
        self.max_drawdown = 0.0
        self.max_drawdown_pct = 0.0
        
        # Statistics
        self.total_trades = 0
        self.winning_trades = 0
        self.losing_trades = 0
        
        # Add initial equity point
        self._add_equity_point(datetime.now(), initial_capital, 0.0, 0.0, 0)
    
    def update_position(self, quantity: int, price: float, timestamp: datetime, 
                       commission: float = 0.0) -> Optional[Trade]:
        """
        Update position with new fill and calculate P&L.
        
        Args:
            quantity: Fill quantity (positive for buy, negative for sell)
            price: Fill price
            timestamp: Fill timestamp
            commission: Commission charged
            
        Returns:
            Trade object if position was closed/reduced, None otherwise
        """
        old_position = Position(
            size=self.position.size,
            average_price=self.position.average_price,
            entry_timestamp=self.position.entry_timestamp,
            unrealized_pnl=self.position.unrealized_pnl
        )
        
        trade = None
        realized_pnl = 0.0
        
        # Handle position changes
        if self.position.is_flat:
            # Opening new position
            self.position.size = quantity
            self.position.average_price = price
            self.position.entry_timestamp = timestamp
            
        elif (quantity > 0 and self.position.is_long) or (quantity < 0 and self.position.is_short):
            # Adding to existing position
            total_cost = (self.position.average_price * self.position.size) + (price * quantity)
            self.position.size += quantity
            self.position.average_price = total_cost / self.position.size
            
        else:
            # Reducing or reversing position
            if abs(quantity) >= self.position.abs_size:
                # Closing entire position (and possibly reversing)
                close_quantity = -self.position.size  # Quantity needed to close
                close_pnl = self._calculate_pnl(close_quantity, price, self.position.average_price)
                
                trade = Trade(
                    entry_timestamp=self.position.entry_timestamp,
                    exit_timestamp=timestamp,
                    direction='long' if old_position.is_long else 'short',
                    quantity=old_position.abs_size,
                    entry_price=old_position.average_price,
                    exit_price=price,
                    pnl=close_pnl,
                    commission=commission
                )
                
                realized_pnl = close_pnl
                
                # Check if reversing position
                remaining_quantity = quantity + self.position.size
                if remaining_quantity != 0:
                    self.position.size = remaining_quantity
                    self.position.average_price = price
                    self.position.entry_timestamp = timestamp
                else:
                    self.position.size = 0
                    self.position.average_price = 0.0
                    self.position.entry_timestamp = None
                    
            else:
                # Partial close
                close_pnl = self._calculate_pnl(quantity, price, self.position.average_price)
                
                trade = Trade(
                    entry_timestamp=self.position.entry_timestamp,
                    exit_timestamp=timestamp,
                    direction='long' if old_position.is_long else 'short',
                    quantity=abs(quantity),
                    entry_price=old_position.average_price,
                    exit_price=price,
                    pnl=close_pnl,
                    commission=commission
                )
                
                realized_pnl = close_pnl
                self.position.size += quantity
        
        # Update P&L and capital
        if realized_pnl != 0:
            self.realized_pnl += realized_pnl
            self.current_capital += realized_pnl
            
        self.total_commission += commission
        self.current_capital -= commission
        
        # Record trade
        if trade:
            self.completed_trades.append(trade)
            self.total_trades += 1
            
            if trade.pnl > 0:
                self.winning_trades += 1
            elif trade.pnl < 0:
                self.losing_trades += 1
        
        # Update unrealized P&L with current price
        self.update_unrealized_pnl(timestamp, price)
        
        return trade
    
    def update_unrealized_pnl(self, timestamp: datetime, current_price: float):
        """
        Update unrealized P&L based on current market price.
        
        Args:
            timestamp: Current timestamp
            current_price: Current market price
        """
        if self.position.is_flat or current_price <= 0:
            self.position.unrealized_pnl = 0.0
        else:
            self.position.unrealized_pnl = self._calculate_pnl(
                -self.position.size,  # Negative to calculate exit P&L
                current_price,
                self.position.average_price
            )
        
        # Update equity curve
        current_equity = self.get_current_equity()
        self._add_equity_point(
            timestamp, 
            current_equity, 
            self.realized_pnl, 
            self.position.unrealized_pnl,
            self.position.size
        )
    
    def _calculate_pnl(self, quantity: int, exit_price: float, entry_price: float) -> float:
        """
        Calculate P&L for position change.
        
        Args:
            quantity: Quantity being closed (negative of position size)
            exit_price: Exit price
            entry_price: Entry price
            
        Returns:
            Realized P&L
        """
        return quantity * (exit_price - entry_price)
    
    def _add_equity_point(self, timestamp: datetime, equity: float, 
                         realized_pnl: float, unrealized_pnl: float, position_size: int):
        """Add point to equity curve and update drawdown."""
        # Update peak and drawdown
        if equity > self.peak_equity:
            self.peak_equity = equity
            
        self.current_drawdown = self.peak_equity - equity
        self.max_drawdown = max(self.max_drawdown, self.current_drawdown)
        
        drawdown_pct = self.current_drawdown / self.peak_equity if self.peak_equity > 0 else 0
        self.max_drawdown_pct = max(self.max_drawdown_pct, drawdown_pct)
        
        # Add equity point
        equity_point = EquityPoint(
            timestamp=timestamp,
            equity=equity,
            realized_pnl=realized_pnl,
            unrealized_pnl=unrealized_pnl,
            position_size=position_size,
            drawdown=self.current_drawdown,
            drawdown_pct=drawdown_pct
        )
        
        self.equity_curve.append(equity_point)
    
    def get_current_equity(self) -> float:
        """Get current total equity (capital + unrealized P&L)."""
        return self.current_capital + self.position.unrealized_pnl
    
    def get_total_pnl(self) -> float:
        """Get total P&L (realized + unrealized)."""
        return self.realized_pnl + self.position.unrealized_pnl
    
    def get_statistics(self) -> Dict:
        """Get comprehensive position statistics."""
        if not self.completed_trades:
            return {
                'total_trades': 0,
                'winning_trades': 0,
                'losing_trades': 0,
                'win_rate': 0.0,
                'avg_win': 0.0,
                'avg_loss': 0.0,
                'avg_trade': 0.0,
                'profit_factor': 0.0,
                'largest_win': 0.0,
                'largest_loss': 0.0,
                'gross_profit': 0.0,
                'gross_loss': 0.0,
                'total_net_profit': self.get_total_pnl(),
                'realized_pnl': self.realized_pnl,
                'unrealized_pnl': self.position.unrealized_pnl,
                'max_drawdown': self.max_drawdown,
                'max_drawdown_pct': self.max_drawdown_pct,
                'current_position': self.position.size,
                'current_equity': self.initial_capital + self.get_total_pnl(),
                'total_commission': self.total_commission,
            }
        
        # Calculate trade statistics
        winning_trades = [t for t in self.completed_trades if t.pnl > 0]
        losing_trades = [t for t in self.completed_trades if t.pnl < 0]
        
        gross_profit = sum(t.pnl for t in winning_trades)
        gross_loss = sum(t.pnl for t in losing_trades)
        
        avg_win = gross_profit / len(winning_trades) if winning_trades else 0.0  
        avg_loss = gross_loss / len(losing_trades) if losing_trades else 0.0
        avg_trade = sum(t.pnl for t in self.completed_trades) / len(self.completed_trades)
        
        profit_factor = abs(gross_profit / gross_loss) if gross_loss != 0 else float('inf')
        
        largest_win = max((t.pnl for t in self.completed_trades), default=0.0)
        largest_loss = min((t.pnl for t in self.completed_trades), default=0.0)
        
        return {
            'total_trades': self.total_trades,
            'winning_trades': self.winning_trades,
            'losing_trades': self.losing_trades,
            'win_rate': self.winning_trades / self.total_trades if self.total_trades > 0 else 0.0,
            'avg_win': avg_win,
            'avg_loss': avg_loss,
            'avg_trade': avg_trade,
            'profit_factor': profit_factor,
            'largest_win': largest_win,
            'largest_loss': largest_loss,
            'gross_profit': gross_profit,
            'gross_loss': gross_loss,
            'total_net_profit': self.get_total_pnl(),
            'realized_pnl': self.realized_pnl,
            'unrealized_pnl': self.position.unrealized_pnl,
            'max_drawdown': self.max_drawdown,
            'max_drawdown_pct': self.max_drawdown_pct,
            'current_position': self.position.size,
            'current_equity': self.get_current_equity(),
            'total_commission': self.total_commission,
        }
    
    def get_trade_history(self) -> List[Trade]:
        """Get complete trade history."""
        return self.completed_trades.copy()
    
    def get_equity_curve_df(self):
        """Get equity curve as pandas DataFrame."""
        import pandas as pd
        
        if not self.equity_curve:
            return pd.DataFrame()
        
        data = []
        for point in self.equity_curve:
            data.append({
                'timestamp': point.timestamp,
                'equity': point.equity,
                'realized_pnl': point.realized_pnl,
                'unrealized_pnl': point.unrealized_pnl,
                'position_size': point.position_size,
                'drawdown': point.drawdown,
                'drawdown_pct': point.drawdown_pct,
            })
        
        return pd.DataFrame(data)
    
    def reset(self):
        """Reset tracker for new backtest."""
        self.current_capital = self.initial_capital
        self.position = Position()
        self.realized_pnl = 0.0
        self.total_commission = 0.0
        self.completed_trades.clear()
        self.equity_curve.clear()
        self.peak_equity = self.initial_capital
        self.current_drawdown = 0.0
        self.max_drawdown = 0.0
        self.max_drawdown_pct = 0.0
        self.total_trades = 0
        self.winning_trades = 0
        self.losing_trades = 0
        
        # Add initial equity point
        self._add_equity_point(datetime.now(), self.initial_capital, 0.0, 0.0, 0)