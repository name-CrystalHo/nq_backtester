"""
Production Data Manager - High-level interface for NQ Backtester data operations

Provides a unified interface for:
- Converting NinjaTrader CSV to Parquet (production storage)
- Reading tick data efficiently from Parquet files
- Managing data storage and organization
- Data validation and integrity checks
"""

import pandas as pd
from pathlib import Path
from datetime import datetime, date
from typing import Dict, List, Optional, Union, Tuple, Generator
import logging
import os
from .converter import convert_csv_to_parquet, validate_csv_file
from .loader import DataLoader

logger = logging.getLogger(__name__)


class ProductionDataManager:
    """
    High-level data management for production NQ backtesting.
    
    Handles the complete data pipeline from NinjaTrader CSV files
    to optimized Parquet storage and efficient data retrieval.
    """
    
    def __init__(self, storage_root: str = None):
        """
        Initialize production data manager.
        
        Args:
            storage_root: Root storage directory (default: auto-detect ./storage/)
        """
        if storage_root is None:
            # Check for alternative storage locations if C: drive is full
            project_root = Path(__file__).parent.parent.parent
            default_storage = project_root / "storage"
            
            # Try alternative drives if default location has no space
            try:
                import shutil
                free_space_gb = shutil.disk_usage(str(default_storage.parent))[2] / (1024**3)
                if free_space_gb < 1.0:  # Less than 1GB free
                    # Try D: drive if it exists
                    alt_storage = Path("D:/nq_backtester_storage")
                    if Path("D:/").exists():
                        logger.warning(f"C: drive has only {free_space_gb:.1f}GB free, using D: drive")
                        storage_root = alt_storage
                    else:
                        logger.warning(f"Low disk space: {free_space_gb:.1f}GB free on C: drive")
                        storage_root = default_storage
                else:
                    storage_root = default_storage
            except Exception:
                storage_root = default_storage
        
        self.storage_root = Path(storage_root)
        self.processed_dir = self.storage_root / "processed"
        self.raw_dir = self.storage_root / "raw"
        
        # Create directories if they don't exist
        self.processed_dir.mkdir(parents=True, exist_ok=True)
        self.raw_dir.mkdir(parents=True, exist_ok=True)
        
        # Initialize data loader
        self.loader = DataLoader(str(self.processed_dir))
        
        logger.info(f"Production Data Manager initialized:")
        logger.info(f"  Storage root: {self.storage_root}")
        logger.info(f"  Processed data: {self.processed_dir}")
        logger.info(f"  Raw data: {self.raw_dir}")
    
    def import_ninja_trader_data(
        self, 
        ninja_trader_path: str = None,
        instrument_filter: str = None,
        max_workers: int = None,
        skip_existing: bool = True
    ) -> Dict:
        """
        Import NinjaTrader CSV data into production Parquet storage.
        
        Args:
            ninja_trader_path: Path to NinjaTrader CSV directory 
                              (default: C:/Users/cryst/Documents/NinjaTrader 8/db/replay.csv)
            instrument_filter: Only process specific instrument (e.g., "NQ")
            max_workers: Number of parallel workers (default: auto-detect)
            skip_existing: Skip files already converted
            
        Returns:
            Conversion summary statistics
        """
        # Auto-detect NinjaTrader path if not specified
        if ninja_trader_path is None:
            ninja_trader_path = r"C:\Users\cryst\Documents\NinjaTrader 8\db\replay.csv"
            logger.info(f"Using default NinjaTrader CSV directory: {ninja_trader_path}")
        
        logger.info(f"🚀 Starting NinjaTrader data import...")
        logger.info(f"   Source: {ninja_trader_path}")
        logger.info(f"   Destination: {self.processed_dir}")
        
        if instrument_filter:
            logger.info(f"   Filter: {instrument_filter}")
        
        # Validate source directory
        source_path = Path(ninja_trader_path)
        if not source_path.exists():
            raise FileNotFoundError(f"NinjaTrader source directory not found: {ninja_trader_path}")
        
        # Run conversion
        summary = convert_csv_to_parquet(
            source_dir=ninja_trader_path,
            output_dir=str(self.processed_dir),
            instrument_filter=instrument_filter,
            max_workers=max_workers,
            skip_existing=skip_existing,
            validate=True
        )
        
        # Update loader cache
        self.loader._instrument_cache = None
        
        logger.info(f"✅ Import complete:")
        logger.info(f"   Files processed: {summary['processed']}")
        logger.info(f"   Total records: {summary['total_rows']:,}")
        logger.info(f"   Storage used: {summary['total_size_mb']:.2f} MB")
        
        return summary
    
    def get_data_overview(self) -> Dict:
        """
        Get overview of available data in production storage.
        
        Returns:
            Dictionary with data statistics and availability
        """
        instruments = self.loader.get_available_instruments()
        
        overview = {
            'storage_root': str(self.storage_root),
            'processed_path': str(self.processed_dir),
            'instruments': {},
            'total_instruments': len(instruments),
            'total_size_mb': 0,
            'date_range': {'start': None, 'end': None}
        }
        
        all_dates = []
        
        for instrument in instruments:
            dates = self.loader.get_available_dates(instrument)
            if dates:
                overview['instruments'][instrument] = {
                    'dates': len(dates),
                    'date_range': f"{min(dates)} to {max(dates)}" if dates else "No dates",
                    'files': []
                }
                all_dates.extend(dates)
                
                # Calculate storage size for this instrument
                instrument_path = self.processed_dir / instrument
                if instrument_path.exists():
                    size_mb = sum(
                        f.stat().st_size for f in instrument_path.rglob("*.parquet")
                    ) / (1024 * 1024)
                    overview['instruments'][instrument]['size_mb'] = size_mb
                    overview['total_size_mb'] += size_mb
        
        if all_dates:
            overview['date_range'] = {
                'start': min(all_dates),
                'end': max(all_dates)
            }
        
        return overview
    
    def load_data(
        self,
        instrument: str,
        start_date: Union[str, date] = None,
        end_date: Union[str, date] = None,
        record_types: List[str] = None
    ) -> pd.DataFrame:
        """
        Load tick data for backtesting.
        
        Args:
            instrument: Instrument name (e.g., "NQ_SEP25")
            start_date: Start date (YYYYMMDD format or date object)
            end_date: End date (YYYYMMDD format or date object)
            record_types: Filter by record types ['L1', 'L2'] or None for all
            
        Returns:
            DataFrame with tick data
        """
        logger.info(f"📊 Loading data for {instrument}")
        
        if start_date and end_date:
            data = self.loader.load_range(instrument, start_date, end_date)
            logger.info(f"   Date range: {start_date} to {end_date}")
        elif start_date:
            # Single date
            data = self.loader.load_day(instrument, start_date)
            logger.info(f"   Single date: {start_date}")
        else:
            # All available data for instrument
            dates = self.loader.get_available_dates(instrument)
            if not dates:
                logger.warning(f"No data found for instrument: {instrument}")
                return pd.DataFrame()
            
            logger.info(f"   Loading all {len(dates)} available dates")
            data = self.loader.load_range(instrument, min(dates), max(dates))
        
        # Handle generator response (when chunked loading is used)
        if hasattr(data, '__next__'):
            # It's a generator, convert to DataFrame
            chunks = list(data)
            if chunks:
                data = pd.concat(chunks, ignore_index=True)
            else:
                data = pd.DataFrame()
        
        # Filter by record types if specified
        if record_types and not data.empty:
            data = data[data['record_type'].isin(record_types)]
            logger.info(f"   Filtered to record types: {record_types}")
        
        if hasattr(data, '__len__'):
            logger.info(f"   Loaded {len(data):,} records")
        return data
    
    def validate_data_integrity(self, instrument: str = None) -> Dict:
        """
        Validate data integrity in production storage.
        
        Args:
            instrument: Specific instrument to validate, or None for all
            
        Returns:
            Validation results
        """
        logger.info("🔍 Validating data integrity...")
        
        instruments = [instrument] if instrument else self.loader.get_available_instruments()
        
        results = {
            'total_instruments': len(instruments),
            'validated_instruments': 0,
            'issues': [],
            'summary': {}
        }
        
        for inst in instruments:
            try:
                dates = self.loader.get_available_dates(inst)
                if not dates:
                    results['issues'].append(f"No data found for {inst}")
                    continue
                
                # Load sample data to validate structure
                sample_data = self.loader.load_day(inst, dates[0])
                
                # Check required columns
                required_cols = ['timestamp', 'record_type', 'price', 'volume']
                missing_cols = [col for col in required_cols if col not in sample_data.columns]
                
                if missing_cols:
                    results['issues'].append(f"{inst}: Missing columns {missing_cols}")
                else:
                    results['validated_instruments'] += 1
                    results['summary'][inst] = {
                        'dates': len(dates),
                        'sample_records': len(sample_data),
                        'record_types': sample_data['record_type'].value_counts().to_dict() if 'record_type' in sample_data.columns else {}
                    }
                
            except Exception as e:
                results['issues'].append(f"{inst}: Validation error - {str(e)}")
        
        logger.info(f"✅ Validation complete: {results['validated_instruments']}/{results['total_instruments']} instruments valid")
        
        if results['issues']:
            logger.warning(f"⚠️ Found {len(results['issues'])} issues")
            for issue in results['issues'][:5]:  # Show first 5 issues
                logger.warning(f"   - {issue}")
        
        return results
    
    def get_storage_stats(self) -> Dict:
        """Get detailed storage statistics."""
        stats = {
            'storage_root': str(self.storage_root),
            'total_size_gb': 0,
            'file_count': 0,
            'instruments': {}
        }
        
        if self.processed_dir.exists():
            for instrument_dir in self.processed_dir.iterdir():
                if instrument_dir.is_dir():
                    parquet_files = list(instrument_dir.rglob("*.parquet"))
                    size_bytes = sum(f.stat().st_size for f in parquet_files)
                    size_gb = size_bytes / (1024**3)
                    
                    stats['instruments'][instrument_dir.name] = {
                        'files': len(parquet_files),
                        'size_gb': size_gb
                    }
                    
                    stats['total_size_gb'] += size_gb
                    stats['file_count'] += len(parquet_files)
        
        return stats
    
    def cleanup_storage(self, instrument: str = None, confirm: bool = False) -> bool:
        """
        Clean up storage (use with caution!).
        
        Args:
            instrument: Specific instrument to clean, or None for all
            confirm: Must be True to actually delete files
            
        Returns:
            True if cleanup performed
        """
        if not confirm:
            logger.warning("⚠️ Cleanup called without confirmation - no action taken")
            logger.info("   Use cleanup_storage(confirm=True) to actually delete files")
            return False
        
        logger.warning(f"🗑️ Cleaning up storage...")
        
        if instrument:
            instrument_path = self.processed_dir / instrument
            if instrument_path.exists():
                import shutil
                shutil.rmtree(instrument_path)
                logger.info(f"   Deleted: {instrument}")
        else:
            # Clean all processed data
            for item in self.processed_dir.iterdir():
                if item.is_dir():
                    import shutil
                    shutil.rmtree(item)
                    logger.info(f"   Deleted: {item.name}")
        
        # Clear cache
        self.loader._instrument_cache = None
        
        logger.warning("✅ Cleanup complete")
        return True


