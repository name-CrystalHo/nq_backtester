"""
Data Converter - Convert NinjaTrader CSV tick data to optimized Parquet format

Converts 500GB of semicolon-delimited CSV files from NinjaTrader Market Replay
to partitioned Parquet format for high-performance backtesting using Polars for
optimal streaming performance and memory efficiency.

Input: CSV files from C:\\Users\\cryst\\Documents\\NinjaTrader 8\\db\\replay.csv\\
Output: Partitioned Parquet files with unified schema for L1/L2 records
"""

import os
import polars as pl
import click
from pathlib import Path
from datetime import datetime
from typing import Dict, List, Optional, Tuple
import logging
from tqdm import tqdm
import re
import time
from concurrent.futures import ProcessPoolExecutor, as_completed
import warnings
import signal
import atexit
import threading

# Import pandas only for test compatibility
try:
    import pandas as pd
    PANDAS_AVAILABLE = True
except ImportError:
    PANDAS_AVAILABLE = False

# Suppress warnings
warnings.filterwarnings('ignore')

# Polars is our primary engine
PARQUET_ENGINE = 'pyarrow'

logger = logging.getLogger(__name__)

# Global tracking of incomplete files for cleanup
_incomplete_files = set()
_cleanup_lock = threading.Lock()

def _register_incomplete_file(file_path):
    """Register a file as being worked on (for cleanup if interrupted)."""
    with _cleanup_lock:
        _incomplete_files.add(Path(file_path))

def _unregister_incomplete_file(file_path):
    """Unregister a file when processing completes successfully."""
    with _cleanup_lock:
        _incomplete_files.discard(Path(file_path))

def _cleanup_incomplete_files():
    """Clean up any incomplete files that were being processed."""
    with _cleanup_lock:
        if _incomplete_files:
            logger.warning(f"🧹 Cleaning up {len(_incomplete_files)} incomplete files...")
            for file_path in list(_incomplete_files):
                try:
                    if file_path.exists():
                        file_path.unlink()
                        logger.info(f"   Removed: {file_path}")
                except Exception as e:
                    logger.error(f"   Failed to remove {file_path}: {e}")
            _incomplete_files.clear()

def _signal_handler(signum, frame):
    """Handle Ctrl+C and other termination signals."""
    logger.warning(f"\n⚠️ Received signal {signum}, cleaning up...")
    _cleanup_incomplete_files()
    logger.info("✅ Cleanup complete, exiting...")
    exit(1)

# Register cleanup handlers
atexit.register(_cleanup_incomplete_files)
signal.signal(signal.SIGINT, _signal_handler)
if hasattr(signal, 'SIGTERM'):
    signal.signal(signal.SIGTERM, _signal_handler)


def _matches_instrument_pattern(instrument_name, pattern):
    """
    Check if instrument matches the given pattern.
    
    Supports same patterns as the CLI:
    - Simple substring: '25' - contains 25
    - Exclusion: '!25' - does NOT contain 25
    - Wildcards: '*25' - ends with 25
    - Regex: 'JUN|MAR' - contains JUN or MAR
    """
    import re
    
    if not pattern:
        return True
    
    # Exclusion pattern (starts with !)
    if pattern.startswith('!'):
        exclude_pattern = pattern[1:]
        try:
            regex = re.compile(exclude_pattern, re.IGNORECASE)
            return not regex.search(instrument_name)
        except re.error:
            return exclude_pattern.upper() not in instrument_name.upper()
    
    # Convert simple wildcards to regex
    if '*' in pattern:
        regex_pattern = pattern.replace('*', '.*')
        try:
            regex = re.compile(regex_pattern, re.IGNORECASE)
            return bool(regex.search(instrument_name))
        except re.error:
            return pattern.replace('*', '').upper() in instrument_name.upper()
    
    # Regular pattern (inclusion)
    try:
        regex = re.compile(pattern, re.IGNORECASE)
        return bool(regex.search(instrument_name))
    except re.error:
        return pattern.upper() in instrument_name.upper()


def create_timestamp_expression():
    """
    Create Polars expression for converting NinjaTrader timestamp to precise datetime.
    
    Critical timestamp conversion:
    - Base: YYYYMMDDhhmmss format (e.g., '20211119000000')  
    - Offset: 100-nanosecond units (e.g., 5150000 = 0.515 milliseconds)
    - Result: Combined precise timestamp
    
    Returns:
        Polars expression for timestamp conversion
    """
    return (
        pl.col("timestamp_raw").str.to_datetime("%Y%m%d%H%M%S", strict=False) +
        pl.duration(nanoseconds=pl.col("timestamp_offset") * 100)
    ).alias("timestamp")


