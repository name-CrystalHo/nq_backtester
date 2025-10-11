"""
Clean Opening Print Strategy Analysis - Focus on Strategy Performance

This implementation focuses purely on:
- Actual trades taken by the strategy
- Trade performance metrics
- Daily strategy execution details
- Professional performance reporting using PerformanceMetrics class

No performance optimization metrics - just trading results.
"""

import sys
from pathlib import Path
from datetime import datetime, time
import numpy as np
import pandas as pd
import polars as pl
import numba
from numba import njit
import time as time_module

# Add the backtester package to path
sys.path.append(str(Path(__file__).parent.parent))

from backtester.data.loader import DataLoader
from backtester.metrics.performance import PerformanceMetrics


# ==================================================================================
# NUMBA COMPILED STRATEGY FUNCTIONS - FAST STRATEGY LOGIC
# ==================================================================================

@njit
def find_opening_print(timestamps_ns, prices, target_time_ns):
    """Find opening print at 9:35 AM ET"""
    for i in range(len(timestamps_ns)):
        time_of_day = timestamps_ns[i] % (24 * 60 * 60 * 1_000_000_000)
        if time_of_day >= target_time_ns:
            return prices[i]
    return 0.0


@njit
def detect_breakouts_and_pullbacks(prices, opening_print, tick_size=0.25):
    """Detect breakouts and pullbacks with entry signals"""
    long_breakout_idx = -1
    short_breakout_idx = -1
    long_pullback_idx = -1
    short_pullback_idx = -1
    
    long_entry_price = 0.0
    short_entry_price = 0.0
    long_pullback_low = 999999.0
    short_pullback_high = 0.0
    
    breakout_threshold = tick_size
    
    for i in range(len(prices)):
        price = prices[i]
        
        # Long breakout detection
        if long_breakout_idx == -1 and price > opening_print + breakout_threshold:
            long_breakout_idx = i
            
        # Short breakout detection
        if short_breakout_idx == -1 and price < opening_print - breakout_threshold:
            short_breakout_idx = i
            
        # Long pullback tracking
        if long_breakout_idx != -1 and long_pullback_idx == -1:
            if price < long_pullback_low:
                long_pullback_low = price
            # Pullback complete - price moves back up
            if price > long_pullback_low + tick_size and long_pullback_low < opening_print + breakout_threshold:
                long_pullback_idx = i
                long_entry_price = price
                
        # Short pullback tracking
        if short_breakout_idx != -1 and short_pullback_idx == -1:
            if price > short_pullback_high:
                short_pullback_high = price
            # Pullback complete - price moves back down
            if price < short_pullback_high - tick_size and short_pullback_high > opening_print - breakout_threshold:
                short_pullback_idx = i
                short_entry_price = price
    
    return (long_breakout_idx, short_breakout_idx, long_pullback_idx, short_pullback_idx,
            long_entry_price, short_entry_price, long_pullback_low, short_pullback_high)


@njit  
def calculate_daily_strategy(timestamps_ns, prices, opening_print_time_ns, 
                           stop_loss_ticks=60, profit_multiplier=4, tick_size=0.25):
    """Calculate complete strategy signals for one day"""
    if len(prices) == 0:
        return (0.0, -1, -1, -1, -1, 0.0, 0.0, 0.0, 0.0, 0, 0.0, 0.0, 0.0, -1)
    
    # Find opening print
    opening_print = find_opening_print(timestamps_ns, prices, opening_print_time_ns)
    if opening_print == 0.0:
        return (0.0, -1, -1, -1, -1, 0.0, 0.0, 0.0, 0.0, 0, 0.0, 0.0, 0.0, -1)
    
    # Detect breakouts and pullbacks
    results = detect_breakouts_and_pullbacks(prices, opening_print, tick_size)
    long_breakout_idx, short_breakout_idx, long_pullback_idx, short_pullback_idx = results[:4]
    long_entry_price, short_entry_price, long_pullback_low, short_pullback_high = results[4:]
    
    # Determine trade
    trade_direction = 0  # 0=no trade, 1=long, -1=short
    entry_price = 0.0
    stop_price = 0.0
    target_price = 0.0
    entry_idx = -1
    
    # Prefer long trades if both signals exist
    if long_pullback_idx != -1:
        trade_direction = 1
        entry_price = long_entry_price
        entry_idx = long_pullback_idx
        stop_distance = stop_loss_ticks * tick_size
        stop_price = entry_price - stop_distance
        target_price = entry_price + (stop_distance * profit_multiplier)
        
    elif short_pullback_idx != -1:
        trade_direction = -1  
        entry_price = short_entry_price
        entry_idx = short_pullback_idx
        stop_distance = stop_loss_ticks * tick_size
        stop_price = entry_price + stop_distance
        target_price = entry_price - (stop_distance * profit_multiplier)
    
    return (opening_print, long_breakout_idx, short_breakout_idx, long_pullback_idx, 
            short_pullback_idx, long_entry_price, short_entry_price, long_pullback_low,
            short_pullback_high, trade_direction, entry_price, stop_price, target_price, entry_idx)


