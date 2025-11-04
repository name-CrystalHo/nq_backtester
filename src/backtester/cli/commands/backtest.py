"""
Backtest command for running strategies on historical data.

Provides flexible data selection with glob patterns and comprehensive performance reporting.
"""

import click
from pathlib import Path
from typing import List, Optional, Dict, Any
from datetime import datetime, timedelta
import sys
import fnmatch
from concurrent.futures import ProcessPoolExecutor, as_completed
import multiprocessing as mp
import os

# Add src to path for imports
project_root = Path(__file__).parent.parent.parent.parent.parent
src_path = project_root / 'src'
if str(src_path) not in sys.path:
    sys.path.insert(0, str(src_path))

from src.backtester.engine.backtester import Backtester, BacktestConfig
from ..utils.listings import (
    list_available_contracts,
    list_available_strategies,
    list_available_data
)


def _run_single_file(args):
    """
    Process a single parquet file.
    
    This function is used by multiprocessing to run backtests in parallel.
    It must be at module level (not nested) for pickling.
    """
    parquet_file, strategy_name, config_dict = args
    
    # Import inside function to avoid pickling issues
    from src.backtester.engine.backtester import Backtester
    
    backtester = Backtester()
    result = backtester.run_backtest(
        strategy_name=strategy_name,
        data_file=str(parquet_file),
        config=config_dict
    )
    
    return result


@click.group(name='backtest')
def backtest_group():
    """Run backtests on historical market data."""
    pass


@backtest_group.command(name='run')
@click.argument('strategy', type=str, required=False)
@click.option('--data', '-d', type=str, default='*',
              help='Data pattern (*, *SEP25, NQ*, "NQ SEP25"). Default: * (all)')
@click.option('--start-date', type=click.DateTime(formats=['%Y-%m-%d']),
              help='Start date (YYYY-MM-DD). Optional.')
@click.option('--end-date', type=click.DateTime(formats=['%Y-%m-%d']),
              help='End date (YYYY-MM-DD). Optional.')
@click.option('--show-trades', is_flag=True,
              help='Show individual trade executions')
@click.option('--capital', default=50000, type=float,
              help='Initial capital (default: $50,000)')
@click.option('--commission', default=0.0, type=float,
              help='Commission per contract (default: $0.00)')
@click.option('--slippage', default=0, type=int,
              help='Slippage in ticks (default: 0)')
@click.option('--max-ticks', type=int,
              help='Max ticks to process (for testing)')
@click.option('--list-contracts', '-lc', is_flag=True,
              help='List available futures contracts')
@click.option('--list-strategies', '-ls', is_flag=True,
              help='List available trading strategies')
@click.option('--list-data', '-ld', is_flag=True,
              help='List available market data files')
@click.option('--workers', '-w', type=int, default=None,
              help='Number of parallel workers (default: CPU count - 2)')
@click.option('--verbose', '-v', is_flag=True,
              help='Verbose output')
