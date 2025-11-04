"""
High-Performance Bar Aggregator with Nanosecond Precision

Provides accurate OHLC bar aggregation from tick data with:
- Nanosecond timestamp precision
- Configurable bar periods (1min, 5min, 15min, etc.)
- Memory-efficient streaming processing
- Real-time bar completion detection
"""

import numpy as np
import polars as pl
from typing import Dict, List, Optional, Callable, Any
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone


@dataclass(slots=True)  # CRITICAL OPTIMIZATION: 10-20% memory + 5-10% speed
class Bar:
    """Represents a single OHLC bar with precise timing"""
    start_time_ns: int
    end_time_ns: int
    open: float
    high: float
    low: float
    close: float
    volume: int = 0
    tick_count: int = 0
    is_complete: bool = False
    
    @property
    def start_time(self) -> datetime:
        """Convert nanosecond timestamp to datetime (local timezone)"""
        return datetime.fromtimestamp(self.start_time_ns / 1_000_000_000)
    
    @property
    def end_time(self) -> datetime:
        """Convert nanosecond timestamp to datetime (local timezone)"""
        return datetime.fromtimestamp(self.end_time_ns / 1_000_000_000)
    
    def is_green(self) -> bool:
        """Check if bar is bullish (close > open)"""
        return self.close > self.open
    
    def is_red(self) -> bool:
        """Check if bar is bearish (close < open)"""
        return self.close < self.open
    
    def is_doji(self) -> bool:
        """Check if bar is doji (close == open)"""
        return abs(self.close - self.open) < 0.01  # Small tolerance for floating point


