"""
Production CLI - Command line interface for production data operations

Quick commands for managing production data:
- show: Display data overview  
- load: Load data for testing
- validate: Check data integrity
- stats: Show storage statistics
"""

import click
from pathlib import Path
import os
from datetime import datetime
from backtester.data import (
    ProductionDataManager,
    show_available_data,
    quick_load_data
)


@click.group()
def prod_cli():
    """Production data management CLI for NQ Backtester."""
    pass


@prod_cli.command()
def show():
    """Show overview of available production data."""
    show_available_data()


@prod_cli.command()
@click.argument('instrument')
@click.option('--date', help='Date in YYYYMMDD format (optional)')
@click.option('--limit', default=5, help='Number of sample records to show')
def load(instrument, date, limit):
    """Load and display sample data for an instrument."""
    click.echo(f"📊 Loading data for {instrument}")
    if date:
        click.echo(f"   Date: {date}")
    
    try:
        data = quick_load_data(instrument, date)
        
        if data.empty:
            click.echo("❌ No data found")
            return
        
        click.echo(f"✅ Loaded {len(data):,} records")
        click.echo(f"🕐 Time range: {data['timestamp'].min()} to {data['timestamp'].max()}")
        
        if 'record_type' in data.columns:
            record_counts = data['record_type'].value_counts()
            click.echo(f"📋 Record types:")
            for record_type, count in record_counts.items():
                click.echo(f"   {record_type}: {count:,} records")
        
        click.echo(f"\n📄 Sample data (first {limit} records):")
        click.echo(data.head(limit).to_string(index=False))
        
    except Exception as e:
        click.echo(f"❌ Error loading data: {e}")


@prod_cli.command()
def validate():
    """Validate data integrity across all instruments."""
    click.echo("🔍 Validating production data integrity...")
    
    manager = ProductionDataManager()
    results = manager.validate_data_integrity()
    
    click.echo(f"✅ Validation complete:")
    click.echo(f"   Validated: {results['validated_instruments']}/{results['total_instruments']} instruments")
    
    if results['issues']:
        click.echo(f"⚠️ Issues found: {len(results['issues'])}")
        for issue in results['issues']:
            click.echo(f"   - {issue}")
    else:
        click.echo("✅ No issues found")


@prod_cli.command()
def stats():
    """Show detailed storage statistics."""
    click.echo("📊 Production Storage Statistics")
    click.echo("=" * 40)
    
    manager = ProductionDataManager()
    stats = manager.get_storage_stats()
    
    click.echo(f"Storage root: {stats['storage_root']}")
    click.echo(f"Total size: {stats['total_size_gb']:.3f} GB")
    click.echo(f"Total files: {stats['file_count']}")
    
    if stats['instruments']:
        click.echo(f"\nInstruments:")
        for instrument, info in stats['instruments'].items():
            click.echo(f"  {instrument}:")
            click.echo(f"    Files: {info['files']}")
            click.echo(f"    Size: {info['size_gb']:.3f} GB")


@prod_cli.command()
@click.option('--dry-run', is_flag=True, help='Show what would be cleaned without actually deleting')
def cleanup(dry_run):
    """Clean up temporary and incomplete files from interrupted conversions."""
    click.echo("🧹 Cleaning up temporary and incomplete files...")
    
    manager = ProductionDataManager()
    storage_path = Path(manager.processed_dir)
    
    # Find temporary files
    temp_files = list(storage_path.rglob("*.tmp"))
    parquet_temp_files = list(storage_path.rglob("*.parquet.tmp"))
    
    all_temp_files = temp_files + parquet_temp_files
    
    if not all_temp_files:
        click.echo("✅ No temporary files found - storage is clean!")
        return
    
    click.echo(f"Found {len(all_temp_files)} temporary files:")
    total_size = 0
    
    for temp_file in all_temp_files:
        try:
            size_mb = temp_file.stat().st_size / (1024 * 1024)
            total_size += size_mb
            click.echo(f"  📄 {temp_file.name} ({size_mb:.2f} MB)")
        except Exception as e:
            click.echo(f"  ❌ {temp_file.name} (error reading: {e})")
    
    click.echo(f"\nTotal temporary files: {len(all_temp_files)} ({total_size:.2f} MB)")
    
    if dry_run:
        click.echo("🔍 Dry run - no files were deleted")
        return
    
    if click.confirm(f"\nDelete all {len(all_temp_files)} temporary files?"):
        deleted = 0
        freed_mb = 0
        
        for temp_file in all_temp_files:
            try:
                size_mb = temp_file.stat().st_size / (1024 * 1024)
                temp_file.unlink()
                deleted += 1
                freed_mb += size_mb
                click.echo(f"  ✅ Deleted {temp_file.name}")
            except Exception as e:
                click.echo(f"  ❌ Failed to delete {temp_file.name}: {e}")
        
        click.echo(f"\n✅ Cleanup complete:")
        click.echo(f"   Files deleted: {deleted}")
        click.echo(f"   Space freed: {freed_mb:.2f} MB")
    else:
        click.echo("❌ Cleanup cancelled")


