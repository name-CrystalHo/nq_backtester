"""
CLI Interface for NQ Backtester

Provides command-line interface for common backtesting operations.
"""

import click
from pathlib import Path
import sys
from datetime import datetime, date
from typing import Optional
import json

# Add backtester to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from backtester import Backtester, DataLoader
from backtester.data.converter import convert_csv_to_parquet, validate_csv_file
from backtester.engine.backtester import BacktestConfig
from backtester.strategies.base_strategy import (
    SimpleMovingAverageStrategy, 
    BuyAndHoldStrategy,
    MeanReversionStrategy
)


@click.group()
@click.version_option(version='1.0.0')
def cli():
    """NQ Backtester - High-performance tick data backtesting for NinjaTrader Market Replay data.
    
    Commands:
      convert  - Convert NinjaTrader CSV to optimized Parquet
      backtest - Run backtesting strategies  
      prod     - Production data management (show, load, import, etc.)
    """
    pass


@cli.command()
@click.option('--source', '-s', required=True, type=click.Path(exists=True),
              help='Source CSV file or directory')
@click.option('--output', '-o', default='./data/parquet', type=click.Path(),
              help='Output directory for Parquet files')
@click.option('--validate', '-v', is_flag=True,
              help='Validate CSV files before conversion')
@click.option('--max-workers', '-w', default=4, type=int,
              help='Maximum number of worker processes')
@click.option('--chunk-size', default=50000, type=int,
              help='Chunk size for processing large files')
def convert(source, output, validate, max_workers, chunk_size):
    """Convert NinjaTrader CSV files to optimized Parquet format."""
    
    click.echo("🔄 Converting NinjaTrader CSV to Parquet...")
    
    source_path = Path(source)
    output_path = Path(output)
    
    # Validation if requested
    if validate:
        click.echo("🔍 Validating CSV files...")
        try:
            if source_path.is_file():
                result = validate_csv_file(source_path)
                if not result['valid']:
                    click.echo("❌ Validation failed:")
                    for error in result['errors']:
                        click.echo(f"   - {error}")
                    sys.exit(1)
                click.echo("✅ Validation passed")
            else:
                click.echo("📁 Directory validation not implemented yet")
        except Exception as e:
            click.echo(f"❌ Validation error: {e}")
            sys.exit(1)
    
    # Perform conversion
    try:
        if source_path.is_file():
            from backtester.data.converter import convert_single_csv
            result = convert_single_csv(source_path, output_path, chunk_size=chunk_size)
            click.echo(f"✅ Converted {result['rows']:,} records")
            click.echo(f"   Output size: {result['size_mb']:.2f} MB")
        else:
            result = convert_csv_to_parquet(
                source_dir=source_path,
                output_dir=output_path,
                max_workers=max_workers,
                chunk_size=chunk_size
            )
            click.echo(f"✅ Converted {result['files_processed']} files")
            click.echo(f"   Total records: {result['total_records']:,}")
            click.echo(f"   Total size: {result['total_size_mb']:.2f} MB")
            
    except Exception as e:
        click.echo(f"❌ Conversion failed: {e}")
        sys.exit(1)


@cli.command()
@click.option('--data-dir', '-d', required=True, type=click.Path(exists=True),
              help='Directory containing Parquet data files')
@click.option('--instrument', '-i', required=True, type=str,
              help='Instrument symbol (e.g., NQ)')
@click.option('--start-date', '-s', required=True, type=click.DateTime(formats=['%Y-%m-%d']),
              help='Start date (YYYY-MM-DD)')
@click.option('--end-date', '-e', required=True, type=click.DateTime(formats=['%Y-%m-%d']),
              help='End date (YYYY-MM-DD)')
@click.option('--strategy', type=click.Choice(['ma', 'buyhold', 'meanrev']), default='ma',
              help='Strategy type')
@click.option('--capital', default=100000, type=float,
              help='Initial capital')
@click.option('--commission', default=2.50, type=float,
              help='Commission per contract')
@click.option('--slippage', default=0, type=int,
              help='Slippage in ticks')
@click.option('--quantity', default=1, type=int,
              help='Position size')
@click.option('--output', '-o', type=click.Path(),
              help='Output file for results')
@click.option('--format', type=click.Choice(['summary', 'ninja', 'json']), default='summary',
              help='Output format')
