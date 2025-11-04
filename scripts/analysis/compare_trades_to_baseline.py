import argparse
import os
from pathlib import Path
from datetime import datetime, timedelta
from typing import List, Tuple, Optional, Dict, Any

import pandas as pd
import numpy as np

# Ensure src is on path
PROJECT_ROOT = Path(__file__).resolve().parents[2]
SRC_PATH = PROJECT_ROOT / "src"
if str(SRC_PATH) not in os.sys.path:
    os.sys.path.insert(0, str(SRC_PATH))

from backtester.engine.backtester import Backtester, BacktestConfig


def filter_files_by_date(files: List[Path], start_date: Optional[datetime], end_date: Optional[datetime]) -> List[Path]:
    """Filter files by date range based on filename YYYYMMDD.parquet.
    NOTE: Files are named one day earlier than their actual content; adjust like CLI.
    """
    if not start_date and not end_date:
        return files
    filtered = []
    for f in files:
        try:
            file_date = datetime.strptime(f.stem, "%Y%m%d").date()
            if start_date and file_date < (start_date.date() - timedelta(days=1)):
                continue
            if end_date and file_date > (end_date.date() - timedelta(days=1)):
                continue
            filtered.append(f)
        except ValueError:
            continue
    return filtered


def _run_single_file(args: Tuple[Path, str, Dict[str, Any]]) -> Dict[str, Any]:
    """Module-level worker for multiprocessing; returns backtest result dict."""
    f, strategy, config = args
    bt = Backtester()
    return bt.run_backtest(strategy_name=strategy, data_file=str(f), config=config)


def collect_generated_trades(
    contract: str,
    start_date: datetime,
    end_date: datetime,
    strategy: str = "wicktest",
    workers: int = 1,
    commission: float = 0.0,
    slippage_ticks: int = 0,
    use_order_book: bool = True,
    l2_streaming: bool = True,
    l2_chunk_size: int = 1_000_000,
) -> pd.DataFrame:
    """Run backtests across the date range and return all completed trades as a DataFrame.

    Uses parallel workers similar to the CLI for speed when workers>1.
    """
    storage_dir = PROJECT_ROOT / "storage" / "parquet" / contract
    if not storage_dir.exists():
        raise FileNotFoundError(f"Data folder not found: {storage_dir}")

    parquet_files = sorted(storage_dir.glob("*.parquet"))
    parquet_files = filter_files_by_date(parquet_files, start_date, end_date)
    if not parquet_files:
        raise FileNotFoundError(f"No parquet files found for {contract} in range {start_date.date()}..{end_date.date()}")

    all_trades: List[Dict[str, Any]] = []

    config = BacktestConfig(
        initial_capital=100_000.0,
        commission_per_contract=commission,
        slippage_ticks=slippage_ticks,
        use_order_book=use_order_book,
        l2_streaming=l2_streaming,
        l2_chunk_size=l2_chunk_size,
    ).__dict__

    # Parallel or serial execution
    if workers is None or workers <= 1:
        bt = Backtester()
        for f in parquet_files:
            res = bt.run_backtest(strategy_name=strategy, data_file=str(f), config=config)
            if not res.get("success"):
                print(f"Warning: backtest failed for {f.name}: {res.get('error')}")
                continue
            trades = res.get("simulator_completed_trades", [])
            for t in trades:
                all_trades.append({
                    "side": t.side,
                    "entry_time_ns": int(t.entry_time_ns),
                    "exit_time_ns": int(t.exit_time_ns),
                    "entry_time": pd.to_datetime(t.entry_time_ns, unit='ns'),
                    "exit_time": pd.to_datetime(t.exit_time_ns, unit='ns'),
                    "entry_price": float(t.entry_price),
                    "exit_price": float(t.exit_price),
                    "pnl": float(t.pnl),
                    "commission": float(t.commission),
                    "duration_seconds": float(t.duration_seconds),
                })
    else:
        from concurrent.futures import ProcessPoolExecutor, as_completed
        tasks = [(f, strategy, config) for f in parquet_files]
        with ProcessPoolExecutor(max_workers=workers) as ex:
            fut_to_file = {ex.submit(_run_single_file, t): t[0] for t in tasks}
            for fut in as_completed(fut_to_file):
                f = fut_to_file[fut]
                try:
                    res = fut.result()
                except Exception as e:
                    print(f"Error in worker for {f.name}: {e}")
                    continue
                if not res.get("success"):
                    print(f"Warning: backtest failed for {f.name}: {res.get('error')}")
                    continue
                for t in res.get("simulator_completed_trades", []):
                    all_trades.append({
                        "side": t.side,
                        "entry_time_ns": int(t.entry_time_ns),
                        "exit_time_ns": int(t.exit_time_ns),
                        "entry_time": pd.to_datetime(t.entry_time_ns, unit='ns'),
                        "exit_time": pd.to_datetime(t.exit_time_ns, unit='ns'),
                        "entry_price": float(t.entry_price),
                        "exit_price": float(t.exit_price),
                        "pnl": float(t.pnl),
                        "commission": float(t.commission),
                        "duration_seconds": float(t.duration_seconds),
                    })

    df = pd.DataFrame(all_trades)
    if df.empty:
        print("No generated trades found in the selected range.")
    return df


