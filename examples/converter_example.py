"""
CSV Converter Example - Convert NinjaTrader Market Replay files to Parquet

This example demonstrates how to convert your NinjaTrader CSV files to
optimized Parquet format for backtesting.
"""

import sys
from pathlib import Path

# Add backtester to path  
sys.path.insert(0, str(Path(__file__).parent.parent))

from backtester.data.converter import convert_csv_to_parquet, validate_csv_file
import argparse
import time


def main():
    """Main converter example function."""
    
    parser = argparse.ArgumentParser(description="Convert NinjaTrader CSV to Parquet")
    parser.add_argument("--source", "-s", type=str, required=True,
                       help="Path to source CSV file or directory")
    parser.add_argument("--output", "-o", type=str, default="./data/parquet",
                       help="Output directory for Parquet files")
    parser.add_argument("--validate", "-v", action="store_true",
                       help="Validate CSV file before conversion")
    parser.add_argument("--max-workers", "-w", type=int, default=4,
                       help="Maximum number of worker processes")
    
    args = parser.parse_args()
    
    print("🔄 NQ Backtester - CSV to Parquet Converter")
    print("=" * 55)
    
    source_path = Path(args.source)
    output_path = Path(args.output)
    
    if not source_path.exists():
        print(f"❌ Source path does not exist: {source_path}")
        return 1
    
    # Validate file if requested
    if args.validate:
        print(f"🔍 Validating CSV file...")
        try:
            validation_result = validate_csv_file(source_path)
            if validation_result['valid']:
                print(f"✅ Validation passed")
                print(f"   Total records: {validation_result['total_records']:,}")
                print(f"   L1 records: {validation_result['l1_records']:,}")
                print(f"   L2 records: {validation_result['l2_records']:,}")
                print(f"   Date range: {validation_result['date_range']}")
                print(f"   Instruments: {validation_result['instruments']}")
            else:
                print(f"❌ Validation failed:")
                for error in validation_result['errors']:
                    print(f"   - {error}")
                return 1
        except Exception as e:
            print(f"❌ Validation error: {e}")
            return 1
    
    # Perform conversion
    print(f"\n📁 Converting files...")
    print(f"   Source: {source_path}")
    print(f"   Output: {output_path}")
    print(f"   Workers: {args.max_workers}")
    
    start_time = time.time()
    
    try:
        if source_path.is_file():
            # Single file conversion
            from backtester.data.converter import convert_single_csv
            result = convert_single_csv(source_path, output_path)
            
            elapsed = time.time() - start_time
            
            print(f"\n✅ Conversion completed in {elapsed:.2f} seconds")
            print(f"   Records processed: {result['rows']:,}")
            print(f"   L1 records: {result['l1_records']:,}")
            print(f"   L2 records: {result['l2_records']:,}")
            print(f"   Output size: {result['size_mb']:.2f} MB")
            print(f"   Processing rate: {result['rows'] / elapsed:,.0f} records/sec")
            
        else:
            # Directory conversion
            result = convert_csv_to_parquet(
                source_dir=source_path,
                output_dir=output_path,
                max_workers=args.max_workers
            )
            
            elapsed = time.time() - start_time
            
            print(f"\n✅ Batch conversion completed in {elapsed:.2f} seconds")
            print(f"   Files processed: {result['files_processed']}")
            print(f"   Total records: {result['total_records']:,}")
            print(f"   Total size: {result['total_size_mb']:.2f} MB")
            print(f"   Average processing rate: {result['total_records'] / elapsed:,.0f} records/sec")
            
            if result['failed_files']:
                print(f"\n⚠️  Failed files:")
                for failed_file, error in result['failed_files'].items():
                    print(f"   - {failed_file}: {error}")
    
    except Exception as e:
        print(f"\n❌ Conversion failed: {e}")
        import traceback
        traceback.print_exc()
        return 1
    
    print(f"\n🎯 Conversion Summary:")
    print(f"   Parquet files are now ready for backtesting!")
    print(f"   Use DataLoader to load data from: {output_path}")
    
    return 0


def show_usage_examples():
    """Show usage examples."""
    
    print("""
Usage Examples:

1. Convert single CSV file:
   python examples/converter_example.py -s "C:\\NinjaTrader 8\\bin\\Custom\\MarketReplay\\NQ 06-21\\20210618.csv"

2. Convert entire directory:
   python examples/converter_example.py -s "C:\\NinjaTrader 8\\bin\\Custom\\MarketReplay\\NQ 06-21\\"

3. Convert with validation:
   python examples/converter_example.py -s "replay.csv" --validate

4. Convert with custom output and workers:
   python examples/converter_example.py -s "data\\csv\\" -o "data\\parquet" -w 8

Expected CSV Format:
   - Semicolon-delimited fields
   - Format: Type;MarketDataType;Date;Time;Price;Volume;BidPrice;AskPrice;...
   - L1 records: market data (last price, volume)
   - L2 records: order book operations (add/update/remove)
   - Date format: YYYYMMDD
   - Time format: microseconds since midnight
   
Performance Notes:
   - Typical conversion rate: 100,000-500,000 records/second
   - Parquet files are ~50-70% smaller than CSV
   - Partitioned by instrument/year/month for efficient querying
   - Uses Snappy compression for optimal balance of size/speed
    """)


if __name__ == "__main__":
    if len(sys.argv) == 1:
        show_usage_examples()
    else:
        sys.exit(main())