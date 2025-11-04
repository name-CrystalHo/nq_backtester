"""
WickTest Strategy - Engulfing Candle Retest Strategy

Python implementation of the NinjaScript WickTest strategy that:
- Identifies strong engulfing candle patterns (≥1.4x body size)
- Trades retests of the engulfed candle's high/low levels
- Uses 5-minute bar aggregation with tick precision
- Implements 1:1 risk/reward ratio with 40-tick stops and targets

Original NinjaScript Logic:
- Detects 3-bar pattern: setup candle, engulfing candle, retest candle
- Long: Red[2] → Bullish engulfing[1] → Retest High[2] 
- Short: Green[2] → Bearish engulfing[1] → Retest Low[2]
- Risk: 40 ticks stop loss, 40 ticks profit target
"""

import sys
import logging
from pathlib import Path
from typing import List, Optional, Dict, Any
import numpy as np
from dataclasses import dataclass

from .base_strategy import BaseStrategy, StrategyParams, Signal
from ..engine.bar_aggregator import Bar, BarAggregator


@dataclass
class WickTestParams(StrategyParams):
    """WickTest strategy specific parameters"""
    
    # Pattern Recognition
    min_engulfing_ratio: float = 1.4  # Minimum engulfing body size (140% of setup candle)
    min_bars_required: int = 2        # Minimum bars needed for pattern (setup + engulfing)
    retest_penetration_ticks: int = 0 # Require penetration beyond level by N ticks (0 = touch allowed)
    
    # Risk Management (NinjaScript defaults)
    risk_ticks: int = 40             # Stop loss in ticks (10 points for NQ)
    profit_ticks: int = 40           # Profit target in ticks (10 points for NQ)
    
    # Position Management
    max_trades_per_day: int = 100    # Maximum trades per day
    max_trades_per_bar: int = 1      # Maximum trades per bar (one_trade_per_bar)
    
    # Timing (NinjaScript session handling)
    exit_on_session_close: bool = True
    exit_before_close_seconds: int = 30
    
    def __post_init__(self):
        """Update base params from NinjaScript values"""
        # Convert ticks to points (NQ tick size = 0.25, so 40 ticks = 10 points)
        self.stop_loss_points = self.risk_ticks * self.tick_size
        self.profit_target_points = self.profit_ticks * self.tick_size
        
        # Set risk management flags
        self.use_stops = True
        self.use_targets = True
        
        # Set strategy name
        if not hasattr(self, 'name') or self.name == "BaseStrategy":
            self.name = "WickTest"