@click.pass_context
def run(ctx, strategy: Optional[str], data: str, start_date: Optional[datetime], 
        end_date: Optional[datetime], show_trades: bool, capital: float,
        commission: float, slippage: int, max_ticks: Optional[int],
        list_contracts: bool, list_strategies: bool, list_data: bool, 
        workers: Optional[int], verbose: bool):
    """
    Run a backtest strategy on historical data.
    
    \b
    DATA PATTERNS:
    *              - All folders in storage/parquet/
    *SEP25         - All September 2025 contracts
    NQ*            - All NQ contracts  
    "NQ SEP25"     - Specific contract (use quotes)
    
    \b
    LIST AVAILABLE OPTIONS:
    --list-contracts    Show available futures contracts
    --list-strategies   Show available trading strategies
    --list-data         Show available market data files
    
    \b
    EXAMPLES:
    nq-backtester backtest run --list-contracts
    nq-backtester backtest run --list-strategies
    nq-backtester backtest run --list-data
    nq-backtester backtest run wicktest
    nq-backtester backtest run wicktest --data "NQ SEP25"
    nq-backtester backtest run wicktest --data "*SEP25" \\
        --start-date 2025-07-01 --end-date 2025-07-31 --show-trades
    """
    # Get verbose from context (set by main CLI --verbose flag)
    ctx_verbose = ctx.obj.get('verbose', False) if ctx.obj else False
    # Use command-specific verbose flag if provided, otherwise use context verbose
    verbose = verbose or ctx_verbose
    
    # Handle list commands first
    if list_contracts:
        list_available_contracts(verbose)
        return
    
    if list_strategies:
        list_available_strategies(verbose)
        return
    
    if list_data:
        list_available_data(verbose)
        return
    
    # Validate strategy argument
    if not strategy:
        click.echo("ERROR: Strategy name is required", err=True)
        click.echo("HINT: Use --list-strategies to see available options", err=True)
        ctx.exit(1)
    
    try:
        # Resolve data pattern
        data_paths = resolve_data_pattern(data, verbose)
        
        if not data_paths:
            click.echo(f"ERROR: No data found matching pattern: {data}", err=True)
            return
        
        click.echo(f"Running {strategy} strategy")
        click.echo(f"Matched {len(data_paths)} data source(s): {', '.join([p.name for p in data_paths])}")
        
        if start_date and end_date:
            click.echo(f"Date range: {start_date.date()} to {end_date.date()}")
        elif start_date:
            click.echo(f"From: {start_date.date()}")
        elif end_date:
            click.echo(f"Until: {end_date.date()}")
        click.echo("")  # Empty line before processing
        
        # Create config
        config = BacktestConfig(
            initial_capital=capital,
            commission_per_contract=commission,
            slippage_ticks=slippage,
            max_ticks=max_ticks
        )
        
        # Determine number of workers
        # Leave 2 CPUs free for OS and other processes to prevent memory errors
        if workers is None:
            workers = max(1, mp.cpu_count() - 2)
        
        # Collect all files to process
        all_files = []
        for data_path in data_paths:
            click.echo(f"Processing: {data_path.name}")
            
            # Get parquet files
            parquet_files = sorted(data_path.glob('*.parquet'))
            
            # Filter by date
            if start_date or end_date:
                parquet_files = filter_files_by_date(parquet_files, start_date, end_date)
            
            if not parquet_files:
                click.echo(f"   WARNING: No files in date range")
                continue
            
            click.echo(f"   Found {len(parquet_files)} file(s)")
            all_files.extend(parquet_files)
        
        if not all_files:
            click.echo("ERROR: No files to process", err=True)
            return
        
        click.echo(f"\nProcessing {len(all_files)} file(s) with {workers} worker(s)\n")
        
        # Process files in parallel
        all_results = []
        
        if workers == 1:
            # Serial processing (for debugging or single-core systems)
            backtester = Backtester()
            for parquet_file in all_files:
                result = backtester.run_backtest(
                    strategy_name=strategy,
                    data_file=str(parquet_file),
                    config=config.__dict__
                )
                if result.get('success'):
                    all_results.append(result)
        else:
            # Parallel processing
            tasks = [(f, strategy, config.__dict__) for f in all_files]
            
            with ProcessPoolExecutor(max_workers=workers) as executor:
                # Submit all tasks
                future_to_file = {
                    executor.submit(_run_single_file, task): task[0] 
                    for task in tasks
                }
                
                # Collect results as they complete
                for future in as_completed(future_to_file):
                    parquet_file = future_to_file[future]
                    try:
                        result = future.result()
                        if result.get('success'):
                            all_results.append(result)
                            if verbose:
                                click.echo(f"Completed: {parquet_file.name}")
                    except Exception as e:
                        click.echo(f"ERROR processing {parquet_file.name}: {e}", err=True)
        
        # Display results
        if all_results:
            display_results(all_results, show_trades, verbose)
        else:
            click.echo("ERROR: No successful results", err=True)
            
    except Exception as e:
        click.echo(f"Backtest failed: {e}", err=True)
        if verbose:
            import traceback
            traceback.print_exc()


