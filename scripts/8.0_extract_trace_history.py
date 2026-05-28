#!/usr/bin/env python
from __future__ import annotations

import argparse
import json
import math
import os
import re
import shutil
import sys
import tarfile
import time
import traceback
from concurrent.futures import ProcessPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd

_ENGINE = None


def utc_stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def parse_date(s: str) -> date:
    return datetime.strptime(s, "%Y-%m-%d").date()


def sql_quote(x: str) -> str:
    return "'" + str(x).replace("'", "''") + "'"


def safe_tag(x: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]+", "_", str(x))


def rel(path: Path, root: Path) -> str:
    try:
        return str(path.relative_to(root))
    except Exception:
        return str(path)


def ensure_clean_link_or_copy(src: Path, dst: Path) -> None:
    dst.parent.mkdir(parents=True, exist_ok=True)
    if dst.exists():
        return
    try:
        os.link(src, dst)
    except Exception:
        shutil.copy2(src, dst)


def read_eligible_cusips(path: Path, max_cusips: int | None = None, seed: int = 1729) -> list[str]:
    df = pd.read_parquet(path, columns=["cusip"])
    cusips = df["cusip"].dropna().astype(str).str.strip().unique().tolist()
    cusips = sorted(c for c in cusips if c)
    if max_cusips is not None and max_cusips > 0 and max_cusips < len(cusips):
        import numpy as np
        rng = np.random.default_rng(seed)
        cusips = sorted(rng.choice(cusips, size=max_cusips, replace=False).tolist())
    return cusips


def chunks(xs: list[str], n: int) -> list[list[str]]:
    return [xs[i : i + n] for i in range(0, len(xs), n)]


@dataclass(frozen=True)
class TraceTask:
    year: int
    chunk_id: int
    start_date: str
    end_date: str
    cusips: tuple[str, ...]


def init_worker() -> None:
    """Initialize one read-only PostgreSQL engine per worker.

    This avoids PyWRDS interactive input() inside multiprocessing workers.
    Credentials are read by libpq/psycopg2 from ~/.pgpass.
    """
    global _ENGINE
    import os
    import sqlalchemy as sa

    user = os.environ.get("WRDS_USERNAME", "nt612")
    host = os.environ.get("WRDS_HOST", "wrds-pgdata.wharton.upenn.edu")
    port = os.environ.get("WRDS_PORT", "9737")
    dbname = os.environ.get("WRDS_DBNAME", "wrds")

    url = f"postgresql+psycopg2://{user}@{host}:{port}/{dbname}"
    _ENGINE = sa.create_engine(
        url,
        connect_args={"sslmode": "require"},
        pool_pre_ping=True,
        pool_size=1,
        max_overflow=0,
    )


def query_one_task(task_dict: dict[str, Any]) -> dict[str, Any]:
    """Run one read-only WRDS aggregation task and write one parquet part."""
    global _ENGINE

    root = Path(task_dict["root"])
    tag = task_dict["tag"]
    source = task_dict["source"]
    part_root = Path(task_dict["part_root"])
    resume = bool(task_dict["resume"])
    min_price = float(task_dict["min_price"])
    max_price = float(task_dict["max_price"])
    min_yield = float(task_dict["min_yield"])
    max_yield = float(task_dict["max_yield"])
    task = TraceTask(**task_dict["task"])

    part_dir = part_root / f"y{task.year}"
    part_dir.mkdir(parents=True, exist_ok=True)
    part_path = part_dir / f"part_y{task.year}_c{task.chunk_id:05d}.parquet"
    status_path = part_dir / f"part_y{task.year}_c{task.chunk_id:05d}.json"

    if resume and status_path.exists():
        try:
            status = json.loads(status_path.read_text())
            if status.get("ok") and (status.get("rows", 0) == 0 or part_path.exists()):
                status["skipped_resume"] = True
                return status
        except Exception:
            pass

    started = time.time()
    out: dict[str, Any] = {
        "ok": False,
        "tag": tag,
        "year": task.year,
        "chunk_id": task.chunk_id,
        "start_date": task.start_date,
        "end_date": task.end_date,
        "n_cusips_query": len(task.cusips),
        "part_path": str(part_path),
        "error": None,
        "rows": 0,
        "n_trades": 0,
        "n_cusips_result": 0,
        "elapsed_sec": None,
    }

    try:
        if _ENGINE is None:
            init_worker()

        cusip_sql = ",".join(sql_quote(c) for c in task.cusips)

        # Read-only, server-side aggregation. No CREATE/DROP/TEMP tables.
        query = f"""
        select
            cusip_id::varchar as cusip,
            trd_exctn_dt::date as trade_date,
            count(*)::bigint as n_trades,
            avg(rptd_pr)::float8 as price_mean,
            avg(yld_pt)::float8 as yield_mean,
            sum(entrd_vol_qt)::float8 as size_sum,
            min(rptd_pr)::float8 as price_min,
            max(rptd_pr)::float8 as price_max,
            min(yld_pt)::float8 as yield_min,
            max(yld_pt)::float8 as yield_max
        from {source}
        where cusip_id in ({cusip_sql})
          and trd_exctn_dt >= date '{task.start_date}'
          and trd_exctn_dt <  date '{task.end_date}'
          and rptd_pr is not null
          and yld_pt is not null
          and entrd_vol_qt is not null
          and rptd_pr between {min_price} and {max_price}
          and yld_pt between {min_yield} and {max_yield}
        group by cusip_id, trd_exctn_dt
        order by cusip_id, trd_exctn_dt
        """

        df = pd.read_sql_query(query, _ENGINE)
        if len(df):
            df["cusip"] = df["cusip"].astype(str)
            df["trade_date"] = pd.to_datetime(df["trade_date"])
            df["year"] = int(task.year)
            df.to_parquet(part_path, index=False)

        out.update(
            {
                "ok": True,
                "rows": int(len(df)),
                "n_trades": int(df["n_trades"].sum()) if len(df) else 0,
                "n_cusips_result": int(df["cusip"].nunique()) if len(df) else 0,
                "min_trade_date": str(df["trade_date"].min()) if len(df) else None,
                "max_trade_date": str(df["trade_date"].max()) if len(df) else None,
                "elapsed_sec": round(time.time() - started, 3),
            }
        )

    except Exception as exc:
        out["error"] = repr(exc)
        out["traceback"] = traceback.format_exc()
        out["elapsed_sec"] = round(time.time() - started, 3)

    status_path.write_text(json.dumps(out, indent=2, sort_keys=True))
    return out


