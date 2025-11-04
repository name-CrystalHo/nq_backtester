# Known Working Tests

After reorganization, these tests are confirmed working:

## ✅ Core Backtester Tests (Fast - ~3s) - **ALL TESTS NOW PASSING!**
```bash
pytest tests/unit/engine/test_backtester.py tests/integration/test_backtester_integration.py -v
```
**Results:** 23 passed (including 5 previously skipped end-to-end tests) in ~3s

**Previously Skipped Tests Now Working:**
- ✅ `test_end_to_end_wicktest_backtest` - Full backtest with real data (50,509 ticks/sec)
- ✅ `test_configuration_validation` - Tests various config options with real data
- ✅ `test_invalid_strategy_handling` - Error handling validation
- ✅ `test_specific_bar_aggregation_july1_1010am` - Validates specific bar from 14M+ ticks
- ✅ `test_invalid_data_file_handling` - File error handling

**Test Data Location:** `tests/unit/storage/parquet/NQ SEP25/`
- `20250327.parquet`, `20250501.parquet`, `20250701.parquet` (copied from production data)

## ✅ Core Module Tests (Fast - ~0.2s)
```bash
pytest tests/unit/core/ -v
```
**Results:** 95 passed in 0.18s

## ✅ Data Processing Tests (Medium - ~10s)
```bash
pytest tests/unit/strategies/test_wicktest.py tests/unit/data/converters/ tests/unit/data/loaders/ -v
```
**Results:** 91 passed in 10.45s

## ✅ Bar Aggregator Tests
```bash
pytest tests/unit/engine/test_bar_aggregator.py -v
```

## ✅ Integration Tests
```bash
pytest tests/integration/test_backtester_integration.py tests/integration/test_bar_aggregation_integration.py tests/integration/test_converter_roundtrip.py -v
```

---

## ⚠️ Tests with Import Issues (Need Fixing)

These tests have import errors and need to be updated or removed:

- `tests/unit/cli/` - imports non-existent `backtester.cli.commands` module
- `tests/unit/data/test_converter.py` - imports non-existent `parse_timestamp` function
- `tests/unit/data/test_core_conversion.py` - imports from `src.backtester` incorrectly
- `tests/unit/integration/test_multi_strategy_backtester.py` - imports non-existent `PortfolioConfig`
- `tests/unit/integration/test_strategy_adapter.py` - imports non-existent `universal_adapter` module
- `tests/unit/integration/test_execution_bridge.py` - imports from `src.backtester`
- `tests/unit/strategies/test_registry.py` - imports non-existent `backtester.strategies.registry`
- `tests/integration/test_production_system.py` - imports from `src.backtester`

---

## Quick Test Commands

### Run all working tests:
```bash
pytest tests/unit/core/ tests/unit/engine/test_backtester.py tests/unit/engine/test_bar_aggregator.py tests/unit/strategies/test_wicktest.py tests/unit/data/converters/ tests/unit/data/loaders/ tests/integration/test_backtester_integration.py tests/integration/test_bar_aggregation_integration.py tests/integration/test_converter_roundtrip.py -v
```

### Run fast tests only (core functionality):
```bash
pytest tests/unit/core/ tests/unit/engine/ tests/integration/test_backtester_integration.py -v
```
**Expected:** 121 tests passing in ~3 seconds (all previously skipped tests now included!)

### Run with coverage:
```bash
pytest tests/unit/engine/test_backtester.py --cov=backtester.engine.backtester --cov-report=term-missing
```
