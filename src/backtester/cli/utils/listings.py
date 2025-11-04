"""
Utilities to list available contracts, strategies, and data for the CLI.

These helpers are intentionally lightweight to avoid import-time errors.
"""

from pathlib import Path
from typing import Iterable
import sys
import click


def _project_root() -> Path:
	# File is: <repo>/src/backtester/cli/utils/listings.py
	# Walk up to repo root consistently (same approach as backtest.py)
	return Path(__file__).resolve().parent.parent.parent.parent.parent


def _echo_list(title: str, items: Iterable[str]) -> None:
	items = sorted(set(items))
	click.echo(title)
	if not items:
		click.echo("  <none>")
		return
	for it in items:
		click.echo(f"  - {it}")


def list_available_contracts(verbose: bool = False) -> None:
	"""List available contract folders under storage/parquet."""
	root = _project_root() / "storage" / "parquet"
	contracts = []
	if root.exists():
		for p in root.iterdir():
			if p.is_dir():
				contracts.append(p.name)
	else:
		if verbose:
			click.echo(f"WARNING: Data root not found: {root}")
	_echo_list("Available contracts (storage/parquet):", contracts)


def list_available_strategies(verbose: bool = False) -> None:
	"""List available strategy modules in src/backtester/strategies."""
	strategies_dir = _project_root() / "src" / "backtester" / "strategies"
	names = []
	if strategies_dir.exists():
		for py in strategies_dir.glob("*.py"):
			stem = py.stem
			if stem.startswith("__"):
				continue
			if stem in {"base_strategy"}:
				continue
			names.append(stem)
	else:
		if verbose:
			click.echo(f"WARNING: Strategies dir not found: {strategies_dir}")
	_echo_list("Available strategies (module names):", names)


def list_available_data(verbose: bool = False) -> None:
	"""List available parquet files under storage/parquet/<CONTRACT>."""
	root = _project_root() / "storage" / "parquet"
	if not root.exists():
		click.echo(f"No data directory found: {root}")
		return
	click.echo("Available data files:")
	any_found = False
	for contract_dir in sorted(p for p in root.iterdir() if p.is_dir()):
		files = sorted(contract_dir.glob("*.parquet"))
		count = len(files)
		click.echo(f"  {contract_dir.name}: {count} file(s)")
		if verbose and count:
			# Show a small sample to avoid spam
			for f in files[:10]:
				click.echo(f"     - {f.name}")
		any_found = any_found or count > 0
	if not any_found:
		click.echo("  <no parquet files found>")