def build_tasks(
    cusips: list[str],
    start_year: int,
    end_year: int,
    global_start: str,
    global_end: str,
    chunk_size: int,
) -> list[TraceTask]:
    cchunks = chunks(cusips, chunk_size)
    gs = parse_date(global_start)
    ge = parse_date(global_end)

    out: list[TraceTask] = []
    for year in range(start_year, end_year + 1):
        ys = max(gs, date(year, 1, 1))
        ye = min(ge, date(year + 1, 1, 1))
        if ys >= ye:
            continue
        for j, chunk in enumerate(cchunks):
            out.append(
                TraceTask(
                    year=year,
                    chunk_id=j,
                    start_date=ys.isoformat(),
                    end_date=ye.isoformat(),
                    cusips=tuple(chunk),
                )
            )
    return out


def link_parts_to_datasets(root: Path, tag: str, part_root: Path, years: list[int]) -> dict[str, str]:
    """Create per-year parquet dataset directories and one combined directory via hardlinks/copies."""
    interim = root / "artifacts" / "interim"
    combined = interim / f"4.1_trace_daily_agg_{tag}.parquet"
    combined.mkdir(parents=True, exist_ok=True)

    paths: dict[str, str] = {"combined": str(combined)}
    for year in years:
        year_dataset = interim / f"4.1_trace_daily_agg_{tag}_{year}.parquet"
        year_dataset.mkdir(parents=True, exist_ok=True)
        paths[str(year)] = str(year_dataset)

        year_parts = sorted((part_root / f"y{year}").glob("*.parquet"))
        for p in year_parts:
            ensure_clean_link_or_copy(p, year_dataset / p.name)
            ensure_clean_link_or_copy(p, combined / p.name)

        (year_dataset / "_SUCCESS").write_text(datetime.now(timezone.utc).isoformat())

    (combined / "_SUCCESS").write_text(datetime.now(timezone.utc).isoformat())
    return paths


def compute_monthly_coverage(part_files: list[Path]) -> pd.DataFrame:
    rows = []
    for p in part_files:
        try:
            df = pd.read_parquet(
                p,
                columns=["trade_date", "cusip", "n_trades", "size_sum", "yield_mean"],
            )
            if df.empty:
                continue
            df["trade_date"] = pd.to_datetime(df["trade_date"])
            df["month"] = df["trade_date"].dt.to_period("M").dt.to_timestamp("M")
            g = df.groupby("month", observed=True).agg(
                rows=("cusip", "size"),
                cusips=("cusip", "nunique"),
                trades=("n_trades", "sum"),
                size_sum=("size_sum", "sum"),
                yield_x_rows=("yield_mean", "sum"),
            ).reset_index()
            rows.append(g)
        except Exception as exc:
            print(f"[WARN] coverage read failed for {p}: {exc}")

    if not rows:
        return pd.DataFrame(columns=["month", "rows", "cusips", "trades", "size_sum", "yield_mean"])

    allg = pd.concat(rows, ignore_index=True)
    out = allg.groupby("month", observed=True).agg(
        rows=("rows", "sum"),
        cusips=("cusips", "sum"),  # chunks are disjoint by CUSIP, so this is exact within month
        trades=("trades", "sum"),
        size_sum=("size_sum", "sum"),
        yield_x_rows=("yield_x_rows", "sum"),
    ).reset_index()
    out["yield_mean"] = out["yield_x_rows"] / out["rows"].where(out["rows"] != 0, pd.NA)
    out = out.drop(columns=["yield_x_rows"])
    return out.sort_values("month")