def safe_csv_processing(df):
    """Safely process CSV with variable column counts."""
    # Target column names in order
    target_names = [
        'record_type', 'market_data_type', 'timestamp_raw', 'timestamp_offset',
        'field4', 'field5', 'field6', 'field7', 'field8'
    ]
    
    # Create mapping for existing columns only
    existing_columns = df.columns
    column_mapping = {}
    for i, col in enumerate(existing_columns):
        if i < len(target_names):
            column_mapping[col] = target_names[i]
    
    # Rename existing columns
    df_renamed = df.rename(column_mapping)
    
    # Add missing columns as null strings
    existing_cols = set(df_renamed.columns)
    for target_name in target_names:
        if target_name not in existing_cols:
            df_renamed = df_renamed.with_columns(pl.lit(None).cast(pl.Utf8).alias(target_name))
    
    # Ensure all columns are strings initially
    df_final = df_renamed.with_columns([
        pl.col(name).cast(pl.Utf8) for name in target_names
    ])
    
    return df_final

def extract_instrument_info(csv_path: Path) -> Tuple[str, str, str]:
    """
    Extract instrument name, year, and month from CSV file path.
    
    Expected structure: 
    C:\\...\\replay.csv\\NQ JUN21\\20211119.csv
    
    Returns:
        (instrument_name, year, month) e.g., ('NQ_JUN21', '2021', '11')
    """
    # Get instrument from parent directory, replace spaces with underscores
    instrument = csv_path.parent.name.replace(' ', '_')
    
    # Extract year and month from filename (YYYYMMDD format)
    filename = csv_path.stem
    if len(filename) >= 8 and filename[:8].isdigit():
        year = filename[:4]
        month = filename[4:6]
    else:
        # Fallback to current date if filename format is unexpected
        current = datetime.now()
        year = str(current.year)
        month = f"{current.month:02d}"
        logger.warning(f"Unexpected filename format: {filename}, using {year}-{month}")
    
    return instrument, year, month


