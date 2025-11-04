"""
Compare CLI backtest output to NinjaTrader baseline CSV.
Fast iteration approach - just run the CLI and compare outputs.
"""

import pandas as pd
import re
from datetime import datetime
from pathlib import Path


def parse_cli_output(txt_file: str) -> pd.DataFrame:
    """Parse trade log from CLI output text file."""
    
    with open(txt_file, 'r', encoding='utf-8') as f:
        lines = f.readlines()
    
    # Find the trade log section
    start_idx = None
    end_idx = None
    
    for i, line in enumerate(lines):
        if '📋 TRADE LOG' in line:
            # Skip the header lines (log header, column names, separator)
            start_idx = i + 3
        elif start_idx and line.startswith('---'):
            if 'Total:' in lines[i+1]:
                end_idx = i
                break
    
    if start_idx is None or end_idx is None:
        print("❌ Could not find trade log in CLI output")
        return pd.DataFrame()
    
    # Parse trades
    trades = []
    for line in lines[start_idx:end_idx]:
        parts = line.split()
        if len(parts) >= 8:
            trade_num = int(parts[0])
            side = parts[1].lower()
            
            # Entry time and price
            entry_date = parts[2]
            entry_time = parts[3]
            entry_dt = datetime.strptime(f"{entry_date} {entry_time}", "%Y-%m-%d %H:%M:%S")
            entry_price = float(parts[4].replace('$', '').replace(',', ''))
            
            # Exit time and price
            exit_date = parts[5]
            exit_time = parts[6]
            exit_dt = datetime.strptime(f"{exit_date} {exit_time}", "%Y-%m-%d %H:%M:%S")
            exit_price = float(parts[7].replace('$', '').replace(',', ''))
            
            # P&L
            pnl_str = parts[8].replace('$', '').replace(',', '')
            pnl = float(pnl_str)
            
            trades.append({
                'trade_num': trade_num,
                'side': side,
                'entry_time': entry_dt,
                'entry_price': entry_price,
                'exit_time': exit_dt,
                'exit_price': exit_price,
                'pnl': pnl
            })
    
    df = pd.DataFrame(trades)
    print(f"✅ Parsed {len(df)} trades from CLI output")
    return df


def load_baseline_csv(csv_file: str) -> pd.DataFrame:
    """Load and parse NinjaTrader baseline CSV."""
    
    df = pd.read_csv(csv_file)
    
    # Parse dates
    df['entry_time'] = pd.to_datetime(df['Entry time'])
    df['exit_time'] = pd.to_datetime(df['Exit time'])
    
    # Parse side (NinjaTrader uses "Long" or "Short")
    df['side'] = df['Market pos.'].str.lower()
    
    # Parse prices
    df['entry_price'] = df['Entry price'].astype(float)
    df['exit_price'] = df['Exit price'].astype(float)
    
    # Parse P&L (handle parentheses for negatives)
    def parse_pnl(val):
        val_str = str(val).strip()
        # Check for parentheses pattern
        if val_str.startswith('(') and val_str.endswith(')'):
            # Remove parentheses and $, convert to negative
            num_str = val_str[1:-1].replace('$', '').replace(',', '')
            return -float(num_str)
        else:
            # Regular positive or negative
            return float(val_str.replace('$', '').replace(',', ''))
    
    df['pnl'] = df['Profit'].apply(parse_pnl)
    
    # Keep only needed columns
    df = df[['side', 'entry_time', 'entry_price', 'exit_time', 'exit_price', 'pnl']].copy()
    
    print(f"✅ Loaded {len(df)} trades from baseline CSV")
    return df