# Heuristics for baseline column detection
CANDIDATE_MAP = {
    "side": ["side", "direction"],
    "entry_time": ["entry_time", "entry", "entry_timestamp", "entry_dt", "entry time"],
    "exit_time": ["exit_time", "exit", "exit_timestamp", "exit_dt", "exit time"],
    "entry_price": ["entry_price", "entry", "entry_px", "entry price"],
    "exit_price": ["exit_price", "exit", "exit_px", "exit price"],
    "pnl": ["pnl", "p&l", "profit", "net_pnl", "net"]
}


def pick_col(cols: List[str], candidates: List[str]) -> Optional[str]:
    lower = {c.lower(): c for c in cols}
    for name in candidates:
        if name in lower:
            return lower[name]
    # try contains search
    for c in cols:
        cl = c.lower()
        for name in candidates:
            if name in cl:
                return c
    return None


def load_baseline_csv(csv_path: Path) -> pd.DataFrame:
    df = pd.read_csv(csv_path)
    cols = list(df.columns)
    mapping = {}
    for key, cands in CANDIDATE_MAP.items():
        col = pick_col(cols, cands)
        if col:
            mapping[key] = col
    # We require entry_time, exit_time, pnl; side can be inferred if missing when prices exist
    required_core = ["entry_time", "exit_time", "pnl"]
    missing_core = [k for k in required_core if k not in mapping]
    if missing_core:
        raise ValueError(f"Baseline CSV missing required columns (detected mapping={mapping}). Missing: {missing_core}")

    # Normalize
    # Clean numeric-like strings (e.g., "$200", "1,250.50", "($200.00)")
    def to_num_clean(series: pd.Series) -> pd.Series:
        cleaned = series.astype(str).str.strip()
        # Detect parentheses pattern for negative numbers: ($200.00)
        is_negative = cleaned.str.contains(r'^\(.*\)$', regex=True, na=False)
        # Remove all non-numeric except decimal and minus
        cleaned = cleaned.str.replace(r'[^0-9\.-]', '', regex=True)
        result = pd.to_numeric(cleaned, errors='coerce')
        # Apply negative sign where parentheses were found
        result = result.where(~is_negative, -result.abs())
        return result

    out = pd.DataFrame({
        "entry_time": pd.to_datetime(df[mapping["entry_time"]], errors='coerce'),
        "exit_time": pd.to_datetime(df[mapping["exit_time"]], errors='coerce'),
        "pnl": to_num_clean(df[mapping["pnl"]])
    })
    if "side" in mapping:
        out["side"] = df[mapping["side"]].astype(str).str.lower().replace({"long":"long", "short":"short", "buy":"long", "sell":"short"})
    if "entry_price" in mapping:
        out["entry_price"] = to_num_clean(df[mapping["entry_price"]])
    if "exit_price" in mapping:
        out["exit_price"] = to_num_clean(df[mapping["exit_price"]])

    # If side missing, attempt to infer from prices and pnl
    if "side" not in out.columns:
        if "entry_price" in out.columns and "exit_price" in out.columns:
            price_diff = out["exit_price"] - out["entry_price"]
            # Heuristic: if pnl >= 0, side follows price move; if pnl < 0, side is opposite
            out["side"] = np.where(
                out["pnl"].fillna(0) >= 0,
                np.where(price_diff.fillna(0) >= 0, "long", "short"),
                np.where(price_diff.fillna(0) >= 0, "short", "long")
            )
        else:
            # Fallback: assume long for non-negative pnl, short otherwise
            out["side"] = np.where(out["pnl"].fillna(0) >= 0, "long", "short")

    # Drop rows with no times
    out = out.dropna(subset=["entry_time", "exit_time"]).reset_index(drop=True)
    return out