class WickTestStrategy(BaseStrategy):
    """
    Engulfing Candle Retest Strategy
    
    Strategy Logic:
    1. Detect 3-bar pattern:
       - Bar[2]: Setup candle (red or green)
       - Bar[1]: Strong engulfing candle (≥140% body size)
       - Bar[0]: Current bar for retest opportunity
       
    2. Entry Conditions:
       - Long: Red[2] + Bullish engulfing[1] → Enter limit at High[2]
       - Short: Green[2] + Bearish engulfing[1] → Enter limit at Low[2]
       
    3. Risk Management:
       - 40-tick stop loss (10 points for NQ)
       - 40-tick profit target (10 points for NQ)
       - 1:1 risk/reward ratio
       - One trade per bar maximum
    """
    
    def __init__(self, params: WickTestParams, bar_aggregator: Optional[BarAggregator] = None):
        """Initialize WickTest strategy"""
        super().__init__(params, bar_aggregator)
        
        # Cast params to WickTestParams for type safety
        self.params: WickTestParams = params
        
        # Strategy state
        self.traded_this_bar: bool = False
        self.daily_trade_count: int = 0
        self.last_bar_start_time: Optional[int] = None
        
        # Pattern recognition state
        self.pattern_detected: Optional[Dict[str, Any]] = None
        self.pattern_detected_bar_index: Optional[int] = None  # Track which bar the pattern was detected on
        self.pending_entry_price: Optional[float] = None
        self.pending_entry_side: Optional[str] = None
        
        # Logger
        self.logger = logging.getLogger(__name__)

    # Debug mode (set via environment variable WICKTEST_DEBUG=1)
        import os
        self.debug_mode: bool = os.environ.get('WICKTEST_DEBUG', '0') == '1'
        # Optional: require penetration ticks via env
        penv = os.environ.get('WICKTEST_PENETRATION_TICKS')
        if penv is not None:
            try:
                self.params.retest_penetration_ticks = int(penv)
            except ValueError:
                pass
        if self.debug_mode:
            # Elevate logger for this module if debug enabled
            self.logger.setLevel(logging.DEBUG)
            self.logger.info("WICKTEST DEBUG MODE ENABLED")
        
        # Trace mode for pattern/retest analysis (WICKTEST_TRACE=1)
        self.trace_mode: bool = os.environ.get('WICKTEST_TRACE', '0') == '1'
        self.trace_window_start: Optional[str] = os.environ.get('WICKTEST_TRACE_WINDOW_START')
        self.trace_window_end: Optional[str] = os.environ.get('WICKTEST_TRACE_WINDOW_END')
        
        # Retest bar tracking for trace
        self.retest_bar_trades: List[float] = []  # Track all trade prices in current retest bar
    
    def generate_signals(self, timestamp_ns: int, price: float, **kwargs) -> List[Signal]:
        """
        Generate trading signals based on bar patterns and retest logic.
        
        Args:
            timestamp_ns: Current timestamp in nanoseconds  
            price: Current market price
            **kwargs: Additional market data
            
        Returns:
            List of trading signals
        """
        signals = []
        
        # Reset traded flag on new bar (equivalent to IsFirstTickOfBar)
        if self._is_first_tick_of_bar():
            self.traded_this_bar = False
            # Don't reset pattern here - we need to check if retest bar expired
        
        # Check if we have enough bars for pattern recognition
        if len(self.bar_history) < self.params.min_bars_required:
            return signals
        
        # Only trade when flat (equivalent to Position.MarketPosition != MarketPosition.Flat check)
        position = self.simulator.get_position()
        if not position.is_flat:
            return signals
        
        # Respect daily trade limits
        if self.daily_trade_count >= self.params.max_trades_per_day:
            return signals
        
        # Only one trade per bar (equivalent to tradedThisBar check)
        if self.traded_this_bar:
            return signals
        
        # Check if current pattern expired (retest bar completed without entry)
        if self.pattern_detected and self.pattern_detected_bar_index is not None:
            # If we're now on a new bar (bar index increased), the retest opportunity expired
            current_bar_count = len(self.bar_history)
            if current_bar_count > self.pattern_detected_bar_index:
                # Pattern expired - retest bar completed without entry
                self.pattern_detected = None
                self.pattern_detected_bar_index = None
        
            # Detect engulfing pattern when we have 2 complete bars in history
        # Pattern detection happens when Bar[1] (engulfing) just completed and Bar[0] starts forming
        if len(self.bar_history) >= 2:
            # Check if we just got a new completed bar (or haven't detected a pattern yet)
            if not self.pattern_detected or len(self.bar_history) != self.pattern_detected_bar_index:
                new_pattern = self._detect_engulfing_pattern(timestamp_ns)
                if new_pattern:
                    self.pattern_detected = new_pattern
                    # Initialize intrabar retest direction state
                    self.pattern_detected['was_above'] = False  # for long retests
                    self.pattern_detected['was_below'] = False  # for short retests
                    # Remember the bar count when pattern was detected
                    # Bar[0] (current retest bar) may not be in history yet
                    self.pattern_detected_bar_index = len(self.bar_history)
                    # Clear retest tracking for new pattern
                    self.retest_bar_trades.clear()        # Check for entry opportunities ONLY if we have a valid pattern
        # and we're still within the retest bar (Bar[0])
        if self.pattern_detected and self.pattern_detected_bar_index == len(self.bar_history):
            entry_signal = self._check_retest_entry(timestamp_ns, price, **kwargs)
            if entry_signal:
                signals.append(entry_signal)
                self.traded_this_bar = True
                self.daily_trade_count += 1
                # Clear pattern after taking the trade
                self.pattern_detected = None
                self.pattern_detected_bar_index = None
        
        return signals
    
    def _is_first_tick_of_bar(self) -> bool:
        """Check if this is the first tick of a new bar"""
        # Use forming bar from the aggregator (current_bar in BaseStrategy is last completed bar)
        if not self.bar_aggregator:
            return False
        current_forming_bar = self.bar_aggregator.get_current_bar()
        if current_forming_bar is None:
            return False
        
        # If forming bar start time changed, a new bar just started
        if self.last_bar_start_time != current_forming_bar.start_time_ns:
            self.last_bar_start_time = current_forming_bar.start_time_ns
            # Reset retest bar trade tracking
            self.retest_bar_trades.clear()
            return True
        return False
    
    def _detect_engulfing_pattern(self, timestamp_ns: int) -> Optional[Dict[str, Any]]:
        """
        Detect strong engulfing candle pattern.
        
        Returns:
            Pattern information if detected, None otherwise
            
        Pattern Logic (from NinjaScript):
        - Bar[2]: Setup candle (red or green)
        - Bar[1]: Engulfing candle (just completed)
        - Bar[0]: Current bar forming (will be the retest bar)
        
        Detection occurs when Bar[1] completes:
        - isFirstCandleRed = Close[2] < Open[2]
        - isFirstCandleGreen = Close[2] > Open[2] 
        - isStrongEngulfing = Math.Abs(Close[1] - Open[1]) >= Math.Abs(Close[2] - Open[2]) * 1.4
        - isPrevBullishEngulfing = isFirstCandleRed && Close[1] > High[2] && isStrongEngulfing
        - isPrevBearishEngulfing = isFirstCandleGreen && Close[1] < Low[2] && isStrongEngulfing
        """
        if len(self.bar_history) < 2:
            return None
        
        # Check trace window
        in_trace_window = self._is_in_trace_window(timestamp_ns)
        
        # When a new bar completes, check the previous 2 bars for pattern
        # bar_history[-2] = Bar[2] (setup candle)
        # bar_history[-1] = Bar[1] (engulfing candle - just completed)
        # Current forming bar will be Bar[0] (retest bar)
        
        setup_bar = self.bar_history[-2]      # Bar[2] - setup candle
        engulfing_bar = self.bar_history[-1]  # Bar[1] - engulfing candle (just completed)
        
        # Check if setup candle is red or green
        is_setup_red = setup_bar.close < setup_bar.open
        is_setup_green = setup_bar.close > setup_bar.open
        
        # Calculate body sizes
        setup_body_size = abs(setup_bar.close - setup_bar.open)
        engulfing_body_size = abs(engulfing_bar.close - engulfing_bar.open)
        
        # Check for strong engulfing (≥140% of setup candle body)
        is_strong_engulfing = engulfing_body_size >= (setup_body_size * self.params.min_engulfing_ratio)
        
        # Debug logging
        if self.debug_mode:
            from datetime import datetime
            setup_time = datetime.fromtimestamp(setup_bar.start_time_ns / 1e9).strftime('%H:%M')
            engulfing_time = datetime.fromtimestamp(engulfing_bar.start_time_ns / 1e9).strftime('%H:%M')
            self.logger.debug(f"[PATTERN CHECK] Bar[2]={setup_time} -> Bar[1]={engulfing_time}")
            self.logger.debug(
                f"  Setup: O=${setup_bar.open:.2f} H=${setup_bar.high:.2f} L=${setup_bar.low:.2f} C=${setup_bar.close:.2f} | Body=${setup_body_size:.2f} | {'RED' if is_setup_red else 'GREEN'}"
            )
            self.logger.debug(
                f"  Engulf: O=${engulfing_bar.open:.2f} H=${engulfing_bar.high:.2f} L=${engulfing_bar.low:.2f} C=${engulfing_bar.close:.2f} | Body=${engulfing_body_size:.2f}"
            )
            self.logger.debug(
                f"  Ratio: {engulfing_body_size / setup_body_size if setup_body_size > 0 else 0:.2f}x (need ≥{self.params.min_engulfing_ratio}x)"
            )
            self.logger.debug(f"  Strong: {is_strong_engulfing}")
        
        # Trace pattern checks (show even failed patterns in trace window)
        if in_trace_window:
            from datetime import datetime
            setup_time = datetime.fromtimestamp(setup_bar.start_time_ns / 1e9).strftime('%H:%M')
            engulfing_time = datetime.fromtimestamp(engulfing_bar.start_time_ns / 1e9).strftime('%H:%M')
            self.logger.debug(f"[PATTERN CHECK] Bar[2]={setup_time} -> Bar[1]={engulfing_time}")
            self.logger.debug(
                f"  Setup: O=${setup_bar.open:.2f} H=${setup_bar.high:.2f} L=${setup_bar.low:.2f} C=${setup_bar.close:.2f} | {'RED' if is_setup_red else 'GREEN'}"
            )
            self.logger.debug(
                f"  Engulf: O=${engulfing_bar.open:.2f} H=${engulfing_bar.high:.2f} L=${engulfing_bar.low:.2f} C=${engulfing_bar.close:.2f}"
            )
            self.logger.debug(
                f"  Body ratio: {engulfing_body_size / setup_body_size if setup_body_size > 0 else 0:.2f}x (need ≥{self.params.min_engulfing_ratio}x)"
            )
            self.logger.debug(f"  Strong engulfing: {is_strong_engulfing}")
            if is_setup_red:
                self.logger.debug(
                    f"  Bullish check: Close[1]={engulfing_bar.close:.2f} > High[2]={setup_bar.high:.2f}? {engulfing_bar.close > setup_bar.high}"
                )
            if is_setup_green:
                self.logger.debug(
                    f"  Bearish check: Close[1]={engulfing_bar.close:.2f} < Low[2]={setup_bar.low:.2f}? {engulfing_bar.close < setup_bar.low}"
                )
        
        # Detect bullish engulfing pattern (CLOSE-based break of prior high)
        is_bullish_engulfing = (
            is_setup_red and 
            engulfing_bar.close > setup_bar.high and
            is_strong_engulfing
        )
        
        # Detect bearish engulfing pattern (CLOSE-based break of prior low)
        is_bearish_engulfing = (
            is_setup_green and
            engulfing_bar.close < setup_bar.low and
            is_strong_engulfing
        )
        
        if self.debug_mode:
            if is_bullish_engulfing:
                self.logger.debug(f"✓ BULLISH ENGULFING! Entry at ${setup_bar.high:.2f}")
            elif is_bearish_engulfing:
                self.logger.debug(f"✓ BEARISH ENGULFING! Entry at ${setup_bar.low:.2f}")
        
        # Trace pattern detection
        if in_trace_window and (is_bullish_engulfing or is_bearish_engulfing):
            from datetime import datetime
            dt = datetime.fromtimestamp(timestamp_ns / 1e9).strftime('%H:%M:%S')
            side = "LONG" if is_bullish_engulfing else "SHORT"
            entry_level = setup_bar.high if is_bullish_engulfing else setup_bar.low
            self.logger.debug(f"[PATTERN] {dt} | {side} setup detected")
            self.logger.debug(
                f"  Setup[2]: O=${setup_bar.open:.2f} H=${setup_bar.high:.2f} L=${setup_bar.low:.2f} C=${setup_bar.close:.2f}"
            )
            self.logger.debug(
                f"  Engulf[1]: O=${engulfing_bar.open:.2f} H=${engulfing_bar.high:.2f} L=${engulfing_bar.low:.2f} C=${engulfing_bar.close:.2f}"
            )
            self.logger.debug(f"  Entry level: ${entry_level:.2f} (setup wick)")
            self.logger.debug(
                f"  Ratio: {engulfing_body_size / setup_body_size if setup_body_size > 0 else 0:.2f}x"
            )
        
        if is_bullish_engulfing:
            return {
                'type': 'bullish_engulfing',
                'setup_bar': setup_bar,
                'engulfing_bar': engulfing_bar,
                'entry_level': setup_bar.high,  # Entry at High[2]
                'side': 'long'
            }
        elif is_bearish_engulfing:
            return {
                'type': 'bearish_engulfing', 
                'setup_bar': setup_bar,
                'engulfing_bar': engulfing_bar,
                'entry_level': setup_bar.low,   # Entry at Low[2] 
                'side': 'short'
            }
        
        return None
    
    def _check_retest_entry(self, timestamp_ns: int, price: float, **kwargs) -> Optional[Signal]:
        """
        Check if current price action creates a retest entry opportunity.
        
        Entry occurs ONLY during Bar[0] (retest bar) formation when price touches:
        - Long: Price touches High[2] (setup bar high)
        - Short: Price touches Low[2] (setup bar low)
        
        Args:
            timestamp_ns: Current timestamp
            price: Current market price
            
        Returns:
            Entry signal if retest conditions are met (market order for immediate fill)
        """
        if not self.pattern_detected:
            return None
        
        # Only allow retest triggers on TRADE ticks (ignore bid/ask quote-only ticks)
        # Heuristic based on backtester: trade ticks arrive with bid=None and ask=None
        bid = kwargs.get('bid', None)
        ask = kwargs.get('ask', None)
        is_trade_tick = (bid is None and ask is None)
        if not is_trade_tick:
            return None
        
        # CRITICAL: Skip invalid prices (0.00 or negative) that can trigger false entries
        if price <= 0.0:
            return None

        entry_level = self.pattern_detected['entry_level']
        side = self.pattern_detected['side']
        
        # Track all valid trade prices during retest bar for trace analysis
        self.retest_bar_trades.append(price)
        
        # Check trace window
        in_trace_window = self._is_in_trace_window(timestamp_ns)
        
        # Check if price has touched the retest level
        penetration = self.params.retest_penetration_ticks * self.params.tick_size
        if side == 'long':
            # Track if we've been above the entry level during this retest bar
            if price > entry_level:
                self.pattern_detected['was_above'] = True
            # Long entry: require retest from above (saw a trade > entry before touch)
            # Require penetration below the level by `penetration` (0 allows touch)
            if price <= (entry_level - penetration) and self.pattern_detected.get('was_above', False):
                if in_trace_window:
                    from datetime import datetime
                    ts = datetime.fromtimestamp(timestamp_ns / 1e9).strftime('%H:%M:%S')
                    trade_min = min(self.retest_bar_trades) if self.retest_bar_trades else price
                    trade_max = max(self.retest_bar_trades) if self.retest_bar_trades else price
                    self.logger.debug(f"[ENTRY] {ts} | LONG triggered")
                    self.logger.debug(f"  Entry level: ${entry_level:.2f} (setup high)")
                    self.logger.debug(f"  Trigger price: ${price:.2f}")
                    self.logger.debug(
                        f"  Retest bar range (trades only): ${trade_min:.2f} - ${trade_max:.2f}"
                    )
                    self.logger.debug(f"  Was above: {self.pattern_detected.get('was_above', False)}")
                    self.logger.debug(f"  Trade count in bar: {len(self.retest_bar_trades)}")
                
                if self.debug_mode:
                    from datetime import datetime
                    ts = datetime.fromtimestamp(timestamp_ns / 1e9).strftime('%H:%M:%S')
                    self.logger.debug(
                        f"[ENTRY] {ts} | LONG at ${entry_level:.2f} (price=${price:.2f})"
                    )
                
                return Signal(
                    timestamp_ns=timestamp_ns,
                    signal_type='entry_long',
                    price=entry_level,  # LIMIT order at exact retest level
                    confidence=1.0,
                    metadata={
                        'pattern_type': self.pattern_detected['type'],
                        'entry_reason': 'bullish_engulfing_retest',
                        'setup_high': self.pattern_detected['setup_bar'].high,
                        'setup_low': self.pattern_detected['setup_bar'].low,
                        'engulfing_close': self.pattern_detected['engulfing_bar'].close,
                        'retest_level': entry_level,
                        'trigger_price': price
                    }
                )
        
        elif side == 'short':
            # Track if we've been below the entry level during this retest bar
            if price < entry_level:
                self.pattern_detected['was_below'] = True
            # Short entry: require retest from below (saw a trade < entry before touch)
            # Require penetration above the level by `penetration` (0 allows touch)
            if price >= (entry_level + penetration) and self.pattern_detected.get('was_below', False):
                if in_trace_window:
                    from datetime import datetime
                    ts = datetime.fromtimestamp(timestamp_ns / 1e9).strftime('%H:%M:%S')
                    trade_min = min(self.retest_bar_trades) if self.retest_bar_trades else price
                    trade_max = max(self.retest_bar_trades) if self.retest_bar_trades else price
                    self.logger.debug(f"[ENTRY] {ts} | SHORT triggered")
                    self.logger.debug(f"  Entry level: ${entry_level:.2f} (setup low)")
                    self.logger.debug(f"  Trigger price: ${price:.2f}")
                    self.logger.debug(
                        f"  Retest bar range (trades only): ${trade_min:.2f} - ${trade_max:.2f}"
                    )
                    self.logger.debug(f"  Was below: {self.pattern_detected.get('was_below', False)}")
                    self.logger.debug(f"  Trade count in bar: {len(self.retest_bar_trades)}")
                
                if self.debug_mode:
                    from datetime import datetime
                    ts = datetime.fromtimestamp(timestamp_ns / 1e9).strftime('%H:%M:%S')
                    self.logger.debug(
                        f"[ENTRY] {ts} | SHORT at ${entry_level:.2f} (price=${price:.2f})"
                    )
                
                return Signal(
                    timestamp_ns=timestamp_ns,
                    signal_type='entry_short',
                    price=entry_level,  # LIMIT order at exact retest level
                    confidence=1.0,
                    metadata={
                        'pattern_type': self.pattern_detected['type'],
                        'entry_reason': 'bearish_engulfing_retest', 
                        'setup_high': self.pattern_detected['setup_bar'].high,
                        'setup_low': self.pattern_detected['setup_bar'].low,
                        'engulfing_close': self.pattern_detected['engulfing_bar'].close,
                        'retest_level': entry_level,
                        'trigger_price': price
                    }
                )
        
        return None
    
    def reset_daily_state(self):
        """Reset daily trading state (called at start of new trading day)"""
        self.daily_trade_count = 0
        self.traded_this_bar = False
        self.daily_pnl = 0.0
        self.max_daily_loss_hit = False
    
    def _is_in_trace_window(self, timestamp_ns: int) -> bool:
        """Check if current timestamp is within trace window"""
        if not self.trace_mode:
            return False
        if not self.trace_window_start or not self.trace_window_end:
            return self.trace_mode  # Trace everything if no window specified
        
        from datetime import datetime
        dt = datetime.fromtimestamp(timestamp_ns / 1e9)
        time_str = dt.strftime('%H:%M:%S')
        return self.trace_window_start <= time_str <= self.trace_window_end
    
    def get_strategy_info(self) -> Dict[str, Any]:
        """Get current strategy information for monitoring"""
        return {
            'name': self.params.name,
            'trades_today': self.daily_trade_count,
            'max_trades_per_day': self.params.max_trades_per_day,
            'traded_this_bar': self.traded_this_bar,
            'pattern_detected': self.pattern_detected is not None,
            'pattern_type': self.pattern_detected.get('type') if self.pattern_detected else None,
            'bars_in_history': len(self.bar_history),
            'daily_pnl': self.daily_pnl,
            'total_signals': self.total_signals,
            'total_entries': self.total_entries,
            'total_exits': self.total_exits
        }


