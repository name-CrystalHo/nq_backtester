"""
Data conversion commands for the CLI.

Handles CSV ↔ Parquet conversions with progress tracking and validation.
Uses ProcessPoolExecutor for true multicore scaling (bypasses Python GIL).
"""

import click
import time
from pathlib import Path
from typing import List, Optional, Tuple
import polars as pl
from concurrent.futures import ProcessPoolExecutor, ThreadPoolExecutor, as_completed
import os

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

# Global converter instance for process pool workers (initialized once per process)
_worker_converter = None


def _init_worker_process(chunk_size: int, streaming_threshold_mb: int):
    """
    Initialize worker process with converter instance.
    
    This function is called once per worker process at startup to reduce
    per-file converter creation overhead.
    
    Args:
        chunk_size: Chunk size for processing
        streaming_threshold_mb: Streaming threshold in MB
    """
    global _worker_converter
    _worker_converter = CSVToParquetConverter(chunk_size=chunk_size)
    _worker_converter.streaming_threshold_mb = streaming_threshold_mb


def _convert_single_file_worker(args):
    """
    Worker function for ProcessPoolExecutor to convert a single CSV file.
    
    Uses pre-initialized converter instance for better performance.
    
    Args:
        args: Tuple containing (csv_file, source_path, output_path, force)
    
    Returns:
        Tuple of (csv_file, result_dict)
    """
    csv_file, source_path, output_path, force = args
    
    try:
        # Use pre-initialized converter instance
        global _worker_converter
        converter = _worker_converter
        
        # Calculate relative path and target parquet file
        rel_path = csv_file.relative_to(source_path)
        parquet_file = output_path / rel_path.with_suffix('.parquet')
        
        # Create subdirectories as needed
        parquet_file.parent.mkdir(parents=True, exist_ok=True)
        
        # Skip if exists and not forcing
        if parquet_file.exists() and not force:
            return csv_file, {'status': 'skipped', 'reason': 'exists'}
        
        # Convert with high-parallelism optimizations (streaming for >100MB files)
        result = converter.convert(csv_file, parquet_file, skip_existing=False, 
                                 fast_validation=True, high_parallelism=True)
        return csv_file, result
        
    except Exception as e:
        return csv_file, {'status': 'error', 'error': str(e)}


def _convert_single_file_sequential(csv_file, source, output, force, converter):
    """
    Sequential version for single-threaded processing.
    
    Args:
        csv_file: Path to CSV file
        source: Source directory path  
        output: Output directory path
        force: Whether to overwrite existing files
        converter: CSVToParquetConverter instance
    
    Returns:
        Tuple of (csv_file, result_dict)
    """
    try:
        # Calculate relative path and target parquet file
        rel_path = csv_file.relative_to(source)
        parquet_file = output / rel_path.with_suffix('.parquet')
        
        # Create subdirectories as needed
        parquet_file.parent.mkdir(parents=True, exist_ok=True)
        
        # Skip if exists and not forcing
        if parquet_file.exists() and not force:
            return csv_file, {'status': 'skipped', 'reason': 'exists'}
        
        # Convert with high-parallelism optimizations for sequential processing  
        result = converter.convert(csv_file, parquet_file, skip_existing=False, 
                                 fast_validation=True, high_parallelism=True)
        return csv_file, result
        
    except Exception as e:
        return csv_file, {'status': 'error', 'error': str(e)}


def _convert_single_file_threaded(args):
    """
    Threaded version for testing compatibility (maintains mocking support).
    
    Args:
        args: Tuple containing (csv_file, source_path, output_path, force, converter)
    
    Returns:
        Tuple of (csv_file, result_dict)  
    """
    csv_file, source_path, output_path, force, converter = args
    return _convert_single_file_sequential(csv_file, source_path, output_path, force, converter)


