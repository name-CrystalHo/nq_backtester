"""
Advanced Strategy Example - Custom trading strategies for the NQ Backtester

This example shows how to create more sophisticated trading strategies
using the backtester framework.
"""

import sys
from pathlib import Path
import pandas as pd
import numpy as np
from typing import Dict, List, Optional
from datetime import datetime, time

# Add backtester to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from backtester.strategies.base_strategy import BaseStrategy
from backtester.engine.backtester import BacktestConfig
from backtester import Backtester, DataLoader


class RSIStrategy(BaseStrategy):
    """RSI-based trading strategy with overbought/oversold levels."""
    
    def __init__(self, period: int = 14, overbought: float = 70, oversold: float = 30, 
                 quantity: int = 1):
        super().__init__()
        self.period = period
        self.overbought = overbought
        self.oversold = oversold
        self.quantity = quantity
        self.prices = []
        self.position = 0
        
        # Strategy state
        self.last_rsi = None
        self.entry_price = None
        
    def initialize(self):
        """Initialize strategy."""
        self.log(f"RSI Strategy initialized: period={self.period}, "
                f"overbought={self.overbought}, oversold={self.oversold}")
    
    def on_bar_update(self):
        """Called on each price update."""
        current_price = self.get_last_price()
        if current_price is None:
            return
        
        # Store price history
        self.prices.append(current_price)
        
        # Need enough data to calculate RSI
        if len(self.prices) < self.period + 1:
            return
        
        # Keep only needed price history
        if len(self.prices) > self.period * 2:
            self.prices = self.prices[-(self.period * 2):]
        
        # Calculate RSI
        rsi = self._calculate_rsi()
        if rsi is None:
            return
        
        self.last_rsi = rsi
        
        # Trading logic
        if self.position == 0:
            # No position - look for entry signals
            if rsi < self.oversold:
                self.log(f"RSI oversold signal: {rsi:.2f} - Going LONG")
                self.enter_long(self.quantity)
                self.position = 1
                self.entry_price = current_price
                
            elif rsi > self.overbought:
                self.log(f"RSI overbought signal: {rsi:.2f} - Going SHORT")
                self.enter_short(self.quantity)
                self.position = -1
                self.entry_price = current_price
        
        elif self.position > 0:
            # Long position - look for exit
            if rsi > self.overbought:
                self.log(f"RSI exit signal (long): {rsi:.2f} - Closing LONG")
                self.exit_long(self.quantity)
                self.position = 0
                self.entry_price = None
        
        elif self.position < 0:
            # Short position - look for exit
            if rsi < self.oversold:
                self.log(f"RSI exit signal (short): {rsi:.2f} - Closing SHORT")
                self.exit_short(self.quantity)
                self.position = 0
                self.entry_price = None
    
    def _calculate_rsi(self) -> Optional[float]:
        """Calculate RSI from price history."""
        if len(self.prices) < self.period + 1:
            return None
        
        # Calculate price changes
        price_changes = np.diff(self.prices[-self.period-1:])
        
        # Separate gains and losses
        gains = np.where(price_changes > 0, price_changes, 0)
        losses = np.where(price_changes < 0, -price_changes, 0)
        
        # Calculate averages
        avg_gain = np.mean(gains)
        avg_loss = np.mean(losses)
        
        if avg_loss == 0:
            return 100  # All gains, RSI = 100
        
        rs = avg_gain / avg_loss
        rsi = 100 - (100 / (1 + rs))
        
        return rsi
    
    def get_strategy_stats(self) -> Dict:
        """Get strategy-specific statistics."""
        return {
            'current_rsi': self.last_rsi,
            'position': self.position,
            'entry_price': self.entry_price,
            'rsi_period': self.period,
            'overbought_level': self.overbought,
            'oversold_level': self.oversold
        }


