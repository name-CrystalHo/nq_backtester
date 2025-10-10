"""
Data Loader - Efficient tick data retrieval from Parquet files

Provides optimized data loading with partitioning support, lazy loading,
and memory-efficient chunking for high-performance backtesting.
"""

import pandas as pd
from pathlib import Path
from datetime import datetime, date
from typing import Dict, List, Optional, Union, Tuple, Generator
import logging
from functools import lru_cache

logger = logging.getLogger(__name__)


class DataLoader:
    """
    Efficient loader for partitioned Parquet tick data.
    
    Supports querying by instrument, date ranges, and record types
    with optimized performance through partitioning and caching.
    """
    
    def __init__(self, data_dir: str = None):
        """
        Initialize data loader.
        
        Args:
            data_dir: Base directory containing partitioned Parquet files
                     If None, auto-detects production storage directory
        """
        if data_dir is None:
            # Auto-detect production storage directory
            project_root = Path(__file__).parent.parent.parent
            data_dir = project_root / "storage" / "processed"
            logger.info(f"Using production storage directory: {data_dir}")
        
        self.data_dir = Path(data_dir)
        self._instrument_cache = None
        
        if not self.data_dir.exists():
            logger.warning(f"Data directory does not exist: {data_dir}")
            logger.info(f"Run the converter first to populate data: python -m backtester.data.converter convert --source YOUR_CSV_PATH")
    
    def get_available_instruments(self) -> List[str]:
        """
        Get list of all available instruments.
        
        Returns:
            List of instrument names (e.g., ['NQ_JUN21', 'ES_MAR22'])
        """
        if self._instrument_cache is not None:
            return self._instrument_cache
        
        instruments = []
        try:
            for item in self.data_dir.iterdir():
                if item.is_dir() and not item.name.startswith('.'):
                    instruments.append(item.name)
        except OSError as e:
            logger.error(f"Error reading data directory: {e}")
            return []
        
        instruments.sort()
        self._instrument_cache = instruments
        return instruments
    
    def get_available_dates(self, instrument: str) -> List[str]:
        """
        Get list of available dates for an instrument.
        
        Args:
            instrument: Instrument name (e.g., 'NQ_JUN21')
        
        Returns:
            List of date strings in YYYYMMDD format, sorted chronologically
        """
        instrument_dir = self.data_dir / instrument
        if not instrument_dir.exists():
            logger.warning(f"Instrument directory not found: {instrument}")
            return []
        
        dates = []
        try:
            # Walk through year=YYYY/month=MM structure
            for year_dir in instrument_dir.iterdir():
                if not year_dir.is_dir() or not year_dir.name.startswith('year='):
                    continue
                    
                for month_dir in year_dir.iterdir():
                    if not month_dir.is_dir() or not month_dir.name.startswith('month='):
                        continue
                    
                    # Find all Parquet files and extract dates
                    for parquet_file in month_dir.glob('*.parquet'):
                        date_str = parquet_file.stem  # Remove .parquet extension
                        if len(date_str) == 8 and date_str.isdigit():
                            dates.append(date_str)
                            
        except OSError as e:
            logger.error(f"Error reading instrument directory {instrument}: {e}")
            return []
        
        return sorted(list(set(dates)))  # Remove duplicates and sort
    
    def _get_file_path(self, instrument: str, date_str: str) -> Optional[Path]:
        """
        Get file path for specific instrument and date.
        
        Args:
            instrument: Instrument name
            date_str: Date in YYYYMMDD format
        
        Returns:
            Path to Parquet file, or None if not found
        """
        if len(date_str) != 8 or not date_str.isdigit():
            logger.error(f"Invalid date format: {date_str}. Expected YYYYMMDD")
            return None
        
        year = date_str[:4]
        month = date_str[4:6]
        
        file_path = (self.data_dir / instrument / f"year={year}" / 
                     f"month={month}" / f"{date_str}.parquet")
        
        return file_path if file_path.exists() else None
    
    def load_day(self, instrument: str, date_str: str, 
                 record_types: Optional[List[str]] = None,
                 time_range: Optional[Tuple[str, str]] = None) -> pd.DataFrame:
        """
        Load all tick data for a single day.
        
        Args:
            instrument: Instrument name (e.g., 'NQ_JUN21')
            date_str: Date in YYYYMMDD format
            record_types: Filter by record types ['L1', 'L2'], or None for both
            time_range: Optional (start_time, end_time) in 'HH:MM:SS' format
        
        Returns:
            DataFrame with tick data, sorted by timestamp
        """
        file_path = self._get_file_path(instrument, date_str)
        if file_path is None:
            logger.warning(f"No data file found for {instrument} on {date_str}")
            return pd.DataFrame()
        
        try:
            # Load Parquet file
            df = pd.read_parquet(file_path)
            
            if df.empty:
                logger.warning(f"Empty data file: {file_path}")
                return df
            
            # Filter by record types
            if record_types:
                df = df[df['record_type'].isin(record_types)]
            
            # Filter by time range
            if time_range:
                start_time, end_time = time_range
                try:
                    # Convert to time objects for comparison
                    start_dt = datetime.strptime(f"{date_str} {start_time}", "%Y%m%d %H:%M:%S")
                    end_dt = datetime.strptime(f"{date_str} {end_time}", "%Y%m%d %H:%M:%S")
                    
                    # Filter timestamps
                    mask = (df['timestamp'] >= start_dt) & (df['timestamp'] <= end_dt)
                    df = df[mask]
                    
                except ValueError as e:
                    logger.error(f"Invalid time range format: {time_range}, error: {e}")
            
            # Ensure chronological order
            df = df.sort_values('timestamp').reset_index(drop=True)
            
            logger.debug(f"Loaded {len(df)} records for {instrument} on {date_str}")
            return df
            
        except Exception as e:
            logger.error(f"Error loading data from {file_path}: {e}")
            return pd.DataFrame()
    
    def load_range(self, instrument: str, start_date: str, end_date: str,
                   record_types: Optional[List[str]] = None,
                   chunk_size: Optional[int] = None) -> Union[pd.DataFrame, Generator[pd.DataFrame, None, None]]:
        """
        Load tick data for a date range.
        
        Args:
            instrument: Instrument name
            start_date: Start date in YYYYMMDD format (inclusive)
            end_date: End date in YYYYMMDD format (inclusive)
            record_types: Filter by record types ['L1', 'L2'], or None for both
            chunk_size: If specified, load in chunks (memory optimization)
        
        Returns:
            DataFrame with combined tick data from all dates
        """
        available_dates = self.get_available_dates(instrument)
        if not available_dates:
            logger.warning(f"No dates available for instrument: {instrument}")
            return pd.DataFrame()
        
        # Filter dates within range
        date_range = [d for d in available_dates if start_date <= d <= end_date]
        
        if not date_range:
            logger.warning(f"No data found for {instrument} between {start_date} and {end_date}")
            return pd.DataFrame()
        
        logger.info(f"Loading {len(date_range)} days for {instrument}: {date_range[0]} to {date_range[-1]}")
        
        # Load data day by day
        dataframes = []
        for date_str in date_range:
            day_data = self.load_day(instrument, date_str, record_types)
            if not day_data.empty:
                dataframes.append(day_data)
            
            # Memory management for large ranges
            if chunk_size and len(dataframes) >= chunk_size:
                # Combine and yield chunk
                chunk_df = pd.concat(dataframes, ignore_index=True)
                chunk_df = chunk_df.sort_values('timestamp').reset_index(drop=True)
                dataframes = []  # Clear memory
                yield chunk_df
        
        # Return combined DataFrame or final chunk
        if dataframes:
            combined_df = pd.concat(dataframes, ignore_index=True)
            combined_df = combined_df.sort_values('timestamp').reset_index(drop=True)
            
            if chunk_size:
                yield combined_df
            else:
                return combined_df
        else:
            return pd.DataFrame()
    
    def load_time_window(self, instrument: str, date_str: str, 
                        start_time: str, end_time: str,
                        record_types: Optional[List[str]] = None) -> pd.DataFrame:
        """
        Load data for specific time window within a day.
        
        Args:
            instrument: Instrument name
            date_str: Date in YYYYMMDD format
            start_time: Start time in 'HH:MM:SS' format
            end_time: End time in 'HH:MM:SS' format
            record_types: Filter by record types
        
        Returns:
            DataFrame with filtered tick data
        """
        return self.load_day(
            instrument=instrument,
            date_str=date_str, 
            record_types=record_types,
            time_range=(start_time, end_time)
        )
    
    @lru_cache(maxsize=32)
    def get_date_summary(self, instrument: str, date_str: str) -> Dict:
        """
        Get summary statistics for a specific date (cached).
        
        Args:
            instrument: Instrument name
            date_str: Date in YYYYMMDD format
        
        Returns:
            Dictionary with summary statistics
        """
        df = self.load_day(instrument, date_str)
        
        if df.empty:
            return {
                'date': date_str,
                'total_records': 0,
                'l1_records': 0,
                'l2_records': 0,
                'first_timestamp': None,
                'last_timestamp': None,
                'price_range': None,
                'total_volume': 0
            }
        
        l1_count = (df['record_type'] == 'L1').sum()
        l2_count = (df['record_type'] == 'L2').sum()
        
        return {
            'date': date_str,
            'total_records': len(df),
            'l1_records': int(l1_count),
            'l2_records': int(l2_count),
            'first_timestamp': df['timestamp'].min(),
            'last_timestamp': df['timestamp'].max(),
            'price_range': (df['price'].min(), df['price'].max()),
            'total_volume': int(df['volume'].sum())
        }
    
    def get_instrument_summary(self, instrument: str, 
                              max_dates: Optional[int] = None) -> Dict:
        """
        Get summary for entire instrument.
        
        Args:
            instrument: Instrument name
            max_dates: Limit analysis to most recent N dates
        
        Returns:
            Dictionary with instrument summary
        """
        available_dates = self.get_available_dates(instrument)
        
        if not available_dates:
            return {
                'instrument': instrument,
                'available_dates': 0,
                'date_range': None,
                'total_records': 0,
                'l1_records': 0,
                'l2_records': 0
            }
        
        # Limit to recent dates if specified
        if max_dates and len(available_dates) > max_dates:
            available_dates = available_dates[-max_dates:]
        
        # Aggregate statistics
        total_records = 0
        total_l1 = 0
        total_l2 = 0
        
        for date_str in available_dates:
            summary = self.get_date_summary(instrument, date_str)
            total_records += summary['total_records']
            total_l1 += summary['l1_records']
            total_l2 += summary['l2_records']
        
        return {
            'instrument': instrument,
            'available_dates': len(available_dates),
            'date_range': (available_dates[0], available_dates[-1]),
            'total_records': total_records,
            'l1_records': total_l1,
            'l2_records': total_l2,
            'analyzed_dates': len(available_dates)
        }
    
    def clear_cache(self):
        """Clear internal caches."""
        self._instrument_cache = None
        self.get_date_summary.cache_clear()
    
    def validate_data_integrity(self, instrument: str, date_str: str) -> Dict:
        """
        Validate data integrity for a specific date.
        
        Args:
            instrument: Instrument name
            date_str: Date to validate
        
        Returns:
            Dictionary with validation results
        """
        df = self.load_day(instrument, date_str)
        
        if df.empty:
            return {
                'valid': False,
                'errors': ['No data found'],
                'warnings': []
            }
        
        errors = []
        warnings = []
        
        # Check timestamp monotonicity
        if not df['timestamp'].is_monotonic_increasing:
            errors.append("Timestamps are not in chronological order")
        
        # Check for missing required fields
        for col in ['record_type', 'market_data_type', 'price', 'volume']:
            if df[col].isna().any():
                errors.append(f"Missing values in column: {col}")
        
        # Check for negative prices/volumes
        if (df['price'] < 0).any():
            warnings.append("Negative prices found")
            
        if (df['volume'] < 0).any():
            warnings.append("Negative volumes found")
        
        # Check record type distribution
        l1_pct = (df['record_type'] == 'L1').mean() * 100
        l2_pct = (df['record_type'] == 'L2').mean() * 100
        
        if l1_pct < 1:
            warnings.append("Very few L1 records (<1%)")
        if l2_pct < 1:
            warnings.append("Very few L2 records (<1%)")
        
        return {
            'valid': len(errors) == 0,
            'errors': errors,
            'warnings': warnings,
            'l1_percentage': l1_pct,
            'l2_percentage': l2_pct,
            'total_records': len(df)
        }