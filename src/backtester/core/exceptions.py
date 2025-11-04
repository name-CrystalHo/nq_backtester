"""Custom exceptions for the backtester."""


class BacktesterError(Exception):
    """Base exception for all backtester errors."""
    pass


class DataError(BacktesterError):
    """Data-related errors."""
    pass


class DataLoadError(DataError):
    """Error loading data."""
    pass


class DataValidationError(DataError):
    """Data validation error."""
    pass


class ConversionError(DataError):
    """Data conversion error."""
    pass


class SchemaError(DataError):
    """Schema validation error."""
    pass


class OrderError(BacktesterError):
    """Order-related errors."""
    pass


class InvalidOrderError(OrderError):
    """Invalid order parameters."""
    pass


class InsufficientFundsError(OrderError):
    """Insufficient funds for order."""
    pass


class OrderNotFoundError(OrderError):
    """Order not found."""
    pass


class ExecutionError(BacktesterError):
    """Order execution and position management errors."""
    pass


class PositionError(BacktesterError):
    """Position-related errors."""
    pass


class StrategyError(BacktesterError):
    """Strategy-related errors."""
    pass


class StrategyNotFoundError(StrategyError):
    """Strategy not found."""
    pass


class IndicatorError(StrategyError):
    """Indicator calculation error."""
    pass


class MetricsError(BacktesterError):
    """Metrics calculation error."""
    pass


class ConfigError(BacktesterError):
    """Configuration error."""
    pass


class OptimizationError(BacktesterError):
    """Optimization error."""
    pass


class VisualizationError(BacktesterError):
    """Visualization error."""
    pass