def convert_large_csv_streamed(csv_path: Path, output_base_dir: Path, skip_existing: bool = True) -> Dict:
    """
    Convert a large CSV file to Parquet using Polars streaming for optimal memory efficiency.
    
    Args:
        csv_path: Path to input CSV file
        output_base_dir: Base output directory for partitioned structure
        skip_existing: Skip if output file already exists
        
    Returns:
        Stats dictionary with conversion results
    """
    logger.info(f"🔄 Converting large CSV with Polars streaming: {csv_path.name}")
    
    try:
        # Extract instrument and date info
        instrument, year, month = extract_instrument_info(csv_path)
        date_part = csv_path.stem
        
        # Create output directory structure
        output_dir = output_base_dir / instrument / f"year={year}" / f"month={month}"
        output_path = output_dir / f"{date_part}.parquet"
        
        # Skip if file already exists and skip_existing is True
        if skip_existing and output_path.exists():
            return {
                'file': str(csv_path),
                'status': 'skipped',
                'rows': 0,
                'l1_records': 0,
                'l2_records': 0,
                'size_mb': 0,
                'error': None
            }
        
        # Create output directory
        output_dir.mkdir(parents=True, exist_ok=True)
        
        # Write to temporary file first for atomic operation
        temp_output_path = output_path.with_suffix('.parquet.tmp')
        _register_incomplete_file(temp_output_path)
        _register_incomplete_file(output_path)
        
        try:
            # Use Polars streaming to process the CSV directly to Parquet
            # This is much more memory efficient than loading everything into RAM
            df = (
                pl.scan_csv(
                    csv_path,
                    separator=';',
                    has_header=False,
                    ignore_errors=True,  # Skip malformed lines
                    truncate_ragged_lines=False,
                    raise_if_empty=False  # Don't raise error on empty files
                )
                # Rename columns to standard names (up to 9 columns max)
                .rename({
                    'column_1': 'record_type',
                    'column_2': 'market_data_type', 
                    'column_3': 'timestamp_raw',
                    'column_4': 'timestamp_offset',
                    'column_5': 'field4',
                    'column_6': 'field5',
                    'column_7': 'field6',
                    'column_8': 'field7',
                    'column_9': 'field8'
                })
                # Ensure all columns exist (add as null if missing)
                .with_columns([
                    pl.col('record_type').cast(pl.Utf8),
                    pl.col('market_data_type').cast(pl.Utf8),
                    pl.col('timestamp_raw').cast(pl.Utf8),
                    pl.col('timestamp_offset').cast(pl.Utf8),
                    pl.col('field4').cast(pl.Utf8),
                    pl.col('field5').cast(pl.Utf8),
                    pl.when(pl.col('field6').is_not_null()).then(pl.col('field6').cast(pl.Utf8)).otherwise(pl.lit(None).cast(pl.Utf8)).alias('field6'),
                    pl.when(pl.col('field7').is_not_null()).then(pl.col('field7').cast(pl.Utf8)).otherwise(pl.lit(None).cast(pl.Utf8)).alias('field7'),
                    pl.when(pl.col('field8').is_not_null()).then(pl.col('field8').cast(pl.Utf8)).otherwise(pl.lit(None).cast(pl.Utf8)).alias('field8'),
                ])
                # Convert string columns to proper types with error handling
                .with_columns([
                    pl.col("market_data_type").str.to_integer(strict=False).fill_null(0).cast(pl.Int16),
                    pl.col("timestamp_offset").str.to_integer(strict=False).fill_null(0).cast(pl.Int32),
                ])
                # Remove rows where timestamp_raw is empty (critical field)
                .filter(pl.col("timestamp_raw").str.len_chars() > 0)
                # Filter valid record types
                .filter(pl.col("record_type").is_in(["L1", "L2"]))
                # Process L1 and L2 records - create unified schema
                .with_columns([
                    # Price: field4 for L1, field7 for L2
                    pl.when(pl.col("record_type") == "L1")
                    .then(pl.col("field4").cast(pl.Float64, strict=False).fill_null(0.0))
                    .when(pl.col("record_type") == "L2")
                    .then(pl.col("field7").cast(pl.Float64, strict=False).fill_null(0.0))
                    .otherwise(0.0)
                    .alias("price"),
                    
                    # Volume: field5 for L1, field8 for L2
                    pl.when(pl.col("record_type") == "L1")
                    .then(pl.col("field5").str.to_integer(strict=False).fill_null(0))
                    .when(pl.col("record_type") == "L2")
                    .then(pl.col("field8").str.to_integer(strict=False).fill_null(0))
                    .otherwise(0)
                    .cast(pl.Int32)
                    .alias("volume"),
                    
                    # Operation: 0 for L1, field4 for L2
                    pl.when(pl.col("record_type") == "L1")
                    .then(0)
                    .when(pl.col("record_type") == "L2")
                    .then(pl.col("field4").str.to_integer(strict=False).fill_null(0))
                    .otherwise(0)
                    .cast(pl.Int16)
                    .alias("operation"),
                    
                    # Position: 0 for L1, field5 for L2
                    pl.when(pl.col("record_type") == "L1")
                    .then(0)
                    .when(pl.col("record_type") == "L2")
                    .then(pl.col("field5").str.to_integer(strict=False).fill_null(0))
                    .otherwise(0)
                    .cast(pl.Int16)
                    .alias("position"),
                    
                    # Market maker: field6, fill empty with ""
                    pl.col("field6").fill_null("").alias("market_maker"),
                    
                    # Create precise timestamps
                    create_timestamp_expression()
                ])
                # Convert record_type to categorical for efficiency
                .with_columns([
                    pl.col("record_type").cast(pl.Categorical),
                    pl.col("market_maker").cast(pl.Utf8)
                ])
                # Select final columns in correct order
                .select([
                    'record_type', 'market_data_type', 'timestamp', 'timestamp_offset',
                    'price', 'volume', 'operation', 'position', 'market_maker'
                ])
                # Ensure chronological ordering (critical for backtesting)
                .sort(["timestamp", "timestamp_offset"])
            )
            
            # Collect statistics before writing (this materializes the lazy frame for stats)
            # but we collect only the minimal data needed for stats
            stats_df = df.select([
                pl.len().alias("total_rows"),
                pl.col("record_type").filter(pl.col("record_type") == "L1").len().alias("l1_records"),
                pl.col("record_type").filter(pl.col("record_type") == "L2").len().alias("l2_records")
            ]).collect()
            
            if stats_df.height == 0:
                return {
                    'file': str(csv_path),
                    'status': 'error',
                    'error': 'No valid records found in CSV',
                    'rows': 0,
                    'l1_records': 0,
                    'l2_records': 0,
                    'size_mb': 0.0
                }
            
            # Get stats
            total_rows = stats_df['total_rows'][0]
            l1_records = stats_df['l1_records'][0]
            l2_records = stats_df['l2_records'][0]
            
            if total_rows == 0:
                return {
                    'file': str(csv_path),
                    'status': 'error',
                    'error': 'No valid records found after processing',
                    'rows': 0,
                    'l1_records': 0,
                    'l2_records': 0,
                    'size_mb': 0.0
                }
            
            # Write to Parquet using streaming (this doesn't load everything into memory)
            df.sink_parquet(
                temp_output_path,
                compression="snappy",
                maintain_order=True  # Critical for backtesting - maintain chronological order
            )
            
            # Atomic rename
            if output_path.exists():
                output_path.unlink()
            temp_output_path.rename(output_path)
            
            # Calculate file size
            size_mb = output_path.stat().st_size / (1024 * 1024)
            
            # Unregister files after success
            _unregister_incomplete_file(temp_output_path)
            _unregister_incomplete_file(output_path)
            
            logger.info(f"✅ Streaming conversion complete: {total_rows:,} records → {size_mb:.2f} MB")
            logger.info(f"   L1={l1_records:,}, L2={l2_records:,}, Total={total_rows:,}")
            
            return {
                'file': str(csv_path),
                'status': 'success',
                'rows': total_rows,
                'l1_records': l1_records,
                'l2_records': l2_records,
                'size_mb': size_mb,
                'error': None
            }
            
        except Exception as e:
            # Cleanup on failure
            if temp_output_path.exists():
                temp_output_path.unlink()
            if output_path.exists():
                output_path.unlink()
            _unregister_incomplete_file(temp_output_path)
            _unregister_incomplete_file(output_path)
            raise e
            
    except Exception as e:
        logger.error(f"Failed streaming conversion of {csv_path}: {str(e)}")
        return {
            'file': str(csv_path),
            'status': 'error',
            'error': str(e),
            'rows': 0,
            'l1_records': 0,
            'l2_records': 0,
            'size_mb': 0.0
        }


