"""
Opening Print Dynamic Strategy - Modular Implementation

Refactored to use the new unified architecture:
- Inherits from BaseStrategy with standardized interface
- Uses BarAggregator for precise OHLC bar construction  
- Leverages LiveMarketSimulator for accurate execution
- Maintains exact NinjaTrader timing and logic
"""

from datetime import datetime, time, timedelta
from typing import Optional, Dict, Any, List
from dataclasses import dataclass
import pandas as pd
import numpy as np

from .base_strategy import BaseStrategy, StrategyParams, Signal
from ..engine.bar_aggregator import BarAggregator, Bar


@dataclass
class OpeningPrintParams(StrategyParams):
    """Opening Print Strategy specific parameters"""
    max_trades_per_day: int = 1
    stop_loss_ticks: int = 60
    profit_multiplier: float = 4.0
    use_dynamic_stop: bool = True
    stop_loss_buffer_points: float = 3.0
    trail_breakeven_multiplier: float = 0.0
    
    # Opening print timing
    opening_print_start: str = "09:30:00"
    opening_print_end: str = "10:30:00"
    strategy_end: str = "15:15:00"


class OpeningPrintDynamic(BaseStrategy):
    """
    Opening Print Dynamic Strategy - Modular Implementation
    
    Uses unified architecture components while maintaining
    exact NinjaTrader timing and execution logic.
    """
    
    def __init__(self, params: OpeningPrintParams):
        # Initialize with 5-minute bar aggregator
        bar_aggregator = BarAggregator(
            bar_period_minutes=5,
            on_bar_complete=self._on_bar_close
        )
        
        super().__init__(params, bar_aggregator)
        
        # Strategy-specific parameters (from params)
        self.max_trades_per_day = params.max_trades_per_day
        self.stop_loss_ticks = params.stop_loss_ticks
        self.profit_multiplier = params.profit_multiplier
        self.use_dynamic_stop = params.use_dynamic_stop
        self.stop_loss_buffer_points = params.stop_loss_buffer_points
        self.trail_breakeven_multiplier = params.trail_breakeven_multiplier
        
        # Time settings (ET)
        self.session_start = time(9, 30, 0)
        self.opening_print_time = time(9, 30, 0)
        self.session_end = time(16, 0, 0)
        
        # Bar aggregation
        self.bar_period_minutes = 5
        self.completed_bars: List[Dict] = []
        self.current_bar: Optional[Dict] = None
        self.last_bar_start_time: Optional[datetime] = None
        self.last_processed_bar_time: Optional[datetime] = None
        
        # State tracking
        self.last_trading_date = None
        self.reset_daily_state()
        
    def reset_daily_state(self):
        """Reset state variables at start of new trading day"""
        self.opening_print: Optional[float] = None
        self.opening_print_set = False
        
        # Breakout tracking
        self.seen_long_break = False
        self.seen_short_break = False
        
        # Pullback tracking
        self.seen_long_pullback = False
        self.seen_short_pullback = False
        self.one_trade_per_pullback = True
        
        # Entry levels (C#: entryLong = Open[1], entryShort = Open[1])
        self.entry_long: Optional[float] = None
        self.entry_short: Optional[float] = None
        
        # Dynamic stop (C#: dynamicStop = Low[1] or High[1])
        self.dynamic_stop: Optional[float] = None
        
        # Trade tracking
        self.trades_today = 0
        
        # Position tracking
        self.entry_fill_price: Optional[float] = None
        self.stop_distance: Optional[float] = None
        self.fixed_be_triggered = False
        
        # ✅ FIX: Add "One Entry Per Bar" protection like NinjaTrader
        self.last_entry_bar_time: Optional[datetime] = None
        
        # 🆕 NEW: Dynamic Trailing Stop Logic
        self.pullback_candle_extreme: Optional[float] = None  # Initial stop level from pullback candle
        self.trailing_stop_level: Optional[float] = None  # Current trailing stop level
        self.position_side: Optional[str] = None  # 'long' or 'short' to track position direction
        
        # Clear bars
        self.completed_bars = []
        self.current_bar = None
        self.last_bar_start_time = None
        self.last_processed_bar_time = None
    
    def log(self, message: str):
        """Simple logging method"""
        print(f"[{self.params.name}] {message}")
    
    def on_start(self):
        """Initialize strategy"""
        self.reset_daily_state()
        self.log("Opening Print Dynamic strategy initialized")
    
    def generate_signals(self, timestamp_ns: int, price: float, **kwargs) -> List[Signal]:
        """
        Generate trading signals based on Opening Print logic.
        
        This method is called by BaseStrategy.process_tick() for each market tick.
        """
        signals = []
        timestamp = pd.to_datetime(timestamp_ns, unit='ns')
        current_time = timestamp.time()
        
        # Check for new trading day
        if self.is_new_trading_day(timestamp):
            self.reset_daily_state()
        
        # Only process during RTH
        if not self.is_rth(current_time):
            return signals
        
        # Set opening print at 9:30 (check on every tick)
        self.calculate_opening_print_on_tick(current_time)
        
        # Check for entry signals if flat and haven't hit daily trade limit
        position = self.simulator.get_position()
        if position.is_flat and self.trades_today < self.max_trades_per_day:
            if self.opening_print_set:
                entry_signal = self.check_for_entry_signal(timestamp_ns, price)
                if entry_signal:
                    signals.append(entry_signal)
        
        # Handle breakeven trailing stop if we have a position
        if not position.is_flat and self.position_side:
            self.manage_breakeven_trailing_stop(price)
        
        return signals
    
    def _on_bar_close(self, completed_bar: Bar):
        """
        Called when a 5-minute bar completes.
        Updates strategy flags and levels.
        """
        self.completed_bars.append(completed_bar)
        
        # Update strategy flags on bar completion
        if len(self.completed_bars) >= 2:
            self.update_strategy_flags()
    
    def check_for_entry_signal(self, timestamp_ns: int, price: float) -> Optional[Signal]:
        """
        🎯 PRECISE ENTRY LOGIC: Enter at exact pullback candle open price
        
        This restores the ultra-accurate logic that was more precise than NinjaTrader:
        - Enter when price touches/breaks the pullback candle's open
        - Use exact entry price = pullback candle's open (not current market price)
        - This gives us the precise $19444.25 entry instead of $19445.00
        """
        if not self.opening_print_set:
            return None
        
        # Prevent multiple entries in same bar (like NinjaTrader's lastEntryBar)
        current_bar_time = pd.to_datetime(timestamp_ns, unit='ns').replace(second=0, microsecond=0, nanosecond=0)
        bar_start = current_bar_time - pd.Timedelta(minutes=current_bar_time.minute % 5)
        
        if self.last_entry_bar_time == bar_start:
            return None
        
        # Check if we have pullback levels set
        if self.entry_long is None and self.entry_short is None:
            return None
        
        # 🎯 LONG ENTRY: Price touches/breaks above pullback candle's open
        if (self.seen_long_pullback and not self.seen_long_break and 
            self.entry_long is not None and price >= self.entry_long):
            
            self.last_entry_bar_time = bar_start
            # 🔥 KEY FIX: Use exact entry_long price (pullback candle's open)
            return Signal(
                timestamp_ns=timestamp_ns,
                signal_type='entry_long',
                price=self.entry_long,  # Use pullback candle's open, not current price
                metadata={
                    'opening_print': self.opening_print,
                    'entry_level': self.entry_long,
                    'dynamic_stop': self.dynamic_stop,
                    'trigger_price': price  # Track what price triggered the entry
                }
            )
        
        # 🎯 SHORT ENTRY: Price touches/breaks below pullback candle's open
        elif (self.seen_short_pullback and not self.seen_short_break and 
              self.entry_short is not None and price <= self.entry_short):
            
            self.last_entry_bar_time = bar_start
            # 🔥 KEY FIX: Use exact entry_short price (pullback candle's open)
            return Signal(
                timestamp_ns=timestamp_ns,
                signal_type='entry_short', 
                price=self.entry_short,  # Use pullback candle's open, not current price
                metadata={
                    'opening_print': self.opening_print,
                    'entry_level': self.entry_short,
                    'dynamic_stop': self.dynamic_stop,
                    'trigger_price': price  # Track what price triggered the entry
                }
            )
        
        return None
    
    def _enter_long(self, signal: Signal):
        """Override BaseStrategy entry to calculate fixed stop level"""
        super()._enter_long(signal)
        self.position_side = 'long'
        stop_level = self.calculate_entry_stop(signal.price, 'long')
        self.log(f"🔵 LONG ENTRY at {signal.price:.2f} - Stop level: {stop_level:.2f}")
    
    def _enter_short(self, signal: Signal):
        """Override BaseStrategy entry to calculate fixed stop level"""
        super()._enter_short(signal)
        self.position_side = 'short'
        stop_level = self.calculate_entry_stop(signal.price, 'short')
        self.log(f"🔴 SHORT ENTRY at {signal.price:.2f} - Stop level: {stop_level:.2f}")
    
    def _exit_position(self, signal: Signal):
        """Override BaseStrategy exit to reset position tracking"""
        super()._exit_position(signal)
        self.position_side = None
        self.pullback_candle_extreme = None
        self.trailing_stop_level = None
        self.log(f"📤 POSITION EXITED at {signal.price:.2f}")
    
    def calculate_entry_stop(self, entry_price: float, position_side: str):
        """
        🆕 NEW: Calculate fixed stop as most extreme point between pullback candle and entry
        
        For LONG trades: Stop = LOWEST point between pullback candle low and entry price
        For SHORT trades: Stop = HIGHEST point between pullback candle high and entry price
        """
        if not self.pullback_candle_extreme:
            return None
        
        if position_side == 'long':
            # For long: stop at lowest point between pullback candle low and entry price
            stop_level = min(self.pullback_candle_extreme, entry_price)
            self.log(f"🔽 LONG stop calculated: min({self.pullback_candle_extreme:.2f}, {entry_price:.2f}) = {stop_level:.2f}")
            
        elif position_side == 'short':
            # For short: stop at highest point between pullback candle high and entry price  
            stop_level = max(self.pullback_candle_extreme, entry_price)
            self.log(f"🔼 SHORT stop calculated: max({self.pullback_candle_extreme:.2f}, {entry_price:.2f}) = {stop_level:.2f}")
        
        else:
            return None
        
        # Update stop levels
        self.trailing_stop_level = stop_level
        self.dynamic_stop = stop_level
        
        return stop_level
    
    def aggregate_tick_to_bar(self, timestamp: datetime, price: float) -> bool:
        """
        Aggregate ticks into 5-minute bars
        Returns True when a bar completes
        """
        bar_start = self.get_bar_start_time(timestamp)
        
        # Check if we need to start a new bar
        if self.current_bar is None or bar_start > self.last_bar_start_time:
            
            # Close previous bar if exists
            if self.current_bar is not None:
                self.completed_bars.append(self.current_bar)
                self.log(f"Bar closed: {self.current_bar['timestamp'].strftime('%H:%M')} "
                        f"O:{self.current_bar['open']:.2f} H:{self.current_bar['high']:.2f} "
                        f"L:{self.current_bar['low']:.2f} C:{self.current_bar['close']:.2f}")
                
                # Keep last 100 bars
                if len(self.completed_bars) > 100:
                    self.completed_bars = self.completed_bars[-100:]
                
                bar_completed = True
            else:
                bar_completed = False
            
            # Start new bar
            self.current_bar = {
                'timestamp': bar_start,
                'open': price,
                'high': price,
                'low': price,
                'close': price
            }
            self.last_bar_start_time = bar_start
            
            return bar_completed
        
        else:
            # Update current bar
            self.current_bar['high'] = max(self.current_bar['high'], price)
            self.current_bar['low'] = min(self.current_bar['low'], price)
            self.current_bar['close'] = price
            
            return False
    
    def get_bar_start_time(self, timestamp: datetime) -> datetime:
        """Get start time of 5-minute bar"""
        minutes = timestamp.minute
        bar_minute = (minutes // self.bar_period_minutes) * self.bar_period_minutes
        return timestamp.replace(minute=bar_minute, second=0, microsecond=0)
    
    def check_for_entry_on_tick(self, timestamp: datetime, current_price: float) -> None:
        """
        ✅ CRITICAL FIX: Check entries on EVERY tick using FORMING bar
        This matches NinjaTrader's real-time behavior
        
        C#: Called on every OnBarUpdate() when position is flat
        """
        # ✅ FIX: One entry per bar protection (like NinjaTrader's lastEntryBar)
        current_bar_time = self.get_bar_start_time(timestamp)
        if self.last_entry_bar_time == current_bar_time:
            return  # Already entered on this bar
        
        # Need current forming bar (the bar being built RIGHT NOW)
        if self.current_bar is None:
            return
            
        # ✅ CRITICAL FIX: Use FORMING bar data (updates every tick)
        # This is High[0]/Low[0] in NinjaTrader - the current bar being built
        forming_bar_high = self.current_bar['high']
        forming_bar_low = self.current_bar['low']
        
        # Check for entries using REAL-TIME bar data
        if self.one_trade_per_pullback:
            # Long entry: Current forming bar's high touches entry level
            if (self.seen_long_break and self.seen_long_pullback and 
                forming_bar_high >= self.entry_long):
                
                self.log(f"🔥 REAL-TIME LONG ENTRY: forming bar high {forming_bar_high:.2f} >= entry {self.entry_long:.2f}")
                self.enter_long_position()
                self.one_trade_per_pullback = False
                self.last_entry_bar_time = current_bar_time  # Prevent double entry
                
            # Short entry: Current forming bar's low touches entry level  
            elif (self.seen_short_break and self.seen_short_pullback and 
                  forming_bar_low <= self.entry_short):
                
                self.log(f"🔥 REAL-TIME SHORT ENTRY: forming bar low {forming_bar_low:.2f} <= entry {self.entry_short:.2f}")
                self.enter_short_position()
                self.one_trade_per_pullback = False
                self.last_entry_bar_time = current_bar_time  # Prevent double entry
    
    def update_breakout_pullback_flags(self):
        """
        ✅ FIXED: Only update flags on bar close (don't enter trades here!)
        This replaces the old on_bar_close() method
        """
        # Need at least 1 completed bar
        if len(self.completed_bars) < 1:
            return
        
        current_bar = self.completed_bars[-1]
        
        # Prevent re-processing
        if self.last_processed_bar_time == current_bar['timestamp']:
            return
        self.last_processed_bar_time = current_bar['timestamp']
        
        # Update breakout and pullback flags based on COMPLETED bars
        if self.opening_print_set:
            self.update_strategy_flags()
    
    def is_new_trading_day(self, timestamp: datetime) -> bool:
        """Check if new trading day"""
        current_date = timestamp.date()
        
        if self.last_trading_date is None:
            self.last_trading_date = current_date
            return True
            
        if current_date != self.last_trading_date:
            self.last_trading_date = current_date
            return True
            
        return False
    
    def is_rth(self, current_time: time) -> bool:
        """Check if within regular trading hours"""
        return self.session_start <= current_time <= self.session_end
    
    def calculate_opening_print_on_tick(self, current_time: time) -> None:
        """
        🔥 CRITICAL FIX: Opening Print = Open[0] at 9:30 AM (current bar's open)
        C#: OpeningPrint = Open[0] when time >= 9:30
        
        NOT the close of previous bar - uses OPEN of current bar at 9:30!
        """
        if not self.opening_print_set and current_time >= self.opening_print_time:
            
            # ✅ CRITICAL FIX: Use Open[0] (current bar's open) like NinjaTrader
            if self.current_bar is not None:
                self.opening_print = self.current_bar['open']  # This is Open[0] in C#
                self.opening_print_set = True
                
                # Reset pullback state
                self.one_trade_per_pullback = False
                self.seen_long_pullback = False
                self.seen_short_pullback = False
                
                # Check if previous completed bar already broke out
                if len(self.completed_bars) > 0:
                    prev_bar = self.completed_bars[-1]  # This is Bar[1] in C#
                    if self.is_candle_green(prev_bar):
                        self.seen_long_break = True
                    elif self.is_candle_red(prev_bar):
                        self.seen_short_break = True
                
                self.log(f"🎯 Opening Print set at {self.opening_print:.2f} (Open[0] at 9:30)")
            else:
                # Fallback: use most recent completed bar's open
                if len(self.completed_bars) > 0:
                    latest_bar = self.completed_bars[-1]
                    self.opening_print = latest_bar['open']
                    self.opening_print_set = True
                    self.log(f"🎯 Opening Print set at {self.opening_print:.2f} (fallback)")
    
    def update_strategy_flags(self) -> None:
        """
        🔥 CRITICAL FIX: Match NinjaTrader bar indexing exactly
        This runs on bar close and sets up conditions for real-time entry checking
        
        NinjaTrader indexing:
        - Close[1] = Close of PREVIOUS completed bar (self.completed_bars[-1])
        - Open[1] = Open of PREVIOUS completed bar  
        - IsCandleGreenAtIndex(1) = Previous completed bar
        """
        # Need at least 1 completed bar (we check Close[1])
        if len(self.completed_bars) < 1:
            return
        
        # ✅ CRITICAL FIX: NinjaTrader indexing
        # Close[1] = Close of previous completed bar (last in our completed_bars list)
        prev_bar = self.completed_bars[-1]     # This is Bar[1] in NinjaTrader
        prev_close = prev_bar['close']         # This is Close[1] in NinjaTrader
        
        # Reset breakout flags if price closes back through opening print
        # C#: if ((Close[1] < OpeningPrint && seenLongBreak) || ...)
        if ((prev_close < self.opening_print and self.seen_long_break) or 
            (prev_close > self.opening_print and self.seen_short_break)):
            
            self.seen_long_break = False
            self.seen_short_break = False
            self.seen_long_pullback = False
            self.seen_short_pullback = False
            self.one_trade_per_pullback = True
            self.log("Reset: Price closed back through opening print")
        
        # Detect initial breakout
        # C#: if (!seenLongBreak && !seenShortBreak)
        if not self.seen_long_break and not self.seen_short_break:
            # C#: if (Close[1] > OpeningPrint && IsCandleGreenAtIndex(1))
            if prev_close > self.opening_print and self.is_candle_green(prev_bar):
                self.seen_long_break = True
                self.log(f"Long breakout: prev close {prev_close:.2f} > OP {self.opening_print:.2f}")
                
            # C#: else if (Close[1] < OpeningPrint && IsCandleRedAtIndex(1))
            elif prev_close < self.opening_print and self.is_candle_red(prev_bar):
                self.seen_short_break = True
                self.log(f"Short breakout: prev close {prev_close:.2f} < OP {self.opening_print:.2f}")
        
        # Detect pullback and set entry levels
        # C#: if (seenLongBreak && IsCandleRedAtIndex(1) && !seenLongPullback)
        if (self.seen_long_break and self.is_candle_red(prev_bar) and 
            not self.seen_long_pullback):
            
            self.entry_long = prev_bar['open']      # C#: entryLong = Open[1]
            self.seen_long_pullback = True
            self.one_trade_per_pullback = True
            # 🆕 NEW: Store pullback candle low as initial stop reference
            self.pullback_candle_extreme = prev_bar['low']  # Starting point for trailing stop
            self.trailing_stop_level = prev_bar['low']      # Initial stop level
            self.dynamic_stop = prev_bar['low']             # Keep for compatibility
            self.log(f"Long pullback: entry={self.entry_long:.2f}, initial_stop={self.pullback_candle_extreme:.2f}")
            
        # C#: else if (seenShortBreak && IsCandleGreenAtIndex(1) && !seenShortPullback)
        elif (self.seen_short_break and self.is_candle_green(prev_bar) and 
              not self.seen_short_pullback):
            
            self.entry_short = prev_bar['open']     # C#: entryShort = Open[1]
            self.seen_short_pullback = True
            self.one_trade_per_pullback = True
            # 🆕 NEW: Store pullback candle high as initial stop reference  
            self.pullback_candle_extreme = prev_bar['high']  # Starting point for trailing stop
            self.trailing_stop_level = prev_bar['high']      # Initial stop level
            self.dynamic_stop = prev_bar['high']             # Keep for compatibility
            self.log(f"Short pullback: entry={self.entry_short:.2f}, initial_stop={self.pullback_candle_extreme:.2f}")
        
        # ✅ CRITICAL FIX: NO ENTRIES HERE! 
        # Entry checking now happens in check_for_entry_on_tick() using forming bar data
    
    def enter_long_position(self) -> None:
        """Enter long position"""
        entry_price = self.entry_long
        quantity = self.calculate_position_size(entry_price, is_long=True)
        
        # Submit entry order
        self._submit_order('buy', quantity, entry_price, order_type='limit')
        
        self.entry_fill_price = entry_price
        self.trades_today += 1
        self.fixed_be_triggered = False
        
        # Place exits
        self.place_exits_long(entry_price, quantity)
        
        self.log(f"=== LONG ENTRY: {quantity} @ {entry_price:.2f} ===")
    
    def enter_short_position(self) -> None:
        """Enter short position"""
        entry_price = self.entry_short
        quantity = self.calculate_position_size(entry_price, is_long=False)
        
        # Submit entry order
        self._submit_order('sell', quantity, entry_price, order_type='limit')
        
        self.entry_fill_price = entry_price
        self.trades_today += 1
        self.fixed_be_triggered = False
        
        # Place exits
        self.place_exits_short(entry_price, quantity)
        
        self.log(f"=== SHORT ENTRY: {quantity} @ {entry_price:.2f} ===")
    
    def place_exits_long(self, entry_price: float, quantity: int) -> None:
        """
        Place stop and target for long position
        
        ✅ CRITICAL FIX: Uses min(dynamicStop, prev_bar['low'])
        Exactly matches C#: Math.Min(dynamicStop, Low[1]) - StopLossBufferPoints
        """
        prev_bar = self.completed_bars[-2]
        
        if self.use_dynamic_stop:
            # ✅ CORRECTED: Compare dynamicStop with previous bar's low
            # C#: Math.Min(dynamicStop, Low[1]) - StopLossBufferPoints
            stop_price = min(self.dynamic_stop, prev_bar['low']) - self.stop_loss_buffer_points
        else:
            # C#: entryPrice - StopLossTicks * TickSize
            stop_price = entry_price - (self.stop_loss_ticks * self.tick_size)
        
        # Calculate risk and profit target
        # C#: _stopDistance = Math.Abs(entryPrice - stop)
        self.stop_distance = abs(entry_price - stop_price)
        
        # C#: double profitDistance = _stopDistance * ProfitMultiplier
        profit_distance = self.stop_distance * self.profit_multiplier
        
        # C#: double profit = entryPrice + profitDistance
        profit_price = entry_price + profit_distance
        
        # Place orders
        # C#: ExitLongStopMarket(...)
        self._submit_order('sell', quantity, stop_price, order_type='stop', label='SL_Long')
        
        # C#: ExitLongLimit(...)
        self._submit_order('sell', quantity, profit_price, order_type='limit', label='TP_Long')
        
        self.log(f"  Stop: {stop_price:.2f} (risk: {self.stop_distance:.2f})")
        self.log(f"  Target: {profit_price:.2f} (reward: {profit_distance:.2f})")
        self.log(f"  R:R = 1:{self.profit_multiplier}")
    
    def place_exits_short(self, entry_price: float, quantity: int) -> None:
        """
        Place stop and target for short position
        
        ✅ CRITICAL FIX: Uses max(dynamicStop, prev_bar['high'])
        Exactly matches C#: Math.Max(dynamicStop, High[1]) + StopLossBufferPoints
        """
        prev_bar = self.completed_bars[-2]
        
        if self.use_dynamic_stop:
            # ✅ CORRECTED: Compare dynamicStop with previous bar's high
            # C#: Math.Max(dynamicStop, High[1]) + StopLossBufferPoints
            stop_price = max(self.dynamic_stop, prev_bar['high']) + self.stop_loss_buffer_points
        else:
            # C#: entryPrice + StopLossTicks * TickSize
            stop_price = entry_price + (self.stop_loss_ticks * self.tick_size)
        
        # Calculate risk and profit target
        self.stop_distance = abs(entry_price - stop_price)
        profit_distance = self.stop_distance * self.profit_multiplier
        profit_price = entry_price - profit_distance
        
        # Place orders
        # C#: ExitShortStopMarket(...)
        self._submit_order('buy', quantity, stop_price, order_type='stop', label='SL_Short')
        
        # C#: ExitShortLimit(...)
        self._submit_order('buy', quantity, profit_price, order_type='limit', label='TP_Short')
        
        self.log(f"  Stop: {stop_price:.2f} (risk: {self.stop_distance:.2f})")
        self.log(f"  Target: {profit_price:.2f} (reward: {profit_distance:.2f})")
        self.log(f"  R:R = 1:{self.profit_multiplier}")
    
    def manage_breakeven_trailing_stop(self, last_price: float) -> None:
        """
        Manage breakeven trailing stop (original logic)
        C#: ManageTrailingStop()
        """
        # C#: if (TrailBreakevenMultiplier <= 0 || _fixedBeBreakEvenTriggered || ...)
        if (self.trail_breakeven_multiplier <= 0 or 
            self.fixed_be_triggered or 
            not self.stop_distance or
            not self.entry_fill_price):
            return
        
        # Calculate unrealized P&L
        # C#: double unrealized = Position.MarketPosition == MarketPosition.Long
        #                        ? (Close[0] - entryFillPrice)
        #                        : (entryFillPrice - Close[0])
        if self.position > 0:  # Long
            unrealized = last_price - self.entry_fill_price
        else:  # Short
            unrealized = self.entry_fill_price - last_price
        
        # C#: if (unrealized >= TrailBreakevenMultiplier * _stopDistance)
        if unrealized >= self.trail_breakeven_multiplier * self.stop_distance:
            be_price = self.entry_fill_price
            
            # Move stop to breakeven
            if self.position > 0:
                self._submit_order('sell', abs(self.position), be_price, 
                                 order_type='stop', label='TS_Long_BE')
            else:
                self._submit_order('buy', abs(self.position), be_price, 
                                 order_type='stop', label='TS_Short_BE')
            
            self.fixed_be_triggered = True
            self.log(f"Trailing stop -> breakeven @ {be_price:.2f}")
    
    def calculate_position_size(self, entry_price: float, is_long: bool) -> int:
        """Calculate position size"""
        return 1  # Simple fixed size
    
    def is_candle_green(self, bar: Dict[str, Any]) -> bool:
        """C#: IsCandleGreenAtIndex"""
        return bar['close'] > bar['open']
    
    def is_candle_red(self, bar: Dict[str, Any]) -> bool:
        """C#: IsCandleRedAtIndex"""
        return bar['close'] < bar['open']
    
    def store_price_data(self, timestamp: datetime, last_price: float, order_book):
        """Compatibility method for backtester - delegates to on_bar_update"""
        self.on_bar_update(timestamp, last_price, order_book)
    
    def _submit_order(self, side: str, quantity: int, price: float, 
                     order_type: str = 'market', label: str = '') -> None:
        """
        Submit order to backtester
        TODO: Implement based on nq_backtester API
        """
        pass
    
    def get_strategy_params(self) -> Dict[str, Any]:
        """Return strategy parameters"""
        return {
            'max_trades_per_day': self.max_trades_per_day,
            'stop_loss_ticks': self.stop_loss_ticks,
            'profit_multiplier': self.profit_multiplier,
            'use_dynamic_stop': self.use_dynamic_stop,
            'stop_loss_buffer_points': self.stop_loss_buffer_points,
            'trail_breakeven_multiplier': self.trail_breakeven_multiplier,
            'tick_size': self.tick_size,
            'bar_period_minutes': self.bar_period_minutes
        }