"""
Parquet to CSV converter for high-performance tick data processing.

This module provides functionality to convert Parquet files back to CSV format,
maintaining data integrity and supporting large file processing with streaming.
"""

import logging
from pathlib import Path
from typing import Dict, Any, Optional
import polars as pl
from datetime import datetime

from .base import BaseConverter
from src.backtester.core import ConversionError, DataValidationError


class ParquetToCSVConverter(BaseConverter):
    """
    High-performance Parquet to CSV converter using Polars.
    
    Features:
    - Streaming support for large files
    - Maintains original CSV semicolon delimiter format
    - Preserves data types and precision
    - Memory-efficient processing
    - Comprehensive error handling
    """
    
    def __init__(self, chunk_size: int = 100_000, streaming_threshold_mb: int = 5000):
        """
        Initialize the Parquet to CSV converter.
        
        Args:
            chunk_size: Number of records to process per chunk for streaming
            streaming_threshold_mb: File size threshold (MB) to trigger streaming mode
        """
        super().__init__()
        self.chunk_size = chunk_size
        self.streaming_threshold_mb = streaming_threshold_mb
        self.logger = logging.getLogger(__name__)
    
    def should_use_streaming(self, input_path: Path) -> bool:
        """
        Determine if streaming should be used based on file size.
        
        Args:
            input_path: Path to input Parquet file
            
        Returns:
            True if streaming should be used
        """
        try:
            file_size_mb = input_path.stat().st_size / (1024 * 1024)
            return file_size_mb > self.streaming_threshold_mb
        except Exception:
            # Default to streaming for safety if we can't determine size
            return True
    
    def validate_input(self, input_path: Path) -> Dict[str, Any]:
        """
        Validate input Parquet file.
        
        Args:
            input_path: Path to Parquet file
            
        Returns:
            Validation result dictionary
        """
        errors = []
        warnings = []
        
        try:
            # Check if file exists
            if not input_path.exists():
                errors.append(f"Parquet file does not exist: {input_path}")
                return {'valid': False, 'errors': errors}
            
            # Check file extension
            if input_path.suffix.lower() not in ['.parquet', '.pq']:
                errors.append(f"File {input_path} is not a Parquet file (invalid extension)")
                return {'valid': False, 'errors': errors}
            
            # Check if file is empty
            if input_path.stat().st_size == 0:
                warnings.append(f"Parquet file {input_path} is empty")
                return {'valid': True, 'errors': [], 'warnings': warnings}
            
            # Try to read schema and validate structure
            try:
                df_lazy = pl.scan_parquet(input_path)
                schema = df_lazy.collect_schema()
                
                # Check for required columns (basic tick data structure)
                expected_columns = ['record_type', 'market_data_type', 'timestamp']
                missing_columns = [col for col in expected_columns if col not in schema]
                
                if missing_columns:
                    errors.append(f"Missing required columns: {missing_columns}")
                
                # Get basic stats without loading full data
                total_records = df_lazy.select(pl.len()).collect().item()
                
                self.logger.debug(f"Parquet validation - Total records: {total_records:,}")
                
                return {
                    'valid': len(errors) == 0,
                    'errors': errors,
                    'warnings': warnings,
                    'total_records': total_records,
                    'schema': dict(schema)
                }
                
            except Exception as e:
                errors.append(f"Failed to read Parquet file structure: {str(e)}")
                return {'valid': False, 'errors': errors}
            
        except Exception as e:
            return {
                'valid': False,
                'errors': [f"Validation error: {str(e)}"]
            }
    
    def convert_streaming(self, input_path: Path, output_path: Path, **kwargs) -> Dict[str, Any]:
        """
        Convert large Parquet file using streaming for memory efficiency.
        
        Args:
            input_path: Path to input Parquet file
            output_path: Path to output CSV file
            **kwargs: Additional parameters
            
        Returns:
            Conversion statistics
        """
        self.logger.info(f"🔄 Converting large Parquet with streaming: {input_path.name}")
        
        try:
            # Use Polars lazy loading for streaming
            df_lazy = pl.scan_parquet(input_path)
            
            # Configure CSV output format to match NinjaTrader format
            df_lazy.sink_csv(
                output_path,
                separator=';',
                include_header=False,  # NinjaTrader CSV doesn't have headers
                quote_style='never',   # No quoting for numeric data
                datetime_format='%Y%m%d%H%M%S%f',  # Match NinjaTrader timestamp format
                float_precision=2      # Preserve price precision
            )
            
            # Get final statistics
            total_records = df_lazy.select(pl.len()).collect().item()
            output_size_mb = output_path.stat().st_size / (1024 * 1024)
            
            self.logger.info(f"✅ Streaming conversion complete: {total_records:,} records, {output_size_mb:.2f} MB")
            
            return {
                'status': 'success',
                'method': 'streaming',
                'records_processed': total_records,
                'output_size_mb': output_size_mb,
                'input_file': str(input_path),
                'output_file': str(output_path)
            }
            
        except Exception as e:
            # Clean up partial output on error
            if output_path.exists():
                output_path.unlink()
            
            error_msg = f"Streaming conversion failed: {str(e)}"
            self.logger.error(error_msg)
            raise ConversionError(error_msg) from e
    
    def convert_standard(self, input_path: Path, output_path: Path, **kwargs) -> Dict[str, Any]:
        """
        Convert Parquet file using standard (in-memory) processing.
        
        Args:
            input_path: Path to input Parquet file
            output_path: Path to output CSV file
            **kwargs: Additional parameters
            
        Returns:
            Conversion statistics
        """
        self.logger.info(f"🔄 Converting Parquet (standard): {input_path.name}")
        
        try:
            # Read entire file into memory
            df = pl.read_parquet(input_path)
            
            # Write CSV in NinjaTrader format
            df.write_csv(
                output_path,
                separator=';',
                include_header=False,
                quote_style='never',
                datetime_format='%Y%m%d%H%M%S%f',
                float_precision=2
            )
            
            # Get statistics
            total_records = len(df)
            output_size_mb = output_path.stat().st_size / (1024 * 1024)
            
            self.logger.info(f"✅ Standard conversion complete: {total_records:,} records, {output_size_mb:.2f} MB")
            
            return {
                'status': 'success',
                'method': 'standard',
                'records_processed': total_records,
                'output_size_mb': output_size_mb,
                'input_file': str(input_path),
                'output_file': str(output_path)
            }
            
        except Exception as e:
            # Clean up partial output on error
            if output_path.exists():
                output_path.unlink()
            
            error_msg = f"Standard conversion failed: {str(e)}"
            self.logger.error(error_msg)
            raise ConversionError(error_msg) from e
    
    def convert(self, input_path: Path, output_path: Path, **kwargs) -> Dict[str, Any]:
        """
        Convert Parquet file to CSV format.
        
        Args:
            input_path: Path to input Parquet file
            output_path: Path to output CSV file
            **kwargs: Additional conversion parameters
                - skip_existing: Skip if output file exists
                - force_streaming: Force streaming mode regardless of file size
                
        Returns:
            Conversion result dictionary
        """
        try:
            input_path = Path(input_path)
            output_path = Path(output_path)
            
            # Check if we should skip existing files
            if kwargs.get('skip_existing', False) and output_path.exists():
                return self.create_result_dict(
                    'skipped', 
                    input_path,
                    error=f"Output file already exists: {output_path}",
                    output_file=str(output_path)
                )
            
            # Validate input
            validation = self.validate_input(input_path)
            if not validation['valid']:
                return self.create_result_dict(
                    'error',
                    input_path,
                    error=f"Input validation failed: {'; '.join(validation['errors'])}",
                    validation_errors=validation['errors']
                )
            
            # Create output directory if needed
            output_path.parent.mkdir(parents=True, exist_ok=True)
            
            # Determine conversion method
            force_streaming = kwargs.get('force_streaming', False)
            use_streaming = force_streaming or self.should_use_streaming(input_path)
            
            # Perform conversion
            if use_streaming:
                return self.convert_streaming(input_path, output_path, **kwargs)
            else:
                return self.convert_standard(input_path, output_path, **kwargs)
                
        except ConversionError as e:
            # Handle conversion errors gracefully
            error_msg = str(e)
            self.logger.error(error_msg)
            return self.create_result_dict(
                'error',
                input_path if 'input_path' in locals() else Path('unknown'),
                error=error_msg
            )
        except Exception as e:
            error_msg = f"Unexpected conversion error: {str(e)}"
            self.logger.error(error_msg)
            return self.create_result_dict(
                'error',
                input_path if 'input_path' in locals() else Path('unknown'),
                error=error_msg
            )