def _should_use_process_executor():
    """
    Determine whether to use ProcessPoolExecutor vs ThreadPoolExecutor.
    
    Uses ThreadPoolExecutor for testing (to maintain mock compatibility)
    and ProcessPoolExecutor for production (for true multicore scaling).
    
    Returns:
        True if ProcessPoolExecutor should be used
    """
    # Use ThreadPoolExecutor when testing (pytest environment)
    # or when NINJA_USE_THREADS env var is set (for debugging)
    return (not os.environ.get('PYTEST_CURRENT_TEST') and 
            not os.environ.get('NINJA_USE_THREADS'))


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


@convert_group.command()
@click.option('--source', '-s', 
              type=click.Path(exists=True, file_okay=False, path_type=Path),
              default=r'C:\Users\cryst\Documents\NinjaTrader 8\db\replay.csv',
              help='Source directory for NinjaTrader CSV files')
@click.option('--output', '-o',
              type=click.Path(path_type=Path),
              default='src/backtester/data/storage/parquet',
              help='Output directory for Parquet files')
@click.option('--filter', '-f',
              help='Regex pattern to filter folders/files (e.g., "NQ SEP25" or ".*SEP25.*")')
@click.option('--dry-run', '-d', is_flag=True,
              help='Show what would be converted without actually converting')
@click.option('--force', is_flag=True,
              help='Overwrite existing output files')
@click.option('--chunk-size', type=int, default=100_000,
              help='Chunk size for processing large files')
@click.option('--streaming-threshold', type=int, default=300,
              help='File size threshold (MB) for streaming mode (default: 300MB)')
@click.option('--parallel', '-p', type=int, default=0,
              help='Number of parallel workers (0=auto-detect, 1=sequential, >1=manual)')
