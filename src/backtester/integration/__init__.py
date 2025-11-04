"""
Integration Module

This module provides adapters and interfaces for connecting
strategies to the backtesting engine.
"""

from .strategy_adapter import (
    StrategyBacktesterAdapter,
    OrderSignal,
    AdapterConfig,
    create_strategy_adapter
)

__all__ = [
    'StrategyBacktesterAdapter',
    'OrderSignal', 
    'AdapterConfig',
    'create_strategy_adapter'
]