def resolve_data_pattern(pattern: str, verbose: bool = False) -> List[Path]:
    """Resolve glob pattern to data directories."""
    project_root = Path(__file__).parent.parent.parent.parent.parent
    storage_path = project_root / 'storage' / 'parquet'
    
    if verbose:
        click.echo(f"Searching: {storage_path}")
        click.echo(f"Pattern: {pattern}")
    
    if not storage_path.exists():
        return []
    
    all_dirs = [d for d in storage_path.iterdir() if d.is_dir()]
    
    if pattern == '*':
        return all_dirs
    else:
        matched = [d for d in all_dirs if fnmatch.fnmatch(d.name, pattern)]
        if verbose:
            click.echo(f"Matched: {[d.name for d in matched]}")
        return matched


def filter_files_by_date(files: List[Path], start_date: Optional[datetime], 
                        end_date: Optional[datetime]) -> List[Path]:
    """Filter files by date range from filename (YYYYMMDD.parquet).
    
    NOTE: The parquet files are named one day earlier than their actual content.
    For example, 20250702.parquet contains data for 2025-07-03.
    We adjust for this offset when filtering.
    """
    if not start_date and not end_date:
        return files
    
    filtered = []
    for f in files:
        try:
            date_str = f.stem
            file_date = datetime.strptime(date_str, '%Y%m%d').date()
            
            # CRITICAL FIX: Files are named one day earlier than their content
            # So we need to subtract one day from the requested dates when comparing
            # Example: To get July 2nd data, we need file "20250701.parquet"
            if start_date and file_date < (start_date.date() - timedelta(days=1)):
                continue
            if end_date and file_date > (end_date.date() - timedelta(days=1)):
                continue
                
            filtered.append(f)
        except ValueError:
            continue
    
    return filtered