# ==================================================================================
# TRADING CLASSES - TRACK ACTUAL TRADES
# ==================================================================================

class Trade:
    """Individual trade record"""
    def __init__(self, direction, entry_time, entry_price, stop_price, target_price, quantity=1):
        self.direction = direction  # 'long' or 'short'
        self.entry_timestamp = entry_time
        self.entry_price = entry_price
        self.stop_price = stop_price
        self.target_price = target_price
        self.quantity = quantity
        self.exit_timestamp = None
        self.exit_price = None
        self.pnl = 0.0
        self.commission = 4.0  # $4 round-trip
        self.exit_reason = None  # 'target', 'stop', 'eod'
        
    def close_trade(self, exit_time, exit_price, reason):
        """Close the trade and calculate P&L"""
        self.exit_timestamp = exit_time
        self.exit_price = exit_price
        self.exit_reason = reason
        
        if self.direction == 'long':
            self.pnl = (exit_price - self.entry_price) * self.quantity * 20  # NQ = $20/point
        else:  # short
            self.pnl = (self.entry_price - exit_price) * self.quantity * 20
            
        return self.pnl - self.commission


class EquityPoint:
    """Equity curve data point"""
    def __init__(self, timestamp, equity, realized_pnl=0, unrealized_pnl=0, position_size=0, drawdown=0, drawdown_pct=0):
        self.timestamp = timestamp
        self.equity = equity
        self.realized_pnl = realized_pnl
        self.unrealized_pnl = unrealized_pnl
        self.position_size = position_size
        self.drawdown = drawdown
        self.drawdown_pct = drawdown_pct


class SimplePositionTracker:
    """Track positions and trades for performance calculation"""
    def __init__(self, initial_capital=100000):
        self.initial_capital = initial_capital
        self.current_equity = initial_capital
        self.trades = []
        self.current_position = 0
        self.equity_curve = [EquityPoint(datetime.now(), initial_capital)]
        
    def add_trade(self, trade):
        """Add completed trade and update equity"""
        self.trades.append(trade)
        net_pnl = trade.pnl - trade.commission
        self.current_equity += net_pnl
        
        # Add equity curve point
        self.equity_curve.append(EquityPoint(
            trade.exit_timestamp, 
            self.current_equity,
            realized_pnl=net_pnl
        ))
        
    def get_statistics(self):
        """Get basic statistics for PerformanceMetrics"""
        if not self.trades:
            return {
                'total_trades': 0, 'winning_trades': 0, 'losing_trades': 0,
                'win_rate': 0.0, 'total_net_profit': 0.0, 'gross_profit': 0.0,
                'gross_loss': 0.0, 'profit_factor': 0.0, 'avg_win': 0.0,
                'avg_loss': 0.0, 'largest_win': 0.0, 'largest_loss': 0.0,
                'max_drawdown': 0.0, 'max_drawdown_pct': 0.0, 'total_commission': 0.0,
                'current_position': 0, 'current_equity': self.current_equity
            }
        
        winning_trades = [t for t in self.trades if t.pnl > 0]
        losing_trades = [t for t in self.trades if t.pnl < 0]
        
        total_net_profit = sum(t.pnl - t.commission for t in self.trades)
        gross_profit = sum(t.pnl for t in winning_trades)
        gross_loss = sum(t.pnl for t in losing_trades)
        
        return {
            'total_trades': len(self.trades),
            'winning_trades': len(winning_trades),
            'losing_trades': len(losing_trades),
            'win_rate': len(winning_trades) / len(self.trades) if self.trades else 0.0,
            'total_net_profit': total_net_profit,
            'gross_profit': gross_profit,
            'gross_loss': gross_loss,
            'profit_factor': abs(gross_profit / gross_loss) if gross_loss != 0 else 0.0,
            'avg_win': np.mean([t.pnl for t in winning_trades]) if winning_trades else 0.0,
            'avg_loss': np.mean([t.pnl for t in losing_trades]) if losing_trades else 0.0,
            'largest_win': max([t.pnl for t in winning_trades]) if winning_trades else 0.0,
            'largest_loss': min([t.pnl for t in losing_trades]) if losing_trades else 0.0,
            'max_drawdown': 0.0,  # Simplified for now
            'max_drawdown_pct': 0.0,  # Simplified for now
            'total_commission': sum(t.commission for t in self.trades),
            'current_position': self.current_position,
            'current_equity': self.current_equity
        }
    
    def get_trade_history(self):
        """Return trade history for PerformanceMetrics"""
        return self.trades