# Chunk processing function removed - using Polars streaming instead


def convert_single_csv(csv_path: Path, output_base_dir: Path, skip_existing: bool = True) -> Dict:
    """
    Convert a single CSV file to Parquet format using Polars with safe column handling.
    
    Args:
        csv_path: Path to input CSV file
        output_base_dir: Base output directory for partitioned structure
        skip_existing: Skip if output file already exists
        
    Returns:
        Stats dictionary with conversion results
    """
    logger.info(f"🔄 Converting CSV: {csv_path.name}")
    
    try:
        # Extract instrument and date info
        instrument, year, month = extract_instrument_info(csv_path)
        date_part = csv_path.stem
        
        # Create output directory structure
        output_dir = output_base_dir / instrument / f"year={year}" / f"month={month}"
        output_path = output_dir / f"{date_part}.parquet"
        
        # Skip if file already exists and skip_existing is True
        if skip_existing and output_path.exists():
            return {
                'file': str(csv_path),
                'status': 'skipped',
                'rows': 0,
                'l1_records': 0,
                'l2_records': 0,
                'size_mb': 0,
                'error': None
            }
        
        # Check file size - for very large files, use streaming processing
        file_size_mb = csv_path.stat().st_size / (1024 * 1024)
        if file_size_mb > 200:  # Files larger than 200MB use streaming processing
            logger.info(f"📊 Large file detected ({file_size_mb:.1f} MB), using streaming processing")
            return convert_large_csv_streamed(csv_path, output_base_dir, skip_existing)
        
        # Create output directory
        output_dir.mkdir(parents=True, exist_ok=True)
        
        # Write to temporary file first for atomic operation
        temp_output_path = output_path.with_suffix('.parquet.tmp')
        _register_incomplete_file(temp_output_path)
        _register_incomplete_file(output_path)
        
        try:
            # Safe CSV reading with variable column handling
            df = pl.read_csv(
                csv_path,
                separator=';',
                has_header=False,
                ignore_errors=True,
                raise_if_empty=False
            )
            
            # Safe column renaming
            target_names = [
                'record_type', 'market_data_type', 'timestamp_raw', 'timestamp_offset',
                'field4', 'field5', 'field6', 'field7', 'field8'
            ]
            
            # Create mapping for existing columns only
            column_mapping = {}
            for i, col in enumerate(df.columns):
                if i < len(target_names):
                    column_mapping[col] = target_names[i]
            
            # Rename existing columns
            df_renamed = df.rename(column_mapping)
            
            # Add missing columns as null
            existing_cols = set(df_renamed.columns)
            for target_name in target_names:
                if target_name not in existing_cols:
                    df_renamed = df_renamed.with_columns(
                        pl.lit(None).cast(pl.Utf8).alias(target_name)
                    )
            
            # Ensure correct column order and types
            df_processed = (
                df_renamed.select([
                    pl.col('record_type').cast(pl.Utf8),
                    pl.col('market_data_type').cast(pl.Utf8),
                    pl.col('timestamp_raw').cast(pl.Utf8),
                    pl.col('timestamp_offset').cast(pl.Utf8),
                    pl.col('field4').cast(pl.Utf8),
                    pl.col('field5').cast(pl.Utf8),
                    pl.col('field6').cast(pl.Utf8),
                    pl.col('field7').cast(pl.Utf8),
                    pl.col('field8').cast(pl.Utf8),
                ])
                # Convert string columns to proper types with strict validation for critical fields
                .with_columns([
                    pl.col("market_data_type").cast(pl.Int16, strict=True),  # Strict for critical field
                    pl.col("timestamp_offset").cast(pl.Int32, strict=False).fill_null(0),
                ])
                # Remove rows where timestamp_raw is empty (critical field)
                .filter(pl.col("timestamp_raw").str.len_chars() > 0)
                # Filter valid record types
                .filter(pl.col("record_type").is_in(["L1", "L2"]))
            )
            
            # Check if we have any valid records and provide informative error messages
            if df_processed.height == 0:
                # Check file size first
                file_size = csv_path.stat().st_size
                
                if file_size == 0:
                    error_msg = 'Empty file (0 bytes) - likely market holiday or weekend'
                    status = 'skipped'  # Treat empty files as skipped rather than error
                elif df.height == 0:
                    error_msg = 'File contains no data rows'
                    status = 'error'
                else:
                    # File has data but no L1/L2 records
                    total_records = df.height
                    if 'record_type' in df.columns:
                        record_types = df.select('record_type').to_series().unique().to_list()
                        error_msg = f'File has {total_records} records but no L1/L2 data (found: {record_types})'
                    else:
                        error_msg = f'File has {total_records} records but invalid format (no record_type column)'
                    status = 'error'
                
                return {
                    'file': str(csv_path),
                    'status': status,
                    'rows': 0,
                    'l1_records': 0,
                    'l2_records': 0,
                    'size_mb': 0,
                    'error': error_msg
                }
            
            # Process L1 and L2 records - create unified schema
            df_final = (
                df_processed
                .with_columns([
                    # Price: field4 for L1, field7 for L2
                    pl.when(pl.col("record_type") == "L1")
                    .then(pl.col("field4").cast(pl.Float64, strict=False).fill_null(0.0))
                    .when(pl.col("record_type") == "L2")
                    .then(pl.col("field7").cast(pl.Float64, strict=False).fill_null(0.0))
                    .otherwise(0.0)
                    .alias("price"),
                    
                    # Volume: field5 for L1, field8 for L2
                    pl.when(pl.col("record_type") == "L1")
                    .then(pl.col("field5").cast(pl.Int32, strict=False).fill_null(0))
                    .when(pl.col("record_type") == "L2")
                    .then(pl.col("field8").cast(pl.Int32, strict=False).fill_null(0))
                    .otherwise(0)
                    .alias("volume"),
                    
                    # Operation: 0 for L1, field4 for L2
                    pl.when(pl.col("record_type") == "L1")
                    .then(pl.lit(0))
                    .when(pl.col("record_type") == "L2")
                    .then(pl.col("field4").cast(pl.Int16, strict=False).fill_null(0))
                    .otherwise(0)
                    .alias("operation"),
                    
                    # Position: field5 for L2 only
                    pl.when(pl.col("record_type") == "L2")
                    .then(pl.col("field5").cast(pl.Int32, strict=False).fill_null(0))
                    .otherwise(pl.lit(None).cast(pl.Int32))
                    .alias("position"),
                    
                    # Market maker: field6 for L2 only
                    pl.when(pl.col("record_type") == "L2")
                    .then(pl.col("field6"))
                    .otherwise(pl.lit(None).cast(pl.Utf8))
                    .alias("market_maker"),
                    
                    # Create timestamp using the create_timestamp_expression helper
                    create_timestamp_expression(),
                ])
                .select([
                    'record_type', 'market_data_type', 'timestamp', 'timestamp_offset',
                    'price', 'volume', 'operation', 'position', 'market_maker'
                ])
                .sort(["timestamp", "timestamp_offset"])
            )
            
            # Count records for stats
            l1_count = df_final.filter(pl.col("record_type") == "L1").height
            l2_count = df_final.filter(pl.col("record_type") == "L2").height
            total_rows = df_final.height
            
            # Write to temporary file first
            df_final.write_parquet(temp_output_path)
            
            # Atomic move to final location - remove existing file first if needed
            if output_path.exists():
                output_path.unlink()
            temp_output_path.rename(output_path)
            
            # Calculate file size
            size_mb = output_path.stat().st_size / (1024 * 1024)
            
            # Clean up tracking
            _unregister_incomplete_file(temp_output_path)
            _unregister_incomplete_file(output_path)
            
            logger.info(f"✅ Converted {csv_path.name}: {total_rows} records ({l1_count} L1, {l2_count} L2) -> {size_mb:.2f} MB")
            
            return {
                'file': str(csv_path),
                'status': 'success',
                'rows': total_rows,
                'l1_records': l1_count,
                'l2_records': l2_count,
                'size_mb': size_mb,
                'error': None
            }
            
        except Exception as e:
            # Clean up temp files on error
            if temp_output_path.exists():
                temp_output_path.unlink()
            _unregister_incomplete_file(temp_output_path)
            _unregister_incomplete_file(output_path)
            raise e
    
    except Exception as e:
        logger.error(f"❌ Error converting {csv_path.name}: {e}")
        return {
            'file': str(csv_path),
            'status': 'error',
            'rows': 0,
            'l1_records': 0,
            'l2_records': 0,
            'size_mb': 0,
            'error': f"Failed to read/process CSV: {str(e)}"
        }


