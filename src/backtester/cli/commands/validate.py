"""
Data validation commands for the CLI.

Provides validation and inspection tools for CSV and Parquet files.
"""

import click
from pathlib import Path
from typing import Dict, Any
import polars as pl

from src.backtester.data.converters import CSVToParquetConverter, ParquetToCSVConverter
from ..utils import (
    validate_file_exists,
    format_file_size,
    print_success,
    print_error,
    print_info,
    print_warning
)


@click.group(name='validate')
def validate_group():
    """Validate and inspect data files."""
    pass


@validate_group.command()
@click.argument('file_path', type=click.Path(exists=True, path_type=Path))
@click.option('--sample-size', type=int, default=100, help='Number of records to sample for validation')
@click.pass_context
def csv(ctx, file_path: Path, sample_size: int):
    """
    Validate CSV file format and content.
    
    FILE_PATH: Path to the CSV file to validate
    
    Example:
        nq-backtester validate csv data.csv
    """
    verbose = ctx.obj.get('verbose', False)
    quiet = ctx.obj.get('quiet', False)
    
    if not validate_file_exists(file_path, 'CSV'):
        return
    
    if not quiet:
        print_info(f"🔍 Validating CSV file: {file_path}")
    
    # Create converter for validation
    converter = CSVToParquetConverter()
    
    try:
        # Validate file
        validation_result = converter.validate_input(file_path)
        
        if not quiet:
            # Display file info
            file_size_mb = file_path.stat().st_size / (1024 * 1024)
            print_info(f"📊 File size: {format_file_size(file_size_mb)} MB")
        
        # Check validation results
        if validation_result['valid']:
            if not quiet:
                print_success("✅ CSV file is valid!")
                
                # Display additional info if available
                if 'total_lines' in validation_result:
                    print_info(f"📄 Total lines: {validation_result['total_lines']:,}")
                
                if 'l1_records' in validation_result:
                    print_info(f"📈 L1 records: {validation_result['l1_records']:,}")
                
                if 'l2_records' in validation_result:
                    print_info(f"📊 L2 records: {validation_result['l2_records']:,}")
                
                if 'sample_lines' in validation_result and verbose:
                    print_info("📝 Sample lines:")
                    for i, line in enumerate(validation_result['sample_lines'][:5], 1):
                        print_info(f"  {i}: {line}")
        else:
            print_error("❌ CSV file validation failed!")
            
            # Display errors
            if 'errors' in validation_result:
                for error in validation_result['errors']:
                    print_error(f"  • {error}")
        
        # Display warnings if any
        if 'warnings' in validation_result and validation_result['warnings']:
            for warning in validation_result['warnings']:
                print_warning(f"⚠️ {warning}")
                
    except Exception as e:
        print_error(f"❌ Validation failed: {e}")
        if verbose:
            import traceback
            traceback.print_exc()


@validate_group.command()
@click.argument('file_path', type=click.Path(exists=True, path_type=Path))
@click.pass_context
def parquet(ctx, file_path: Path):
    """
    Validate Parquet file format and content.
    
    FILE_PATH: Path to the Parquet file to validate
    
    Example:
        nq-backtester validate parquet data.parquet
    """
    verbose = ctx.obj.get('verbose', False)
    quiet = ctx.obj.get('quiet', False)
    
    if not validate_file_exists(file_path, 'Parquet'):
        return
    
    if not quiet:
        print_info(f"🔍 Validating Parquet file: {file_path}")
    
    # Create converter for validation
    converter = ParquetToCSVConverter()
    
    try:
        # Validate file
        validation_result = converter.validate_input(file_path)
        
        if not quiet:
            # Display file info
            file_size_mb = file_path.stat().st_size / (1024 * 1024)
            print_info(f"📊 File size: {format_file_size(file_size_mb)} MB")
        
        # Check validation results
        if validation_result['valid']:
            if not quiet:
                print_success("✅ Parquet file is valid!")
                
                # Display additional info
                if 'total_records' in validation_result:
                    print_info(f"📄 Total records: {validation_result['total_records']:,}")
                
                if 'schema' in validation_result and verbose:
                    print_info("🏗️ Schema:")
                    for col_name, col_type in validation_result['schema'].items():
                        print_info(f"  • {col_name}: {col_type}")
        else:
            print_error("❌ Parquet file validation failed!")
            
            # Display errors
            if 'errors' in validation_result:
                for error in validation_result['errors']:
                    print_error(f"  • {error}")
        
        # Display warnings if any
        if 'warnings' in validation_result and validation_result['warnings']:
            for warning in validation_result['warnings']:
                print_warning(f"⚠️ {warning}")
                
    except Exception as e:
        print_error(f"❌ Validation failed: {e}")
        if verbose:
            import traceback
            traceback.print_exc()