def match_trades(generated: pd.DataFrame, baseline: pd.DataFrame, time_tol_s: int, price_tick_tol: float, pnl_tol: float, tick_size: float = 0.25) -> Tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """Return (matched_ok, matched_pnl_diff, extra_generated, missing_generated)."""
    if generated.empty and baseline.empty:
        return (pd.DataFrame(), pd.DataFrame(), pd.DataFrame(), pd.DataFrame())

    # Index baseline by side for speed
    base = baseline.copy().reset_index().rename(columns={"index": "baseline_idx"})
    gen = generated.copy().reset_index().rename(columns={"index": "generated_idx"})

    used_baseline = set()
    rows_ok = []
    rows_pnl_diff = []

    # Precompute seconds columns
    gen["entry_sec"] = gen["entry_time"].astype("int64") // 1_000_000_000
    base["entry_sec"] = base["entry_time"].astype("int64") // 1_000_000_000

    for _, g in gen.iterrows():
        # CONSTRAINT: Only match trades from the same trading date to avoid cross-day errors
        g_date = g.entry_time.date()
        
        candidates = base[
            (base.side == g.side) & 
            (base.entry_time.dt.date == g_date) &
            (~base.baseline_idx.isin(list(used_baseline)))
        ]
        if candidates.empty:
            continue
        # filter by entry time window
        cand = candidates[(candidates["entry_sec"].sub(g["entry_sec"]).abs() <= time_tol_s)]
        if cand.empty:
            # choose nearest from SAME DATE only (don't match across days!)
            cand = candidates.iloc[[int((candidates["entry_sec"] - g["entry_sec"]).abs().argmin())]]
        else:
            # pick closest by time
            cand = cand.iloc[[int((cand["entry_sec"] - g["entry_sec"]).abs().argmin())]]

        b = cand.iloc[0]
        used_baseline.add(int(b.baseline_idx))

        # Compute differences
        pnl_delta = float(g.pnl) - float(b.pnl)
        entry_time_delta_s = abs(int(g.entry_sec) - int(b.entry_sec))
        exit_time_delta_s = abs(int((g.exit_time.value - b.exit_time.value) // 1_000_000_000)) if not pd.isna(b.exit_time) else np.nan

        # Optional price comparison if present
        price_delta_ticks = np.nan
        if ("entry_price" in g) and ("entry_price" in b) and not pd.isna(b.get("entry_price", np.nan)):
            price_delta_ticks = abs(float(g.get("entry_price", np.nan)) - float(b.get("entry_price", np.nan))) / tick_size

        same_by_pnl = abs(pnl_delta) <= pnl_tol
        same_by_time = entry_time_delta_s <= time_tol_s
        same_by_price = (np.isnan(price_delta_ticks) or price_delta_ticks <= price_tick_tol)

        # Track winner/loser outcomes
        gen_outcome = "winner" if g.pnl > 0 else "loser" if g.pnl < 0 else "breakeven"
        base_outcome = "winner" if b.pnl > 0 else "loser" if b.pnl < 0 else "breakeven"
        outcome_flipped = (g.pnl > 0) != (b.pnl > 0) and g.pnl != 0 and b.pnl != 0

        record = {
            "generated_idx": int(g.generated_idx),
            "baseline_idx": int(b.baseline_idx),
            "side": g.side,
            "gen_entry_time": g.entry_time,
            "base_entry_time": b.entry_time,
            "gen_exit_time": g.exit_time,
            "base_exit_time": b.exit_time,
            "gen_entry_price": g.get("entry_price", np.nan),
            "base_entry_price": b.get("entry_price", np.nan),
            "gen_exit_price": g.get("exit_price", np.nan),
            "base_exit_price": b.get("exit_price", np.nan),
            "gen_pnl": g.pnl,
            "base_pnl": b.pnl,
            "gen_outcome": gen_outcome,
            "base_outcome": base_outcome,
            "outcome_flipped": outcome_flipped,
            "pnl_delta": pnl_delta,
            "entry_time_delta_s": entry_time_delta_s,
            "exit_time_delta_s": exit_time_delta_s,
            "entry_price_delta_ticks": price_delta_ticks,
        }
        if same_by_pnl and same_by_time and same_by_price:
            rows_ok.append(record)
        else:
            rows_pnl_diff.append(record)

    matched_ok = pd.DataFrame(rows_ok)
    matched_pnl_diff = pd.DataFrame(rows_pnl_diff)

    # Extras/missing
    matched_base_idxs = set(matched_ok.get("baseline_idx", pd.Series(dtype=int)).tolist() + matched_pnl_diff.get("baseline_idx", pd.Series(dtype=int)).tolist())
    matched_gen_idxs = set(matched_ok.get("generated_idx", pd.Series(dtype=int)).tolist() + matched_pnl_diff.get("generated_idx", pd.Series(dtype=int)).tolist())

    extra_generated = gen[~gen.generated_idx.isin(list(matched_gen_idxs))]
    missing_generated = base[~base.baseline_idx.isin(list(matched_base_idxs))]

    return matched_ok, matched_pnl_diff, extra_generated, missing_generated


def main():
    parser = argparse.ArgumentParser(description="Compare generated trades to a baseline CSV with fuzzy matching.")
    parser.add_argument("--baseline", required=True, help="Path to baseline CSV (e.g., wicktestsep25.csv)")
    parser.add_argument("--contract", default="NQ SEP25", help="Contract folder name under storage/parquet")
    parser.add_argument("--strategy", default="wicktest", help="Strategy name")
    parser.add_argument("--start-date", default="2025-06-16", help="YYYY-MM-DD")
    parser.add_argument("--end-date", default="2025-09-12", help="YYYY-MM-DD")
    parser.add_argument("--commission", type=float, default=0.0, help="Commission per contract for generated trades")
    parser.add_argument("--slippage-ticks", type=int, default=0, help="Slippage in ticks for generated trades")
    parser.add_argument("--time-tol-s", type=int, default=10, help="Time tolerance in seconds for matching")
    parser.add_argument("--price-tick-tol", type=float, default=2.0, help="Entry price tolerance in ticks")
    parser.add_argument("--pnl-tol", type=float, default=40.0, help="P&L tolerance in dollars (NQ: $5 per tick; e.g., 40 ≈ 8 ticks)")
    parser.add_argument("--outdir", default=str(PROJECT_ROOT / "results"), help="Directory to write reports")
    parser.add_argument("--min-entry-time", default=None, help="Optional minimum entry time-of-day filter (ET), format HH:MM:SS; filters both generated and baseline entries")
    parser.add_argument("--workers", type=int, default=0, help="Number of parallel workers (0=auto)")
    parser.add_argument("--show-trades", action="store_true", help="Print concise trade tables to console for differences")
    parser.add_argument("--print-limit", type=int, default=None, help="Max rows to print per table when --show-trades is set (None=all)")
    # Memory/performance tuning options
    parser.add_argument("--l2-chunk-size", type=int, default=1_000_000, help="L2 chunk size per worker; smaller reduces RAM usage")
    parser.add_argument("--no-order-book", action="store_true", help="Disable order book (L2) to reduce memory usage")
    parser.add_argument("--no-l2-streaming", action="store_true", help="Disable L2 streaming mode")

    args = parser.parse_args()

    start_date = datetime.strptime(args.start_date, "%Y-%m-%d")
    end_date = datetime.strptime(args.end_date, "%Y-%m-%d")

    # Determine workers adaptively when 0
    workers = args.workers
    if workers == 0:
        try:
            cpu = os.cpu_count() or 1
            workers = max(1, min(8, cpu - 2))
        except Exception:
            workers = 1

    print(f"Collecting generated trades for {args.contract} {start_date.date()}..{end_date.date()} using {args.strategy} with workers={workers}...")
    gen_df = collect_generated_trades(
        contract=args.contract,
        start_date=start_date,
        end_date=end_date,
        strategy=args.strategy,
        workers=workers,
        commission=args.commission,
        slippage_ticks=args.slippage_ticks,
        use_order_book=(not args.no_order_book),
        l2_streaming=(not args.no_l2_streaming),
        l2_chunk_size=int(args.l2_chunk_size),
    )

    print(f"Loading baseline CSV: {args.baseline}")
    base_df = load_baseline_csv(Path(args.baseline))

    # Optional filter: minimum entry time-of-day (ET)
    if args.min_entry_time:
        try:
            from datetime import datetime as _dt
            min_t = _dt.strptime(args.min_entry_time, "%H:%M:%S").time()
            def _tod(s: pd.Series) -> pd.Series:
                return s.dt.time
            gen_before = len(gen_df)
            base_before = len(base_df)
            gen_df = gen_df[_tod(gen_df["entry_time"]) >= min_t].copy()
            base_df = base_df[_tod(base_df["entry_time"]) >= min_t].copy()
            print(f"Applied min entry time filter >= {args.min_entry_time} ET: generated {gen_before}->{len(gen_df)}, baseline {base_before}->{len(base_df)}")
        except Exception as e:
            print(f"Warning: failed to apply --min-entry-time filter '{args.min_entry_time}': {e}")

    print(f"Matching trades with tolerances: time={args.time_tol_s}s, price_ticks={args.price_tick_tol}, pnl=${args.pnl_tol}")
    matched_ok, matched_pnl_diff, extra_gen, missing_gen = match_trades(
        gen_df, base_df, time_tol_s=args.time_tol_s, price_tick_tol=args.price_tick_tol, pnl_tol=args.pnl_tol
    )

    outdir = Path(args.outdir)
    outdir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")

    ok_path = outdir / f"trade_match_ok_{stamp}.csv"
    diff_path = outdir / f"trade_match_pnl_diff_{stamp}.csv"
    extra_path = outdir / f"trade_extra_generated_{stamp}.csv"
    missing_path = outdir / f"trade_missing_generated_{stamp}.csv"

    matched_ok.to_csv(ok_path, index=False)
    matched_pnl_diff.to_csv(diff_path, index=False)
    extra_gen.to_csv(extra_path, index=False)
    missing_gen.to_csv(missing_path, index=False)

    # Richer summary
    print("\nSummary:")
    print(f"  Generated trades: {len(gen_df)}  (sum P&L=${gen_df['pnl'].sum():.2f})")
    print(f"  Baseline trades:  {len(base_df)}  (sum P&L=${base_df['pnl'].sum():.2f})")
    print(f"  Matched OK:       {len(matched_ok)}")
    if not matched_pnl_diff.empty:
        abs_pnl_delta_mean = matched_pnl_diff['pnl_delta'].abs().dropna().mean()
        abs_pnl_delta_med = matched_pnl_diff['pnl_delta'].abs().dropna().median()
        time_delta_mean = matched_pnl_diff['entry_time_delta_s'].dropna().mean()
        # Count outcome flips (winner↔loser)
        flipped_count = matched_pnl_diff.get('outcome_flipped', pd.Series(dtype=bool)).sum()
        print(f"  P&L/time/price diffs: {len(matched_pnl_diff)} (mean |ΔPnL|=${abs_pnl_delta_mean:.2f}, median |ΔPnL|=${abs_pnl_delta_med:.2f}, mean Δt={time_delta_mean:.1f}s)")
        if flipped_count > 0:
            print(f"  ⚠️  Outcome FLIPPED (winner↔loser): {flipped_count}")
    else:
        print(f"  P&L/time/price diffs: 0")
    print(f"  In baseline only (missing vs base): {len(missing_gen)}")
    print(f"  In generated only (extra generated): {len(extra_gen)}")

    print("\nReports written to:")
    print(f"  {ok_path}")
    print(f"  {diff_path}")
    print(f"  {extra_path}")
    print(f"  {missing_path}")

    # Optional on-console tables
    if args.show_trades:
        def print_table(df: pd.DataFrame, title: str, cols: List[str]):
            limit = args.print_limit if args.print_limit else len(df)
            print(f"\n=== {title} (showing {min(limit, len(df))} of {len(df)}) ===")
            if df.empty:
                print("<none>")
                return
            use_cols = [c for c in cols if c in df.columns]
            preview = df[use_cols].copy().head(limit) if limit else df[use_cols].copy()
            # Narrow formatting for times and floats
            with pd.option_context('display.max_rows', None if not limit else limit, 'display.width', 200):
                print(preview.to_string(index=False))

        # Show baseline-only (missing_gen)
        print_table(
            missing_gen,
            "Trades in BASELINE CSV only",
            ["baseline_idx", "side", "entry_time", "exit_time", "entry_price", "exit_price", "pnl"]
        )

        # Show generated-only (extra_gen)
        print_table(
            extra_gen,
            "Trades in GENERATED run only",
            ["generated_idx", "side", "entry_time", "exit_time", "entry_price", "exit_price", "pnl"]
        )

        # Show a few mismatched pairs with deltas
        print_table(
            matched_pnl_diff,
            "Closest matches with differences (pairwise)",
            [
                "generated_idx", "baseline_idx", "side",
                "gen_entry_time", "base_entry_time", "entry_time_delta_s",
                "gen_entry_price", "base_entry_price", "entry_price_delta_ticks",
                "gen_pnl", "base_pnl", "pnl_delta",
                "gen_outcome", "base_outcome", "outcome_flipped"
            ]
        )


if __name__ == "__main__":
    main()