def display_results(results: List[Dict[str, Any]], show_trades: bool, verbose: bool):
    """Display backtest results."""
    total_ticks = sum(r.get('ticks_processed', 0) for r in results)
    total_time = sum(r.get('execution_time', 0) for r in results)
    total_signals = sum(r.get('signals_generated', 0) for r in results)
    
    # Get simulator trade counts
    simulator_trades = sum(r.get('simulator_trades', 0) for r in results)
    simulator_fills = sum(r.get('simulator_fills', 0) for r in results)
    
    # Calculate P&L from simulator trades
    all_sim_trades = []
    for r in results:
        if 'simulator_completed_trades' in r:
            all_sim_trades.extend(r['simulator_completed_trades'])
    
    # Sort trades chronologically by entry time
    all_sim_trades.sort(key=lambda t: t.entry_time)
    
    # Extract date range from file names
    date_range_str = ""
    if results:
        file_dates = []
        for r in results:
            data_file = r.get('data_file', '')
            if data_file:
                # Extract date from filename (format: YYYYMMDD.parquet)
                filename = Path(data_file).stem
                try:
                    # The file represents data for the NEXT day
                    # e.g., 20250630.parquet contains data for July 1st
                    file_date = datetime.strptime(filename, '%Y%m%d')
                    actual_date = file_date + timedelta(days=1)
                    file_dates.append(actual_date)
                except ValueError:
                    continue
        
        if file_dates:
            file_dates.sort()
            start_date = file_dates[0].strftime('%Y-%m-%d')
            end_date = file_dates[-1].strftime('%Y-%m-%d')
            if start_date == end_date:
                date_range_str = f"\nDate tested: {start_date}"
            else:
                date_range_str = f"\nDate range: {start_date} to {end_date}"
    
    click.echo("\n" + "="*80)
    click.echo("BACKTEST RESULTS")
    click.echo("="*80)
    
    if results:
        click.echo(f"\nStrategy: {results[0].get('strategy_name', 'Unknown')}")
        click.echo(f"Files processed: {len(results)}")
        if date_range_str:
            click.echo(date_range_str)
    
    if simulator_trades > 0 and all_sim_trades:
        total_pnl = sum(t.pnl for t in all_sim_trades)
        winning_trades = [t for t in all_sim_trades if t.pnl > 0]
        losing_trades = [t for t in all_sim_trades if t.pnl < 0]
        win_rate = len(winning_trades) / len(all_sim_trades) * 100 if all_sim_trades else 0
        
        click.echo(f"\nPerformance Summary:")
        click.echo(f"   Total P&L: ${total_pnl:,.2f}")
        click.echo(f"   Total Trades: {len(all_sim_trades)}")
        click.echo(f"   Winning trades: {len(winning_trades)}")
        click.echo(f"   Losing trades: {len(losing_trades)}")
        click.echo(f"   Win Rate: {win_rate:.1f}%")
        
        if winning_trades and losing_trades:
            avg_win = sum(t.pnl for t in winning_trades) / len(winning_trades)
            avg_loss = sum(t.pnl for t in losing_trades) / len(losing_trades)
            gross_profit = sum(t.pnl for t in winning_trades)
            gross_loss = abs(sum(t.pnl for t in losing_trades))
            profit_factor = gross_profit / gross_loss if gross_loss > 0 else float('inf')
            click.echo(f"   Avg Win: ${avg_win:.2f}")
            click.echo(f"   Avg Loss: ${avg_loss:.2f}")
            click.echo(f"   Profit Factor: {profit_factor:.2f}")
        
        # Show individual trades if requested
        if show_trades:
            click.echo(f"\n{'='*80}")
            click.echo(f"TRADE LOG ({len(all_sim_trades)} trades)")
            click.echo(f"{'='*80}")
            click.echo(f"{'#':<4} {'Side':<6} {'Entry Time':<20} {'Entry $':<10} {'Exit Time':<20} {'Exit $':<10} {'P&L':<10} {'Dur':<8}")
            click.echo("-"*80)
            
            for i, trade in enumerate(all_sim_trades, 1):
                duration_mins = trade.duration_seconds / 60
                if duration_mins < 60:
                    duration_str = f"{duration_mins:.0f}m"
                else:
                    duration_str = f"{duration_mins/60:.1f}h"
                    
                entry_time_str = trade.entry_time.strftime("%Y-%m-%d %H:%M:%S")
                exit_time_str = trade.exit_time.strftime("%Y-%m-%d %H:%M:%S")
                pnl_str = f"${trade.pnl:,.2f}"
                
                # Color code P&L (if terminal supports it)
                if trade.pnl > 0:
                    pnl_str = click.style(pnl_str, fg='green')
                elif trade.pnl < 0:
                    pnl_str = click.style(pnl_str, fg='red')
                
                click.echo(f"{i:<4} {trade.side.upper():<6} {entry_time_str:<20} ${trade.entry_price:<9.2f} {exit_time_str:<20} ${trade.exit_price:<9.2f} {pnl_str:<19} {duration_str:<8}")
            
            click.echo("-"*80)
            click.echo(f"Total: ${total_pnl:,.2f}")
    else:
        click.echo("\nNo completed trades")
    
    if verbose:
        click.echo(f"\nExecution Metrics:")
        click.echo(f"   Ticks processed: {total_ticks:,}")
        click.echo(f"   Execution time: {total_time:.2f}s")
        if total_time > 0:
            click.echo(f"   Throughput: {total_ticks/total_time:,.0f} ticks/sec")
        
        if results and 'strategy_info' in results[0]:
            bars_count = results[0]['strategy_info'].get('bars_in_history', 0)
            click.echo(f"   Bars created: {bars_count:,}")
        click.echo(f"   Signals generated: {total_signals:,}")
        click.echo(f"   Order fills: {simulator_fills:,}")
    
    click.echo("\n" + "="*80)
