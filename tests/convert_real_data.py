"""
Test the real NinjaTrader CSV to Parquet conversion

This script tests the conversion of the real NinjaTrader CSV file
and creates the corresponding Parquet file in the test_data directory.
"""

import sys
from pathlib import Path
import tempfile
import shutil
import time

# Add backtester to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from backtester.data.converter import convert_single_csv, validate_csv_file
from backtester.data.loader import DataLoader


def test_real_csv_to_parquet_conversion():
    """
    Convert the real NinjaTrader CSV file to Parquet and validate the conversion.
    Also saves the Parquet file to test_data for future use.
    """
    print("🚀 Testing Real NinjaTrader CSV to Parquet Conversion")
    print("=" * 60)
    
    # Paths
    test_dir = Path(__file__).parent
    csv_file = test_dir / "test_data" / "csv" / "NQ SEP25" / "20250330.csv"
    parquet_output_dir = test_dir / "test_data" / "parquet"
    
    # Check if CSV file exists
    if not csv_file.exists():
        print(f"❌ CSV file not found: {csv_file}")
        return False
    
    print(f"📁 Input CSV file: {csv_file}")
    print(f"   Size: {csv_file.stat().st_size / (1024*1024):.2f} MB")
    
    # Step 1: Validate CSV file
    print("\n📋 Step 1: Validating CSV file...")
    validation = validate_csv_file(csv_file)
    
    print(f"   Valid: {'✅ YES' if validation['valid'] else '⚠️ ISSUES'}")
    print(f"   Total records: {validation.get('total_records', 0):,}")
    print(f"   L1 records: {validation.get('l1_records', 0):,}")
    print(f"   L2 records: {validation.get('l2_records', 0):,}")
    print(f"   Instruments: {validation.get('instruments', [])}")
    print(f"   Date range: {validation.get('date_range', 'N/A')}")
    
    if not validation['valid']:
        print(f"   Errors (first 10):")
        for i, error in enumerate(validation.get('errors', [])[:10]):
            print(f"     {i+1}. {error}")
        if len(validation.get('errors', [])) > 10:
            print(f"     ... and {len(validation['errors']) - 10} more errors")
        
        print(f"\n❌ VALIDATION FAILED - Cannot proceed with conversion!")
        print(f"   The CSV file has validation errors that prevent proper conversion.")
        print(f"   Please check the file format and fix the issues before converting.")
        return False
    
    # Step 2: Convert to Parquet
    print(f"\n🔄 Step 2: Converting to Parquet...")
    print(f"   Output directory: {parquet_output_dir}")
    
    # Create output directory
    parquet_output_dir.mkdir(parents=True, exist_ok=True)
    
    # Measure conversion time
    start_time = time.time()
    result = convert_single_csv(csv_file, parquet_output_dir, skip_existing=False)
    conversion_time = time.time() - start_time
    
    if result.get('status') == 'error':
        error_msg = result.get('error') or 'Unknown error'
        print(f"❌ Conversion failed: {error_msg}")
        print(f"   Full result: {result}")
        return False
    elif result.get('status') == 'skipped':
        print(f"⚠️ Conversion was skipped (file already exists)")
        print(f"   Using existing Parquet files for validation")
    elif result.get('status') != 'success':
        print(f"❌ Unexpected conversion status: {result.get('status')}")
        print(f"   Full result: {result}")
        return False
    
    # Performance metrics
    file_size_mb = csv_file.stat().st_size / (1024 * 1024)
    records_per_sec = result['rows'] / conversion_time if conversion_time > 0 else 0
    compression_ratio = result['size_mb'] / file_size_mb if file_size_mb > 0 else 0
    
    print(f"✅ Conversion successful!")
    print(f"   Processing time: {conversion_time:.2f} seconds")
    print(f"   Records processed: {result['rows']:,}")
    print(f"   L1 records: {result['l1_records']:,}")
    print(f"   L2 records: {result['l2_records']:,}")
    print(f"   Output size: {result['size_mb']:.3f} MB")
    print(f"   Processing rate: {records_per_sec:,.0f} records/sec")
    print(f"   Compression ratio: {compression_ratio:.2%}")
    print(f"   Size reduction: {(1-compression_ratio):.1%}")
    
    # Step 3: Validate output files
    print(f"\n📊 Step 3: Validating output files...")
    
    parquet_files = list(parquet_output_dir.rglob("*.parquet"))
    print(f"   Created {len(parquet_files)} Parquet file(s):")
    
    for pf in parquet_files:
        rel_path = pf.relative_to(parquet_output_dir)
        file_size = pf.stat().st_size / (1024 * 1024)  # MB
        print(f"     📄 {rel_path} ({file_size:.3f} MB)")
    
    if not parquet_files:
        print(f"❌ No Parquet files created!")
        return False
    
    # Step 4: Test DataLoader integration
    print(f"\n📈 Step 4: Testing DataLoader integration...")
    
    loader = DataLoader(str(parquet_output_dir))
    
    # Test instrument discovery
    instruments = loader.get_available_instruments()
    print(f"   Available instruments: {instruments}")
    
    if not instruments:
        print(f"❌ No instruments found by DataLoader!")
        return False
    
    # Test date discovery
    instrument = instruments[0]
    dates = loader.get_available_dates(instrument)
    print(f"   Available dates for {instrument}: {dates}")
    
    if not dates:
        print(f"❌ No dates found for instrument {instrument}!")
        return False
    
    # Load and validate data - use the date with most records
    date_record_counts = {}
    for date in dates:
        data_sample = loader.load_day(instrument, date)
        date_record_counts[date] = len(data_sample)
    
    # Use the date with the most records (our main test file)
    test_date = max(date_record_counts.keys(), key=lambda d: date_record_counts[d])
    data = loader.load_day(instrument, test_date)
    print(f"   Loaded {len(data):,} records for {test_date} (largest dataset)")
    
    if data.empty:
        print(f"❌ Loaded data is empty!")
        return False
    
    # Show data structure
    print(f"   Data columns: {list(data.columns)}")
    print(f"   Time range: {data['timestamp'].min()} to {data['timestamp'].max()}")
    
    # Record type analysis
    if 'record_type' in data.columns:
        record_counts = data['record_type'].value_counts()
        print(f"   Record types: {dict(record_counts)}")
    
    # Show sample records
    print(f"   Sample records (first 5):")
    sample_cols = ['timestamp', 'record_type', 'market_data_type', 'price', 'volume']
    available_cols = [col for col in sample_cols if col in data.columns]
    sample_data = data[available_cols].head()
    
    for i, row in sample_data.iterrows():
        timestamp = row['timestamp'].strftime('%H:%M:%S.%f')[:-3] if 'timestamp' in row else 'N/A'
        record_type = row.get('record_type', 'N/A')
        price = row.get('price', 'N/A')
        volume = row.get('volume', 'N/A')
        print(f"     {timestamp} | {record_type} | ${price} | Vol: {volume}")
    
    # Step 5: Data integrity validation
    print(f"\n🔍 Step 5: Data integrity validation...")
    
    # Compare record counts - use conversion result vs actual loaded data
    csv_total = result.get('rows', 0)  # Use actual conversion count, not validation sample
    parquet_total = len(data)
    
    print(f"   CSV records converted: {csv_total:,}")
    print(f"   Parquet records loaded: {parquet_total:,}")
    
    if csv_total != parquet_total:
        print(f"⚠️ Record count mismatch!")
        print(f"   Difference: {abs(csv_total - parquet_total):,} records")
        
        # Allow small differences due to filtering/errors
        diff_percentage = abs(csv_total - parquet_total) / max(csv_total, 1)
        if diff_percentage > 0.01:  # More than 1% difference
            print(f"❌ Record count difference too large: {diff_percentage:.2%}")
            print(f"   This suggests a data loading or conversion issue")
            return False
        else:
            print(f"✅ Record count difference acceptable: {diff_percentage:.3%}")
    else:
        print(f"✅ Record counts match perfectly!")
    
    # Validate data types
    expected_types = {
        'timestamp': 'datetime64',
        'record_type': 'object',
        'market_data_type': ['int64', 'int32'],
        'price': 'float64',
        'volume': ['int64', 'int32', 'float64']
    }
    
    for col, expected_type in expected_types.items():
        if col in data.columns:
            actual_type = str(data[col].dtype)
            if isinstance(expected_type, list):
                type_ok = any(expected in actual_type for expected in expected_type)
            else:
                type_ok = expected_type in actual_type
            
            status = "✅" if type_ok else "⚠️"
            print(f"   {status} {col}: {actual_type}")
    
    # Final summary
    print(f"\n🎉 CONVERSION COMPLETE!")
    print(f"   ✅ CSV file validated: {csv_total:,} records")
    print(f"   ✅ Parquet conversion: {parquet_total:,} records")
    print(f"   ✅ DataLoader integration: Working")
    print(f"   ✅ Performance: {records_per_sec:,.0f} records/sec")
    print(f"   ✅ Compression: {(1-compression_ratio):.1%} size reduction")
    
    print(f"\n📁 Output files saved to: {parquet_output_dir}")
    print(f"   Use these files for future testing and development!")
    
    return True


if __name__ == "__main__":
    success = test_real_csv_to_parquet_conversion()
    exit(0 if success else 1)