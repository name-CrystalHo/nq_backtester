"""
Main CLI application for NQ Backtester.

Provides command-line tools for data conversion, validation, and processing
of NinjaTrader tick data files.
"""

import click
import sys
from pathlib import Path
from typing import Optional

# Import command modules
from .commands.convert import convert_group
from .commands.validate import validate_group
from .commands.info import info_group
from .commands.backtest import backtest_group


@click.group(name='nq-backtester')
@click.version_option(version='1.0.0', prog_name='NQ Backtester CLI')
@click.option('--verbose', '-v', is_flag=True, help='Enable verbose output')
@click.option('--quiet', '-q', is_flag=True, help='Suppress output except errors')
@click.pass_context
def cli(ctx, verbose: bool, quiet: bool):
    """
    NQ Backtester CLI - High-performance tick data processing tools.
    
    Convert, validate, and process NinjaTrader CSV files with optimized
    Parquet storage for backtesting applications.
    """
    # Ensure context object exists
    ctx.ensure_object(dict)
    
    # Set verbosity levels
    if quiet and verbose:
        click.echo("Error: Cannot use both --quiet and --verbose", err=True)
        sys.exit(1)
    
    ctx.obj['verbose'] = verbose
    ctx.obj['quiet'] = quiet


# Add command groups
cli.add_command(convert_group)
cli.add_command(validate_group)
cli.add_command(info_group)
cli.add_command(backtest_group)


def main():
    """Entry point for CLI application."""
    try:
        cli()
    except KeyboardInterrupt:
        click.echo("\n⚠️  Operation cancelled by user", err=True)
        sys.exit(1)
    except Exception as e:
        click.echo(f"❌ Unexpected error: {e}", err=True)
        sys.exit(1)


if __name__ == '__main__':
    main()