def convert_csv_to_parquet(
    source_dir: str = None,  # Auto-detect NinjaTrader path
    output_dir: str = None,  # Auto-detect production path
    instrument_filter: Optional[str] = None,
    skip_existing: bool = True,
    max_workers: int = None,  # Auto-detect CPU count
    validate_output: bool = False
) -> Dict:
    """
    Main conversion function to convert CSV tick data to Parquet format.
    """
    # Simple wrapper around convert_single_csv for now
    from concurrent.futures import ThreadPoolExecutor, as_completed
    
    # Default paths
    if source_dir is None:
        source_dir = Path.home() / "Documents" / "NinjaTrader 8" / "db" / "replay.csv"
    else:
        source_dir = Path(source_dir)
    
    if output_dir is None:
        output_dir = Path("storage") / "processed"
    else:
        output_dir = Path(output_dir)
    
    # Auto-detect CPU count
    if max_workers is None:
        max_workers = min(8, (os.cpu_count() or 1) + 4)
    
    logger.info(f"🚀 Starting conversion: {source_dir} -> {output_dir}")
    logger.info(f"👥 Using {max_workers} workers")
    
    # Find CSV files
    csv_files = []
    if source_dir.is_file():
        csv_files = [source_dir]
    else:
        pattern = "*.csv"
        if instrument_filter:
            pattern = f"*{instrument_filter}*.csv"
        csv_files = list(source_dir.rglob(pattern))
    
    if not csv_files:
        return {
            'status': 'error',
            'message': f'No CSV files found in {source_dir}',
            'processed': 0,
            'failed': 0,
            'skipped': 0
        }
    
    logger.info(f"📁 Found {len(csv_files)} CSV files")
    
    # Process files
    results = {'successful': 0, 'failed': 0, 'skipped': 0, 'total_size_mb': 0.0}
    
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        # Submit all conversion tasks
        future_to_file = {
            executor.submit(convert_single_csv, csv_file, output_dir, skip_existing): csv_file
            for csv_file in csv_files
        }
        
        # Process completed tasks
        with tqdm(total=len(csv_files), desc="Converting") as pbar:
            for future in as_completed(future_to_file):
                csv_file = future_to_file[future]
                try:
                    result = future.result()
                    if result['status'] == 'success':
                        results['successful'] += 1
                        results['total_size_mb'] += result['size_mb']
                    elif result['status'] == 'skipped':
                        results['skipped'] += 1
                    else:
                        results['failed'] += 1
                        logger.error(f"❌ Failed {csv_file.name}: {result.get('error', 'Unknown error')}")
                except Exception as e:
                    results['failed'] += 1
                    logger.error(f"❌ Exception processing {csv_file.name}: {e}")
                
                pbar.update(1)
    
    logger.info(f"✅ Conversion complete: {results['successful']} successful, {results['failed']} failed, {results['skipped']} skipped")
    
    return {
        'status': 'success' if results['failed'] == 0 else 'partial',
        'processed': results['successful'],
        'failed': results['failed'], 
        'skipped': results['skipped'],
        'total_size_mb': results['total_size_mb']
    }


