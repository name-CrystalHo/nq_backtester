"""Base converter classes for data format conversion."""

from abc import ABC, abstractmethod
from pathlib import Path
from typing import Dict, Any, Optional, List
import logging
from datetime import datetime

from ...core import (
    DataError, ConversionError, DataValidationError, InstrumentId,
    DEFAULT_CHUNK_SIZE
)

logger = logging.getLogger(__name__)


class BaseConverter(ABC):
    """Base class for all data converters."""
    
    def __init__(self, chunk_size: int = DEFAULT_CHUNK_SIZE):
        """Initialize converter with chunk size for memory management."""
        self.chunk_size = chunk_size
        self.logger = logging.getLogger(self.__class__.__name__)
    
    @abstractmethod
    def convert(self, input_path: Path, output_path: Path, **kwargs) -> Dict[str, Any]:
        """
        Convert data from input format to output format.
        
        Args:
            input_path: Path to input file
            output_path: Path to output file
            **kwargs: Additional conversion parameters
            
        Returns:
            Dict with conversion statistics and status
        """
        pass
    
    @abstractmethod
    def validate_input(self, input_path: Path) -> Dict[str, Any]:
        """
        Validate input file format and structure.
        
        Args:
            input_path: Path to input file
            
        Returns:
            Dict with validation results
        """
        pass
    
    def extract_instrument_info(self, file_path: Path) -> tuple[str, str, str]:
        """
        Extract instrument name, year, and month from file path.
        
        Expected structure for NinjaTrader files:
        - CSV: C:\\...\\replay.csv\\NQ JUN21\\20211119.csv
        - NRD: C:\\...\\replay\\NQ JUN21\\20211119.nrd
        
        Returns:
            (instrument_name, year, month) e.g., ('NQ_JUN21', '2021', '11')
        """
        # Get instrument from parent directory, replace spaces with underscores
        instrument = file_path.parent.name.replace(' ', '_')
        
        # Extract year and month from filename (YYYYMMDD format)
        filename = file_path.stem
        if len(filename) >= 8 and filename[:8].isdigit():
            year = filename[:4]
            month = filename[4:6]
        else:
            # Fallback to current date if filename format is unexpected
            current = datetime.now()
            year = str(current.year)
            month = f"{current.month:02d}"
            self.logger.warning(f"Unexpected filename format: {filename}, using {year}-{month}")
        
        return instrument, year, month
    
    def create_output_path(self, input_path: Path, output_base_dir: Path, 
                          extension: str = ".parquet") -> Path:
        """
        Create output path with partitioned structure.
        
        Args:
            input_path: Path to input file
            output_base_dir: Base output directory
            extension: File extension for output
            
        Returns:
            Path to output file with partitioned structure
        """
        instrument, year, month = self.extract_instrument_info(input_path)
        date_part = input_path.stem
        
        # Create partitioned directory structure
        output_dir = output_base_dir / instrument / f"year={year}" / f"month={month}"
        output_path = output_dir / f"{date_part}{extension}"
        
        return output_path
    
    def should_skip_existing(self, output_path: Path, skip_existing: bool = True) -> bool:
        """Check if conversion should be skipped for existing files."""
        if skip_existing and output_path.exists():
            self.logger.info(f"Skipping existing file: {output_path}")
            return True
        return False
    
    def create_result_dict(self, status: str, input_file: Path, 
                          rows: int = 0, size_mb: float = 0.0, 
                          error: Optional[str] = None, **kwargs) -> Dict[str, Any]:
        """Create standardized result dictionary."""
        result = {
            'file': str(input_file),
            'status': status,
            'rows': rows,
            'size_mb': size_mb,
            'error': error,
            'timestamp': datetime.now().isoformat()
        }
        result.update(kwargs)
        return result


class TickDataConverter(BaseConverter):
    """Base class for tick data converters."""
    
    def validate_tick_data(self, data_stats: Dict[str, Any]) -> bool:
        """
        Validate tick data statistics.
        
        Args:
            data_stats: Dictionary with data statistics
            
        Returns:
            True if validation passes
        """
        # Check for reasonable record counts
        total_records = data_stats.get('total_records', 0)
        l1_records = data_stats.get('l1_records', 0)
        l2_records = data_stats.get('l2_records', 0)
        
        if total_records == 0:
            raise ConversionError("No valid tick data records found")
        
        if l1_records == 0 and l2_records == 0:
            raise ConversionError("No L1 or L2 tick data records found")
        
        # Check for reasonable L1/L2 ratio (L1 should be majority)
        if total_records > 1000 and l1_records < total_records * 0.1:
            self.logger.warning(f"Low L1 record ratio: {l1_records}/{total_records}")
        
        return True


class CSVConverter(TickDataConverter):
    """Base class for CSV data converters."""
    
    def __init__(self, chunk_size: int = DEFAULT_CHUNK_SIZE):
        """Initialize CSV converter."""
        super().__init__(chunk_size)
        self.csv_base_path = Path("C:/Users/cryst/Documents/NinjaTrader 8/db/replay.csv")
    
    def validate_input(self, input_path: Path) -> Dict[str, Any]:
        """Validate CSV file format and structure."""
        try:
            if not input_path.exists():
                return {
                    'valid': False,
                    'errors': [f"File does not exist: {input_path}"]
                }
            
            if input_path.suffix.lower() != '.csv':
                return {
                    'valid': False,
                    'errors': [f"File is not a CSV file: {input_path}"]
                }
            
            file_size = input_path.stat().st_size
            if file_size == 0:
                return {
                    'valid': True,  # Empty files are valid (market holidays)
                    'errors': [],
                    'warnings': ['File is empty - likely market holiday or weekend'],
                    'file_size_bytes': file_size,
                    'estimated_records': 0
                }
            
            # Quick validation - read first few lines
            try:
                with open(input_path, 'r', encoding='utf-8-sig') as f:
                    first_lines = [f.readline().strip() for _ in range(min(5, 100))]
                    
                valid_lines = 0
                for line in first_lines:
                    if line and ';' in line:
                        parts = line.split(';')
                        if len(parts) >= 6 and parts[0] in ['L1', 'L2']:
                            valid_lines += 1
                
                if valid_lines == 0 and first_lines:
                    return {
                        'valid': False,
                        'errors': ['No valid L1/L2 records found in first 5 lines']
                    }
                    
            except UnicodeDecodeError:
                return {
                    'valid': False,
                    'errors': ['File encoding error - unable to read as UTF-8']
                }
            
            return {
                'valid': True,
                'errors': [],
                'file_size_bytes': file_size,
                'estimated_records': file_size // 50  # Rough estimate
            }
            
        except Exception as e:
            return {
                'valid': False,
                'errors': [f"Validation error: {str(e)}"]
            }
    
    def find_csv_files(self, instrument_filter: Optional[str] = None) -> List[Path]:
        """
        Find CSV files in the standard NinjaTrader location.
        
        Args:
            instrument_filter: Optional instrument filter pattern
            
        Returns:
            List of CSV file paths
        """
        csv_files = []
        
        if not self.csv_base_path.exists():
            self.logger.warning(f"CSV base path does not exist: {self.csv_base_path}")
            return csv_files
        
        # Find all .csv files
        for csv_file in self.csv_base_path.rglob("*.csv"):
            if instrument_filter:
                instrument = csv_file.parent.name
                if instrument_filter.upper() not in instrument.upper():
                    continue
            csv_files.append(csv_file)
        
        return sorted(csv_files)