@validate_group.command()
@click.argument('csv_file', type=click.Path(exists=True, path_type=Path))
@click.argument('parquet_file', type=click.Path(exists=True, path_type=Path))
@click.option('--sample-size', type=int, default=1000, help='Number of records to compare')
@click.pass_context
def roundtrip(ctx, csv_file: Path, parquet_file: Path, sample_size: int):
    """
    Validate roundtrip conversion between CSV and Parquet files.
    
    CSV_FILE: Path to the CSV file
    PARQUET_FILE: Path to the Parquet file
    
    Example:
        nq-backtester validate roundtrip original.csv converted.parquet
    """
    verbose = ctx.obj.get('verbose', False)
    quiet = ctx.obj.get('quiet', False)
    
    if not validate_file_exists(csv_file, 'CSV'):
        return
    if not validate_file_exists(parquet_file, 'Parquet'):
        return
    
    if not quiet:
        print_info(f"🔍 Validating roundtrip conversion")
        print_info(f"📄 CSV: {csv_file}")
        print_info(f"💾 Parquet: {parquet_file}")
    
    try:
        # Count records in both files
        if not quiet:
            print_info("📊 Counting records...")
        
        # Count CSV records
        with open(csv_file, 'r') as f:
            csv_count = sum(1 for _ in f)
        
        # Count Parquet records
        df_parquet = pl.read_parquet(parquet_file)
        parquet_count = len(df_parquet)
        
        if not quiet:
            print_info(f"📈 CSV records: {csv_count:,}")
            print_info(f"💾 Parquet records: {parquet_count:,}")
        
        # Compare counts
        if csv_count == parquet_count:
            print_success("✅ Record counts match!")
        else:
            print_error(f"❌ Record count mismatch: {csv_count:,} vs {parquet_count:,}")
            return
        
        # Sample data comparison if requested
        if sample_size > 0 and not quiet:
            print_info(f"🔍 Comparing {min(sample_size, csv_count)} sample records...")
            
            # Read sample from CSV
            csv_sample = []
            with open(csv_file, 'r') as f:
                for i, line in enumerate(f):
                    if i >= sample_size:
                        break
                    csv_sample.append(line.strip().split(';'))
            
            # Get sample from Parquet
            parquet_sample = df_parquet.head(sample_size)
            
            # Basic comparison (this is simplified - you might want more detailed comparison)
            mismatches = 0
            for i in range(min(len(csv_sample), len(parquet_sample))):
                # Compare key fields (this is a simplified comparison)
                if len(csv_sample[i]) >= 2 and len(parquet_sample) > i:
                    csv_record_type = csv_sample[i][0] if len(csv_sample[i]) > 0 else ''
                    parquet_record_type = str(parquet_sample[i, 0]) if parquet_sample.shape[1] > 0 else ''
                    
                    if csv_record_type != parquet_record_type:
                        mismatches += 1
                        if verbose and mismatches <= 3:
                            print_warning(f"Mismatch at record {i+1}: '{csv_record_type}' vs '{parquet_record_type}'")
            
            if mismatches == 0:
                print_success(f"✅ Sample validation passed ({sample_size:,} records)")
            else:
                mismatch_rate = mismatches / min(len(csv_sample), len(parquet_sample))
                if mismatch_rate < 0.05:  # Less than 5% mismatch
                    print_warning(f"⚠️ Minor mismatches found: {mismatches} ({mismatch_rate:.1%})")
                else:
                    print_error(f"❌ Significant mismatches found: {mismatches} ({mismatch_rate:.1%})")
                    
    except Exception as e:
        print_error(f"❌ Roundtrip validation failed: {e}")
        if verbose:
            import traceback
            traceback.print_exc()