def compare_trades(cli_df: pd.DataFrame, baseline_df: pd.DataFrame):
    """Compare trades and generate report."""
    
    print("\n" + "="*80)
    print("📊 COMPARISON SUMMARY")
    print("="*80)
    
    print(f"\n📈 Trade Counts:")
    print(f"   CLI Output:  {len(cli_df)} trades")
    print(f"   Baseline:    {len(baseline_df)} trades")
    print(f"   Difference:  {len(cli_df) - len(baseline_df)} trades")
    
    print(f"\n💰 Total P&L:")
    cli_pnl = cli_df['pnl'].sum()
    baseline_pnl = baseline_df['pnl'].sum()
    print(f"   CLI Output:  ${cli_pnl:,.2f}")
    print(f"   Baseline:    ${baseline_pnl:,.2f}")
    print(f"   Difference:  ${cli_pnl - baseline_pnl:,.2f}")
    
    # Show side breakdown
    print(f"\n📊 Trade Breakdown:")
    print(f"   CLI Long:    {len(cli_df[cli_df['side'] == 'long'])}")
    print(f"   CLI Short:   {len(cli_df[cli_df['side'] == 'short'])}")
    print(f"   Base Long:   {len(baseline_df[baseline_df['side'] == 'long'])}")
    print(f"   Base Short:  {len(baseline_df[baseline_df['side'] == 'short'])}")
    
    # Show time ranges
    print(f"\n📅 Time Ranges:")
    print(f"   CLI:      {cli_df['entry_time'].min()} to {cli_df['entry_time'].max()}")
    print(f"   Baseline: {baseline_df['entry_time'].min()} to {baseline_df['entry_time'].max()}")
    
    # Sample comparison - first 10 trades side by side
    print(f"\n{'='*80}")
    print("📋 SAMPLE COMPARISON (First 10 Trades)")
    print(f"{'='*80}")
    print(f"\n{'Source':<12} {'#':<4} {'Side':<6} {'Entry Time':<20} {'Entry $':<10} {'P&L':<10}")
    print("-"*80)
    
    for i in range(min(10, len(cli_df), len(baseline_df))):
        # CLI trade
        c = cli_df.iloc[i]
        print(f"{'CLI':<12} {c['trade_num']:<4} {c['side'].upper():<6} {c['entry_time'].strftime('%Y-%m-%d %H:%M:%S'):<20} ${c['entry_price']:<9.2f} ${c['pnl']:<9.2f}")
        
        # Baseline trade
        b = baseline_df.iloc[i]
        print(f"{'Baseline':<12} {i+1:<4} {b['side'].upper():<6} {b['entry_time'].strftime('%Y-%m-%d %H:%M:%S'):<20} ${b['entry_price']:<9.2f} ${b['pnl']:<9.2f}")
        
        # Show difference if any
        time_diff_seconds = abs((c['entry_time'] - b['entry_time']).total_seconds())
        price_diff = abs(c['entry_price'] - b['entry_price'])
        pnl_diff = abs(c['pnl'] - b['pnl'])
        
        if time_diff_seconds > 5 or price_diff > 1.0 or pnl_diff > 10:
            print(f"{'  DIFF':<12} {'':4} {'':6} {f'Δ{time_diff_seconds:.0f}s':<20} {f'Δ{price_diff:.2f}':<10} {f'Δ{pnl_diff:.2f}':<10}")
        
        print()
    
    print("="*80)
    print("\n💡 Next Steps:")
    print("   1. Review the trade counts and P&L differences")
    print("   2. Check the sample comparison for any obvious mismatches")
    print("   3. If differences exist, investigate specific dates/times")
    print()


if __name__ == "__main__":
    # File paths
    cli_output = "results/wicktest_cli_output_20251027.txt"
    baseline_csv = r"C:\Users\cryst\Documents\wicktestsep25.csv"
    
    # Parse files
    print("🔄 Loading data...\n")
    cli_df = parse_cli_output(cli_output)
    baseline_df = load_baseline_csv(baseline_csv)
    
    if cli_df.empty or baseline_df.empty:
        print("❌ Failed to load data")
    else:
        # Compare
        compare_trades(cli_df, baseline_df)
