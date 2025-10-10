"""
NQ Backtester - High-Performance Tick Data Backtesting Framework

Professional-grade Python backtester using full order book simulation
from NinjaTrader Market Replay data.
"""

__version__ = "0.1.0"

# Core components
from .engine.backtester import Backtester
from .data.loader import DataLoader
from .data.order_book import OrderBook
from .strategies.base_strategy import BaseStrategy
from .metrics.performance import PerformanceMetrics

__all__ = [
    "Backtester",
    "DataLoader", 
    "OrderBook",
    "BaseStrategy",
    "PerformanceMetrics",
]