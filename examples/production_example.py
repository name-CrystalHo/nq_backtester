"""
Production Data Management Example

This example demonstrates how to use the production data management features
of the NQ Backtester for real-world trading data workflows.
"""

from backtester.data import (
    ProductionDataManager, 
    get_production_data_manager,
    quick_load_data,
    show_available_data
)
import pandas as pd
from datetime import datetime


def example_production_workflow():
    """
    Complete example of production data workflow:
    1. Initialize production data manager
    2. Import NinjaTrader CSV data
    3. Validate data integrity
    4. Load data for backtesting
    """
    
    print("🚀 NQ Backtester Production Data Workflow Example")
    print("=" * 60)
    
    # 1. Initialize production data manager
    print("\n1️⃣ Initializing Production Data Manager...")
    manager = ProductionDataManager()
    
    # Show current storage stats
    stats = manager.get_storage_stats()
    print(f"   Storage location: {stats['storage_root']}")
    print(f"   Current size: {stats['total_size_gb']:.3f} GB")
    print(f"   Files: {stats['file_count']}")
    
    # 2. Check what data is available
    print("\n2️⃣ Checking Available Data...")
    overview = manager.get_data_overview()
    
    if overview['total_instruments'] == 0:
        print("   ⚠️ No data found in production storage")
        print("   📖 To import NinjaTrader data, use:")
        print('   manager.import_ninja_trader_data("C:/path/to/ninja/trader/csv")')
        
        # Show example with test data if available
        example_with_test_data()
        return
    
    print(f"   📊 Found {overview['total_instruments']} instruments")
    print(f"   💾 Total storage: {overview['total_size_mb']:.2f} MB")
    
    if overview['date_range']['start']:
        print(f"   📅 Date range: {overview['date_range']['start']} to {overview['date_range']['end']}")
    
    # Show details for each instrument
    for instrument, info in overview['instruments'].items():
        print(f"      {instrument}: {info['dates']} days, {info.get('size_mb', 0):.2f} MB")
    
    # 3. Validate data integrity
    print("\n3️⃣ Validating Data Integrity...")
    validation = manager.validate_data_integrity()
    
    print(f"   ✅ Validated: {validation['validated_instruments']}/{validation['total_instruments']} instruments")
    
    if validation['issues']:
        print(f"   ⚠️ Issues found: {len(validation['issues'])}")
        for issue in validation['issues'][:3]:  # Show first 3
            print(f"      - {issue}")
    
    # 4. Load data for backtesting
    print("\n4️⃣ Loading Data for Backtesting...")
    
    # Get first available instrument
    instruments = list(overview['instruments'].keys())
    if instruments:
        first_instrument = instruments[0]
        print(f"   📈 Loading data for: {first_instrument}")
        
        # Load sample data
        sample_data = manager.load_data(first_instrument)
        
        if not sample_data.empty:
            print(f"   📊 Loaded {len(sample_data):,} tick records")
            print(f"   🕐 Time range: {sample_data['timestamp'].min()} to {sample_data['timestamp'].max()}")
            
            # Show record type breakdown
            if 'record_type' in sample_data.columns:
                record_counts = sample_data['record_type'].value_counts()
                print(f"   📋 Record types:")
                for record_type, count in record_counts.items():
                    print(f"      {record_type}: {count:,} records")
            
            # Show sample of data
            print(f"\n   📄 Sample data:")
            print(sample_data.head(3).to_string(index=False))
        
        else:
            print("   ⚠️ No data loaded")


def example_with_test_data():
    """Example using test data if production data isn't available."""
    
    print("\n📝 Example with Test Data:")
    print("-" * 30)
    
    try:
        # Try to use test data
        from pathlib import Path
        test_data_path = Path("tests/test_data/parquet")
        
        if test_data_path.exists():
            # Initialize manager with test data
            manager = ProductionDataManager(str(test_data_path.parent))
            
            # Show what's in test storage
            test_overview = manager.get_data_overview()
            
            if test_overview['total_instruments'] > 0:
                print(f"   📊 Found test data: {test_overview['total_instruments']} instruments")
                
                # Load sample test data
                first_instrument = list(test_overview['instruments'].keys())[0]
                sample_data = manager.load_data(first_instrument)
                
                print(f"   📈 Test instrument: {first_instrument}")
                print(f"   📊 Records: {len(sample_data):,}")
                
                if not sample_data.empty:
                    print(f"   📄 Sample:")
                    print(sample_data.head(2).to_string(index=False))
            else:
                print("   ⚠️ No test data found either")
        else:
            print("   ⚠️ No test data directory found")
            
    except Exception as e:
        print(f"   ❌ Error with test data: {e}")


def example_data_import():
    """
    Example of importing NinjaTrader CSV data.
    
    NOTE: Uncomment and modify paths for your actual data location.
    """
    
    print("\n💾 Data Import Example (Template)")
    print("=" * 40)
    
    print("""
# To import your NinjaTrader CSV data:

from backtester.data import ProductionDataManager

# Initialize manager
manager = ProductionDataManager()

# Import NinjaTrader CSV files
# Replace with your actual NinjaTrader CSV path
ninja_trader_path = "C:/NinjaTrader8/db/replay/csv"

# Import all data
summary = manager.import_ninja_trader_data(ninja_trader_path)

# Or import specific instrument only
summary = manager.import_ninja_trader_data(
    ninja_trader_path, 
    instrument_filter="NQ"  # Only NQ futures
)

print(f"Imported {summary['processed']} files")
print(f"Total records: {summary['total_rows']:,}")
print(f"Storage used: {summary['total_size_mb']:.2f} MB")
""")


def example_quick_functions():
    """Example of using quick convenience functions."""
    
    print("\n⚡ Quick Function Examples")
    print("=" * 30)
    
    # Show available data
    print("1. Show available data:")
    print("   show_available_data()")
    
    print("\n2. Quick data loading:")
    print('   data = quick_load_data("NQ_SEP25", "20250330")')
    print('   data = quick_load_data("NQ_SEP25")  # All dates')
    
    # Try the actual functions if data exists
    try:
        show_available_data()
    except Exception as e:
        print(f"   (No data available: {e})")


def performance_tips():
    """Performance tips for production usage."""
    
    print("\n🚀 Performance Tips for Production")
    print("=" * 40)
    
    tips = [
        "1. Import data once, read many times - Parquet is optimized for read performance",
        "2. Use date range filtering when loading large datasets",
        "3. Filter by record_type if you only need L1 or L2 data", 
        "4. The loader automatically caches metadata for faster subsequent reads",
        "5. Storage is organized by instrument/year/month for efficient querying",
        "6. Consider loading data in chunks for very large backtests",
        "7. Use max_workers parameter in import to match your CPU cores"
    ]
    
    for tip in tips:
        print(f"   {tip}")


if __name__ == "__main__":
    # Run the complete example
    example_production_workflow()
    
    # Show import template
    example_data_import()
    
    # Show quick functions
    example_quick_functions()
    
    # Show performance tips
    performance_tips()
    
    print(f"\n✅ Production example complete!")
    print(f"📖 Ready to import your NinjaTrader data and start backtesting!")