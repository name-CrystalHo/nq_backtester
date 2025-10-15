"""Configuration management for the backtester."""

import os
from pathlib import Path
from typing import Dict, Any, Optional, Union
from dataclasses import dataclass, asdict

try:
    import yaml
    HAS_YAML = True
except ImportError:
    HAS_YAML = False

from .constants import (
    DEFAULT_TICK_SIZE, DEFAULT_CONTRACT_MULTIPLIER, DEFAULT_COMMISSION,
    NQ_TICK_SIZE, NQ_MULTIPLIER, DEFAULT_WORKER_COUNT
)
from .exceptions import ConfigError


@dataclass
class DatabaseConfig:
    """Database configuration."""
    engine: str = "parquet"
    data_path: str = "./storage/processed"
    cache_path: str = "./storage/cache"
    
    
@dataclass
class InstrumentConfig:
    """Instrument-specific configuration."""
    name: str
    tick_size: float
    contract_multiplier: int
    commission_per_trade: float
    margin_requirement: float = 0.0
    
    
@dataclass
class BacktestConfig:
    """Backtest configuration."""
    initial_capital: float = 100_000.0
    commission_per_trade: float = DEFAULT_COMMISSION
    slippage_ticks: int = 0
    max_position_size: int = 10
    
    
@dataclass
class DataConfig:
    """Data processing configuration."""
    chunk_size: int = 100_000
    worker_count: int = DEFAULT_WORKER_COUNT
    memory_limit_gb: float = 8.0
    cache_enabled: bool = True
    
    
@dataclass
class LoggingConfig:
    """Logging configuration."""
    level: str = "INFO"
    format: str = "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
    file_path: Optional[str] = None
    
    
@dataclass
class Config:
    """Main configuration container."""
    database: DatabaseConfig
    backtest: BacktestConfig
    data: DataConfig
    logging: LoggingConfig
    instruments: Dict[str, InstrumentConfig]
    
    @classmethod
    def from_dict(cls, config_dict: Dict[str, Any]) -> 'Config':
        """Create config from dictionary."""
        try:
            return cls(
                database=DatabaseConfig(**config_dict.get('database', {})),
                backtest=BacktestConfig(**config_dict.get('backtest', {})),
                data=DataConfig(**config_dict.get('data', {})),
                logging=LoggingConfig(**config_dict.get('logging', {})),
                instruments={
                    name: InstrumentConfig(**{**params, 'name': name})
                    for name, params in config_dict.get('instruments', {}).items()
                }
            )
        except Exception as e:
            raise ConfigError(f"Failed to create config from dict: {e}") from e
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert config to dictionary."""
        return {
            'database': asdict(self.database),
            'backtest': asdict(self.backtest),
            'data': asdict(self.data),
            'logging': asdict(self.logging),
            'instruments': {
                name: asdict(inst) for name, inst in self.instruments.items()
            }
        }
    
    @classmethod
    def load_from_file(cls, config_path: Union[str, Path]) -> 'Config':
        """Load configuration from YAML file."""
        if not HAS_YAML:
            raise ConfigError("PyYAML is required to load config from file. Install with: pip install pyyaml")
        
        config_path = Path(config_path)
        
        if not config_path.exists():
            raise ConfigError(f"Config file not found: {config_path}")
        
        try:
            with open(config_path, 'r', encoding='utf-8') as f:
                config_dict = yaml.safe_load(f)
            return cls.from_dict(config_dict)
        except yaml.YAMLError as e:
            raise ConfigError(f"Failed to parse YAML config: {e}") from e
        except Exception as e:
            raise ConfigError(f"Failed to load config: {e}") from e
    
    def save_to_file(self, config_path: Union[str, Path]) -> None:
        """Save configuration to YAML file."""
        if not HAS_YAML:
            raise ConfigError("PyYAML is required to save config to file. Install with: pip install pyyaml")
        
        config_path = Path(config_path)
        config_path.parent.mkdir(parents=True, exist_ok=True)
        
        try:
            with open(config_path, 'w', encoding='utf-8') as f:
                yaml.dump(self.to_dict(), f, default_flow_style=False, indent=2)
        except Exception as e:
            raise ConfigError(f"Failed to save config: {e}") from e


def get_default_config() -> Config:
    """Get default configuration."""
    return Config(
        database=DatabaseConfig(),
        backtest=BacktestConfig(),
        data=DataConfig(),
        logging=LoggingConfig(),
        instruments={
            'NQ': InstrumentConfig(
                name='NQ',
                tick_size=NQ_TICK_SIZE,
                contract_multiplier=NQ_MULTIPLIER,
                commission_per_trade=DEFAULT_COMMISSION
            )
        }
    )


def load_config(config_path: Optional[Union[str, Path]] = None) -> Config:
    """Load configuration with fallback to defaults."""
    if config_path is None:
        # Try to find config file in standard locations
        possible_paths = [
            Path("config/default.yaml"),
            Path("./default.yaml"),
            Path("config.yaml"),
        ]
        
        for path in possible_paths:
            if path.exists():
                config_path = path
                break
    
    if config_path and Path(config_path).exists():
        try:
            return Config.load_from_file(config_path)
        except ConfigError:
            # Fall back to default if YAML loading fails
            return get_default_config()
    else:
        return get_default_config()


def get_env_config() -> Dict[str, Any]:
    """Get configuration overrides from environment variables."""
    env_config = {}
    
    # Database config
    if data_path := os.getenv('BACKTESTER_DATA_PATH'):
        env_config.setdefault('database', {})['data_path'] = data_path
    
    # Backtest config  
    if initial_capital := os.getenv('BACKTESTER_INITIAL_CAPITAL'):
        env_config.setdefault('backtest', {})['initial_capital'] = float(initial_capital)
    
    # Data config
    if worker_count := os.getenv('BACKTESTER_WORKER_COUNT'):
        env_config.setdefault('data', {})['worker_count'] = int(worker_count)
    
    # Logging config
    if log_level := os.getenv('BACKTESTER_LOG_LEVEL'):
        env_config.setdefault('logging', {})['level'] = log_level
    
    return env_config