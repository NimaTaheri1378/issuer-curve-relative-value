#!/usr/bin/env python
from __future__ import annotations

import argparse
import json
import math
import os
import re
import sys
import tarfile
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

import pandas as pd
import wrds


def utc_stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def ensure_dir(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    return path


def q(s: str) -> str:
    """SQL single-quote a CUSIP-like string."""
    return "'" + str(s).replace("'", "''") + "'"


def parse_source(src: str) -> tuple[str, str]:
    if "." not in src:
        raise ValueError("--trace-source must be library.table")
    lib, tab = src.split(".", 1)
    if not lib or not tab:
        raise ValueError("--trace-source must be library.table")
    return lib, tab


def split_chunks(items: list[str], chunk_size: int) -> Iterable[tuple[int, list[str]]]:
    for start in range(0, len(items), chunk_size):
        yield start, items[start : start + chunk_size]


def safe_panel_load(path: Path) -> pd.DataFrame:
    if not path.exists():
        raise FileNotFoundError(f"Missing eligible bonds parquet: {path}")
    df = pd.read_parquet(path)
    if "cusip" not in df.columns:
        raise ValueError(f"Expected column 'cusip' in {path}; columns={list(df.columns)}")
    return df


def make_query(
    trace_source: str,
    cusips: list[str],
    start_date: str,
    end_date: str,
    min_price: float,
    max_price: float,
    min_yield: float,
    max_yield: float,
) -> str:
    cusip_sql = ",".join(q(c) for c in cusips)
    return f"""
        SELECT
            cusip_id AS cusip,
            trd_exctn_dt AS trade_date,
            COUNT(*)::bigint AS n_trades,
            AVG(rptd_pr)::double precision AS price_mean,
            AVG(yld_pt)::double precision AS yield_mean,
            SUM(entrd_vol_qt)::double precision AS size_sum,
            MIN(rptd_pr)::double precision AS price_min,
            MAX(rptd_pr)::double precision AS price_max,
            MIN(yld_pt)::double precision AS yield_min,
            MAX(yld_pt)::double precision AS yield_max
        FROM {trace_source}
        WHERE cusip_id IN ({cusip_sql})
          AND trd_exctn_dt >= DATE '{start_date}'
          AND trd_exctn_dt <  DATE '{end_date}'
          AND rptd_pr IS NOT NULL
          AND yld_pt IS NOT NULL
          AND entrd_vol_qt IS NOT NULL
          AND rptd_pr BETWEEN {float(min_price)} AND {float(max_price)}
          AND yld_pt BETWEEN {float(min_yield)} AND {float(max_yield)}
        GROUP BY cusip_id, trd_exctn_dt
        ORDER BY cusip_id, trd_exctn_dt
    """


def combine_partitions(parts_dir: Path, combined_path: Path) -> pd.DataFrame:
    files = sorted(parts_dir.glob("part_*.parquet"))
    if not files:
        raise RuntimeError(f"No TRACE part files found in {parts_dir}")

    frames = []
    for f in files:
        try:
            d = pd.read_parquet(f)
            if len(d):
                frames.append(d)
        except Exception as exc:
            print(f"[WARN] could not read {f}: {exc}")

    if not frames:
        out = pd.DataFrame(
            columns=[
                "cusip",
                "trade_date",
                "n_trades",
                "price_mean",
                "yield_mean",
                "size_sum",
                "price_min",
                "price_max",
                "yield_min",
                "yield_max",
            ]
        )
    else:
        out = pd.concat(frames, ignore_index=True)
        out["trade_date"] = pd.to_datetime(out["trade_date"])
        out = out.sort_values(["cusip", "trade_date"]).reset_index(drop=True)

    combined_path.parent.mkdir(parents=True, exist_ok=True)
    out.to_parquet(combined_path, index=False)
    return out


def write_reports(
    root: Path,
    tag: str,
    summary: dict,
    combined: pd.DataFrame,
    errors: list[dict],
) -> None:
    disc = ensure_dir(root / "artifacts" / "discovery")
    fig_dir = ensure_dir(root / "reports" / "figures")

    summary_path = disc / f"4.1_trace_summary_{tag}.json"
    summary_path.write_text(json.dumps(summary, indent=2, sort_keys=True, default=str), encoding="utf-8")

    if len(combined):
        monthly = combined.copy()
        monthly["month"] = pd.to_datetime(monthly["trade_date"]).dt.to_period("M").dt.to_timestamp("M")
        monthly_cov = (
            monthly.groupby("month", as_index=False)
            .agg(
                rows=("cusip", "size"),
                cusips=("cusip", "nunique"),
                trades=("n_trades", "sum"),
                size_sum=("size_sum", "sum"),
                yield_mean=("yield_mean", "mean"),
            )
            .sort_values("month")
        )
    else:
        monthly_cov = pd.DataFrame(columns=["month", "rows", "cusips", "trades", "size_sum", "yield_mean"])

    monthly_path = disc / f"4.1_trace_monthly_coverage_{tag}.csv"
    monthly_cov.to_csv(monthly_path, index=False)

    errors_path = disc / f"4.1_trace_errors_{tag}.json"
    errors_path.write_text(json.dumps(errors, indent=2, sort_keys=True, default=str), encoding="utf-8")

    # Figures are optional; skip gracefully if matplotlib unavailable.
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt

        if len(monthly_cov):
            fig, ax = plt.subplots(figsize=(10, 4.8))
            ax.bar(monthly_cov["month"].astype(str), monthly_cov["rows"].astype(float))
            ax.set_title(f"TRACE bond-day coverage by month ({tag})")
            ax.set_ylabel("Bond-day rows")
            ax.set_xlabel("Month")
            ax.tick_params(axis="x", rotation=45)
            ax.grid(axis="y", alpha=0.25)
            fig.tight_layout()
            fig.savefig(fig_dir / f"4.1_trace_monthly_coverage_{tag}.png", dpi=220, bbox_inches="tight")
            fig.savefig(fig_dir / f"4.1_trace_monthly_coverage_{tag}.svg", bbox_inches="tight")
            plt.close(fig)

            fig, ax = plt.subplots(figsize=(8, 4.8))
            vals = combined["yield_mean"].dropna()
            vals = vals[(vals >= -5) & (vals <= 50)]
            ax.hist(vals, bins=80)
            ax.set_title(f"TRACE daily mean yield distribution ({tag})")
            ax.set_xlabel("Yield, pct")
            ax.set_ylabel("Bond-days")
            ax.grid(axis="y", alpha=0.25)
            fig.tight_layout()
            fig.savefig(fig_dir / f"4.1_trace_yield_distribution_{tag}.png", dpi=220, bbox_inches="tight")
            fig.savefig(fig_dir / f"4.1_trace_yield_distribution_{tag}.svg", bbox_inches="tight")
            plt.close(fig)
    except Exception as exc:
        print(f"[WARN] figure generation skipped: {exc}")

    preview = combined.head(15) if len(combined) else combined
    report = [
        f"# 4.1 TRACE extraction report ({tag})",
        "",
        f"- Run UTC: `{summary.get('run_utc')}`",
        f"- TRACE source: `{summary.get('trace_source')}`",
        f"- Date window: `{summary.get('start_date')}` to `{summary.get('end_date')}`",
        f"- Eligible CUSIPs considered: `{summary.get('eligible_cusips')}`",
        f"- CUSIPs queried: `{summary.get('queried_cusips')}`",
        f"- Chunk size: `{summary.get('chunk_size')}`",
        f"- Chunks total: `{summary.get('chunks_total')}`",
        f"- Chunks completed: `{summary.get('chunks_completed')}`",
        f"- Chunks failed: `{summary.get('chunks_failed')}`",
        f"- Aggregated bond-day rows: `{summary.get('aggregated_rows')}`",
        f"- Aggregated CUSIPs: `{summary.get('aggregated_cusips')}`",
        f"- Approx raw trades represented: `{summary.get('approx_trades')}`",
        "",
        "## Monthly coverage",
        "",
        monthly_cov.to_string(index=False) if len(monthly_cov) else "No rows.",
        "",
        "## Preview",
        "",
        preview.to_string(index=False) if len(preview) else "No rows.",
        "",
        "## Outputs",
        "",
        f"- `artifacts/interim/4.1_trace_daily_agg_{tag}.parquet`",
        f"- `artifacts/discovery/4.1_trace_summary_{tag}.json`",
        f"- `artifacts/discovery/4.1_trace_monthly_coverage_{tag}.csv`",
        f"- `artifacts/discovery/4.1_trace_errors_{tag}.json`",
        "",
        "## Next step",
        "",
        f"Run 5.0, 6.0, and 7.0 with tag `{tag}` if coverage is materially larger than the pilot.",
        "",
    ]

    report_path = disc / f"4.1_trace_extraction_report_{tag}.md"
    report_path.write_text("\n".join(report), encoding="utf-8")


def bundle_reports(root: Path, tag: str, run_id: str) -> Path:
    bundle = root / f"step4_1_trace_logs_reports_{tag}_{run_id}.tar.gz"
    with tarfile.open(bundle, "w:gz") as tar:
        for rel in [
            "logs",
            f"artifacts/discovery/4.1_trace_summary_{tag}.json",
            f"artifacts/discovery/4.1_trace_monthly_coverage_{tag}.csv",
            f"artifacts/discovery/4.1_trace_errors_{tag}.json",
            f"artifacts/discovery/4.1_trace_extraction_report_{tag}.md",
            "reports/figures",
            "configs",
        ]:
            path = root / rel
            if path.exists():
                tar.add(path, arcname=rel)
    return bundle


def main() -> int:
    parser = argparse.ArgumentParser(description="Read-only WRDS TRACE extraction using chunked IN lists and server-side aggregation.")
    parser.add_argument("--project-root", default=".")
    parser.add_argument("--eligible-bonds", default="artifacts/interim/4.0_fisd_eligible_bonds.parquet")
    parser.add_argument("--trace-source", default="wrdsapps_bondret.trace_enhanced_clean")
    parser.add_argument("--start-date", default="2024-01-01")
    parser.add_argument("--end-date", default="2025-01-01")
    parser.add_argument("--tag", default="full2024")
    parser.add_argument("--max-cusips", type=int, default=None, help="Optional random sample; omit for all eligible CUSIPs.")
    parser.add_argument("--sample-seed", type=int, default=1729)
    parser.add_argument("--chunk-size", type=int, default=1000)
    parser.add_argument("--min-price", type=float, default=1.0)
    parser.add_argument("--max-price", type=float, default=250.0)
    parser.add_argument("--min-yield", type=float, default=-25.0)
    parser.add_argument("--max-yield", type=float, default=100.0)
    parser.add_argument("--resume", action="store_true", help="Skip chunks whose part parquet already exists.")
    parser.add_argument("--no-bundle", action="store_true")
    args = parser.parse_args()

    root = Path(args.project_root).resolve()
    logs = ensure_dir(root / "logs")
    interim = ensure_dir(root / "artifacts" / "interim")
    parts_dir = ensure_dir(interim / f"4.1_trace_parts_{args.tag}")
    run_id = utc_stamp()
    log_path = logs / f"4.1_trace_extract_{args.tag}_{run_id}.log"

    class Tee:
        def __init__(self, *files):
            self.files = files
        def write(self, data):
            for f in self.files:
                f.write(data)
                f.flush()
        def flush(self):
            for f in self.files:
                f.flush()

    with log_path.open("w", encoding="utf-8") as log_fh:
        sys.stdout = Tee(sys.__stdout__, log_fh)
        sys.stderr = Tee(sys.__stderr__, log_fh)

        print("=" * 72)
        print(f"4.1 TRACE extraction ({args.tag})")
        print(f"Run UTC: {run_id}")
        print(f"Project: {root}")
        print(f"Python: {sys.executable}")
        print(f"Trace source: {args.trace_source}")
        print(f"Date window: {args.start_date} to {args.end_date}")
        print(f"Chunk size: {args.chunk_size}")
        print("=" * 72)

        fisd = safe_panel_load(root / args.eligible_bonds)
        cusips = sorted(set(fisd["cusip"].dropna().astype(str)))
        eligible_n = len(cusips)

        if args.max_cusips is not None and args.max_cusips < eligible_n:
            import numpy as np
            rng = np.random.default_rng(args.sample_seed)
            cusips = sorted(rng.choice(cusips, size=args.max_cusips, replace=False).tolist())

        chunks_total = math.ceil(len(cusips) / args.chunk_size)
        print(f"[CUSIPS] eligible={eligible_n:,}; queried={len(cusips):,}; chunks={chunks_total:,}")

        # quick parse validation
        parse_source(args.trace_source)

        errors: list[dict] = []
        completed = 0
        rows_accum = 0
        t0 = time.time()

        db = wrds.Connection()
        try:
            for idx, (start, chunk) in enumerate(split_chunks(cusips, args.chunk_size), start=1):
                part_path = parts_dir / f"part_{idx:05d}.parquet"
                if args.resume and part_path.exists():
                    try:
                        part_rows = len(pd.read_parquet(part_path, columns=["cusip"]))
                    except Exception:
                        part_rows = -1
                    print(f"[SKIP] chunk {idx:>5}/{chunks_total} already exists rows={part_rows}")
                    completed += 1
                    continue

                print(f"[QUERY] chunk {idx:>5}/{chunks_total} CUSIP offset {start:,}-{start+len(chunk):,}", flush=True)
                query = make_query(
                    trace_source=args.trace_source,
                    cusips=chunk,
                    start_date=args.start_date,
                    end_date=args.end_date,
                    min_price=args.min_price,
                    max_price=args.max_price,
                    min_yield=args.min_yield,
                    max_yield=args.max_yield,
                )

                try:
                    part = db.raw_sql(query)
                    if len(part):
                        part["trade_date"] = pd.to_datetime(part["trade_date"])
                    part.to_parquet(part_path, index=False)
                    completed += 1
                    rows_accum += len(part)
                    print(f"        rows={len(part):,}; cumulative_rows={rows_accum:,}; elapsed_min={(time.time()-t0)/60:.1f}")
                except Exception as exc:
                    err = {"chunk_index": idx, "offset": start, "n_cusips": len(chunk), "error": repr(exc)}
                    errors.append(err)
                    print(f"[ERROR] {err}")
        finally:
            try:
                db.close()
            except Exception:
                pass

        print("[COMBINE] reading part parquet files")
        combined_path = interim / f"4.1_trace_daily_agg_{args.tag}.parquet"
        combined = combine_partitions(parts_dir, combined_path)
        approx_trades = int(pd.to_numeric(combined.get("n_trades", pd.Series(dtype=float)), errors="coerce").fillna(0).sum()) if len(combined) else 0

        summary = {
            "run_utc": datetime.now(timezone.utc).isoformat(),
            "tag": args.tag,
            "trace_source": args.trace_source,
            "start_date": args.start_date,
            "end_date": args.end_date,
            "eligible_cusips": eligible_n,
            "queried_cusips": len(cusips),
            "chunk_size": args.chunk_size,
            "chunks_total": chunks_total,
            "chunks_completed": completed,
            "chunks_failed": len(errors),
            "aggregated_rows": int(len(combined)),
            "aggregated_cusips": int(combined["cusip"].nunique()) if len(combined) else 0,
            "approx_trades": approx_trades,
            "combined_path": str(combined_path.relative_to(root)),
            "parts_dir": str(parts_dir.relative_to(root)),
            "elapsed_seconds": round(time.time() - t0, 3),
        }

        print(f"[WROTE] {combined_path}")
        print(f"[SUMMARY] {json.dumps(summary, indent=2)}")

        write_reports(root, args.tag, summary, combined, errors)
        print(f"[WROTE] artifacts/discovery/4.1_trace_extraction_report_{args.tag}.md")

        if not args.no_bundle:
            bundle = bundle_reports(root, args.tag, run_id)
            print(f"[BUNDLE] {bundle}")

        if errors:
            print("[WARN] Some chunks failed; rerun with --resume after checking errors if needed.")
        print("[DONE] 4.1 TRACE extraction complete")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
