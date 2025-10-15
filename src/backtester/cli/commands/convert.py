"""
Data conversion commands for the CLI.

Handles CSV ↔ Parquet conversions with progress tracking and validation.
"""

import click
import time
from pathlib import Path
from typing import List, Optional, Tuple
import polars as pl

from src.backtester.data.converters import CSVToParquetConverter, ParquetToCSVConverter
from ..utils import (
    validate_file_exists, 
    format_file_size, 
    format_duration,
    create_progress_bar,
    print_success,
    print_error,
    print_info
)


@click.group(name='convert')
def convert_group():
    """Convert between CSV and Parquet formats."""
    pass


@convert_group.command()
@click.argument('input_path', type=click.Path(exists=True, path_type=Path))
@click.argument('output_path', type=click.Path(path_type=Path))
@click.option('--force', '-f', is_flag=True, help='Overwrite existing output file')
@click.option('--validate', '-v', is_flag=True, help='Validate conversion after completion')
@click.option('--chunk-size', type=int, default=100_000, help='Chunk size for streaming processing')
@click.pass_context
def csv_to_parquet(ctx, input_path: Path, output_path: Path, force: bool, 
                  validate: bool, chunk_size: int):
    """
    Convert CSV file to Parquet format.
    
    INPUT_PATH: Path to the CSV file to convert
    OUTPUT_PATH: Path where the Parquet file will be saved
    
    Example:
        nq-backtester convert csv-to-parquet data.csv data.parquet
    """
    verbose = ctx.obj.get('verbose', False)
    quiet = ctx.obj.get('quiet', False)
    
    # Validate input
    if not validate_file_exists(input_path, 'CSV'):
        return
    
    if output_path.exists() and not force:
        print_error(f"Output file already exists: {output_path}")
        print_info("Use --force to overwrite")
        return
    
    # Display file information
    if not quiet:
        file_size_mb = input_path.stat().st_size / (1024 * 1024)
        print_info(f"📁 Input: {input_path}")
        print_info(f"📊 Size: {format_file_size(file_size_mb)} MB")
        print_info(f"💾 Output: {output_path}")
        
        if file_size_mb > 5000:  # Hardcoded threshold from converter
            print_info("🚀 Using standard mode (large file)")
        else:
            print_info("⚡ Using standard mode")
    
    # Create converter
    converter = CSVToParquetConverter(chunk_size=chunk_size)
    # Note: streaming_threshold is hardcoded in the converter
    
    # Start conversion with progress tracking
    start_time = time.perf_counter()
    
    if not quiet:
        with create_progress_bar("Converting CSV to Parquet") as progress:
            task = progress.add_task("Processing...", total=None)
            result = converter.convert(input_path, output_path)
            progress.update(task, completed=100, total=100)
    else:
        result = converter.convert(input_path, output_path)
    
    end_time = time.perf_counter()
    duration = end_time - start_time
    
    # Handle results
    if result['status'] == 'success':
        if not quiet:
            print_success("✅ Conversion completed successfully!")
            print_info(f"⏱️  Duration: {format_duration(duration)}")
            print_info(f"📊 Records: {result.get('rows', 'N/A'):,}")
            
            if 'output_size_mb' in result:
                print_info(f"💾 Output size: {format_file_size(result['output_size_mb'])} MB")
        
        # Optional validation
        if validate:
            _validate_conversion(input_path, output_path, verbose, quiet)
            
    elif result['status'] == 'skipped':
        if not quiet:
            print_info("⚠️  Conversion skipped (file already exists)")
    else:
        print_error(f"❌ Conversion failed: {result.get('error', 'Unknown error')}")
        if verbose and 'details' in result:
            print_error(f"Details: {result['details']}")


@convert_group.command()
@click.argument('input_path', type=click.Path(exists=True, path_type=Path))
@click.argument('output_path', type=click.Path(path_type=Path))
@click.option('--force', '-f', is_flag=True, help='Overwrite existing output file')
@click.option('--validate', '-v', is_flag=True, help='Validate conversion after completion')
@click.option('--chunk-size', type=int, default=100_000, help='Chunk size for streaming processing')
@click.option('--streaming-threshold', type=int, default=5000, help='File size threshold (MB) for streaming mode')
@click.pass_context
def parquet_to_csv(ctx, input_path: Path, output_path: Path, force: bool, 
                  validate: bool, chunk_size: int, streaming_threshold: int):
    """
    Convert Parquet file to CSV format.
    
    INPUT_PATH: Path to the Parquet file to convert
    OUTPUT_PATH: Path where the CSV file will be saved
    
    Example:
        nq-backtester convert parquet-to-csv data.parquet data.csv
    """
    verbose = ctx.obj.get('verbose', False)
    quiet = ctx.obj.get('quiet', False)
    
    # Validate input
    if not validate_file_exists(input_path, 'Parquet'):
        return
    
    if output_path.exists() and not force:
        print_error(f"Output file already exists: {output_path}")
        print_info("Use --force to overwrite")
        return
    
    # Display file information
    if not quiet:
        file_size_mb = input_path.stat().st_size / (1024 * 1024)
        print_info(f"📁 Input: {input_path}")
        print_info(f"📊 Size: {format_file_size(file_size_mb)} MB")
        print_info(f"💾 Output: {output_path}")
        
        if file_size_mb > streaming_threshold:
            print_info("🚀 Using streaming mode")
        else:
            print_info("⚡ Using standard mode")
    
    # Create converter
    converter = ParquetToCSVConverter(
        chunk_size=chunk_size,
        streaming_threshold_mb=streaming_threshold
    )
    
    # Start conversion with progress tracking
    start_time = time.perf_counter()
    
    if not quiet:
        with create_progress_bar("Converting Parquet to CSV") as progress:
            task = progress.add_task("Processing...", total=None)
            result = converter.convert(input_path, output_path)
            progress.update(task, completed=100, total=100)
    else:
        result = converter.convert(input_path, output_path)
    
    end_time = time.perf_counter()
    duration = end_time - start_time
    
    # Handle results
    if result['status'] == 'success':
        if not quiet:
            print_success("✅ Conversion completed successfully!")
            print_info(f"⏱️  Duration: {format_duration(duration)}")
            print_info(f"📊 Records: {result.get('records_processed', 'N/A'):,}")
            
            if 'output_size_mb' in result:
                print_info(f"💾 Output size: {format_file_size(result['output_size_mb'])} MB")
                
    elif result['status'] == 'skipped':
        if not quiet:
            print_info("⚠️  Conversion skipped (file already exists)")
    else:
        print_error(f"❌ Conversion failed: {result.get('error', 'Unknown error')}")
        if verbose and 'details' in result:
            print_error(f"Details: {result['details']}")