def _filter_instruments_by_pattern(instruments, pattern):
    """
    Filter instruments using advanced pattern matching.
    
    Supports:
    - Simple substring: '25' - ONLY instruments containing 25 (2025 contracts)
    - Simple substring: 'SEP25' - ONLY instruments containing SEP25  
    - Exclusion: '!25' - does NOT contain 25 (exclude 2025 contracts)
    - Regex: 'JUN|MAR' - contains JUN OR MAR
    - Wildcard: '*25' - anything ending with 25
    - Complex regex: 'NQ.*2[234]' - NQ contracts from 2022-2024
    """
    import re
    
    if not pattern:
        return instruments
    
    # Exclusion pattern (starts with !)
    if pattern.startswith('!'):
        exclude_pattern = pattern[1:]
        try:
            # Try as regex first
            regex = re.compile(exclude_pattern, re.IGNORECASE)
            return [inst for inst in instruments if not regex.search(inst)]
        except re.error:
            # Fall back to simple substring exclusion
            return [inst for inst in instruments if exclude_pattern.upper() not in inst.upper()]
    
    # Convert simple wildcards to regex
    if '*' in pattern:
        # Convert shell-style wildcards to regex
        regex_pattern = pattern.replace('*', '.*')
        try:
            regex = re.compile(regex_pattern, re.IGNORECASE)
            return [inst for inst in instruments if regex.search(inst)]
        except re.error:
            # Fall back to simple substring matching
            return [inst for inst in instruments if pattern.replace('*', '').upper() in inst.upper()]
    
    # Regular pattern (inclusion) - try as regex first, then substring
    try:
        # Try as regex first
        regex = re.compile(pattern, re.IGNORECASE)
        return [inst for inst in instruments if regex.search(inst)]
    except re.error:
        # Fall back to simple substring matching (INCLUDE only matches)
        return [inst for inst in instruments if pattern.upper() in inst.upper()]