class BollingerBandsStrategy(BaseStrategy):
    """Bollinger Bands mean reversion strategy."""
    
    def __init__(self, period: int = 20, std_dev: float = 2.0, quantity: int = 1):
        super().__init__()
        self.period = period
        self.std_dev = std_dev
        self.quantity = quantity
        self.prices = []
        self.position = 0
        
        # Strategy state
        self.upper_band = None
        self.lower_band = None
        self.middle_band = None
        self.entry_price = None
        
    def initialize(self):
        """Initialize strategy."""
        self.log(f"Bollinger Bands Strategy: period={self.period}, std_dev={self.std_dev}")
    
    def on_bar_update(self):
        """Called on each price update."""
        current_price = self.get_last_price()
        if current_price is None:
            return
        
        # Store price history
        self.prices.append(current_price)
        
        # Need enough data to calculate bands
        if len(self.prices) < self.period:
            return
        
        # Keep only needed price history
        if len(self.prices) > self.period * 2:
            self.prices = self.prices[-(self.period * 2):]
        
        # Calculate Bollinger Bands
        recent_prices = self.prices[-self.period:]
        self.middle_band = np.mean(recent_prices)
        std = np.std(recent_prices, ddof=1)
        self.upper_band = self.middle_band + (self.std_dev * std)
        self.lower_band = self.middle_band - (self.std_dev * std)
        
        # Trading logic
        if self.position == 0:
            # No position - look for entry signals
            if current_price <= self.lower_band:
                self.log(f"Price at lower band: {current_price:.2f} <= {self.lower_band:.2f} - Going LONG")
                self.enter_long(self.quantity)
                self.position = 1
                self.entry_price = current_price
                
            elif current_price >= self.upper_band:
                self.log(f"Price at upper band: {current_price:.2f} >= {self.upper_band:.2f} - Going SHORT")
                self.enter_short(self.quantity)
                self.position = -1
                self.entry_price = current_price
        
        elif self.position > 0:
            # Long position - exit at middle band or upper band
            if current_price >= self.middle_band:
                self.log(f"Long exit at middle band: {current_price:.2f} >= {self.middle_band:.2f}")
                self.exit_long(self.quantity)
                self.position = 0
                self.entry_price = None
        
        elif self.position < 0:
            # Short position - exit at middle band
            if current_price <= self.middle_band:
                self.log(f"Short exit at middle band: {current_price:.2f} <= {self.middle_band:.2f}")
                self.exit_short(self.quantity)
                self.position = 0
                self.entry_price = None
    
    def get_strategy_stats(self) -> Dict:
        """Get strategy-specific statistics."""
        return {
            'upper_band': self.upper_band,
            'middle_band': self.middle_band,
            'lower_band': self.lower_band,
            'position': self.position,
            'entry_price': self.entry_price,
            'period': self.period,
            'std_dev_multiplier': self.std_dev
        }