def make_report(
    root: Path,
    tag: str,
    args: argparse.Namespace,
    results: list[dict[str, Any]],
    dataset_paths: dict[str, str],
    monthly: pd.DataFrame,
) -> None:
    disc = root / "artifacts" / "discovery"
    disc.mkdir(parents=True, exist_ok=True)

    ok = [r for r in results if r.get("ok")]
    bad = [r for r in results if not r.get("ok")]
    rows_total = sum(int(r.get("rows", 0) or 0) for r in ok)
    trades_total = sum(int(r.get("n_trades", 0) or 0) for r in ok)

    status_csv = disc / f"8.0_trace_history_task_status_{tag}.csv"
    pd.DataFrame(results).to_csv(status_csv, index=False)

    summary = {
        "tag": tag,
        "run_utc": datetime.now(timezone.utc).isoformat(),
        "trace_source": args.trace_source,
        "start_year": args.start_year,
        "end_year": args.end_year,
        "start_date": args.start_date,
        "end_date": args.end_date,
        "chunk_size": args.chunk_size,
        "workers": args.workers,
        "tasks_total": len(results),
        "tasks_ok": len(ok),
        "tasks_failed": len(bad),
        "aggregated_rows": int(rows_total),
        "raw_trades_represented": int(trades_total),
        "dataset_paths": dataset_paths,
        "status_csv": rel(status_csv, root),
    }

    summary_path = disc / f"8.0_trace_history_summary_{tag}.json"
    summary_path.write_text(json.dumps(summary, indent=2, sort_keys=True))

    monthly_path = disc / f"8.0_trace_history_monthly_coverage_{tag}.csv"
    monthly.to_csv(monthly_path, index=False)

    report = [
        f"# 8.0 TRACE historical extraction report ({tag})",
        "",
        f"- Run UTC: `{summary['run_utc']}`",
        f"- TRACE source: `{args.trace_source}`",
        f"- Date window: `{args.start_date}` to `{args.end_date}`",
        f"- Years: `{args.start_year}` to `{args.end_year}`",
        f"- Workers: `{args.workers}`",
        f"- Chunk size: `{args.chunk_size}`",
        f"- Tasks total: `{len(results)}`",
        f"- Tasks completed: `{len(ok)}`",
        f"- Tasks failed: `{len(bad)}`",
        f"- Aggregated bond-day rows: `{rows_total}`",
        f"- Approx raw trades represented: `{trades_total}`",
        "",
        "## Output datasets",
        "",
        f"- Combined: `{rel(Path(dataset_paths['combined']), root)}`",
    ]

    for year in range(args.start_year, args.end_year + 1):
        if str(year) in dataset_paths:
            report.append(f"- {year}: `{rel(Path(dataset_paths[str(year)]), root)}`")

    report += ["", "## Monthly coverage", ""]
    if not monthly.empty:
        report.append(monthly.to_string(index=False))
    else:
        report.append("No rows extracted.")

    if bad:
        report += ["", "## Failed tasks", "", pd.DataFrame(bad).head(20).to_string(index=False)]

    report += [
        "",
        "## Next step",
        "",
        f"Run `bash run_8.1_curve_targets_baseline_history.sh` with `TAG={tag}` after validating failed tasks are zero.",
        "",
    ]

    report_path = disc / f"8.0_trace_history_report_{tag}.md"
    report_path.write_text("\n".join(report), encoding="utf-8")

    print("[WROTE]", report_path)
    print("[WROTE]", summary_path)
    print("[WROTE]", monthly_path)