def _interactive_data_selection(ninja_trader_path, instrument_filter):
    """Interactive selection of data to import."""
    source_path = Path(ninja_trader_path)
    
    if not source_path.exists():
        click.echo(f"❌ Source directory not found: {ninja_trader_path}")
        return None
    
    # Get available instruments
    instruments = []
    for item in source_path.iterdir():
        if item.is_dir():
            instruments.append(item.name)
    
    if not instruments:
        click.echo("❌ No instrument directories found")
        return None
    
    instruments.sort()
    
    click.echo(f"\n📊 Found {len(instruments)} instruments in {ninja_trader_path}")
    click.echo("=" * 60)
    
    # Show instruments with file counts
    for i, inst in enumerate(instruments, 1):
        inst_path = source_path / inst
        csv_files = list(inst_path.glob("*.csv"))
        total_size = sum(f.stat().st_size for f in csv_files) / (1024**3)  # GB
        click.echo(f"{i:2d}. {inst:<15} ({len(csv_files):3d} files, {total_size:.2f} GB)")
    
    click.echo("=" * 60)
    
    # If instrument filter already provided, confirm it
    if instrument_filter:
        matching_instruments = [inst for inst in instruments if instrument_filter.upper() in inst.upper()]
        if matching_instruments:
            click.echo(f"\n🎯 Instrument filter '{instrument_filter}' matches {len(matching_instruments)} instruments:")
            for inst in matching_instruments:
                click.echo(f"   - {inst}")
            
            if click.confirm(f"\nProceed with filter '{instrument_filter}'?"):
                return instrument_filter
            else:
                click.echo("Filter cancelled, showing full selection...")
        else:
            click.echo(f"⚠️ No instruments match filter '{instrument_filter}'")
            if not click.confirm("Continue with manual selection?"):
                return None
    
    # Interactive selection
    click.echo(f"\n🚀 Data Import Options:")
    click.echo("1. Import ALL instruments (full dataset)")
    click.echo("2. Import specific instrument")
    click.echo("3. Import instruments matching pattern (e.g., 'NQ')")
    click.echo("4. Cancel")
    
    choice = click.prompt("\nSelect option", type=int, default=1)
    
    if choice == 1:
        # All instruments
        total_files = sum(len(list((source_path / inst).glob("*.csv"))) for inst in instruments)
        total_size = sum(
            sum(f.stat().st_size for f in (source_path / inst).glob("*.csv")) 
            for inst in instruments
        ) / (1024**3)
        
        click.echo(f"\n⚠️ This will process ALL {len(instruments)} instruments:")
        click.echo(f"   📁 Total files: {total_files:,}")
        click.echo(f"   💾 Total size: {total_size:.2f} GB")
        click.echo(f"   🗜️ Expected output: ~{total_size*0.11:.2f} GB (89% compression)")
        click.echo(f"   ⏱️ Estimated time: {total_files/10000:.1f} minutes at 10K files/hour")
        click.echo(f"   💻 Recommended workers: 16-22 for your 24-core system")
        
        if click.confirm("\nProceed with FULL import?", default=False):
            return None  # None means all instruments
        else:
            return _interactive_data_selection(ninja_trader_path, None)  # Restart selection
            
    elif choice == 2:
        # Specific instrument
        click.echo(f"\nAvailable instruments:")
        for i, inst in enumerate(instruments, 1):
            click.echo(f"{i:2d}. {inst}")
        
        inst_choice = click.prompt(f"\nSelect instrument (1-{len(instruments)})", type=int)
        if 1 <= inst_choice <= len(instruments):
            selected = instruments[inst_choice - 1]
            inst_path = source_path / selected
            csv_files = list(inst_path.glob("*.csv"))
            size_gb = sum(f.stat().st_size for f in csv_files) / (1024**3)
            
            click.echo(f"\n📊 Selected: {selected}")
            click.echo(f"   📁 Files: {len(csv_files)}")
            click.echo(f"   💾 Size: {size_gb:.2f} GB")
            
            if click.confirm(f"Import {selected}?"):
                return selected
        
        click.echo("Invalid selection")
        return None
        
    elif choice == 3:
        # Advanced pattern matching
        click.echo(f"\n🎯 Pattern Matching Options:")
        click.echo("Examples:")
        click.echo("  '25' - ONLY 2025 contracts (NQ JUN25, NQ SEP25, etc.)")
        click.echo("  'SEP25' - ONLY September 2025 contracts")
        click.echo("  '*25' - ONLY contracts ending with 25")
        click.echo("  '22|23' - ONLY 2022 OR 2023 contracts (regex)")
        click.echo("  '!25' - EXCLUDE 2025 contracts (everything except 25)")
        click.echo("  'JUN.*2[234]' - Regex: JUN contracts from 2022-2024")
        
        pattern = click.prompt("\nEnter pattern", type=str)
        matching = _filter_instruments_by_pattern(instruments, pattern)
        
        if not matching:
            click.echo(f"❌ No instruments match pattern '{pattern}'")
            return None
            
        click.echo(f"\n🎯 Pattern '{pattern}' matches {len(matching)} instruments:")
        total_files = 0
        total_size = 0
        for inst in matching:
            inst_path = source_path / inst
            csv_files = list(inst_path.glob("*.csv"))
            size_gb = sum(f.stat().st_size for f in csv_files) / (1024**3)
            total_files += len(csv_files)
            total_size += size_gb
            click.echo(f"   - {inst:<15} ({len(csv_files):3d} files, {size_gb:.2f} GB)")
        
        click.echo(f"\nTotal to import: {len(matching)} instruments, {total_files} files, {total_size:.2f} GB")
        
        if click.confirm(f"\nImport all instruments matching '{pattern}'?"):
            return pattern
        else:
            return None
            
    else:
        # Cancel
        return None


@prod_cli.command()
@click.argument('ninja_trader_path', required=False)
@click.option('--instrument', help='Filter by specific instrument (e.g., NQ)')
@click.option('--workers', type=int, help='Number of worker processes')
@click.option('--skip-existing/--overwrite', default=True, help='Skip existing files')
@click.option('--interactive/--no-interactive', default=True, help='Interactive mode for data selection')
def import_data(ninja_trader_path, instrument, workers, skip_existing, interactive):
    """Import NinjaTrader CSV data to production storage."""
    if ninja_trader_path is None:
        ninja_trader_path = r"C:\Users\cryst\Documents\NinjaTrader 8\db\replay.csv"
        click.echo(f"🚀 Importing NinjaTrader data (using default path)...")
    else:
        click.echo(f"🚀 Importing NinjaTrader data...")
    
    click.echo(f"   Source: {ninja_trader_path}")
    
    # Interactive mode for data selection
    if interactive:
        final_instrument = _interactive_data_selection(ninja_trader_path, instrument)
        if final_instrument is None:
            click.echo("❌ Operation cancelled")
            return
    else:
        final_instrument = instrument
    
    if final_instrument:
        click.echo(f"   Filter: {final_instrument}")
    
    try:
        manager = ProductionDataManager()
        summary = manager.import_ninja_trader_data(
            ninja_trader_path=ninja_trader_path,
            instrument_filter=final_instrument,
            max_workers=workers,
            skip_existing=skip_existing
        )
        
        click.echo(f"✅ Import complete:")
        click.echo(f"   Files processed: {summary['processed']}")
        click.echo(f"   Total records: {summary['total_rows']:,}")
        click.echo(f"   Storage used: {summary['total_size_mb']:.2f} MB")
        
    except Exception as e:
        click.echo(f"❌ Import failed: {e}")


if __name__ == '__main__':
    prod_cli()