def backtest(data_dir, instrument, start_date, end_date, strategy, capital, 
             commission, slippage, quantity, output, format):
    """Run a backtest on historical data."""
    
    click.echo(f"🎯 Running backtest: {instrument} from {start_date.date()} to {end_date.date()}")
    
    try:
        # Initialize data loader
        loader = DataLoader(data_dir)
        
        # Check data availability
        available_instruments = loader.get_available_instruments()
        if instrument not in available_instruments:
            click.echo(f"❌ Instrument '{instrument}' not found")
            click.echo(f"   Available instruments: {available_instruments}")
            sys.exit(1)
        
        # Create strategy
        if strategy == 'ma':
            strategy_obj = SimpleMovingAverageStrategy(short_window=5, long_window=10, quantity=quantity)
        elif strategy == 'buyhold':
            strategy_obj = BuyAndHoldStrategy(quantity=quantity)
        elif strategy == 'meanrev':
            strategy_obj = MeanReversionStrategy(window=20, threshold=2.0, quantity=quantity)
        else:
            click.echo(f"❌ Unknown strategy: {strategy}")
            sys.exit(1)
        
        # Create config
        config = BacktestConfig(
            initial_capital=capital,
            commission_per_contract=commission,
            slippage_ticks=slippage
        )
        
        # Run backtest
        backtester = Backtester(strategy_obj, loader, config)
        results = backtester.run(
            instrument, 
            start_date.date(), 
            end_date.date()
        )
        
        # Output results
        if format == 'summary':
            results.print_summary(f"{strategy.upper()} Strategy Results")
            
        elif format == 'ninja':
            if output:
                results.export_ninja_format(output)
                click.echo(f"📄 Results exported to: {output}")
            else:
                click.echo("❌ Output file required for ninja format")
                
        elif format == 'json':
            metrics = results.get_performance_metrics()
            result_data = {
                'strategy': strategy,
                'instrument': instrument,
                'start_date': start_date.date().isoformat(),
                'end_date': end_date.date().isoformat(),
                'config': {
                    'capital': capital,
                    'commission': commission,
                    'slippage': slippage,
                    'quantity': quantity
                },
                'metrics': metrics
            }
            
            if output:
                with open(output, 'w') as f:
                    json.dump(result_data, f, indent=2, default=str)
                click.echo(f"📄 Results exported to: {output}")
            else:
                click.echo(json.dumps(result_data, indent=2, default=str))
        
        # Show summary stats
        click.echo(f"\n📊 Summary:")
        click.echo(f"   Total Return: {results.total_return:.2%}")
        click.echo(f"   Total Trades: {results.total_trades}")
        click.echo(f"   Win Rate: {results.win_rate:.2%}")
        click.echo(f"   Max Drawdown: {results.max_drawdown:.2%}")
        
    except Exception as e:
        click.echo(f"❌ Backtest failed: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


@cli.command()
@click.option('--data-dir', '-d', required=True, type=click.Path(exists=True),
              help='Directory containing Parquet data files')
def info(data_dir):
    """Show information about available data."""
    
    try:
        loader = DataLoader(data_dir)
        
        click.echo("📊 Data Information")
        click.echo("=" * 30)
        
        instruments = loader.get_available_instruments()
        click.echo(f"Instruments: {len(instruments)}")
        
        for instrument in instruments:
            click.echo(f"\n📈 {instrument}:")
            dates = loader.get_available_dates(instrument)
            if dates:
                click.echo(f"   Date range: {min(dates)} to {max(dates)}")
                click.echo(f"   Total days: {len(dates)}")
                
                # Sample a day to show record count
                sample_date = dates[0]
                sample_data = loader.load_day(instrument, sample_date)
                click.echo(f"   Sample day ({sample_date}): {len(sample_data):,} records")
            else:
                click.echo("   No dates available")
                
    except Exception as e:
        click.echo(f"❌ Failed to read data info: {e}")
        sys.exit(1)


@cli.command()
@click.option('--data-dir', '-d', required=True, type=click.Path(exists=True),
              help='Directory containing Parquet data files')
@click.option('--instrument', '-i', required=True, type=str,
              help='Instrument symbol')
@click.option('--date', required=True, type=click.DateTime(formats=['%Y-%m-%d']),
              help='Date to validate (YYYY-MM-DD)')
@click.option('--sample-size', default=1000, type=int,
              help='Number of records to sample for validation')
def validate(data_dir, instrument, date, sample_size):
    """Validate data integrity and show sample records."""
    
    try:
        loader = DataLoader(data_dir)
        
        click.echo(f"🔍 Validating {instrument} data for {date.date()}")
        
        # Load data
        data = loader.load_day(instrument, date.date())
        
        if data.empty:
            click.echo("❌ No data found for specified date")
            sys.exit(1)
        
        click.echo(f"✅ Loaded {len(data):,} records")
        
        # Basic validation
        click.echo("\n📋 Data Validation:")
        
        # Check for required columns
        required_cols = ['timestamp', 'market_data_type', 'price', 'volume']
        missing_cols = [col for col in required_cols if col not in data.columns]
        if missing_cols:
            click.echo(f"❌ Missing columns: {missing_cols}")
        else:
            click.echo("✅ All required columns present")
        
        # Check for null values
        null_counts = data.isnull().sum()
        if null_counts.any():
            click.echo("⚠️  Null values found:")
            for col, count in null_counts[null_counts > 0].items():
                click.echo(f"   {col}: {count}")
        else:
            click.echo("✅ No null values found")
        
        # Check timestamp ordering
        if data['timestamp'].is_monotonic_increasing:
            click.echo("✅ Timestamps are properly ordered")
        else:
            click.echo("⚠️  Timestamps are not properly ordered")
        
        # Show data sample
        sample_data = data.head(sample_size)
        click.echo(f"\n📄 Sample Records (first {len(sample_data)}):")
        
        # Group by type for cleaner display
        l1_data = sample_data[sample_data['market_data_type'] == 1]
        l2_data = sample_data[sample_data['market_data_type'] == 0]
        
        if not l1_data.empty:
            click.echo(f"\nL1 Records ({len(l1_data)}):")
            click.echo(l1_data[['timestamp', 'price', 'volume']].head().to_string(index=False))
        
        if not l2_data.empty:
            click.echo(f"\nL2 Records ({len(l2_data)}):")
            l2_sample = l2_data[['timestamp', 'operation', 'position', 'price', 'volume']].head()
            click.echo(l2_sample.to_string(index=False))
        
        # Show time range
        time_range = data['timestamp'].max() - data['timestamp'].min()
        click.echo(f"\n⏱️  Time Range: {time_range}")
        click.echo(f"   Start: {data['timestamp'].min()}")
        click.echo(f"   End: {data['timestamp'].max()}")
        
    except Exception as e:
        click.echo(f"❌ Validation failed: {e}")
        sys.exit(1)


# Add production CLI as subcommand
from .prod_cli import prod_cli
cli.add_command(prod_cli, name='prod')


if __name__ == '__main__':
    cli()