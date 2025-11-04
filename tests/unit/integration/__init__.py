"""
Integration tests package for the universal strategy architecture.

This package contains comprehensive unit tests for:
- StrategyRegistry: Strategy registration, factory pattern, parameter validation
- StrategyBacktesterAdapter: Signal processing, order handling, performance tracking  
- MultiStrategyBacktester: Portfolio execution, capital allocation, correlation analysis

Test Coverage:
- Strategy registration and discovery
- Parameter validation and error handling
- Signal-to-order translation
- Position size management and risk controls
- Multi-strategy coordination and performance comparison
- Error handling and edge cases
- Configuration management and customization
- Performance statistics and reporting

Usage:
    Run all integration tests:
        python -m pytest tests/unit/integration/ -v
    
    Run specific test modules:
        python -m pytest tests/unit/integration/test_strategy_registry.py -v
        python -m pytest tests/unit/integration/test_strategy_adapter.py -v  
        python -m pytest tests/unit/integration/test_multi_strategy_backtester.py -v
"""

# Test module exports for easier importing  
try:
    from .test_universal_architecture import *
except ImportError:
    pass

__all__ = [
    # Universal Architecture Tests
    'TestStrategyRegistry',
    'TestUniversalAdapter', 
    'TestOrderSignal',
    'TestAdapterConfig',
    'TestIntegration'
]