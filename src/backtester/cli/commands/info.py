"""
Information and inspection commands for the CLI.

Provides tools to inspect file contents, schemas, and statistics.
"""

import click
from pathlib import Path
from typing import Dict, Any
import polars as pl

from ..utils import (
    validate_file_exists,
    format_file_size,
    format_duration,
    print_success,
    print_error,
    print_info,
    truncate_path
)


@click.group(name='info')
def info_group():
    """Get information about data files."""
    pass


@info_group.command()
@click.argument('file_path', type=click.Path(exists=True, path_type=Path))
@click.option('--sample-lines', type=int, default=5, help='Number of sample lines to display')
@click.pass_context
def csv(ctx, file_path: Path, sample_lines: int):
    """
    Display information about a CSV file.
    
    FILE_PATH: Path to the CSV file
    
    Example:
        nq-backtester info csv data.csv
    """
    verbose = ctx.obj.get('verbose', False)
    quiet = ctx.obj.get('quiet', False)
    
    if not validate_file_exists(file_path, 'CSV'):
        return
    
    try:
        # Basic file info
        stat = file_path.stat()
        file_size_mb = stat.st_size / (1024 * 1024)
        
        print_info(f"📄 CSV File Information")
        print_info(f"═" * 50)
        print_info(f"📁 Path: {file_path}")
        print_info(f"📊 Size: {format_file_size(file_size_mb)} MB ({stat.st_size:,} bytes)")
        
        # Count lines and analyze content
        print_info("🔍 Analyzing content...")
        
        l1_count = 0
        l2_count = 0
        total_lines = 0
        sample_content = []
        
        with open(file_path, 'r', encoding='utf-8') as f:
            for i, line in enumerate(f):
                total_lines += 1
                
                # Collect sample lines
                if i < sample_lines:
                    sample_content.append(line.strip())
                
                # Count record types
                if line.startswith('L1;'):
                    l1_count += 1
                elif line.startswith('L2;'):
                    l2_count += 1
                
                # Don't analyze entire large files
                if i > 100000 and not verbose:
                    print_info("⚠️ Large file - showing partial analysis (use --verbose for full analysis)")
                    break
        
        # Display statistics
        print_info(f"📈 Statistics:")
        print_info(f"  • Total lines: {total_lines:,}")
        print_info(f"  • L1 records: {l1_count:,}")
        print_info(f"  • L2 records: {l2_count:,}")
        print_info(f"  • Other records: {total_lines - l1_count - l2_count:,}")
        
        # Display sample content
        if sample_content:
            print_info(f"📝 Sample content (first {len(sample_content)} lines):")
            for i, line in enumerate(sample_content, 1):
                print_info(f"  {i}: {line}")
        
        # Format analysis
        if sample_content:
            first_line = sample_content[0]
            fields = first_line.split(';')
            print_info(f"🏗️ Format analysis:")
            print_info(f"  • Delimiter: semicolon (;)")
            print_info(f"  • Fields per record: {len(fields)}")
            
            if verbose and len(fields) >= 4:
                print_info(f"  • Field structure:")
                field_names = ['RecordType', 'MarketDataType', 'Timestamp', 'TimestampOffset', 
                              'Price', 'Volume', 'Operation', 'Position', 'MarketMaker']
                for i, field in enumerate(fields[:len(field_names)]):
                    field_name = field_names[i] if i < len(field_names) else f'Field{i+1}'
                    print_info(f"    {i+1}. {field_name}: {field}")
                    
    except Exception as e:
        print_error(f"❌ Error analyzing CSV file: {e}")
        if verbose:
            import traceback
            traceback.print_exc()


