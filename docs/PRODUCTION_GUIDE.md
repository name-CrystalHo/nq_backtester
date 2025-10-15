# Production Data Management Guide

The NQ Backtester includes a comprehensive production data management system that handles:

- **High-performance CSV to Parquet conversion** (556K+ records/sec)
- **Intelligent production storage organization** with auto-path detection
- **Efficient data loading** with partitioning and caching
- **Data validation and integrity checks**
- **Easy-to-use CLI and programmatic interfaces**

## Quick Start

### 1. Import Your NinjaTrader Data

**Interactive Mode (Recommended):**
```bash
# Interactive selection with data overview and options
python -m backtester.cli prod import-data

# This will show you:
# - All available instruments with file counts and sizes
# - Options to import all data or specific selections
# - Performance estimates and recommendations
```

**Direct Commands:**
```bash
# Import specific instrument
python -m backtester.cli prod import-data --instrument "NQ SEP25"

# Import by pattern (all 2025 contracts)
python -m backtester.cli prod import-data --instrument "25"

# Import everything with maximum performance
python -m backtester.cli prod import-data --workers 22 --no-interactive
```

### 2. View Available Data

```bash
# Show overview of production data
python -m backtester.cli prod show

# Show detailed storage statistics  
python -m backtester.cli prod stats

# Validate data integrity
python -m backtester.cli prod validate
```

### 3. Load Data for Backtesting

```bash
# Load and preview specific instrument/date
python -m backtester.cli prod load NQ_SEP25 --date 20250330

# Load all available data for instrument
python -m backtester.cli prod load NQ_SEP25
```

## Programmatic Interface

### Basic Usage

```python
from src.backtester.data import ProductionDataManager, quick_load_data, show_available_data

# Quick data overview
show_available_data()

# Quick data loading
data = quick_load_data("NQ_SEP25", "20250330")  # Specific date
data = quick_load_data("NQ_SEP25")              # All dates

print(f"Loaded {len(data):,} tick records")
```

### Advanced Usage

```python
from src.backtester.data import ProductionDataManager

# Initialize production manager
manager = ProductionDataManager()

# Import NinjaTrader data
summary = manager.import_ninja_trader_data(
    ninja_trader_path="C:/NinjaTrader8/db/replay/csv",
    instrument_filter="NQ",  # Optional: filter by instrument
    max_workers=22,          # Optional: specify CPU cores
    skip_existing=True       # Optional: skip already converted files
)

print(f"Imported {summary['total_rows']:,} records")
print(f"Storage used: {summary['total_size_mb']:.2f} MB")

# Load data with filtering
data = manager.load_data(
    instrument="NQ_SEP25",
    start_date="20250328",
    end_date="20250330", 
    record_types=["L1"]  # Optional: filter by L1/L2 data
)

# Data validation
validation = manager.validate_data_integrity("NQ_SEP25")
print(f"Validation: {validation['validated_instruments']}/{validation['total_instruments']} OK")

# Storage statistics
stats = manager.get_storage_stats()
print(f"Total storage: {stats['total_size_gb']:.3f} GB")
```

## Storage Organization

The production system automatically organizes data in an optimized hierarchy:

```
storage/
├── processed/           # Parquet files (production data)
│   └── NQ_SEP25/       # Instrument name
│       └── year=2025/
│           └── month=03/
│               ├── 20250328.parquet
│               └── 20250330.parquet
└── raw/                # Raw CSV files (optional backup)
```

**Benefits:**
- **Partitioned by year/month** for efficient querying
- **89% compression ratio** vs CSV files
- **Auto-detection** of project paths
- **Separation** of production vs test data

## Performance Features

### Conversion Performance
- **556K+ records/sec** processing speed
- **Auto-scaling** to available CPU cores (24-core = 22 workers)
- **22.8 MB/s** throughput with 89% compression
- **Progress monitoring** with ETA and memory usage