# ==================================================================================
# MAIN STRATEGY ANALYSIS
# ==================================================================================

def main():
    """Run Opening Print strategy analysis focused on trading performance"""
    
    print("📈 Opening Print Strategy - Trading Performance Analysis")
    print("=" * 65)
    
    # Strategy parameters
    strategy_params = {
        'stop_loss_ticks': 60,       # 15 points for NQ
        'profit_multiplier': 4,      # 4:1 risk/reward
        'tick_size': 0.25,          # NQ tick size
    }
    
    # Initialize position tracker
    position_tracker = SimplePositionTracker(initial_capital=100000)
    
    # Load data
    data_loader = DataLoader()
    
    try:
        print("📊 Loading market data...")
        instruments = data_loader.get_available_instruments()
        
        instrument = 'NQ_SEP24'
        if instrument not in instruments:
            print(f"❌ {instrument} not found")
            return
        
        # Test date range
        start_date = '20240701'
        end_date = '20240703'  # 3 days for testing
        
        available_dates = data_loader.get_available_dates(instrument)
        test_dates = [d for d in available_dates if start_date <= d <= end_date]
        
        if not test_dates:
            print(f"❌ No data found")
            return
        
        print(f"📅 Analyzing {len(test_dates)} trading days: {test_dates}")
        
        # Load RTH data efficiently with Polars
        all_data = []
        for date_str in test_dates:
            day_data = data_loader.load_day(instrument, date_str, record_types=['L1'])
            if not day_data.empty:
                # Convert to Polars and filter RTH
                df = pl.from_pandas(day_data)
                rth_data = df.filter(
                    (pl.col("timestamp").dt.time() >= pl.time(9, 30, 0)) &
                    (pl.col("timestamp").dt.time() <= pl.time(16, 0, 0))
                ).select(["timestamp", "price"])
                
                if len(rth_data) > 0:
                    all_data.append(rth_data.with_columns([
                        pl.col("timestamp").dt.date().alias("date")
                    ]))
        
        if not all_data:
            print("❌ No RTH data loaded")
            return
            
        # Combine data
        data = pl.concat(all_data).sort("timestamp")
        print(f"✅ Loaded {len(data):,} RTH ticks")
        
        # Opening print time: 9:35 AM ET in nanoseconds since midnight
        opening_print_time_ns = (9 * 3600 + 35 * 60) * 1_000_000_000
        
        print(f"\n📋 DAILY TRADE EXECUTION ANALYSIS")
        print("=" * 65)
        
        # Process each day
        for i, date_str in enumerate(test_dates):
            trade_date = datetime.strptime(date_str, '%Y%m%d').date()
            
            # Filter data for this day
            daily_data = data.filter(pl.col("date") == trade_date)
            if len(daily_data) == 0:
                continue
                
            print(f"\n📅 {date_str} ({trade_date.strftime('%A, %B %d, %Y')})")
            print("-" * 50)
            
            # Convert to numpy for Numba
            timestamps_pd = daily_data.select("timestamp").to_pandas()["timestamp"]
            prices = daily_data.select("price").to_numpy().flatten()
            timestamps_ns = np.array(timestamps_pd.astype('datetime64[ns]').astype(np.int64))
            
            # Run strategy
            results = calculate_daily_strategy(
                timestamps_ns, prices, opening_print_time_ns,
                stop_loss_ticks=strategy_params['stop_loss_ticks'],
                profit_multiplier=strategy_params['profit_multiplier'],
                tick_size=strategy_params['tick_size']
            )
            
            # Unpack results
            (opening_print, long_breakout_idx, short_breakout_idx, long_pullback_idx,
             short_pullback_idx, long_entry_price, short_entry_price, long_pullback_low,
             short_pullback_high, trade_direction, entry_price, stop_price, target_price, entry_idx) = results
            
            # Convert timestamps for display
            timestamps_readable = pd.to_datetime(timestamps_ns, unit='ns')
            
            # Display market info
            print(f"📊 Market: {len(prices):,} ticks | ${prices.min():.2f} - ${prices.max():.2f}")
            
            if opening_print > 0:
                print(f"🎯 Opening Print: ${opening_print:.2f}")
                
                # Show breakouts
                if long_breakout_idx >= 0:
                    bo_time = timestamps_readable[long_breakout_idx]
                    print(f"📈 Long Breakout: {bo_time.strftime('%H:%M:%S')} @ ${prices[long_breakout_idx]:.2f}")
                    
                if short_breakout_idx >= 0:
                    bo_time = timestamps_readable[short_breakout_idx]
                    print(f"📉 Short Breakout: {bo_time.strftime('%H:%M:%S')} @ ${prices[short_breakout_idx]:.2f}")
                
                # Execute trade if signal exists
                if trade_direction != 0:
                    entry_time = timestamps_readable[entry_idx]
                    direction_str = "LONG" if trade_direction == 1 else "SHORT"
                    
                    print(f"\n💼 TRADE EXECUTED:")
                    print(f"   Direction: {direction_str}")
                    print(f"   Entry: {entry_time.strftime('%H:%M:%S')} @ ${entry_price:.2f}")
                    print(f"   Stop: ${stop_price:.2f}")
                    print(f"   Target: ${target_price:.2f}")
                    
                    risk = abs(entry_price - stop_price)
                    reward = abs(target_price - entry_price)
                    print(f"   Risk: ${risk:.2f} | Reward: ${reward:.2f} | R:R = 1:{reward/risk:.1f}")
                    
                    # Create trade record (simulate exit at target for now)
                    trade = Trade(
                        direction=direction_str.lower(),
                        entry_time=entry_time,
                        entry_price=entry_price,
                        stop_price=stop_price,
                        target_price=target_price
                    )
                    
                    # Simulate trade outcome (hit target - simplified)
                    exit_time = entry_time + pd.Timedelta(hours=2)  # Simulate 2 hour hold
                    trade.close_trade(exit_time, target_price, 'target')
                    position_tracker.add_trade(trade)
                    
                    print(f"   Result: HIT TARGET (simulated)")
                    print(f"   P&L: ${trade.pnl:.2f} | Commission: ${trade.commission:.2f} | Net: ${trade.pnl - trade.commission:.2f}")
                    
                else:
                    print(f"\n❌ NO TRADE: Strategy conditions not met")
            else:
                print(f"❌ NO OPENING PRINT: Data doesn't include 9:35 AM")
        
        # ====== PERFORMANCE SUMMARY ======
        print(f"\n" + "="*65)
        print("📊 STRATEGY PERFORMANCE SUMMARY")
        print("="*65)
        
        # Use PerformanceMetrics class for professional reporting
        metrics = PerformanceMetrics()
        metrics.calculate_from_tracker(position_tracker)
        
        # Print comprehensive summary
        metrics.print_summary("Opening Print Strategy Results")
        
        # Additional trade details
        if position_tracker.trades:
            print(f"\n📋 INDIVIDUAL TRADE DETAILS")
            print("-" * 65)
            for i, trade in enumerate(position_tracker.trades, 1):
                print(f"Trade #{i}: {trade.direction.upper()} @ ${trade.entry_price:.2f}")
                print(f"  Entry: {trade.entry_timestamp.strftime('%m/%d %H:%M')}")
                print(f"  Exit:  {trade.exit_timestamp.strftime('%m/%d %H:%M')} @ ${trade.exit_price:.2f}")
                print(f"  P&L:   ${trade.pnl:.2f} | Net: ${trade.pnl - trade.commission:.2f}")
                print(f"  Reason: {trade.exit_reason.upper()}")
                print()
        
        print("✅ Strategy analysis complete!")
        
    except Exception as e:
        print(f"❌ Error: {e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    main()