@info_group.command()
@click.argument('file_path', type=click.Path(exists=True, path_type=Path))
@click.option('--sample-rows', type=int, default=5, help='Number of sample rows to display')
@click.pass_context
def parquet(ctx, file_path: Path, sample_rows: int):
    """
    Display information about a Parquet file.
    
    FILE_PATH: Path to the Parquet file
    
    Example:
        nq-backtester info parquet data.parquet
    """
    verbose = ctx.obj.get('verbose', False)
    quiet = ctx.obj.get('quiet', False)
    
    if not validate_file_exists(file_path, 'Parquet'):
        return
    
    try:
        # Basic file info
        stat = file_path.stat()
        file_size_mb = stat.st_size / (1024 * 1024)
        
        print_info(f"💾 Parquet File Information")
        print_info(f"═" * 50)
        print_info(f"📁 Path: {file_path}")
        print_info(f"📊 Size: {format_file_size(file_size_mb)} MB ({stat.st_size:,} bytes)")
        
        # Read Parquet metadata
        print_info("🔍 Reading metadata...")
        
        # Use scan_parquet to avoid loading entire file
        df_lazy = pl.scan_parquet(file_path)
        schema = df_lazy.collect_schema()
        
        # Get basic stats by reading a small sample first
        sample_df = pl.read_parquet(file_path, n_rows=10000)  # Read first 10k rows
        total_rows = len(sample_df)
        
        # Try to get exact count if file is not too large
        if file_size_mb < 100:  # Only for files < 100MB
            full_df = pl.read_parquet(file_path)
            total_rows = len(full_df)
        else:
            print_info("⚠️ Large file - showing approximate row count from sample")
        
        print_info(f"📈 Statistics:")
        print_info(f"  • Total rows: {total_rows:,}")
        print_info(f"  • Columns: {len(schema)}")
        
        # Display schema
        print_info(f"🏗️ Schema:")
        for col_name, col_type in schema.items():
            print_info(f"  • {col_name}: {col_type}")
        
        # Display sample data
        if sample_rows > 0:
            print_info(f"📝 Sample data (first {sample_rows} rows):")
            sample_data = sample_df.head(sample_rows)
            
            # Create a simple table display
            col_names = list(schema.keys())
            
            # Header
            header = " | ".join(f"{name[:12]:12}" for name in col_names)
            print_info(f"  {header}")
            print_info(f"  {'-' * len(header)}")
            
            # Data rows
            for i in range(min(sample_rows, len(sample_data))):
                row_data = []
                for col in col_names:
                    value = str(sample_data[i, col])
                    if len(value) > 12:
                        value = value[:9] + "..."
                    row_data.append(f"{value:12}")
                
                row_str = " | ".join(row_data)
                print_info(f"  {row_str}")
        
        # Additional analysis if verbose
        if verbose and 'record_type' in schema:
            print_info("📊 Record type distribution:")
            record_counts = sample_df.group_by('record_type').len().sort('len', descending=True)
            for row in record_counts.iter_rows():
                record_type, count = row
                print_info(f"  • {record_type}: {count:,}")
                
    except Exception as e:
        print_error(f"❌ Error analyzing Parquet file: {e}")
        if verbose:
            import traceback
            traceback.print_exc()


@info_group.command()
@click.argument('directory', type=click.Path(exists=True, file_okay=False, path_type=Path))
@click.option('--pattern', default='*.*', help='File pattern to match')
@click.option('--recursive', '-r', is_flag=True, help='Search subdirectories recursively')
@click.pass_context
def directory(ctx, directory: Path, pattern: str, recursive: bool):
    """
    Display information about files in a directory.
    
    DIRECTORY: Path to the directory to analyze
    
    Example:
        nq-backtester info directory ./data --pattern "*.csv"
    """
    verbose = ctx.obj.get('verbose', False)
    quiet = ctx.obj.get('quiet', False)
    
    try:
        print_info(f"📁 Directory Information")
        print_info(f"═" * 50)
        print_info(f"📂 Path: {directory}")
        print_info(f"🔍 Pattern: {pattern}")
        print_info(f"🔄 Recursive: {'Yes' if recursive else 'No'}")
        
        # Find files
        if recursive:
            files = list(directory.rglob(pattern))
        else:
            files = list(directory.glob(pattern))
        
        if not files:
            print_info("❌ No files found matching pattern")
            return
        
        # Categorize files
        csv_files = [f for f in files if f.suffix.lower() == '.csv']
        parquet_files = [f for f in files if f.suffix.lower() == '.parquet']
        other_files = [f for f in files if f.suffix.lower() not in ['.csv', '.parquet']]
        
        print_info(f"📊 File summary:")
        print_info(f"  • Total files: {len(files)}")
        print_info(f"  • CSV files: {len(csv_files)}")
        print_info(f"  • Parquet files: {len(parquet_files)}")
        print_info(f"  • Other files: {len(other_files)}")
        
        # Calculate total size
        total_size = sum(f.stat().st_size for f in files if f.is_file())
        total_size_mb = total_size / (1024 * 1024)
        print_info(f"  • Total size: {format_file_size(total_size_mb)} MB")
        
        # Display file list if not too many files
        if len(files) <= 20 or verbose:
            print_info(f"📋 File list:")
            
            # Group by type for better display
            for file_type, file_list in [('CSV', csv_files), ('Parquet', parquet_files), ('Other', other_files)]:
                if file_list:
                    print_info(f"  {file_type} files:")
                    for file_path in file_list:
                        size_mb = file_path.stat().st_size / (1024 * 1024)
                        rel_path = file_path.relative_to(directory) if recursive else file_path.name
                        display_path = truncate_path(rel_path, 40)
                        print_info(f"    • {display_path} ({format_file_size(size_mb)} MB)")
        else:
            print_info(f"📋 Too many files to display ({len(files)}). Use --verbose to show all.")
            
        # Show largest files
        if len(files) > 5:
            largest_files = sorted(files, key=lambda f: f.stat().st_size, reverse=True)[:5]
            print_info(f"📈 Largest files:")
            for file_path in largest_files:
                size_mb = file_path.stat().st_size / (1024 * 1024)
                rel_path = file_path.relative_to(directory) if recursive else file_path.name
                display_path = truncate_path(rel_path, 40)
                print_info(f"  • {display_path} ({format_file_size(size_mb)} MB)")
                
    except Exception as e:
        print_error(f"❌ Error analyzing directory: {e}")
        if verbose:
            import traceback
            traceback.print_exc()