def main() -> int:
    parser = argparse.ArgumentParser(description="Parallel read-only WRDS TRACE historical extraction.")
    parser.add_argument("--project-root", default=".")
    parser.add_argument("--eligible-bonds", default="artifacts/interim/4.0_fisd_eligible_bonds.parquet")
    parser.add_argument("--trace-source", default="wrdsapps_bondret.trace_enhanced_clean")
    parser.add_argument("--start-year", type=int, default=2004)
    parser.add_argument("--end-year", type=int, default=2025)
    parser.add_argument("--start-date", default="2004-01-01")
    parser.add_argument("--end-date", default="2026-01-01")
    parser.add_argument("--tag", default="full2004_2025")
    parser.add_argument("--chunk-size", type=int, default=int(os.environ.get("TRACE_CHUNK_SIZE", "1000")))
    parser.add_argument("--workers", type=int, default=int(os.environ.get("TRACE_WORKERS", "8")))
    parser.add_argument("--max-cusips", type=int, default=None)
    parser.add_argument("--sample-seed", type=int, default=1729)
    parser.add_argument("--min-price", type=float, default=1.0)
    parser.add_argument("--max-price", type=float, default=250.0)
    parser.add_argument("--min-yield", type=float, default=-25.0)
    parser.add_argument("--max-yield", type=float, default=100.0)
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--bundle", action="store_true")
    args = parser.parse_args()

    root = Path(args.project_root).resolve()
    tag = safe_tag(args.tag)
    disc = root / "artifacts" / "discovery"
    interim = root / "artifacts" / "interim"
    logs = root / "logs"
    for p in [disc, interim, logs]:
        p.mkdir(parents=True, exist_ok=True)

    print("=" * 80)
    print("8.0 historical TRACE extraction")
    print("UTC:", datetime.now(timezone.utc).isoformat())
    print("Project:", root)
    print("Tag:", tag)
    print("Workers:", args.workers)
    print("Chunk size:", args.chunk_size)
    print("Date window:", args.start_date, "to", args.end_date)
    print("=" * 80)

    eligible_path = root / args.eligible_bonds
    cusips = read_eligible_cusips(eligible_path, max_cusips=args.max_cusips, seed=args.sample_seed)
    print(f"[CUSIPS] {len(cusips):,} eligible CUSIPs loaded from {eligible_path}")

    tasks = build_tasks(cusips, args.start_year, args.end_year, args.start_date, args.end_date, args.chunk_size)
    print(f"[TASKS] {len(tasks):,} year × CUSIP-chunk tasks")

    part_root = interim / f"trace_parts_{tag}"
    part_root.mkdir(parents=True, exist_ok=True)

    task_dicts = []
    for t in tasks:
        task_dicts.append(
            {
                "root": str(root),
                "tag": tag,
                "source": args.trace_source,
                "part_root": str(part_root),
                "resume": bool(args.resume),
                "min_price": args.min_price,
                "max_price": args.max_price,
                "min_yield": args.min_yield,
                "max_yield": args.max_yield,
                "task": {
                    "year": t.year,
                    "chunk_id": t.chunk_id,
                    "start_date": t.start_date,
                    "end_date": t.end_date,
                    "cusips": t.cusips,
                },
            }
        )

    results: list[dict[str, Any]] = []
    start = time.time()
    progress_path = disc / f"8.0_trace_history_progress_{tag}.jsonl"

    with ProcessPoolExecutor(max_workers=max(1, args.workers), initializer=init_worker) as ex:
        future_map = {ex.submit(query_one_task, td): td["task"] for td in task_dicts}
        for k, fut in enumerate(as_completed(future_map), 1):
            res = fut.result()
            results.append(res)
            with progress_path.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(res, sort_keys=True) + "\n")
            if k == 1 or k % 25 == 0 or k == len(task_dicts):
                ok = sum(1 for r in results if r.get("ok"))
                bad = sum(1 for r in results if not r.get("ok"))
                rows = sum(int(r.get("rows", 0) or 0) for r in results if r.get("ok"))
                trades = sum(int(r.get("n_trades", 0) or 0) for r in results if r.get("ok"))
                elapsed = (time.time() - start) / 60.0
                rate = k / max(elapsed, 1e-9)
                remain = (len(task_dicts) - k) / max(rate, 1e-9)
                print(
                    f"[PROGRESS] {k:,}/{len(task_dicts):,} tasks | ok={ok:,} bad={bad:,} "
                    f"rows={rows:,} trades={trades:,} elapsed={elapsed:.1f}m eta={remain:.1f}m",
                    flush=True,
                )

    years = list(range(args.start_year, args.end_year + 1))
    dataset_paths = link_parts_to_datasets(root, tag, part_root, years)
    part_files = sorted(part_root.glob("y*/*.parquet"))
    monthly = compute_monthly_coverage(part_files)
    make_report(root, tag, args, results, dataset_paths, monthly)

    if args.bundle:
        bundle = root / f"step8_0_trace_history_logs_reports_{tag}_{utc_stamp()}.tar.gz"
        with tarfile.open(bundle, "w:gz") as tar:
            for relp in ["logs", "artifacts/discovery", "configs", "scripts/8.0_extract_trace_history.py"]:
                p = root / relp
                if p.exists():
                    tar.add(p, arcname=relp)
        print("[BUNDLE]", bundle)

    failed = sum(1 for r in results if not r.get("ok"))
    print("[DONE] failed tasks:", failed)
    return 0 if failed == 0 else 2


if __name__ == "__main__":
    raise SystemExit(main())