### Loading Performance
- **Columnar Parquet format** optimized for analytics
- **Lazy loading** with automatic caching
- **Partitioned queries** for fast date range filtering
- **Memory-efficient chunking** for large datasets

### Production Features
- **Skip existing files** for incremental imports
- **Data validation** with integrity checks
- **Auto-path detection** across development environments
- **Storage statistics** and monitoring

## Data Validation

The system includes comprehensive validation:

```python
# Validate specific instrument
results = manager.validate_data_integrity("NQ_SEP25")

# Validate all instruments  
results = manager.validate_data_integrity()

print(f"Issues found: {len(results['issues'])}")
for issue in results['issues']:
    print(f"  - {issue}")
```

**Validation Checks:**
- Required columns present (`timestamp`, `record_type`, `price`, `volume`)
- Data structure consistency
- File integrity and accessibility
- Record type distribution (L1/L2)

## Integration with Backtesting

The production data integrates seamlessly with the backtesting engine:

```python
from src.backtester.data import quick_load_data
from src.backtester import Backtester
from src.backtester.strategies import SimpleMovingAverageStrategy

# Load production data
data = quick_load_data("NQ_SEP25", "20250330")

# Run backtest
strategy = SimpleMovingAverageStrategy(fast=10, slow=20)
backtester = Backtester(data, initial_capital=100000)

results = backtester.run(strategy)
print(f"Total return: {results.total_return:.2%}")
```

## Troubleshooting

### No Data Found
```bash
# Check if data directory exists and has content
python -m backtester.cli prod show

# Verify your NinjaTrader CSV path and reimport
python -m backtester.cli prod import-data "C:/correct/path/to/csv"
```

### Import Errors
```bash
# Validate source CSV files first
python -m backtester.cli validate "C:/path/to/csv/file.csv"

# Import with more verbose output
python -m backtester.cli prod import-data "C:/path" --instrument NQ
```

### Performance Issues
```bash
# Check storage stats
python -m backtester.cli prod stats

# Use fewer workers if memory constrained
python -m backtester.cli prod import-data "C:/path" --workers 8
```

### Data Integrity Issues
```bash
# Run full validation
python -m backtester.cli prod validate

# Reimport specific data if corrupted
python -m backtester.cli prod import-data "C:/path" --instrument NQ --overwrite
```

## Best Practices

### Data Import
1. **Import once, read many times** - Parquet optimized for read performance
2. **Use instrument filtering** for large datasets (`--instrument NQ`)
3. **Match worker count to CPU cores** for optimal performance
4. **Backup original CSV files** before conversion

### Data Loading  
1. **Use date range filtering** for large backtests
2. **Filter by record type** if only L1 or L2 needed
3. **Load in chunks** for memory-constrained environments
4. **Cache frequently used datasets**

### Production Deployment
1. **Separate test and production data** (automatic with this system)
2. **Monitor storage usage** with `prod stats`
3. **Validate data integrity** regularly with `prod validate`
4. **Use CLI for automation** and scripting

## API Reference

### ProductionDataManager

| Method | Description |
|--------|-------------|
| `import_ninja_trader_data()` | Import CSV files to Parquet |
| `load_data()` | Load tick data for backtesting |
| `get_data_overview()` | Get summary of available data |
| `validate_data_integrity()` | Check data integrity |
| `get_storage_stats()` | Get detailed storage statistics |

### Quick Functions

| Function | Description |
|----------|-------------|
| `show_available_data()` | Print data overview |
| `quick_load_data()` | Load data quickly |
| `get_production_data_manager()` | Get manager instance |

### CLI Commands

| Command | Description |
|---------|-------------|
| `prod show` | Show data overview |
| `prod load` | Load and preview data |
| `prod stats` | Show storage statistics |
| `prod validate` | Validate data integrity |
| `prod import-data` | Import NinjaTrader CSV files |

---

**Ready to start backtesting with production-grade data management!** 🚀