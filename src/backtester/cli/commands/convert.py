"""
Data conversion commands for the CLI.

Provides commands to convert NinjaTrader CSV data to Parquet format.
"""

import click
from pathlib import Path
from typing import Optional

# Import the converter function from the data module
from backtester.data.converter import convert_csv_to_parquet


@click.group(name='convert')
def convert_group():
    """Convert between CSV and Parquet formats."""
    pass


@convert_group.command(name='ninjatrader')
@click.option(
    '--source',
    default=None,
    type=click.Path(exists=True),
    help='Source directory containing CSV files (default: C:\\Users\\cryst\\Documents\\NinjaTrader 8\\db\\replay.csv)'
)
@click.option(
    '--output',
    default=None,
    type=click.Path(),
    help='Output directory for Parquet files (default: ./storage/parquet)'
)
@click.option(
    '--instrument',
    help='Filter by instrument name (e.g., "NQ SEP25")'
)
@click.option(
    '--skip-existing/--force',
    default=True,
    help='Skip files that already exist in output (default: skip)'
)
@click.option(
    '--validate',
    is_flag=True,
    help='Run validation after conversion'
)
@click.option(
    '--workers',
    default=None,
    type=int,
    help='Number of parallel processes (default: auto-detect CPU count)'
)
def ninjatrader(source: Optional[str], output: Optional[str], instrument: Optional[str], 
                skip_existing: bool, validate: bool, workers: Optional[int]):
    """
    Convert NinjaTrader CSV files to optimized Parquet format.
    
    This command converts NinjaTrader Market Replay CSV files to Parquet format
    for high-performance backtesting. It supports parallel processing and can
    filter by instrument.
    
    Examples:
    
    \b
    # Convert all NQ SEP25 files
    python -m src.backtester.cli convert ninjatrader --instrument "NQ SEP25"
    
    \b
    # Convert with custom paths
    python -m src.backtester.cli convert ninjatrader \\
        --source "C:\\Data\\NinjaTrader\\csv" \\
        --output "storage/parquet"
    
    \b
    # Force reconversion of existing files
    python -m src.backtester.cli convert ninjatrader \\
        --instrument "NQ SEP25" \\
        --force
    """
    click.echo("🎯 NinjaTrader CSV to Parquet Converter")
    click.echo("=" * 50)
    
    if source:
        click.echo(f"📁 Source: {source}")
    else:
        click.echo(f"📁 Source: C:\\Users\\cryst\\Documents\\NinjaTrader 8\\db\\replay.csv (default)")
    
    if output:
        click.echo(f"💾 Output: {output}")
    else:
        click.echo(f"💾 Output: ./storage/parquet (default)")
    
    if instrument:
        click.echo(f"🔍 Filter: {instrument}")
    
    click.echo(f"⚡ Workers: {workers if workers else 'auto-detect'}")
    click.echo(f"♻️  Skip existing: {skip_existing}")
    click.echo("")
    
    try:
        # Convert output path to correct default
        if output is None:
            output = str(Path("storage") / "parquet")
        
        summary = convert_csv_to_parquet(
            source_dir=source,
            output_dir=output,
            instrument_filter=instrument,
            skip_existing=skip_existing,
            max_workers=workers,
            validate_output=validate
        )
        
        click.echo("\n" + "=" * 50)
        click.echo("📊 CONVERSION SUMMARY")
        click.echo("=" * 50)
        click.echo(f"Successfully processed: {summary.get('processed', 0)}")
        click.echo(f"Skipped (already exist): {summary.get('skipped', 0)}")
        click.echo(f"Failed: {summary.get('failed', 0)}")
        click.echo(f"Total size: {summary.get('total_size_mb', 0):.2f} MB")
        
        if summary.get('status') == 'success':
            click.echo(f"\n✅ Conversion completed successfully!")
        elif summary.get('status') == 'partial':
            click.echo(f"\n⚠️  Conversion completed with some failures.")
        
        if summary.get('processed', 0) == 0 and summary.get('skipped', 0) > 0:
            click.echo(f"\n⚠️  All files were skipped (already exist). Use --force to reconvert.")
            
    except Exception as e:
        click.echo(f"\n❌ Conversion failed: {e}", err=True)
        raise click.ClickException(str(e))