@click.pass_context
def ninjatrader_convert(ctx, source: Path, output: Path, filter: Optional[str], 
                       dry_run: bool, force: bool, chunk_size: int, 
                       streaming_threshold: int, parallel: int):
    """
    Convert NinjaTrader CSV data to Parquet with flexible filtering.
    
    This command is optimized for NinjaTrader's directory structure and supports
    filtering by instrument folders, date ranges, or specific files using regex.
    
    Performance Options:
        --parallel 0          # Auto-detect optimal workers (default, recommended)
        --parallel 4          # Force 4 parallel workers  
        --streaming-threshold 100  # Use streaming for files >100MB (faster for large files)
        --chunk-size 500000   # Larger chunks for better performance (default: 100k)
    
    Examples:
        # Convert with auto-detected optimal workers (recommended)
        nq-backtester convert ninjatrader-convert --filter "NQ SEP25"
        
        # Convert with manual worker count
        nq-backtester convert ninjatrader-convert --filter "NQ SEP25" --parallel 8
        
        # High-performance conversion with auto-optimization
        nq-backtester convert ninjatrader-convert --filter "NQ SEP25" --streaming-threshold 100
        
        # Dry run to see what would be converted
        nq-backtester convert ninjatrader-convert --filter "NQ SEP25" --dry-run
    """
    import re
    verbose = ctx.obj.get('verbose', False)
    quiet = ctx.obj.get('quiet', False)
    
    def calculate_optimal_workers(manual_workers: int, total_files: int) -> int:
        """
        Calculate optimal number of workers based on system resources.
        
        Args:
            manual_workers: User-specified worker count (0=auto)
            total_files: Total number of files to process
            
        Returns:
            Optimal number of workers
        """
        import psutil
        import os
        
        # If user specified manual workers, respect their choice
        if manual_workers > 0:
            return manual_workers
        
        try:
            # Get system information
            cpu_count = os.cpu_count() or 4  # Fallback to 4 if unknown
            memory_gb = psutil.virtual_memory().total / (1024**3)
            available_memory_gb = psutil.virtual_memory().available / (1024**3)
            
            # Adaptive worker calculation
            # Base on CPU cores but consider memory and I/O constraints
            
            # OPTIMIZED: Target 8-10 workers for optimal I/O performance (empirically tested)
            if cpu_count <= 4:
                base_workers = max(1, cpu_count - 1)  # Leave 1 core free
            elif cpu_count <= 8:
                base_workers = min(8, cpu_count - 1)  # Sweet spot for I/O
            else:
                # High-end systems: 8-10 workers provide best I/O utilization
                base_workers = min(10, cpu_count // 2)  # Cap at 10 for optimal performance
            
            # Reduced memory per worker with optimizations (400MB vs 750MB)
            memory_limited_workers = int(available_memory_gb / 0.5)  # 500MB per worker
            
            # Choose the limiting factor
            optimal_workers = min(base_workers, memory_limited_workers)
            
            # Don't exceed the number of files (no point having more workers than files)
            optimal_workers = min(optimal_workers, total_files)
            
            # Ensure at least 1 worker
            optimal_workers = max(1, optimal_workers)
            
            # PERFORMANCE: Cap at 10 workers for optimal I/O (prevents disk thrashing)
            optimal_workers = min(optimal_workers, 10)
            
            if not quiet:
                print_info(f"🧠 System resources: {cpu_count} CPU cores, {available_memory_gb:.1f}GB available RAM")
                print_info(f"⚡ Auto-detected optimal workers: {optimal_workers}")
                if optimal_workers != base_workers:
                    if optimal_workers == memory_limited_workers:
                        print_info(f"   └─ Limited by available memory ({available_memory_gb:.1f}GB)")
                    elif optimal_workers == total_files:
                        print_info(f"   └─ Limited by file count ({total_files} files)")
            
            return optimal_workers
            
        except Exception as e:
            # Fallback to conservative default if detection fails
            fallback_workers = min(4, total_files) if total_files > 0 else 1
            if not quiet:
                print_info(f"⚠️  Auto-detection failed ({e}), using {fallback_workers} workers")
            return fallback_workers
    
    if not source.exists():
        print_error(f"Source directory does not exist: {source}")
        print_info("Please ensure NinjaTrader is installed and has replay data")
        return
    
    # Create output directory
    output.mkdir(parents=True, exist_ok=True)
    
    # Find CSV files with optional filtering
    csv_files = []
    
    if filter:
        try:
            pattern = re.compile(filter, re.IGNORECASE)
            if not quiet:
                print_info(f"🔍 Applying filter: {filter}")
        except re.error as e:
            print_error(f"Invalid regex pattern: {e}")
            return
    else:
        pattern = None
        if not quiet:
            print_info("⚠️  No filter specified - will process ALL CSV files")
            print_info("   This could be 500GB+ of data. Consider using --filter option.")
    
    # Walk through directory structure
    for item in source.rglob('*.csv'):
        if pattern:
            # Check if any part of the path matches the pattern
            path_parts = str(item.relative_to(source)).replace('\\', '/')
            if pattern.search(path_parts):
                csv_files.append(item)
        else:
            csv_files.append(item)
    
    if not csv_files:
        print_error("No CSV files found matching the criteria")
        if filter:
            print_info(f"Filter: {filter}")
        print_info(f"Source: {source}")
        return
    
    # PERFORMANCE OPTIMIZATION: Sort files by size (largest first) for better worker utilization
    # This prevents idle workers at the end and ensures large files start processing early
    csv_files.sort(key=lambda f: f.stat().st_size, reverse=True)
    
    # Calculate total size
    total_size_bytes = sum(f.stat().st_size for f in csv_files)
    total_size_gb = total_size_bytes / (1024 ** 3)
    
    # Calculate optimal workers based on system resources
    optimal_workers = calculate_optimal_workers(parallel, len(csv_files))
    parallel = optimal_workers  # Update parallel count with optimal value
    
    if not quiet:
        print_info(f"📊 Found {len(csv_files)} CSV files")
        print_info(f"💾 Total size: {total_size_gb:.2f} GB")
        print_info(f"📁 Source: {source}")
        print_info(f"💾 Output: {output}")
    
    # Show files that would be processed
    if verbose or dry_run:
        print_info(f"\n📋 Files to process:")
        for csv_file in csv_files[:10]:  # Show first 10
            rel_path = csv_file.relative_to(source)
            size_mb = csv_file.stat().st_size / (1024 ** 2)
            print_info(f"  • {rel_path} ({size_mb:.1f} MB)")
        
        if len(csv_files) > 10:
            print_info(f"  ... and {len(csv_files) - 10} more files")
    
    # Dry run - just show what would happen
    if dry_run:
        print_info(f"\n🔍 DRY RUN: Would convert {len(csv_files)} files ({total_size_gb:.2f} GB)")
        
        # Show expected parquet structure
        print_info(f"\n📁 Expected Parquet Structure:")
        print_info(f"Output Directory: {output}")
        
        # Group files by their directory structure
        dir_structure = {}
        estimated_parquet_size = 0
        
        # Create converter instance to check streaming decisions
        dry_run_converter = CSVToParquetConverter(chunk_size=chunk_size)
        dry_run_converter.streaming_threshold_mb = streaming_threshold
        
        for csv_file in csv_files[:10]:  # Show first 10 files
            rel_path = csv_file.relative_to(source)
            parquet_path = rel_path.with_suffix('.parquet')
            
            # Get directory
            parent_dir = parquet_path.parent
            if parent_dir not in dir_structure:
                dir_structure[parent_dir] = []
            
            # Estimate parquet size (typically 20-30% of CSV size)
            csv_size_mb = csv_file.stat().st_size / (1024 ** 2)
            estimated_parquet_mb = csv_size_mb * 0.25  # Conservative 25% compression
            estimated_parquet_size += estimated_parquet_mb
            
            # Check processing mode
            try:
                will_stream = dry_run_converter.should_use_streaming(csv_file)
                mode_indicator = "🌊" if will_stream else "📄"
                mode_text = "stream" if will_stream else "regular"
            except Exception:
                # Fallback for testing - use simple threshold check
                will_stream = csv_size_mb > streaming_threshold
                mode_indicator = "🌊" if will_stream else "📄"
                mode_text = "stream" if will_stream else "regular"
            
            dir_structure[parent_dir].append((parquet_path.name, estimated_parquet_mb, mode_indicator, mode_text))
        
        # Display structure with processing modes
        for parent_dir, files in dir_structure.items():
            if parent_dir == Path('.'):
                print_info(f"├── (root)")
            else:
                print_info(f"├── {parent_dir}/")
            
            for i, file_info in enumerate(files):
                filename, size_mb, mode_indicator, mode_text = file_info
                prefix = "└──" if i == len(files) - 1 else "├──"
                print_info(f"│   {prefix} {mode_indicator} {filename} (~{size_mb:.1f} MB, {mode_text})")
        
        if len(csv_files) > 10:
            remaining_size = (total_size_gb * 1024 - estimated_parquet_size) * 0.25
            print_info(f"│   ... and {len(csv_files) - 10} more files (~{remaining_size:.0f} MB)")
        
        total_estimated_gb = total_size_gb * 0.25  # 25% compression estimate
        print_info(f"\n💾 Estimated Parquet Size: ~{total_estimated_gb:.2f} GB")
        
        # Show adaptive threshold information
        try:
            adaptive_threshold = dry_run_converter._calculate_adaptive_threshold()
            print_info(f"🧠 Adaptive streaming threshold: {adaptive_threshold:.0f} MB (base: {streaming_threshold} MB)")
            print_info(f"🌊 Streaming mode: files > {adaptive_threshold:.0f} MB")
            print_info(f"📄 Regular mode: files ≤ {adaptive_threshold:.0f} MB")
        except Exception:
            # Fallback for testing or other issues
            print_info(f"🧠 Base streaming threshold: {streaming_threshold} MB")
            print_info(f"🌊 Streaming mode: files > {streaming_threshold} MB")
            print_info(f"📄 Regular mode: files ≤ {streaming_threshold} MB")
        
        print_info("📋 Add --force to actually perform the conversion")
        return
    
    # Confirm for large operations
    if total_size_gb > 10 and not force:
        print_info(f"\n⚠️  Large operation: {total_size_gb:.2f} GB of data")
        if not click.confirm("Continue with conversion?"):
            print_info("Operation cancelled")
            return
    
    # Process files
    converter = CSVToParquetConverter(chunk_size=chunk_size)
    converter.streaming_threshold_mb = streaming_threshold  # Override default 5GB threshold
    successful = 0
    failed = 0
    skipped = 0
    start_time = time.perf_counter()
    
    if not quiet:
        with create_progress_bar("Converting NinjaTrader data", show_current_file=True) as progress:
            task = progress.add_task(
                f"Processing files (workers: {parallel})...", 
                total=len(csv_files),
                current_file=""
            )
            
            # Use parallel processing if parallel > 1, otherwise sequential
            if parallel > 1:
                # Choose executor type based on environment (Process for production, Thread for testing)
                use_processes = _should_use_process_executor()
                executor_class = ProcessPoolExecutor if use_processes else ThreadPoolExecutor
                executor_name = "ProcessPool" if use_processes else "ThreadPool"
                
                # Log executor choice for transparency
                if hasattr(converter, 'logger'):
                    converter.logger.info(f"🚀 Using {executor_name}Executor for true multicore scaling")
                
                # Configure executor with initializer for ProcessPoolExecutor
                executor_kwargs = {'max_workers': parallel}
                if use_processes:
                    # Add process pool initializer to reduce per-file setup overhead
                    executor_kwargs['initializer'] = _init_worker_process
                    executor_kwargs['initargs'] = (chunk_size, streaming_threshold)
                
                with executor_class(**executor_kwargs) as executor:
                    if use_processes:
                        # ProcessPoolExecutor: use pre-initialized converter
                        worker_args = [
                            (csv_file, source, output, force)
                            for csv_file in csv_files
                        ]
                        future_to_file = {
                            executor.submit(_convert_single_file_worker, args): args[0]
                            for args in worker_args
                        }
                    else:
                        # ThreadPoolExecutor: can share converter instance  
                        worker_args = [
                            (csv_file, source, output, force, converter)
                            for csv_file in csv_files
                        ]
                        future_to_file = {
                            executor.submit(_convert_single_file_threaded, args): args[0]
                            for args in worker_args
                        }
                    
                    completed_count = 0
                    total_speed = 0
                    speed_count = 0
                    
                    # Process completed tasks
                    for future in as_completed(future_to_file):
                        csv_file = future_to_file[future]
                        completed_count += 1
                        
                        try:
                            file_path, result = future.result()
                            rel_path = file_path.relative_to(source)
                            
                            # Update progress
                            progress.update(
                                task, 
                                current_file=f"[{completed_count}/{len(csv_files)}] {rel_path.name}"
                            )
                            
                            # Process result
                            if result['status'] == 'success':
                                successful += 1
                                # Calculate speed if timing info available
                                if 'duration' in result and result['duration'] > 0:
                                    size_mb = file_path.stat().st_size / (1024 ** 2)
                                    speed_mbps = size_mb / result['duration']
                                    total_speed += speed_mbps
                                    speed_count += 1
                            elif result['status'] == 'skipped' or result.get('reason') == 'exists':
                                skipped += 1
                            else:
                                failed += 1
                                progress.update(
                                    task,
                                    current_file=f"❌ FAILED: {rel_path.name}"
                                )
                            
                        except Exception as e:
                            failed += 1
                            rel_path = csv_file.relative_to(source)
                            progress.update(
                                task,
                                current_file=f"❌ ERROR: {rel_path.name} - {str(e)}"
                            )
                        
                        # Update average speed
                        if speed_count > 0:
                            avg_speed = total_speed / speed_count
                            progress.update(
                                task,
                                description=f"Converting ({avg_speed:.1f} MB/s avg, {parallel} workers)"
                            )
                        
                        progress.advance(task)
            else:
                # Sequential processing (original logic)
                for i, csv_file in enumerate(csv_files):
                    file_path, result = _convert_single_file_sequential(csv_file, source, output, force, converter)
                    rel_path = file_path.relative_to(source)
                    
                    # Update progress with current file info
                    progress.update(
                        task, 
                        current_file=f"[{i+1}/{len(csv_files)}] {rel_path.name}"
                    )
                    
                    # Process result
                    if result['status'] == 'success':
                        successful += 1
                    elif result['status'] == 'skipped' or result.get('reason') == 'exists':
                        skipped += 1
                    else:
                        failed += 1
                        progress.update(
                            task,
                            current_file=f"❌ FAILED: {rel_path.name}"
                        )
                    
                    progress.advance(task)
            
            # Final update
            progress.update(task, current_file="✅ Conversion complete!")
    else:
        # Quiet mode processing
        if parallel > 1:
            # Choose executor type based on environment
            use_processes = _should_use_process_executor()
            executor_class = ProcessPoolExecutor if use_processes else ThreadPoolExecutor
            
            # Configure executor with initializer for ProcessPoolExecutor
            executor_kwargs = {'max_workers': parallel}
            if use_processes:
                # Add process pool initializer to reduce per-file setup overhead
                executor_kwargs['initializer'] = _init_worker_process
                executor_kwargs['initargs'] = (chunk_size, streaming_threshold)
            
            # Parallel processing in quiet mode
            with executor_class(**executor_kwargs) as executor:
                if use_processes:
                    # ProcessPoolExecutor: use pre-initialized converter
                    worker_args = [
                        (csv_file, source, output, force)
                        for csv_file in csv_files
                    ]
                    future_to_file = {
                        executor.submit(_convert_single_file_worker, args): args[0]
                        for args in worker_args
                    }
                else:
                    # ThreadPoolExecutor: can share converter instance
                    worker_args = [
                        (csv_file, source, output, force, converter)
                        for csv_file in csv_files
                    ]
                    future_to_file = {
                        executor.submit(_convert_single_file_threaded, args): args[0]
                        for args in worker_args
                    }
                
                for future in as_completed(future_to_file):
                    try:
                        file_path, result = future.result()
                        if result['status'] == 'success':
                            successful += 1
                        elif result['status'] == 'skipped' or result.get('reason') == 'exists':
                            skipped += 1
                        else:
                            failed += 1
                    except Exception:
                        failed += 1
        else:
            # Sequential processing in quiet mode
            for csv_file in csv_files:
                file_path, result = _convert_single_file_sequential(csv_file, source, output, force, converter)
                if result['status'] == 'success':
                    successful += 1
                elif result['status'] == 'skipped' or result.get('reason') == 'exists':
                    skipped += 1
                else:
                    failed += 1
    
    # Summary
    end_time = time.perf_counter()
    duration = end_time - start_time
    
    if not quiet:
        print_success("🎉 NinjaTrader conversion completed!")
        print_info(f"✅ Successful: {successful}")
        if skipped > 0:
            print_info(f"⚠️  Skipped: {skipped}")
        if failed > 0:
            print_error(f"❌ Failed: {failed}")
        print_info(f"⏱️  Duration: {format_duration(duration)}")
        
        # Calculate processing speed
        if duration > 0 and successful > 0:
            avg_speed = total_size_gb / duration * 1024  # MB/s
            files_per_sec = successful / duration
            print_info(f"🚀 Average speed: {avg_speed:.1f} MB/s")
            print_info(f"📊 Processing rate: {files_per_sec:.1f} files/sec")
            if parallel > 1:
                print_info(f"⚡ Parallel workers: {parallel}")
                print_info(f"� Effective throughput: {avg_speed * parallel:.1f} MB/s theoretical")
        
        print_info(f"�💾 Output location: {output}")
        
        # Show compression achieved and performance tips
        if successful > 0:
            print_info(f"🗜️  Expected compression: ~75% (original: {total_size_gb:.2f} GB → estimated: {total_size_gb * 0.25:.2f} GB)")
            if parallel == 1 and successful > 10:
                print_info("💡 Tip: Use --parallel 4 for faster conversion of large datasets")


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