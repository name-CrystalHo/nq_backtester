# Test Structure

This directory contains all tests for the NQ Backtester project, organized to mirror the source code structure.

## Directory Layout

```
tests/
├── conftest.py              # Shared pytest fixtures and configuration
├── unit/                    # Unit tests (mirror backtester/ structure)
│   ├── cli/                # Tests for CLI commands
│   ├── core/               # Tests for core functionality
│   ├── data/               # Tests for data modules
│   │   ├── test_converter.py
│   │   └── test_core_conversion.py
│   ├── engine/             # Tests for backtesting engine
│   │   ├── test_backtester.py
│   │   └── test_bar_aggregator.py
│   ├── integration/        # Tests for integration modules
│   ├── metrics/            # Tests for performance metrics
│   ├── strategies/         # Tests for trading strategies
│   └── ...
├── integration/            # Integration tests (end-to-end)
│   ├── test_backtester_integration.py
│   ├── test_production_system.py
│   └── ...
└── performance/            # Performance/benchmark tests
```

## Running Tests

### Run all tests
```bash
python -m pytest tests/
```

### Run unit tests only
```bash
python -m pytest tests/unit/
```

### Run integration tests only
```bash
python -m pytest tests/integration/
```

### Run specific test file
```bash
python -m pytest tests/unit/engine/test_backtester.py -v
```

### Run with coverage
```bash
python -m pytest tests/ --cov=backtester --cov-report=html
```

## Test Organization Principles

1. **Unit tests** (`tests/unit/`) mirror the `backtester/` package structure
   - Each module in `backtester/` has a corresponding test file in `tests/unit/`
   - Example: `backtester/engine/backtester.py` → `tests/unit/engine/test_backtester.py`

2. **Integration tests** (`tests/integration/`) test interactions between components
   - End-to-end workflows
   - Multi-module interactions
   - Production system tests

3. **Performance tests** (`tests/performance/`) benchmark critical paths
   - Data loading performance
   - Backtesting speed
   - Memory usage

## Import Handling

All test files should import from `backtester` package directly:

```python
from backtester.engine.backtester import Backtester
from backtester.strategies.base_strategy import BaseStrategy
```

The `conftest.py` file automatically adds the project root to `sys.path`, so manual path manipulation is not needed in individual test files.

## Writing New Tests

When adding a new module to `backtester/`, create a corresponding test file:

1. Determine the module location: `backtester/<subpackage>/<module>.py`
2. Create test file: `tests/unit/<subpackage>/test_<module>.py`
3. Use standard pytest conventions (`test_*` functions/methods)
4. Import directly from `backtester` package

Example:
```python
# tests/unit/engine/test_new_module.py
import pytest
from backtester.engine.new_module import NewClass

def test_new_functionality():
    obj = NewClass()
    assert obj.method() == expected_result
```