@click.option(
    '--source',
    default='C:\\Users\\cryst\\Documents\\NinjaTrader 8\\db\\replay.csv',
    type=click.Path(),
    help='Source directory containing CSV files (default: C:\\Users\\cryst\\Documents\\NinjaTrader 8\\db\\replay.csv)'
)
@click.option(
    '--output',
    default=None,
    type=click.Path(),
    help='Output directory for Parquet files (default: ./storage/processed)'
)
@click.option(
    '--instrument',
    help='Filter by instrument name (e.g., "NQ JUN21")'
)
@click.option(
    '--skip-existing',
    is_flag=True,
    default=True,
    help='Skip files that already exist in output'
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
def convert(source, output, instrument, skip_existing, validate, workers):
    """Convert NinjaTrader CSV files to optimized Parquet format"""
    
    click.echo(f"Converting CSV files from: {source}")
    click.echo(f"Output directory: {output}")
    
    if instrument:
        click.echo(f"Filtering by instrument: {instrument}")
    
    try:
        summary = convert_csv_to_parquet(
            source_dir=source,
            output_dir=output,
            instrument_filter=instrument,
            skip_existing=skip_existing,
            max_workers=workers,
            validate=validate
        )
        
        click.echo("\n" + "="*50)
        click.echo("CONVERSION SUMMARY")
        click.echo("="*50)
        click.echo(f"Total files found: {summary['total_files']}")
        click.echo(f"Successfully processed: {summary['processed']}")
        click.echo(f"Skipped (already exist): {summary['skipped']}")
        click.echo(f"Errors: {summary['errors']}")
        click.echo(f"Total records: {summary['total_rows']:,}")
        click.echo(f"L1 records: {summary['total_l1']:,}")
        click.echo(f"L2 records: {summary['total_l2']:,}")
        click.echo(f"Total size: {summary['total_size_mb']:.2f} MB")
        
        if summary['failed_files']:
            click.echo(f"\nFailed files:")
            for failed_file in summary['failed_files'][:10]:  # Show first 10
                click.echo(f"  - {failed_file}")
            if len(summary['failed_files']) > 10:
                click.echo(f"  ... and {len(summary['failed_files']) - 10} more")
        
    except Exception as e:
        click.echo(f"Error: {e}", err=True)
        raise click.ClickException(str(e))


@click.group()
def cli():
    """CSV to Parquet conversion utilities"""
    pass


@cli.command()
@click.argument('directory', type=click.Path(exists=True))
@click.option('--sample', default=10, type=int, help='Number of files to validate')
def verify(directory, sample):
    """Verify converted Parquet files"""
    
    click.echo(f"Validating Parquet files in: {directory}")
    
    success = validate_sample(directory, sample)
    
    if success:
        click.echo("✅ All validations passed!")
    else:
        click.echo("❌ Some validations failed!")
        raise click.ClickException("Validation failed")


def validate_csv_file(csv_path: Path) -> Dict:
    """
    Validate CSV file format and content.
    
    Args:
        csv_path: Path to CSV file to validate
        
    Returns:
        Dict with validation results
    """
    try:
        errors = []
        
        # Check file exists and is readable
        if not csv_path.exists():
            errors.append(f"File does not exist: {csv_path}")
            return {'valid': False, 'errors': errors}
        
        if not csv_path.is_file():
            errors.append(f"Path is not a file: {csv_path}")
            return {'valid': False, 'errors': errors}
        
        # Try to read and validate the file
        sample_lines = []
        total_file_lines = 0
        with open(csv_path, 'r', encoding='utf-8') as f:
            for i, line in enumerate(f):
                total_file_lines += 1
                if i < 1000:  # Sample first 1000 lines for detailed validation
                    sample_lines.append(line.strip())
                elif i % 10000 == 0:  # Sample every 10,000th line after that
                    sample_lines.append(line.strip())
        
        if not sample_lines:
            errors.append("File is empty")
            return {'valid': False, 'errors': errors}
        
        # Validate format
        l1_records = 0
        l2_records = 0
        total_records = 0
        dates = set()
        instruments = set()
        
        for line_num, line in enumerate(sample_lines, 1):
            if not line:
                continue
                
            parts = line.split(';')
            if len(parts) < 6:
                errors.append(f"Line {line_num}: Insufficient fields ({len(parts)} < 6)")
                continue
            
            try:
                # Basic field validation
                record_type = parts[0]
                
                if record_type not in ['L1', 'L2']:
                    errors.append(f"Line {line_num}: Invalid record type '{record_type}'")
                    continue
                
                # Validate field counts for each record type
                if record_type == 'L1' and len(parts) < 6:
                    errors.append(f"Line {line_num}: L1 record needs at least 6 fields, got {len(parts)}")
                    continue
                elif record_type == 'L2' and len(parts) < 9:
                    errors.append(f"Line {line_num}: L2 record needs at least 9 fields, got {len(parts)}")
                    continue
                
                # Parse common fields with safe conversion
                try:
                    market_data_type = int(parts[1]) if parts[1].strip() else 0
                except (ValueError, IndexError):
                    market_data_type = 0
                    
                date_str = parts[2]
                
                try:
                    time_offset = int(parts[3]) if parts[3].strip() else 0
                except (ValueError, IndexError):
                    time_offset = 0
                
                # Validate record-specific fields with safe conversion
                if record_type == 'L1':
                    # L1: L1;MarketDataType;Timestamp;TimestampOffset;Price;Volume
                    try:
                        price = float(parts[4]) if parts[4].strip() else 0.0
                    except (ValueError, IndexError):
                        price = 0.0
                    try:
                        volume = int(parts[5]) if parts[5].strip() else 0
                    except (ValueError, IndexError):
                        volume = 0
                    l1_records += 1
                elif record_type == 'L2':
                    # L2: L2;MarketDataType;Timestamp;TimestampOffset;Operation;Position;MarketMaker;Price;Volume
                    try:
                        operation = int(parts[4]) if parts[4].strip() else 0
                    except (ValueError, IndexError):
                        operation = 0
                    try:
                        position = int(parts[5]) if parts[5].strip() else 0
                    except (ValueError, IndexError):
                        position = 0
                        
                    market_maker = parts[6] if len(parts) > 6 else ""  # Can be empty
                    
                    try:
                        price = float(parts[7]) if len(parts) > 7 and parts[7].strip() else 0.0
                    except (ValueError, IndexError):
                        price = 0.0
                    try:
                        volume = int(parts[8]) if len(parts) > 8 and parts[8].strip() else 0
                    except (ValueError, IndexError):
                        volume = 0
                    l2_records += 1
                
                total_records += 1
                
                # Extract date and instrument info
                dates.add(date_str)
                
                # Instrument from parent directory
                instrument = csv_path.parent.name.replace(' ', '_')
                instruments.add(instrument)
                
            except ValueError as e:
                errors.append(f"Line {line_num}: Invalid numeric field - {e}")
        
        # Summary
        date_range = f"{min(dates)} to {max(dates)}" if dates else "No dates found"
        
        return {
            'valid': len(errors) == 0,
            'errors': errors,
            'total_records': total_records,
            'l1_records': l1_records,
            'l2_records': l2_records,
            'date_range': date_range,
            'instruments': list(instruments)
        }
        
    except Exception as e:
        return {
            'valid': False,
            'errors': [f"Validation error: {str(e)}"]
        }


if __name__ == '__main__':
    cli()