# Convenience functions for quick access
def get_production_data_manager() -> ProductionDataManager:
    """Get a production data manager instance."""
    return ProductionDataManager()


def quick_load_data(instrument: str, date: str = None) -> pd.DataFrame:
    """
    Quick function to load data for a specific instrument and date.
    
    Args:
        instrument: Instrument name (e.g., "NQ_SEP25")
        date: Date in YYYYMMDD format, or None for all available data
        
    Returns:
        DataFrame with tick data
    """
    manager = get_production_data_manager()
    return manager.load_data(instrument, date)


def show_available_data():
    """Print overview of available data in production storage."""
    manager = get_production_data_manager()
    overview = manager.get_data_overview()
    
    print(f"📊 NQ Backtester Production Data Overview")
    print(f"=" * 50)
    print(f"Storage: {overview['storage_root']}")
    print(f"Total size: {overview['total_size_mb']:.2f} MB")
    print(f"Instruments: {overview['total_instruments']}")
    
    if overview['date_range']['start']:
        print(f"Date range: {overview['date_range']['start']} to {overview['date_range']['end']}")
    
    print(f"\nInstruments:")
    for instrument, info in overview['instruments'].items():
        print(f"  {instrument}: {info['dates']} days, {info.get('size_mb', 0):.2f} MB")
    
    if overview['total_instruments'] == 0:
        print("\n⚠️ No data found. Run the converter first:")
        print("   python -m backtester.data.converter convert --source YOUR_NINJA_TRADER_PATH")


if __name__ == "__main__":
    # Show data overview when run directly
    show_available_data()