def create_wicktest_strategy(
    risk_ticks: int = 40,
    profit_ticks: int = 40,
    min_engulfing_ratio: float = 1.4,
    max_trades_per_day: int = 100
) -> WickTestStrategy:
    """
    Factory function to create WickTest strategy with common configurations.
    
    Args:
        risk_ticks: Stop loss in ticks (default: 40)
        profit_ticks: Profit target in ticks (default: 40) 
        min_engulfing_ratio: Minimum engulfing ratio (default: 1.4)
        max_trades_per_day: Maximum trades per day (default: 100)
        
    Returns:
        Configured WickTestStrategy instance
    """
    
    # Create 5-minute bar aggregator for strategy
    bar_aggregator = BarAggregator(
        bar_period_minutes=5
    )
    
    # Create strategy parameters
    params = WickTestParams(
        name="WickTest",
        risk_ticks=risk_ticks,
        profit_ticks=profit_ticks,
        min_engulfing_ratio=min_engulfing_ratio,
        max_trades_per_day=max_trades_per_day,
        
        # NQ-specific settings
        tick_size=0.25,
        point_value=20.0,
        # Note: commission_per_trade defaults to 0.0 and is set via CLI --commission flag
        
        # Risk management
        max_position_size=1,
        risk_per_trade=100.0,
        max_daily_loss=500.0,
        
        # Session management
        start_time="09:30:00",
        end_time="16:00:00",
        max_trade_duration=300
    )
    
    return WickTestStrategy(params, bar_aggregator)


if __name__ == "__main__":
    """Example usage of WickTest strategy"""
    
    # Create strategy
    strategy = create_wicktest_strategy(
        risk_ticks=40,
        profit_ticks=40,
        min_engulfing_ratio=1.4
    )
    
    print("🎯 WickTest Strategy Created")
    print("=" * 40)
    print(f"Strategy: {strategy.params.name}")
    print(f"Risk: {strategy.params.risk_ticks} ticks ({strategy.params.stop_loss_points} points)")
    print(f"Target: {strategy.params.profit_ticks} ticks ({strategy.params.profit_target_points} points)")
    print(f"Engulfing Ratio: {strategy.params.min_engulfing_ratio}x")
    print(f"Max Trades/Day: {strategy.params.max_trades_per_day}")
    print()
    
    # Display strategy info
    info = strategy.get_strategy_info()
    for key, value in info.items():
        print(f"{key}: {value}")