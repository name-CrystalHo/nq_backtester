"""
Unified Backtesting Engine - Central Orchestrator

Coordinates all components for comprehensive strategy backtesting:
- Data loading and processing
- Strategy execution and simulation
- Performance analysis and reporting
- Multi-timeframe support
"""

from typing import Dict, List, Optional, Any, Union, Callable, Tuple
from dataclasses import dataclass
from datetime import datetime, timedelta
import pandas as pd
import numpy as np
from pathlib import Path
import logging

from ..data.loader import DataLoader
from ..data.production_manager import ProductionDataManager
from .bar_aggregator import BarAggregator, Bar
from .live_market_simulator import LiveMarketSimulator
from ..strategies.base_strategy import BaseStrategy, StrategyParams
from ..metrics.performance import PerformanceAnalyzer


@dataclass
class BacktestConfig:
    """Configuration for backtest execution"""
    # Data parameters
    symbol: str = "NQ"
    start_date: str = "2024-07-01"
    end_date: str = "2024-07-31"
    data_source: str = "production"  # 'production' or 'local'
    
    # Execution parameters
    tick_interval_seconds: float = 0.001  # Process every millisecond
    max_ticks_per_day: int = 1_000_000   # Safety limit
    
    # Output parameters
    save_results: bool = True
    results_directory: str = "results"
    generate_plots: bool = True
    verbose: bool = True
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert config to dictionary"""
        return {
            'symbol': self.symbol,
            'start_date': self.start_date,
            'end_date': self.end_date,
            'data_source': self.data_source,
            'tick_interval_seconds': self.tick_interval_seconds,
            'max_ticks_per_day': self.max_ticks_per_day,
            'save_results': self.save_results,
            'results_directory': self.results_directory,
            'generate_plots': self.generate_plots,
            'verbose': self.verbose
        }


@dataclass
class BacktestResults:
    """Comprehensive backtest results"""
    config: BacktestConfig
    strategy_params: StrategyParams
    performance_stats: Dict[str, Any]
    trades_df: pd.DataFrame
    signals_df: pd.DataFrame
    daily_stats: pd.DataFrame
    execution_stats: Dict[str, Any]
    
    def save(self, directory: str):
        """Save results to directory"""
        output_dir = Path(directory)
        output_dir.mkdir(parents=True, exist_ok=True)
        
        # Save DataFrames
        if not self.trades_df.empty:
            self.trades_df.to_csv(output_dir / "trades.csv", index=False)
        
        if not self.signals_df.empty:
            self.signals_df.to_csv(output_dir / "signals.csv", index=False)
        
        if not self.daily_stats.empty:
            self.daily_stats.to_csv(output_dir / "daily_stats.csv", index=False)
        
        # Save configuration and stats
        import json
        with open(output_dir / "config.json", 'w') as f:
            json.dump(self.config.to_dict(), f, indent=2)
        
        with open(output_dir / "strategy_params.json", 'w') as f:
            json.dump(self.strategy_params.to_dict(), f, indent=2)
        
        with open(output_dir / "performance_stats.json", 'w') as f:
            json.dump(self.performance_stats, f, indent=2, default=str)
        
        with open(output_dir / "execution_stats.json", 'w') as f:
            json.dump(self.execution_stats, f, indent=2, default=str)


class UnifiedBacktester:
    """
    Unified backtesting engine that orchestrates all components.
    
    Features:
    - Flexible data source integration
    - Multi-strategy support
    - Real-time performance tracking
    - Comprehensive result analysis
    - Production-ready execution
    """
    
    def __init__(
        self,
        config: BacktestConfig,
        logger: Optional[logging.Logger] = None
    ):
        """
        Initialize unified backtester.
        
        Args:
            config: Backtest configuration
            logger: Optional logger instance
        """
        self.config = config
        self.logger = logger or self._setup_logger()
        
        # Initialize components
        self.data_manager: Optional[ProductionDataManager] = None
        self.data_loader: Optional[DataLoader] = None
        self.performance_analyzer = PerformanceAnalyzer()
        
        # Execution state
        self.is_running: bool = False
        self.current_date: Optional[str] = None
        self.total_ticks_processed: int = 0
        self.total_execution_time: float = 0.0
        self.strategies: List[BaseStrategy] = []
        
        # Results tracking
        self.daily_results: List[Dict[str, Any]] = []
        self.execution_metrics: Dict[str, Any] = {}
    
    def _setup_logger(self) -> logging.Logger:
        """Setup default logger"""
        logger = logging.getLogger("UnifiedBacktester")
        if not logger.handlers:
            handler = logging.StreamHandler()
            formatter = logging.Formatter(
                '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
            )
            handler.setFormatter(formatter)
            logger.addHandler(handler)
            logger.setLevel(logging.INFO if self.config.verbose else logging.WARNING)
        return logger
    
    def add_strategy(self, strategy: BaseStrategy) -> int:
        """
        Add strategy to backtest.
        
        Args:
            strategy: Strategy instance to add
            
        Returns:
            Strategy index
        """
        self.strategies.append(strategy)
        strategy_idx = len(self.strategies) - 1
        
        self.logger.info(f"Added strategy {strategy_idx}: {strategy.params.name}")
        return strategy_idx
    
    def run_backtest(self) -> List[BacktestResults]:
        """
        Execute the backtest for all strategies.
        
        Returns:
            List of results for each strategy
        """
        if not self.strategies:
            raise ValueError("No strategies added to backtest")
        
        self.logger.info(f"Starting backtest: {self.config.symbol} "
                        f"from {self.config.start_date} to {self.config.end_date}")
        
        # Initialize data source
        self._initialize_data_source()
        
        # Reset all strategies
        for strategy in self.strategies:
            strategy.reset()
        
        # Execute backtest
        self.is_running = True
        start_time = pd.Timestamp.now()
        
        try:
            self._execute_backtest()
        except Exception as e:
            self.logger.error(f"Backtest execution failed: {e}")
            raise
        finally:
            self.is_running = False
        
        end_time = pd.Timestamp.now()
        self.total_execution_time = (end_time - start_time).total_seconds()
        
        # Generate results
        results = self._generate_results()
        
        # Save results if configured
        if self.config.save_results:
            self._save_all_results(results)
        
        self.logger.info(f"Backtest completed in {self.total_execution_time:.2f} seconds")
        self.logger.info(f"Processed {self.total_ticks_processed:,} ticks "
                        f"({self.total_ticks_processed/self.total_execution_time:.0f} ticks/sec)")
        
        return results
    
    def _initialize_data_source(self):
        """Initialize data source based on configuration"""
        if self.config.data_source == "production":
            self.data_manager = ProductionDataManager()
            self.logger.info("Initialized production data manager")
        else:
            # Initialize local data loader
            data_dir = Path("storage/processed") / f"{self.config.symbol}_SEP24"
            self.data_loader = DataLoader(str(data_dir))
            self.logger.info(f"Initialized local data loader: {data_dir}")
    
    def _execute_backtest(self):
        """Execute the main backtest loop"""
        # Get date range
        start_date = pd.to_datetime(self.config.start_date)
        end_date = pd.to_datetime(self.config.end_date)
        
        current_date = start_date
        while current_date <= end_date:
            date_str = current_date.strftime("%Y%m%d")
            self.current_date = date_str
            
            self.logger.info(f"Processing {date_str}")
            
            # Load data for this date
            tick_data = self._load_date_data(date_str)
            
            if tick_data is None or tick_data.empty:
                self.logger.warning(f"No data available for {date_str}")
                current_date += timedelta(days=1)
                continue
            
            # Process ticks for this date
            daily_stats = self._process_daily_ticks(tick_data, date_str)
            self.daily_results.append(daily_stats)
            
            current_date += timedelta(days=1)
    
    def _load_date_data(self, date_str: str) -> Optional[pd.DataFrame]:
        """Load tick data for a specific date"""
        try:
            if self.data_manager:
                # Load from production system
                return self.data_manager.load_tick_data(self.config.symbol, date_str)
            elif self.data_loader:
                # Load from local files
                filename = f"{date_str}.parquet"
                return self.data_loader.load_data(filename)
            else:
                raise ValueError("No data source initialized")
                
        except Exception as e:
            self.logger.error(f"Failed to load data for {date_str}: {e}")
            return None
    
    def _process_daily_ticks(self, tick_data: pd.DataFrame, date_str: str) -> Dict[str, Any]:
        """Process all ticks for a single day"""
        daily_start_time = pd.Timestamp.now()
        ticks_processed = 0
        
        # Initialize daily tracking
        daily_stats = {
            'date': date_str,
            'ticks_processed': 0,
            'processing_time_seconds': 0.0,
            'ticks_per_second': 0.0,
            'strategies': {}
        }
        
        # Filter valid ticks (remove zero prices, etc.)
        valid_ticks = tick_data[tick_data['price'] > 0].copy()
        valid_ticks = valid_ticks.sort_values('timestamp_ns')
        
        # Process each tick
        for _, tick in valid_ticks.iterrows():
            timestamp_ns = int(tick['timestamp_ns'])
            price = float(tick['price'])
            
            # Process tick through all strategies
            for i, strategy in enumerate(self.strategies):
                try:
                    signals, fills = strategy.process_tick(timestamp_ns, price)
                    
                    # Track strategy-specific stats
                    if i not in daily_stats['strategies']:
                        daily_stats['strategies'][i] = {
                            'name': strategy.params.name,
                            'signals_generated': 0,
                            'fills_executed': 0,
                            'unrealized_pnl': 0.0
                        }
                    
                    daily_stats['strategies'][i]['signals_generated'] += len(signals)
                    daily_stats['strategies'][i]['fills_executed'] += len(fills)
                    daily_stats['strategies'][i]['unrealized_pnl'] = strategy.simulator.get_position().unrealized_pnl
                    
                except Exception as e:
                    self.logger.error(f"Error processing tick for strategy {i}: {e}")
                    continue
            
            ticks_processed += 1
            self.total_ticks_processed += 1
            
            # Safety check
            if ticks_processed >= self.config.max_ticks_per_day:
                self.logger.warning(f"Hit max ticks per day limit: {self.config.max_ticks_per_day}")
                break
        
        # Calculate daily performance
        daily_end_time = pd.Timestamp.now()
        processing_time = (daily_end_time - daily_start_time).total_seconds()
        
        daily_stats['ticks_processed'] = ticks_processed
        daily_stats['processing_time_seconds'] = processing_time
        daily_stats['ticks_per_second'] = ticks_processed / processing_time if processing_time > 0 else 0
        
        self.logger.info(f"  Processed {ticks_processed:,} ticks in {processing_time:.2f}s "
                        f"({daily_stats['ticks_per_second']:.0f} ticks/sec)")
        
        return daily_stats
    
    def _generate_results(self) -> List[BacktestResults]:
        """Generate comprehensive results for all strategies"""
        results = []
        
        for i, strategy in enumerate(self.strategies):
            # Get strategy performance stats
            performance_stats = strategy.get_performance_stats()
            trades_df = strategy.get_trades_df()
            signals_df = strategy.get_signals_df()
            
            # Create daily stats DataFrame
            daily_data = []
            for daily_result in self.daily_results:
                if i in daily_result['strategies']:
                    strategy_daily = daily_result['strategies'][i].copy()
                    strategy_daily['date'] = daily_result['date']
                    strategy_daily['total_ticks'] = daily_result['ticks_processed']
                    strategy_daily['processing_time'] = daily_result['processing_time_seconds']
                    daily_data.append(strategy_daily)
            
            daily_stats_df = pd.DataFrame(daily_data) if daily_data else pd.DataFrame()
            
            # Execution statistics
            execution_stats = {
                'total_execution_time_seconds': self.total_execution_time,
                'total_ticks_processed': self.total_ticks_processed,
                'average_ticks_per_second': self.total_ticks_processed / self.total_execution_time if self.total_execution_time > 0 else 0,
                'dates_processed': len(self.daily_results),
                'strategy_index': i
            }
            
            # Create results object
            result = BacktestResults(
                config=self.config,
                strategy_params=strategy.params,
                performance_stats=performance_stats,
                trades_df=trades_df,
                signals_df=signals_df,
                daily_stats=daily_stats_df,
                execution_stats=execution_stats
            )
            
            results.append(result)
            
            # Log summary
            self.logger.info(f"Strategy {i} ({strategy.params.name}) Results:")
            self.logger.info(f"  Total Trades: {performance_stats['total_trades']}")
            self.logger.info(f"  Total P&L: ${performance_stats['total_pnl']:.2f}")
            self.logger.info(f"  Win Rate: {performance_stats['win_rate']:.1%}")
            self.logger.info(f"  Profit Factor: {performance_stats['profit_factor']:.2f}")
        
        return results
    
    def _save_all_results(self, results: List[BacktestResults]):
        """Save all strategy results"""
        base_dir = Path(self.config.results_directory)
        base_dir.mkdir(parents=True, exist_ok=True)
        
        # Create timestamped directory
        timestamp = pd.Timestamp.now().strftime("%Y%m%d_%H%M%S")
        results_dir = base_dir / f"backtest_{timestamp}"
        results_dir.mkdir(exist_ok=True)
        
        # Save each strategy's results
        for i, result in enumerate(results):
            strategy_dir = results_dir / f"strategy_{i}_{result.strategy_params.name}"
            result.save(str(strategy_dir))
        
        self.logger.info(f"Results saved to: {results_dir}")
    
    def get_execution_summary(self) -> Dict[str, Any]:
        """Get execution performance summary"""
        return {
            'total_execution_time_seconds': self.total_execution_time,
            'total_ticks_processed': self.total_ticks_processed,
            'average_ticks_per_second': self.total_ticks_processed / self.total_execution_time if self.total_execution_time > 0 else 0,
            'dates_processed': len(self.daily_results),
            'strategies_executed': len(self.strategies),
            'config': self.config.to_dict()
        }