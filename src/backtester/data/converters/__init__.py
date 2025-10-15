"""Data converters for NinjaTrader CSV tick data."""

from .base import BaseConverter, TickDataConverter, CSVConverter
from .csv_to_parquet import CSVToParquetConverter
from .parquet_to_csv import ParquetToCSVConverter

__all__ = [
    # Base classes
    'BaseConverter',
    'TickDataConverter', 
    'CSVConverter',
    
    # Concrete converters
    'CSVToParquetConverter',
    'ParquetToCSVConverter',
]

# Convenience factory functions
def create_csv_converter(**kwargs) -> CSVToParquetConverter:
    """Create CSV to Parquet converter with default settings."""
    return CSVToParquetConverter(**kwargs)

# Converter registry
CONVERTER_REGISTRY = {
    'csv_to_parquet': CSVToParquetConverter,
    'parquet_to_csv': ParquetToCSVConverter,
}

def get_converter(converter_type: str, **kwargs):
    """
    Get converter instance by type.
    
    Args:
        converter_type: Type of converter ('csv_to_parquet', 'parquet_to_csv')
        **kwargs: Arguments to pass to converter constructor
        
    Returns:
        Converter instance
        
    Raises:
        ValueError: If converter type is not recognized
    """
    if converter_type not in CONVERTER_REGISTRY:
        available = ', '.join(CONVERTER_REGISTRY.keys())
        raise ValueError(f"Unknown converter type '{converter_type}'. Available: {available}")
    
    converter_class = CONVERTER_REGISTRY[converter_type]
    return converter_class(**kwargs)