@convert_group.command()
@click.argument('input_dir', type=click.Path(exists=True, file_okay=False, path_type=Path))
@click.argument('output_dir', type=click.Path(path_type=Path))
@click.option('--pattern', default='*.csv', help='File pattern to match (default: *.csv)')
@click.option('--force', '-f', is_flag=True, help='Overwrite existing output files')
@click.option('--parallel', '-p', type=int, default=1, help='Number of parallel processes')
@click.option('--chunk-size', type=int, default=100_000, help='Chunk size for streaming processing')
@click.pass_context
def batch_csv_to_parquet(ctx, input_dir: Path, output_dir: Path, pattern: str,
                        force: bool, parallel: int, chunk_size: int):
    """
    Convert multiple CSV files to Parquet format.
    
    INPUT_DIR: Directory containing CSV files
    OUTPUT_DIR: Directory where Parquet files will be saved
    
    Example:
        nq-backtester convert batch-csv-to-parquet ./csv_data ./parquet_data
    """
    verbose = ctx.obj.get('verbose', False)
    quiet = ctx.obj.get('quiet', False)
    
    # Find CSV files
    csv_files = list(input_dir.glob(pattern))
    if not csv_files:
        print_error(f"No files matching pattern '{pattern}' found in {input_dir}")
        return
    
    # Create output directory
    output_dir.mkdir(parents=True, exist_ok=True)
    
    if not quiet:
        print_info(f"🔍 Found {len(csv_files)} files to convert")
        print_info(f"📁 Input directory: {input_dir}")
        print_info(f"💾 Output directory: {output_dir}")
    
    # Create converter
    converter = CSVToParquetConverter(chunk_size=chunk_size)
    
    # Track results
    successful = 0
    failed = 0
    skipped = 0
    start_time = time.perf_counter()
    
    # Process files
    if not quiet:
        with create_progress_bar("Batch conversion") as progress:
            task = progress.add_task("Converting files...", total=len(csv_files))
            
            for csv_file in csv_files:
                parquet_file = output_dir / f"{csv_file.stem}.parquet"
                
                # Skip if exists and not forcing
                if parquet_file.exists() and not force:
                    skipped += 1
                    progress.advance(task)
                    continue
                
                # Convert file
                result = converter.convert(csv_file, parquet_file)
                
                if result['status'] == 'success':
                    successful += 1
                elif result['status'] == 'skipped':
                    skipped += 1
                else:
                    failed += 1
                    if verbose:
                        print_error(f"Failed to convert {csv_file}: {result.get('error', 'Unknown error')}")
                
                progress.advance(task)
    else:
        # Quiet mode - no progress bar
        for csv_file in csv_files:
            parquet_file = output_dir / f"{csv_file.stem}.parquet"
            
            if parquet_file.exists() and not force:
                skipped += 1
                continue
            
            result = converter.convert(csv_file, parquet_file)
            
            if result['status'] == 'success':
                successful += 1
            elif result['status'] == 'skipped':
                skipped += 1
            else:
                failed += 1
    
    # Summary
    end_time = time.perf_counter()
    duration = end_time - start_time
    
    if not quiet:
        print_success("🎉 Batch conversion completed!")
        print_info(f"✅ Successful: {successful}")
        if skipped > 0:
            print_info(f"⚠️  Skipped: {skipped}")
        if failed > 0:
            print_error(f"❌ Failed: {failed}")
        print_info(f"⏱️  Total duration: {format_duration(duration)}")


def _validate_conversion(input_path: Path, output_path: Path, verbose: bool, quiet: bool):
    """Validate that conversion was successful by comparing record counts."""
    try:
        if not quiet:
            print_info("🔍 Validating conversion...")
        
        # Count input records
        if input_path.suffix.lower() == '.csv':
            with open(input_path, 'r') as f:
                input_records = sum(1 for _ in f)
        else:
            df = pl.read_parquet(input_path)
            input_records = len(df)
        
        # Count output records
        if output_path.suffix.lower() == '.parquet':
            df = pl.read_parquet(output_path)
            output_records = len(df)
        else:
            with open(output_path, 'r') as f:
                output_records = sum(1 for _ in f)
        
        # Compare
        if input_records == output_records:
            if not quiet:
                print_success(f"✅ Validation passed: {input_records:,} records preserved")
        else:
            print_error(f"❌ Validation failed: {input_records:,} → {output_records:,} records")
            
    except Exception as e:
        print_error(f"❌ Validation failed: {e}")
        if verbose:
            import traceback
            traceback.print_exc()