class BreakoutStrategy(BaseStrategy):
    """Breakout strategy using support/resistance levels."""
    
    def __init__(self, lookback_period: int = 50, quantity: int = 1, 
                 stop_loss_ticks: int = 10, profit_target_ticks: int = 20):
        super().__init__()
        self.lookback_period = lookback_period
        self.quantity = quantity
        self.stop_loss_ticks = stop_loss_ticks
        self.profit_target_ticks = profit_target_ticks
        
        self.prices = []
        self.position = 0
        self.entry_price = None
        self.stop_loss_price = None
        self.profit_target_price = None
        
        # Support/Resistance levels
        self.resistance_level = None
        self.support_level = None
        
    def initialize(self):
        """Initialize strategy."""
        self.log(f"Breakout Strategy: lookback={self.lookback_period}, "
                f"stop_loss={self.stop_loss_ticks}, target={self.profit_target_ticks}")
    
    def on_bar_update(self):
        """Called on each price update."""
        current_price = self.get_last_price()
        if current_price is None:
            return
        
        # Store price history
        self.prices.append(current_price)
        
        # Need enough data to calculate support/resistance
        if len(self.prices) < self.lookback_period:
            return
        
        # Keep only needed price history
        if len(self.prices) > self.lookback_period * 2:
            self.prices = self.prices[-(self.lookback_period * 2):]
        
        # Calculate support and resistance levels
        recent_prices = self.prices[-self.lookback_period:]
        self.resistance_level = max(recent_prices)
        self.support_level = min(recent_prices)
        
        # Check for position management first
        if self.position != 0:
            self._check_exit_conditions(current_price)
            return
        
        # Look for breakout signals
        if current_price > self.resistance_level:
            # Breakout above resistance - go long
            self.log(f"Breakout above resistance: {current_price:.2f} > {self.resistance_level:.2f}")
            self.enter_long(self.quantity)
            self.position = 1
            self.entry_price = current_price
            self.stop_loss_price = current_price - (self.stop_loss_ticks * 0.25)
            self.profit_target_price = current_price + (self.profit_target_ticks * 0.25)
            
        elif current_price < self.support_level:
            # Breakdown below support - go short
            self.log(f"Breakdown below support: {current_price:.2f} < {self.support_level:.2f}")
            self.enter_short(self.quantity)
            self.position = -1
            self.entry_price = current_price
            self.stop_loss_price = current_price + (self.stop_loss_ticks * 0.25)
            self.profit_target_price = current_price - (self.profit_target_ticks * 0.25)
    
    def _check_exit_conditions(self, current_price: float):
        """Check stop loss and profit target conditions."""
        if self.position > 0:
            # Long position
            if current_price <= self.stop_loss_price:
                self.log(f"Long stop loss hit: {current_price:.2f} <= {self.stop_loss_price:.2f}")
                self.exit_long(self.quantity)
                self._reset_position()
            elif current_price >= self.profit_target_price:
                self.log(f"Long profit target hit: {current_price:.2f} >= {self.profit_target_price:.2f}")
                self.exit_long(self.quantity)
                self._reset_position()
                
        elif self.position < 0:
            # Short position
            if current_price >= self.stop_loss_price:
                self.log(f"Short stop loss hit: {current_price:.2f} >= {self.stop_loss_price:.2f}")
                self.exit_short(self.quantity)
                self._reset_position()
            elif current_price <= self.profit_target_price:
                self.log(f"Short profit target hit: {current_price:.2f} <= {self.profit_target_price:.2f}")
                self.exit_short(self.quantity)
                self._reset_position()
    
    def _reset_position(self):
        """Reset position tracking variables."""
        self.position = 0
        self.entry_price = None
        self.stop_loss_price = None
        self.profit_target_price = None
    
    def get_strategy_stats(self) -> Dict:
        """Get strategy-specific statistics."""
        return {
            'resistance_level': self.resistance_level,
            'support_level': self.support_level,
            'position': self.position,
            'entry_price': self.entry_price,
            'stop_loss_price': self.stop_loss_price,
            'profit_target_price': self.profit_target_price,
            'lookback_period': self.lookback_period,
            'stop_loss_ticks': self.stop_loss_ticks,
            'profit_target_ticks': self.profit_target_ticks
        }


def run_strategy_comparison():
    """Run multiple strategies for comparison."""
    
    print("🎯 Advanced Strategy Comparison")
    print("=" * 50)
    
    # Note: This is a demonstration - you would replace this with real data loading
    print("📝 Note: This example requires real market data.")
    print("   Use converter_example.py to convert your NinjaTrader CSV files first.")
    print("\nStrategy Classes Available:")
    print("  - RSIStrategy: RSI-based overbought/oversold signals")  
    print("  - BollingerBandsStrategy: Mean reversion using Bollinger Bands")
    print("  - BreakoutStrategy: Support/resistance breakout with stops")
    
    # Show strategy parameter examples
    strategies = [
        ("RSI Strategy", RSIStrategy(period=14, overbought=70, oversold=30)),
        ("Bollinger Bands", BollingerBandsStrategy(period=20, std_dev=2.0)),
        ("Breakout Strategy", BreakoutStrategy(lookback_period=50, stop_loss_ticks=10))
    ]
    
    for name, strategy in strategies:
        print(f"\n📈 {name} Configuration:")
        stats = strategy.get_strategy_stats()
        for key, value in stats.items():
            if value is not None:
                print(f"    {key}: {value}")
    
    print("\n" + "=" * 50)
    print("🚀 To run these strategies with real data:")
    print("=" * 50)
    print("""
1. Convert your NinjaTrader data:
   python examples/converter_example.py -s "path/to/csv"

2. Modify this script to load your data:
   loader = DataLoader("path/to/parquet")
   
3. Run backtest:
   config = BacktestConfig(initial_capital=100000)
   strategy = RSIStrategy(period=14)
   backtester = Backtester(strategy, loader, config)
   results = backtester.run("NQ", start_date, end_date)
   
4. Analyze results:
   results.print_summary()
   results.export_ninja_format("results.csv")
    """)


if __name__ == "__main__":
    run_strategy_comparison()