"""
Performance Metrics - Generate metrics matching NinjaTrader's Strategy Analyzer

Calculates comprehensive performance statistics that exactly match
NinjaTrader's output for validation and comparison purposes.
"""

import polars as pl
import numpy as np
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Any
import logging

logger = logging.getLogger(__name__)


class PerformanceMetrics:
    """
    Comprehensive performance metrics matching NinjaTrader's Strategy Analyzer.
    
    Calculates profit metrics, win/loss statistics, drawdown analysis,
    and risk-adjusted returns for backtesting validation.
    """
    
    def __init__(self):
        """Initialize empty metrics."""
        # Profit Metrics
        self.total_net_profit = 0.0
        self.gross_profit = 0.0
        self.gross_loss = 0.0
        self.profit_factor = 0.0
        
        # Win/Loss Statistics
        self.total_trades = 0
        self.winning_trades = 0
        self.losing_trades = 0
        self.win_rate = 0.0
        self.avg_win = 0.0
        self.avg_loss = 0.0
        self.avg_win_loss_ratio = 0.0
        self.largest_win = 0.0
        self.largest_loss = 0.0
        self.avg_trade_pnl = 0.0
        
        # Drawdown Metrics
        self.max_drawdown = 0.0
        self.max_drawdown_pct = 0.0
        self.max_drawdown_duration = 0
        
        # Risk Metrics
        self.sharpe_ratio = 0.0
        self.sortino_ratio = 0.0
        
        # Additional Metrics
        self.total_commission = 0.0
        self.avg_bars_in_trade = 0.0
        self.current_position = 0
        self.current_equity = 0.0
        
        # Raw data for analysis
        self.trade_list: List[Any] = []
        self.equity_curve: List[Any] = []
    
    def calculate_from_tracker(self, position_tracker: Any):
        """
        Calculate all metrics from position tracker.
        
        Args:
            position_tracker: PositionTracker instance with trade history
        """
        stats = position_tracker.get_statistics()
        
        # Basic metrics from tracker
        self.total_trades = stats['total_trades']
        self.winning_trades = stats['winning_trades']
        self.losing_trades = stats['losing_trades']
        self.win_rate = stats['win_rate']
        self.total_net_profit = stats['total_net_profit']
        self.gross_profit = stats['gross_profit']
        self.gross_loss = stats['gross_loss']
        self.profit_factor = stats['profit_factor']
        self.avg_win = stats['avg_win']
        self.avg_loss = stats['avg_loss']
        self.largest_win = stats['largest_win']
        self.largest_loss = stats['largest_loss']
        self.max_drawdown = stats['max_drawdown']
        self.max_drawdown_pct = stats['max_drawdown_pct']
        self.total_commission = stats['total_commission']
        self.current_position = stats['current_position']
        self.current_equity = stats['current_equity']
        
        # Get raw data
        self.trade_list = position_tracker.get_trade_history()
        self.equity_curve = position_tracker.equity_curve
        
        # Calculate derived metrics
        self._calculate_derived_metrics()
    
    def _calculate_derived_metrics(self):
        """Calculate metrics derived from basic statistics."""
        # Average trade P&L
        if self.total_trades > 0:
            total_pnl = sum(trade.pnl for trade in self.trade_list)
            self.avg_trade_pnl = total_pnl / self.total_trades
        
        # Win/Loss ratio
        if self.avg_loss != 0:
            self.avg_win_loss_ratio = abs(self.avg_win / self.avg_loss)
        
        # Average bars in trade (if trade duration data available)
        if self.trade_list:
            durations = []
            for trade in self.trade_list:
                if hasattr(trade, 'entry_timestamp') and hasattr(trade, 'exit_timestamp'):
                    duration = (trade.exit_timestamp - trade.entry_timestamp).total_seconds() / 3600  # Hours
                    durations.append(duration)
            
            if durations:
                self.avg_bars_in_trade = sum(durations) / len(durations)
        
        # Risk-adjusted metrics
        self._calculate_risk_metrics()
        
        # Drawdown duration
        self._calculate_drawdown_duration()
    
    def _calculate_risk_metrics(self):
        """Calculate Sharpe ratio and other risk metrics."""
        if not self.equity_curve or len(self.equity_curve) < 2:
            return
        
        # Calculate daily returns
        equity_values = [point.equity for point in self.equity_curve]
        returns = []
        
        for i in range(1, len(equity_values)):
            if equity_values[i-1] != 0:
                daily_return = (equity_values[i] - equity_values[i-1]) / equity_values[i-1]
                returns.append(daily_return)
        
        if not returns:
            return
        
        # Sharpe ratio (assuming risk-free rate = 0)
        mean_return = np.mean(returns)
        std_return = np.std(returns)
        
        if std_return != 0:
            self.sharpe_ratio = mean_return / std_return * np.sqrt(252)  # Annualized
        
        # Sortino ratio (downside deviation)
        negative_returns = [r for r in returns if r < 0]
        if negative_returns:
            downside_std = np.std(negative_returns)
            if downside_std != 0:
                self.sortino_ratio = mean_return / downside_std * np.sqrt(252)
    
    def _calculate_drawdown_duration(self):
        """Calculate maximum drawdown duration in periods."""
        if not self.equity_curve:
            return
        
        peak = self.equity_curve[0].equity
        peak_index = 0
        max_duration = 0
        current_duration = 0
        
        for i, point in enumerate(self.equity_curve):
            if point.equity > peak:
                peak = point.equity
                peak_index = i
                current_duration = 0
            else:
                current_duration = i - peak_index
                max_duration = max(max_duration, current_duration)
        
        self.max_drawdown_duration = max_duration
    
    def to_dict(self) -> Dict[str, Any]:
        """
        Convert metrics to dictionary format.
        
        Returns:
            Dictionary with all performance metrics
        """
        return {
            # Profit Metrics
            'total_net_profit': self.total_net_profit,
            'gross_profit': self.gross_profit,
            'gross_loss': self.gross_loss,
            'profit_factor': self.profit_factor,
            
            # Win/Loss Statistics
            'total_trades': self.total_trades,
            'winning_trades': self.winning_trades,
            'losing_trades': self.losing_trades,
            'win_rate': self.win_rate,
            'avg_win': self.avg_win,
            'avg_loss': self.avg_loss,
            'avg_win_loss_ratio': self.avg_win_loss_ratio,
            'largest_win': self.largest_win,
            'largest_loss': self.largest_loss,
            'avg_trade_pnl': self.avg_trade_pnl,
            
            # Drawdown Metrics
            'max_drawdown': self.max_drawdown,
            'max_drawdown_pct': self.max_drawdown_pct,
            'max_drawdown_duration': self.max_drawdown_duration,
            
            # Risk Metrics
            'sharpe_ratio': self.sharpe_ratio,
            'sortino_ratio': self.sortino_ratio,
            
            # Additional Metrics
            'total_commission': self.total_commission,
            'avg_bars_in_trade': self.avg_bars_in_trade,
            'current_position': self.current_position,
            'current_equity': self.current_equity,
        }
    
    def to_dataframe(self):
        """
        Convert metrics to Polars DataFrame.
        
        Returns:
            Polars DataFrame with metrics as rows
        """
        metrics_dict = self.to_dict()
        df = pl.DataFrame({
            'Metric': list(metrics_dict.keys()),
            'Value': list(metrics_dict.values())
        })
        return df
    
    def print_summary(self, title: str = "Backtest Results"):
        """
        Print formatted performance summary.
        
        Args:
            title: Title for the summary report
        """
        print(f"\n{'='*60}")
        print(f"{title:^60}")
        print(f"{'='*60}")
        
        print(f"\n📊 PROFIT METRICS")
        print(f"{'─'*40}")
        print(f"Total Net Profit:     ${self.total_net_profit:>12,.2f}")
        print(f"Gross Profit:         ${self.gross_profit:>12,.2f}")
        print(f"Gross Loss:           ${self.gross_loss:>12,.2f}")
        print(f"Profit Factor:        {self.profit_factor:>12.2f}")
        
        print(f"\n🎯 WIN/LOSS STATISTICS")
        print(f"{'─'*40}")
        print(f"Total Trades:         {self.total_trades:>12}")
        print(f"Winning Trades:       {self.winning_trades:>12}")
        print(f"Losing Trades:        {self.losing_trades:>12}")
        print(f"Win Rate:             {self.win_rate:>11.1%}")
        print(f"Average Win:          ${self.avg_win:>12.2f}")
        print(f"Average Loss:         ${self.avg_loss:>12.2f}")
        print(f"Win/Loss Ratio:       {self.avg_win_loss_ratio:>12.2f}")
        print(f"Largest Win:          ${self.largest_win:>12.2f}")
        print(f"Largest Loss:         ${self.largest_loss:>12.2f}")
        print(f"Average Trade:        ${self.avg_trade_pnl:>12.2f}")
        
        print(f"\n📉 DRAWDOWN ANALYSIS")
        print(f"{'─'*40}")
        print(f"Max Drawdown:         ${self.max_drawdown:>12,.2f}")
        print(f"Max Drawdown %:       {self.max_drawdown_pct:>11.2%}")
        print(f"Max DD Duration:      {self.max_drawdown_duration:>12} periods")
        
        print(f"\n⚖️  RISK METRICS")
        print(f"{'─'*40}")
        print(f"Sharpe Ratio:         {self.sharpe_ratio:>12.3f}")
        print(f"Sortino Ratio:        {self.sortino_ratio:>12.3f}")
        
        print(f"\n💰 ADDITIONAL INFO")
        print(f"{'─'*40}")
        print(f"Total Commission:     ${self.total_commission:>12.2f}")
        print(f"Current Position:     {self.current_position:>12}")
        print(f"Current Equity:       ${self.current_equity:>12,.2f}")
        print(f"Avg Trade Duration:   {self.avg_bars_in_trade:>12.1f} hours")
        
        print(f"\n{'='*60}")
    
    def export_ninja_format(self, filename: str):
        """
        Export metrics in NinjaTrader-compatible format.
        
        Args:
            filename: Output filename for CSV export
        """
        ninja_metrics = {
            'Total net profit': f"${self.total_net_profit:,.2f}",
            'Gross profit': f"${self.gross_profit:,.2f}",
            'Gross loss': f"${self.gross_loss:,.2f}",
            'Profit factor': f"{self.profit_factor:.2f}",
            'Total trades': str(self.total_trades),
            'Winning trades': str(self.winning_trades),
            'Losing trades': str(self.losing_trades),
            'Percent profitable': f"{self.win_rate:.1%}",
            'Avg. winning trade': f"${self.avg_win:.2f}",
            'Avg. losing trade': f"${self.avg_loss:.2f}",
            'Ratio avg win / avg loss': f"{self.avg_win_loss_ratio:.2f}",
            'Largest winning trade': f"${self.largest_win:.2f}",
            'Largest losing trade': f"${self.largest_loss:.2f}",
            'Max. consecutive winners': "N/A",  # Would need additional calculation
            'Max. consecutive losers': "N/A",   # Would need additional calculation
            'Avg. # bars in trades': f"{self.avg_bars_in_trade:.1f}",
            'Max. time to recover': f"{self.max_drawdown_duration}",
            'Max. intraday drawdown': f"${self.max_drawdown:,.2f}",
            'Commission': f"${self.total_commission:.2f}",
        }
        
        df = pl.DataFrame({
            'Metric': list(ninja_metrics.keys()),
            'Value': list(ninja_metrics.values())
        })
        df.write_csv(filename)
        logger.info(f"NinjaTrader-format metrics exported to {filename}")
    
    def get_trade_analysis_df(self):
        """
        Get detailed trade analysis as Polars DataFrame.
        
        Returns:
            Polars DataFrame with individual trade details
        """
        if not self.trade_list:
            return pl.DataFrame([])
        
        trade_data = []
        for i, trade in enumerate(self.trade_list, 1):
            trade_data.append({
                'Trade #': i,
                'Entry Time': trade.entry_timestamp,
                'Exit Time': trade.exit_timestamp,
                'Direction': trade.direction.capitalize(),
                'Quantity': trade.quantity,
                'Entry Price': trade.entry_price,
                'Exit Price': trade.exit_price,
                'P&L': trade.pnl,
                'Commission': trade.commission,
                'Net P&L': trade.pnl - trade.commission,
                'Duration (Hours)': (trade.exit_timestamp - trade.entry_timestamp).total_seconds() / 3600,
                'MAE': getattr(trade, 'mae', 0.0),
                'MFE': getattr(trade, 'mfe', 0.0),
            })
        
        return pl.DataFrame(trade_data)
    
    def get_equity_curve_df(self):
        """
        Get equity curve as Polars DataFrame.
        
        Returns:
            Polars DataFrame with equity curve data
        """
        if not self.equity_curve:
            return pl.DataFrame([])
        
        equity_data = []
        for point in self.equity_curve:
            equity_data.append({
                'Timestamp': point.timestamp,
                'Equity': point.equity,
                'Realized P&L': point.realized_pnl,
                'Unrealized P&L': point.unrealized_pnl,
                'Position Size': point.position_size,
                'Drawdown': point.drawdown,
                'Drawdown %': point.drawdown_pct,
            })
        
        return pl.DataFrame(equity_data)