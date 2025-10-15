"""CSV to Parquet converter for NinjaTrader tick data."""

import polars as pl
from pathlib import Path
from typing import Dict, Any, Optional
import threading
import signal
import atexit

from .base import CSVConverter
from ...core import ConversionError, DataError

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
            logger = __import__('logging').getLogger(__name__)
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
    logger = __import__('logging').getLogger(__name__)
    logger.warning(f"\n⚠️ Received signal {signum}, cleaning up...")
    _cleanup_incomplete_files()
    logger.info("✅ Cleanup complete, exiting...")
    exit(1)


# Register cleanup handlers
atexit.register(_cleanup_incomplete_files)
signal.signal(signal.SIGINT, _signal_handler)
if hasattr(signal, 'SIGTERM'):
    signal.signal(signal.SIGTERM, _signal_handler)


class CSVToParquetConverter(CSVConverter):
    """Convert NinjaTrader CSV tick data to Parquet format using Polars."""
    
    def __init__(self, chunk_size: int = 100_000):
        """Initialize CSV converter."""
        super().__init__(chunk_size)
        self.streaming_threshold_mb = 5000  # Use streaming for files > 5GB (effectively disable for most cases)
    
    def create_timestamp_expression(self):
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
    
    def create_partitioned_output_path(self, input_path: Path, output_base_dir: Path) -> Path:
        """Create partitioned output path from input path."""
        instrument, year, month = self.extract_instrument_info(input_path)
        date_part = input_path.stem
        
        # Create partitioned directory structure
        output_dir = output_base_dir / f"instrument={instrument}" / f"year={year}" / f"month={month}"
        output_path = output_dir / f"{date_part}.parquet"
        
        return output_path
    
    def validate_input(self, input_path: Path) -> Dict[str, Any]:
        """Validate CSV file format and content."""
        try:
            errors = []
            
            # Check file exists and is readable
            if not input_path.exists():
                errors.append(f"File does not exist: {input_path}")
                return {'valid': False, 'errors': errors}
            
            if not input_path.is_file():
                errors.append(f"Path is not a file: {input_path}")
                return {'valid': False, 'errors': errors}
            
            if input_path.suffix.lower() != '.csv':
                errors.append(f"File is not a CSV file: {input_path}")
                return {'valid': False, 'errors': errors}
            
            # Try to read and validate the file structure
            sample_lines = []
            total_file_lines = 0
            
            try:
                with open(input_path, 'r', encoding='utf-8') as f:
                    for i, line in enumerate(f):
                        total_file_lines += 1
                        if i < 100:  # Sample first 100 lines for validation
                            sample_lines.append(line.strip())
                        if i > 1000:  # Don't read entire large files for validation
                            break
            except UnicodeDecodeError:
                errors.append("File is not valid UTF-8 text")
                return {'valid': False, 'errors': errors}
            
            if not sample_lines:
                errors.append("File is empty")
                return {'valid': False, 'errors': errors}
            
            # Validate CSV format
            l1_records = 0
            l2_records = 0
            
            for line_num, line in enumerate(sample_lines[:50], 1):  # Check first 50 lines
                if not line:
                    continue
                    
                parts = line.split(';')
                if len(parts) < 6:
                    errors.append(f"Line {line_num}: Insufficient fields ({len(parts)} < 6)")
                    continue
                
                record_type = parts[0]
                if record_type == 'L1':
                    l1_records += 1
                elif record_type == 'L2':
                    l2_records += 1
                elif record_type not in ['L1', 'L2']:
                    errors.append(f"Line {line_num}: Invalid record type '{record_type}'")
            
            if l1_records == 0 and l2_records == 0:
                errors.append("No valid L1 or L2 records found in sample")
            
            return {
                'valid': len(errors) == 0,
                'errors': errors,
                'total_lines': total_file_lines,
                'sample_l1_records': l1_records,
                'sample_l2_records': l2_records
            }
            
        except Exception as e:
            return {
                'valid': False,
                'errors': [f"Validation error: {str(e)}"]
            }
    
    def should_use_streaming(self, input_path: Path) -> bool:
        """
        Determine if streaming should be used based on file size.
        
        Args:
            input_path: Path to input CSV file
            
        Returns:
            True if streaming should be used
        """
        try:
            file_size_mb = input_path.stat().st_size / (1024 * 1024)
            return file_size_mb > self.streaming_threshold_mb
        except Exception:
            # Default to streaming for safety if we can't determine size
            return True
    
    def convert_streaming(self, input_path: Path, output_path: Path, **kwargs) -> Dict[str, Any]:
        """
        Convert large CSV file using Polars streaming for memory efficiency.
        
        Args:
            input_path: Path to input CSV file
            output_path: Path to output Parquet file (or base directory for partitioned output)
            **kwargs: Additional parameters
            
        Returns:
            Conversion statistics
        """
        self.logger.info(f"🔄 Converting large CSV with streaming: {input_path.name}")
        
        # Create partitioned output path if output_path is a directory
        if output_path.is_dir() or not output_path.suffix:
            output_path = self.create_partitioned_output_path(input_path, output_path)
        
        # Create output directory
        output_path.parent.mkdir(parents=True, exist_ok=True)
        
        # Write to temporary file first for atomic operation
        temp_output_path = output_path.with_suffix('.parquet.tmp')
        _register_incomplete_file(temp_output_path)
        _register_incomplete_file(output_path)
        
        try:
            # Use Polars streaming to process the CSV directly to Parquet
            # Handle empty fields by forcing consistent schema
            df = (
                pl.scan_csv(
                    input_path,
                    separator=';',
                    has_header=False,
                    ignore_errors=True,
                    truncate_ragged_lines=False,
                    raise_if_empty=False,
                    null_values=["", "NULL", "null"],  # Treat empty strings as null
                    schema={
                        'column_1': pl.Utf8,  # record_type
                        'column_2': pl.Utf8,  # market_data_type
                        'column_3': pl.Utf8,  # timestamp_raw
                        'column_4': pl.Utf8,  # timestamp_offset
                        'column_5': pl.Utf8,  # field4
                        'column_6': pl.Utf8,  # field5
                        'column_7': pl.Utf8,  # field6
                        'column_8': pl.Utf8,  # field7
                        'column_9': pl.Utf8   # field8
                    }
                )
                # Rename columns to standard names (up to 9 columns max)
                .select([
                    pl.col("column_1").alias("record_type"),
                    pl.col("column_2").alias("market_data_type"),
                    pl.col("column_3").alias("timestamp_raw"),
                    pl.col("column_4").alias("timestamp_offset"),
                    pl.col("column_5").alias("field4"),
                    pl.col("column_6").alias("field5"),
                    pl.col("column_7").alias("field6"),
                    pl.col("column_8").alias("field7"),
                    pl.col("column_9").alias("field8")
                ])
                # Ensure all columns exist and have correct types
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
                # Convert critical fields to proper types
                .with_columns([
                    pl.col("market_data_type").str.to_integer(strict=False).fill_null(0).cast(pl.Int16),
                    pl.col("timestamp_offset").str.to_integer(strict=False).fill_null(0).cast(pl.Int32),
                ])
                # Remove invalid records
                .filter(pl.col("timestamp_raw").str.len_chars() > 0)
                .filter(pl.col("record_type").is_in(["L1", "L2"]))
                # Create unified schema for L1/L2 records
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
                    
                    # Position: field5 for L2 only
                    pl.when(pl.col("record_type") == "L2")
                    .then(pl.col("field5").str.to_integer(strict=False).fill_null(0))
                    .otherwise(pl.lit(None).cast(pl.Int32))
                    .alias("position"),
                    
                    # Market maker: field6 for L2, empty for L1
                    pl.when(pl.col("record_type") == "L2")
                    .then(pl.col("field6").fill_null(""))
                    .otherwise("")
                    .alias("market_maker"),
                    
                    # Create precise timestamps
                    self.create_timestamp_expression()
                ])
                # Select final columns and ensure chronological order
                .select([
                    'record_type', 'market_data_type', 'timestamp', 'timestamp_offset',
                    'price', 'volume', 'operation', 'position', 'market_maker'
                ])
                .sort(["timestamp", "timestamp_offset"])
            )
            
            # Get statistics before writing
            stats_df = df.select([
                pl.len().alias("total_rows"),
                pl.col("record_type").filter(pl.col("record_type") == "L1").len().alias("l1_records"),
                pl.col("record_type").filter(pl.col("record_type") == "L2").len().alias("l2_records")
            ]).collect()
            
            if stats_df.height == 0:
                raise ConversionError("No valid records found in CSV")
            
            total_rows = stats_df['total_rows'][0]
            l1_records = stats_df['l1_records'][0]  
            l2_records = stats_df['l2_records'][0]
            
            if total_rows == 0:
                raise ConversionError("No valid records after processing")
            
            # Write to Parquet using streaming
            df.sink_parquet(
                temp_output_path,
                compression="snappy",
                maintain_order=True
            )
            
            # Atomic rename
            if output_path.exists():
                output_path.unlink()
            temp_output_path.rename(output_path)
            
            # Calculate file size
            size_mb = output_path.stat().st_size / (1024 * 1024)
            
            # Cleanup tracking
            _unregister_incomplete_file(temp_output_path)
            _unregister_incomplete_file(output_path)
            
            self.logger.info(f"✅ Streaming conversion complete: {total_rows:,} records → {size_mb:.2f} MB")
            
            return self.create_result_dict(
                status='success',
                input_file=input_path,
                rows=total_rows,
                size_mb=size_mb,
                l1_records=l1_records,
                l2_records=l2_records
            )
            
        except Exception as e:
            # Cleanup on failure
            if temp_output_path.exists():
                temp_output_path.unlink()
            if output_path.exists():
                output_path.unlink()
            _unregister_incomplete_file(temp_output_path)
            _unregister_incomplete_file(output_path)
            raise ConversionError(f"Streaming conversion failed: {str(e)}") from e
    
    def convert_regular(self, input_path: Path, output_path: Path, **kwargs) -> Dict[str, Any]:
        """
        Convert regular-sized CSV file using standard Polars operations.
        
        Args:
            input_path: Path to input CSV file
            output_path: Path to output Parquet file (or base directory for partitioned output)
            **kwargs: Additional parameters
            
        Returns:
            Conversion statistics
        """
        self.logger.info(f"🔄 Converting CSV: {input_path.name}")
        
        # Create partitioned output path if output_path is a directory
        if output_path.is_dir() or not output_path.suffix:
            output_path = self.create_partitioned_output_path(input_path, output_path)
        
        # Create output directory
        output_path.parent.mkdir(parents=True, exist_ok=True)
        
        # Write to temporary file first
        temp_output_path = output_path.with_suffix('.parquet.tmp')
        _register_incomplete_file(temp_output_path)
        _register_incomplete_file(output_path)
        
        try:
            # Read CSV with safe column handling
            df = pl.read_csv(
                input_path,
                separator=';',
                has_header=False,
                ignore_errors=True,
                raise_if_empty=False
            )
            
            # Standardize column names (up to 9 columns)
            target_names = [
                'record_type', 'market_data_type', 'timestamp_raw', 'timestamp_offset',
                'field4', 'field5', 'field6', 'field7', 'field8'
            ]
            
            # Create mapping for existing columns
            column_mapping = {}
            for i, col in enumerate(df.columns):
                if i < len(target_names):
                    column_mapping[col] = target_names[i]
            
            # Rename and add missing columns
            df_renamed = df.rename(column_mapping)
            existing_cols = set(df_renamed.columns)
            
            for target_name in target_names:
                if target_name not in existing_cols:
                    df_renamed = df_renamed.with_columns(
                        pl.lit(None).cast(pl.Utf8).alias(target_name)
                    )
            
            # Process the data
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
                .with_columns([
                    pl.col("market_data_type").cast(pl.Int16, strict=True),
                    pl.col("timestamp_offset").cast(pl.Int32, strict=False).fill_null(0),
                ])
                .filter(pl.col("timestamp_raw").str.len_chars() > 0)
                .filter(pl.col("record_type").is_in(["L1", "L2"]))
            )
            
            # Check for valid records
            if df_processed.height == 0:
                file_size = input_path.stat().st_size
                if file_size == 0:
                    return self.create_result_dict(
                        status='skipped',
                        input_file=input_path,
                        error='Empty file (0 bytes) - likely market holiday or weekend'
                    )
                else:
                    return self.create_result_dict(
                        status='error',
                        input_file=input_path,
                        error='File contains no valid L1/L2 records'
                    )
            
            # Create unified schema
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
                    
                    # Create precise timestamps
                    self.create_timestamp_expression(),
                ])
                .select([
                    'record_type', 'market_data_type', 'timestamp', 'timestamp_offset',
                    'price', 'volume', 'operation', 'position', 'market_maker'
                ])
                .sort(["timestamp", "timestamp_offset"])
            )
            
            # Get statistics
            l1_count = df_final.filter(pl.col("record_type") == "L1").height
            l2_count = df_final.filter(pl.col("record_type") == "L2").height
            total_rows = df_final.height
            
            # Write to Parquet
            df_final.write_parquet(temp_output_path)
            
            # Atomic rename
            if output_path.exists():
                output_path.unlink()
            temp_output_path.rename(output_path)
            
            # Calculate file size
            size_mb = output_path.stat().st_size / (1024 * 1024)
            
            # Cleanup tracking
            _unregister_incomplete_file(temp_output_path)
            _unregister_incomplete_file(output_path)
            
            self.logger.info(f"✅ Converted {input_path.name}: {total_rows} records → {size_mb:.2f} MB")
            
            return self.create_result_dict(
                status='success',
                input_file=input_path,
                rows=total_rows,
                size_mb=size_mb,
                l1_records=l1_count,
                l2_records=l2_count
            )
            
        except Exception as e:
            # Cleanup on failure
            if temp_output_path.exists():
                temp_output_path.unlink()
            _unregister_incomplete_file(temp_output_path)
            _unregister_incomplete_file(output_path)
            raise ConversionError(f"Regular conversion failed: {str(e)}") from e
    
    def convert(self, input_path: Path, output_path: Path, skip_existing: bool = True, **kwargs) -> Dict[str, Any]:
        """
        Convert CSV file to Parquet format.
        
        Args:
            input_path: Path to input CSV file
            output_path: Path to output Parquet file
            skip_existing: Skip if output already exists
            **kwargs: Additional parameters
            
        Returns:
            Conversion statistics
        """
        try:
            # Check if we should skip
            if self.should_skip_existing(output_path, skip_existing):
                return self.create_result_dict(
                    status='skipped',
                    input_file=input_path
                )
            
            # Validate input
            validation = self.validate_input(input_path)
            if not validation['valid']:
                return self.create_result_dict(
                    status='error',
                    input_file=input_path,
                    error='; '.join(validation['errors'])
                )
            
            # Choose conversion method based on file size
            file_size_mb = input_path.stat().st_size / (1024 * 1024)
            
            if file_size_mb > self.streaming_threshold_mb:
                return self.convert_streaming(input_path, output_path, **kwargs)
            else:
                return self.convert_regular(input_path, output_path, **kwargs)
                
        except Exception as e:
            self.logger.error(f"❌ Error converting {input_path.name}: {e}")
            return self.create_result_dict(
                status='error',
                input_file=input_path,
                error=str(e)
            )