class BarAggregator:
    """
    High-performance bar aggregator with nanosecond precision.
    
    Features:
    - Streaming tick processing
    - Real-time bar completion callbacks  
    - Multiple timeframe support
    - Memory efficient (configurable history length)
    """
    
    def __init__(
        self,
        bar_period_minutes: int = 5,
        max_history: int = 1000,
        on_bar_complete: Optional[Callable[[Bar], None]] = None
    ):
        """
        Initialize bar aggregator.
        
        Args:
            bar_period_minutes: Bar period in minutes (1, 5, 15, 30, 60, etc.)
            max_history: Maximum number of completed bars to keep in memory
            on_bar_complete: Callback function called when a bar completes
        """
        self.bar_period_minutes = bar_period_minutes
        self.bar_period_ns = bar_period_minutes * 60 * 1_000_000_000  # Convert to nanoseconds
        self.max_history = max_history
        self.on_bar_complete = on_bar_complete
        
        # State tracking
        self.completed_bars: List[Bar] = []
        self.current_bar: Optional[Bar] = None
        self.current_bar_start_ns: int = 0
        self.last_tick_time_ns: int = 0
        
        # Statistics
        self.total_ticks_processed: int = 0
        self.total_bars_created: int = 0
    
    def process_tick(
        self, 
        timestamp_ns: int, 
        price: float, 
        volume: int = 1
    ) -> Optional[Bar]:
        """
        Process a single tick and return completed bar if any.
        
        Args:
            timestamp_ns: Tick timestamp in nanoseconds since epoch
            price: Tick price
            volume: Tick volume (default: 1)
            
        Returns:
            Completed bar if a bar boundary was crossed, None otherwise
        """
        # Data quality filter: Skip invalid prices (common in market data)
        if price <= 0.0:
            return None
        
        self.total_ticks_processed += 1
        self.last_tick_time_ns = timestamp_ns
        
        # Calculate bar start time (aligned to bar period boundaries)
        bar_start_ns = self._get_bar_start_time(timestamp_ns)
        
        completed_bar = None
        
        # Check if we need to start a new bar
        if bar_start_ns != self.current_bar_start_ns:
            # Complete current bar if it exists
            if self.current_bar is not None:
                self.current_bar.is_complete = True
                self.current_bar.end_time_ns = bar_start_ns  # End of previous bar
                
                # Add to completed bars
                self.completed_bars.append(self.current_bar)
                completed_bar = self.current_bar
                self.total_bars_created += 1
                
                # Trigger callback
                if self.on_bar_complete:
                    self.on_bar_complete(self.current_bar)
                
                # Maintain history limit
                if len(self.completed_bars) > self.max_history:
                    self.completed_bars.pop(0)
            
            # Start new bar
            self.current_bar_start_ns = bar_start_ns
            self.current_bar = Bar(
                start_time_ns=bar_start_ns,
                end_time_ns=bar_start_ns + self.bar_period_ns,
                open=price,
                high=price,
                low=price,
                close=price,
                volume=volume,
                tick_count=1
            )
        else:
            # Update current bar
            if self.current_bar is not None:
                self.current_bar.high = max(self.current_bar.high, price)
                self.current_bar.low = min(self.current_bar.low, price)
                self.current_bar.close = price
                self.current_bar.volume += volume
                self.current_bar.tick_count += 1
        
        return completed_bar
    
    def _get_bar_start_time(self, timestamp_ns: int) -> int:
        """
        Calculate the start time of the bar period for a given timestamp.
        
        Args:
            timestamp_ns: Timestamp in nanoseconds
            
        Returns:
            Bar start time in nanoseconds (aligned to period boundary)
        """
        # Convert to seconds for calculation
        timestamp_seconds = timestamp_ns // 1_000_000_000
        
        # Get day start (midnight) in seconds
        day_start_seconds = (timestamp_seconds // 86400) * 86400
        
        # Calculate seconds since midnight
        seconds_since_midnight = timestamp_seconds - day_start_seconds
        
        # Calculate bar period in seconds
        bar_period_seconds = self.bar_period_minutes * 60
        
        # Find the bar boundary
        bar_start_seconds_offset = (seconds_since_midnight // bar_period_seconds) * bar_period_seconds
        bar_start_seconds = day_start_seconds + bar_start_seconds_offset
        
        # Convert back to nanoseconds
        return bar_start_seconds * 1_000_000_000
    
    def get_bars(self, count: int = None) -> List[Bar]:
        """
        Get completed bars.
        
        Args:
            count: Number of most recent bars to return (None for all)
            
        Returns:
            List of completed bars
        """
        if count is None:
            return self.completed_bars.copy()
        else:
            return self.completed_bars[-count:] if count > 0 else []
    
    def get_current_bar(self) -> Optional[Bar]:
        """Get the current forming bar (not yet complete)"""
        return self.current_bar
    
    def get_last_completed_bar(self) -> Optional[Bar]:
        """Get the most recently completed bar"""
        return self.completed_bars[-1] if self.completed_bars else None
    
    def get_stats(self) -> Dict[str, Any]:
        """Get aggregator statistics"""
        return {
            'total_ticks_processed': self.total_ticks_processed,
            'total_bars_created': self.total_bars_created,
            'completed_bars_count': len(self.completed_bars),
            'current_bar_exists': self.current_bar is not None,
            'bar_period_minutes': self.bar_period_minutes,
            'last_tick_time': datetime.fromtimestamp(self.last_tick_time_ns / 1_000_000_000, tz=timezone.utc) if self.last_tick_time_ns else None
        }
    
    def reset(self):
        """Reset aggregator state (clear all bars and statistics)"""
        self.completed_bars.clear()
        self.current_bar = None
        self.current_bar_start_ns = 0
        self.last_tick_time_ns = 0
        self.total_ticks_processed = 0
        self.total_bars_created = 0


class MultiTimeframeAggregator:
    """
    Manage multiple bar aggregators for different timeframes simultaneously.
    
    Useful for strategies that need multiple timeframe analysis (e.g., 1min, 5min, 15min)
    """
    
    def __init__(
        self,
        timeframes: Dict[str, int],  # {'1min': 1, '5min': 5, '15min': 15}
        max_history: int = 1000
    ):
        """
        Initialize multi-timeframe aggregator.
        
        Args:
            timeframes: Dictionary mapping names to bar periods in minutes
            max_history: Maximum bars to keep for each timeframe
        """
        self.timeframes = timeframes
        self.aggregators: Dict[str, BarAggregator] = {}
        
        # Create aggregators for each timeframe
        for name, period_minutes in timeframes.items():
            self.aggregators[name] = BarAggregator(
                bar_period_minutes=period_minutes,
                max_history=max_history
            )
    
    def process_tick(self, timestamp_ns: int, price: float, volume: int = 1) -> Dict[str, Optional[Bar]]:
        """
        Process tick across all timeframes.
        
        Returns:
            Dictionary mapping timeframe names to completed bars (None if no completion)
        """
        # Data quality filter applied at the multi-timeframe level too
        if price <= 0.0:
            return {name: None for name in self.aggregators.keys()}
        
        completed_bars = {}
        
        for name, aggregator in self.aggregators.items():
            completed_bar = aggregator.process_tick(timestamp_ns, price, volume)
            completed_bars[name] = completed_bar
        
        return completed_bars
    
    def get_bars(self, timeframe: str, count: int = None) -> List[Bar]:
        """Get bars for specific timeframe"""
        if timeframe not in self.aggregators:
            raise ValueError(f"Unknown timeframe: {timeframe}")
        return self.aggregators[timeframe].get_bars(count)
    
    def get_current_bar(self, timeframe: str) -> Optional[Bar]:
        """Get current forming bar for specific timeframe"""
        if timeframe not in self.aggregators:
            raise ValueError(f"Unknown timeframe: {timeframe}")
        return self.aggregators[timeframe].get_current_bar()
    
    def get_all_stats(self) -> Dict[str, Dict]:
        """Get statistics for all timeframes"""
        return {name: agg.get_stats() for name, agg in self.aggregators.items()}


# Utility functions for common operations
def bars_to_dataframe(bars: List[Bar]) -> pl.DataFrame:
    """Convert list of bars to Polars DataFrame"""
    if not bars:
        return pl.DataFrame()
    
    data = []
    for bar in bars:
        data.append({
            'timestamp': bar.start_time,
            'open': bar.open,
            'high': bar.high,
            'low': bar.low,
            'close': bar.close,
            'volume': bar.volume,
            'tick_count': bar.tick_count,
            'is_green': bar.is_green(),
            'is_red': bar.is_red()
        })
    
    return pl.DataFrame(data)


def find_pattern_bars(bars: List[Bar], pattern: str) -> List[int]:
    """
    Find bars matching a specific pattern.
    
    Args:
        bars: List of bars to search
        pattern: Pattern string like "GRG" (Green-Red-Green) or "RGR"
        
    Returns:
        List of indices where pattern starts
    """
    if len(pattern) > len(bars):
        return []
    
    pattern_map = {'G': 'green', 'R': 'red', 'D': 'doji'}
    matches = []
    
    for i in range(len(bars) - len(pattern) + 1):
        match = True
        for j, char in enumerate(pattern):
            bar = bars[i + j]
            if char == 'G' and not bar.is_green():
                match = False
                break
            elif char == 'R' and not bar.is_red():
                match = False
                break
            elif char == 'D' and not bar.is_doji():
                match = False
                break
        
        if match:
            matches.append(i)
    
    return matches