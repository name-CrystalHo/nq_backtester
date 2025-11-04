"""
Simple script to run backtest and output results to text file.
This replaces the CLI for faster iteration.
"""

import sys
from pathlib import Path
from datetime import datetime, timedelta
import pandas as pd

# Add src to path
project_root = Path(__file__).parent
src_path = project_root / 'src'
sys.path.insert(0, str(src_path))

from backtester.engine.backtester import Backtester, BacktestConfig


def run_backtest(
    strategy_name: str,
    contract: str,
    start_date: str,  # Format: "YYYY-MM-DD"
    end_date: str,    # Format: "YYYY-MM-DD"
    output_file: str = None
):
    """
    Run backtest for a date range and output results.
    
    Args:
        strategy_name: Name of strategy (e.g., "wicktest")
        contract: Contract name (e.g., "NQ SEP25")
        start_date: Start date as "YYYY-MM-DD"
        end_date: End date as "YYYY-MM-DD"
        output_file: Optional output file path. If None, prints to console.
    """
    
    # Parse dates
    start = datetime.strptime(start_date, "%Y-%m-%d")
    end = datetime.strptime(end_date, "%Y-%m-%d")
    
    # Find data directory
    storage_path = project_root / 'storage' / 'parquet' / contract
    if not storage_path.exists():
        print(f"❌ Data directory not found: {storage_path}")
        return
    
    # Get parquet files in date range
    # NOTE: Files are named one day earlier than their content
    # e.g., 20250630.parquet contains July 1st data
    all_files = sorted(storage_path.glob('*.parquet'))
    
    filtered_files = []
    for f in all_files:
        try:
            file_date = datetime.strptime(f.stem, '%Y%m%d').date()
            # Adjust for file naming offset (file is named one day earlier)
            if start.date() - timedelta(days=1) <= file_date <= end.date() - timedelta(days=1):
                filtered_files.append(f)
        except ValueError:
            continue
    
    if not filtered_files:
        print(f"❌ No files found in date range {start_date} to {end_date}")
        return
    
    print(f"🎯 Running {strategy_name} strategy on {contract}")
    print(f"📅 Date range: {start_date} to {end_date}")
    print(f"📊 Processing {len(filtered_files)} file(s)")
    print()
    
    # Configure backtester
    config = BacktestConfig(
        initial_capital=50000,
        commission_per_contract=0.0,
        slippage_ticks=0,
        max_ticks=None
    )
    
    # Run backtest on each file
    backtester = Backtester()
    all_trades = []
    
    for i, data_file in enumerate(filtered_files, 1):
        file_date_obj = datetime.strptime(data_file.stem, '%Y%m%d') + timedelta(days=1)
        file_date_str = file_date_obj.strftime('%Y-%m-%d')
        
        print(f"Processing [{i}/{len(filtered_files)}]: {file_date_str}...", end=" ")
        
        result = backtester.run_backtest(
            strategy_name=strategy_name,
            data_file=str(data_file),
            config=config.__dict__
        )
        
        if result.get('success'):
            trades = result.get('simulator_completed_trades', [])
            all_trades.extend(trades)
            print(f"✅ {len(trades)} trades")
        else:
            print(f"❌ Failed")
    
    print()
    
    # Prepare output
    output_lines = []
    output_lines.append("=" * 80)
    output_lines.append("📊 BACKTEST RESULTS")
    output_lines.append("=" * 80)
    output_lines.append(f"\n📈 Strategy: {strategy_name}")
    output_lines.append(f"📁 Contract: {contract}")
    output_lines.append(f"📅 Date range: {start_date} to {end_date}")
    output_lines.append(f"📊 Files processed: {len(filtered_files)}")
    
    if all_trades:
        # Sort trades by entry time
        all_trades.sort(key=lambda t: t.entry_time)
        
        # Calculate statistics
        total_pnl = sum(t.pnl for t in all_trades)
        winning_trades = [t for t in all_trades if t.pnl > 0]
        losing_trades = [t for t in all_trades if t.pnl < 0]
        breakeven_trades = [t for t in all_trades if t.pnl == 0]
        win_rate = len(winning_trades) / len(all_trades) * 100 if all_trades else 0
        
        output_lines.append(f"\n💰 Performance Summary:")
        output_lines.append(f"   Total P&L: ${total_pnl:,.2f}")
        output_lines.append(f"   Total Trades: {len(all_trades)}")
        output_lines.append(f"   Winning trades: {len(winning_trades)}")
        output_lines.append(f"   Losing trades: {len(losing_trades)}")
        output_lines.append(f"   Breakeven trades: {len(breakeven_trades)}")
        output_lines.append(f"   Win Rate: {win_rate:.1f}%")
        
        if winning_trades and losing_trades:
            avg_win = sum(t.pnl for t in winning_trades) / len(winning_trades)
            avg_loss = sum(t.pnl for t in losing_trades) / len(losing_trades)
            gross_profit = sum(t.pnl for t in winning_trades)
            gross_loss = abs(sum(t.pnl for t in losing_trades))
            profit_factor = gross_profit / gross_loss if gross_loss > 0 else float('inf')
            
            output_lines.append(f"   Avg Win: ${avg_win:.2f}")
            output_lines.append(f"   Avg Loss: ${avg_loss:.2f}")
            output_lines.append(f"   Profit Factor: {profit_factor:.2f}")
        
        # Trade log
        output_lines.append(f"\n{'=' * 80}")
        output_lines.append(f"📋 TRADE LOG ({len(all_trades)} trades)")
        output_lines.append(f"{'=' * 80}")
        output_lines.append(f"{'#':<4} {'Side':<6} {'Entry Time':<20} {'Entry $':<10} {'Exit Time':<20} {'Exit $':<10} {'P&L':<12} {'Dur':<8}")
        output_lines.append("-" * 80)
        
        for i, trade in enumerate(all_trades, 1):
            duration_mins = trade.duration_seconds / 60
            if duration_mins < 60:
                duration_str = f"{duration_mins:.0f}m"
            else:
                duration_str = f"{duration_mins / 60:.1f}h"
            
            entry_time_str = trade.entry_time.strftime("%Y-%m-%d %H:%M:%S")
            exit_time_str = trade.exit_time.strftime("%Y-%m-%d %H:%M:%S")
            pnl_str = f"${trade.pnl:,.2f}"
            
            line = f"{i:<4} {trade.side.upper():<6} {entry_time_str:<20} ${trade.entry_price:<9.2f} {exit_time_str:<20} ${trade.exit_price:<9.2f} {pnl_str:<12} {duration_str:<8}"
            output_lines.append(line)
        
        output_lines.append("-" * 80)
        output_lines.append(f"Total: ${total_pnl:,.2f}")
    else:
        output_lines.append("\n⚠️  No completed trades")
    
    output_lines.append("\n" + "=" * 80)
    
    # Output results
    output_text = "\n".join(output_lines)
    
    if output_file:
        output_path = Path(output_file)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        with open(output_path, 'w', encoding='utf-8') as f:
            f.write(output_text)
        print(f"✅ Results saved to: {output_file}")
    else:
        print(output_text)


if __name__ == "__main__":
    # Run backtest for the requested date range
    run_backtest(
        strategy_name="wicktest",
        contract="NQ SEP25",
        start_date="2025-06-16",
        end_date="2025-06-16",  # Just 6/16 for debugging
        output_file="results/wicktest_cli_output_20251027.txt"
    )
