#!/usr/bin/env python
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tarfile
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd


def utc_stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def run_cmd(cmd: list[str], cwd: Path, log_path: Path, env: dict[str, str]) -> int:
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with log_path.open("a", encoding="utf-8") as fh:
        fh.write("\n" + "=" * 80 + "\n")
        fh.write("RUN: " + " ".join(cmd) + "\n")
        fh.write("UTC: " + datetime.now(timezone.utc).isoformat() + "\n")
        fh.write("=" * 80 + "\n")
        fh.flush()
        proc = subprocess.Popen(
            cmd,
            cwd=str(cwd),
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            env=env,
            bufsize=1,
        )
        assert proc.stdout is not None
        for line in proc.stdout:
            print(line, end="")
            fh.write(line)
        return proc.wait()


def parquet_has_data(path: Path) -> bool:
    if path.is_file():
        return path.stat().st_size > 0
    if path.is_dir():
        return any(path.glob("*.parquet")) or any(path.glob("**/*.parquet"))
    return False


def link_or_copy(src: Path, dst: Path) -> None:
    dst.parent.mkdir(parents=True, exist_ok=True)
    if dst.exists():
        dst.unlink()
    try:
        os.link(src, dst)
    except Exception:
        shutil.copy2(src, dst)


def summarize_parquet(path: Path, columns: list[str] | None = None) -> dict:
    try:
        df = pd.read_parquet(path, columns=columns)
        out = {"rows": int(len(df))}
        for c in ["cusip", "issuer_id", "week_end", "feature_month", "target_month"]:
            if c in df.columns:
                out[f"unique_{c}"] = int(df[c].nunique())
        return out
    except Exception as exc:
        return {"error": repr(exc)}


def main() -> int:
    parser = argparse.ArgumentParser(description="Run full-history curves by year, then full-history targets and baseline.")
    parser.add_argument("--project-root", default=".")
    parser.add_argument("--tag", default="full2004_2025")
    parser.add_argument("--start-year", type=int, default=2004)
    parser.add_argument("--end-year", type=int, default=2025)
    parser.add_argument("--year-workers", type=int, default=int(os.environ.get("CURVE_YEAR_WORKERS", "4")))
    parser.add_argument("--n-jobs-per-year", type=int, default=int(os.environ.get("N_JOBS_PER_YEAR", "8")))
    parser.add_argument("--min-bonds-per-issuer-week", type=int, default=int(os.environ.get("MIN_BONDS_PER_ISSUER_WEEK", "3")))
    parser.add_argument("--min-bonds-per-issuer-month", type=int, default=int(os.environ.get("MIN_BONDS_PER_ISSUER_MONTH", "3")))
    parser.add_argument("--quantile", type=float, default=float(os.environ.get("SIDE_QUANTILE", "0.20")))
    parser.add_argument("--return-chunk-size", type=int, default=int(os.environ.get("RET_CHUNK_SIZE", "1000")))
    parser.add_argument("--force-curves", action="store_true")
    parser.add_argument("--bundle", action="store_true")
    args = parser.parse_args()

    root = Path(args.project_root).resolve()
    py = os.environ.get("PYTHON_BIN") or os.environ.get("PY") or sys.executable
    if not Path(py).exists():
        py = sys.executable

    logs = root / "logs"
    processed = root / "artifacts" / "processed"
    discovery = root / "artifacts" / "discovery"
    for p in [logs, processed, discovery]:
        p.mkdir(parents=True, exist_ok=True)

    tag = args.tag
    run_id = utc_stamp()

    print("=" * 80)
    print("8.1 full-history curve/target/baseline driver")
    print("Project:", root)
    print("Tag:", tag)
    print("Years:", args.start_year, "to", args.end_year)
    print("Year workers:", args.year_workers)
    print("Jobs per year:", args.n_jobs_per_year)
    print("=" * 80)

    base_env = os.environ.copy()
    base_env["PYTHONPATH"] = f"{root / 'src'}:{base_env.get('PYTHONPATH', '')}"
    # Each year job controls its own multiprocessing. Keep BLAS at 1 to avoid 32Ã— oversubscription.
    for k in ["OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS", "NUMEXPR_NUM_THREADS"]:
        base_env[k] = "1"

    years = list(range(args.start_year, args.end_year + 1))
    curve_results: list[dict] = []

    def run_year(year: int) -> dict:
        ytag = f"{tag}_{year}"
        trace_panel = root / "artifacts" / "interim" / f"4.1_trace_daily_agg_{tag}_{year}.parquet"
        resid_out = root / "artifacts" / "processed" / f"5.0_curve_residuals_{ytag}.parquet"
        log_path = logs / f"8.1_curve_{ytag}_{run_id}.log"

        if not parquet_has_data(trace_panel):
            return {"year": year, "ok": False, "skipped": True, "reason": f"missing trace panel {trace_panel}"}

        if resid_out.exists() and not args.force_curves:
            return {"year": year, "ok": True, "skipped": True, "reason": "existing residual file", "residual_path": str(resid_out)}

        cmd = [
            py,
            "scripts/5.0_fit_curves.py",
            "--trace-panel",
            str(trace_panel),
            "--fisd-panel",
            "artifacts/interim/4.0_fisd_eligible_bonds.parquet",
            "--tag",
            ytag,
            "--min-bonds-per-issuer-week",
            str(args.min_bonds_per_issuer_week),
            "--n-jobs",
            str(args.n_jobs_per_year),
        ]
        t0 = time.time()
        rc = run_cmd(cmd, cwd=root, log_path=log_path, env=base_env)
        return {
            "year": year,
            "ok": rc == 0 and resid_out.exists(),
            "returncode": rc,
            "elapsed_sec": round(time.time() - t0, 3),
            "residual_path": str(resid_out),
            "log": str(log_path),
        }

    with ThreadPoolExecutor(max_workers=max(1, args.year_workers)) as ex:
        futures = {ex.submit(run_year, y): y for y in years}
        for fut in as_completed(futures):
            res = fut.result()
            curve_results.append(res)
            print("[YEAR DONE]", res)

    curve_results = sorted(curve_results, key=lambda x: x["year"])
    failed = [r for r in curve_results if not r.get("ok")]
    status_path = discovery / f"8.1_curve_year_status_{tag}.csv"
    pd.DataFrame(curve_results).to_csv(status_path, index=False)
    print("[WROTE]", status_path)

    if failed:
        print("[ERROR] Some curve years failed. Fix/resume before targets.")
        print(pd.DataFrame(failed).to_string(index=False))
        return 2

    # Combine per-year residual files into one parquet dataset directory by hardlink/copy.
    combined_resid = processed / f"5.0_curve_residuals_{tag}.parquet"
    combined_params = processed / f"5.0_issuer_curve_params_{tag}.parquet"
    if combined_resid.exists():
        shutil.rmtree(combined_resid) if combined_resid.is_dir() else combined_resid.unlink()
    if combined_params.exists():
        shutil.rmtree(combined_params) if combined_params.is_dir() else combined_params.unlink()
    combined_resid.mkdir(parents=True, exist_ok=True)
    combined_params.mkdir(parents=True, exist_ok=True)

    for year in years:
        ytag = f"{tag}_{year}"
        src_resid = processed / f"5.0_curve_residuals_{ytag}.parquet"
        src_params = processed / f"5.0_issuer_curve_params_{ytag}.parquet"
        if src_resid.exists():
            link_or_copy(src_resid, combined_resid / f"part_residuals_{year}.parquet")
        if src_params.exists():
            link_or_copy(src_params, combined_params / f"part_params_{year}.parquet")

    (combined_resid / "_SUCCESS").write_text(datetime.now(timezone.utc).isoformat())
    (combined_params / "_SUCCESS").write_text(datetime.now(timezone.utc).isoformat())
    print("[COMBINED]", combined_resid)
    print("[COMBINED]", combined_params)

    # Full-history target construction.
    log6 = logs / f"8.1_targets_{tag}_{run_id}.log"
    cmd6 = [
        py,
        "scripts/6.0_build_targets.py",
        "--project-root",
        str(root),
        "--tag",
        tag,
        "--residuals",
        str(combined_resid),
        "--chunk-size",
        str(args.return_chunk_size),
        "--bundle",
    ]
    rc6 = run_cmd(cmd6, cwd=root, log_path=log6, env=base_env)
    if rc6 != 0:
        print("[ERROR] 6.0 failed", rc6)
        return rc6

    # Full-history residual-sort baseline.
    log7 = logs / f"8.1_baseline_{tag}_{run_id}.log"
    cmd7 = [
        py,
        "scripts/7.0_residual_sort_baseline.py",
        "--project-root",
        str(root),
        "--tag",
        tag,
        "--panel",
        f"artifacts/processed/6.0_model_panel_{tag}.parquet",
        "--min-bonds-per-issuer-month",
        str(args.min_bonds_per_issuer_month),
        "--quantile",
        str(args.quantile),
        "--bundle",
    ]
    rc7 = run_cmd(cmd7, cwd=root, log_path=log7, env=base_env)
    if rc7 != 0:
        print("[ERROR] 7.0 failed", rc7)
        return rc7

    # Write combined summary.
    summary = {
        "tag": tag,
        "run_utc": datetime.now(timezone.utc).isoformat(),
        "years": years,
        "curve_year_workers": args.year_workers,
        "n_jobs_per_year": args.n_jobs_per_year,
        "combined_residuals": str(combined_resid),
        "combined_params": str(combined_params),
        "curve_year_status": str(status_path),
        "residual_summary": summarize_parquet(combined_resid, columns=None),
        "model_panel_summary": summarize_parquet(processed / f"6.0_model_panel_{tag}.parquet", columns=None),
    }
    summary_path = discovery / f"8.1_history_pipeline_summary_{tag}.json"
    summary_path.write_text(json.dumps(summary, indent=2, sort_keys=True))

    report_path = discovery / f"8.1_history_pipeline_report_{tag}.md"
    report = [
        f"# 8.1 Full-history curve/target/baseline report ({tag})",
        "",
        f"- Run UTC: `{summary['run_utc']}`",
        f"- Years: `{args.start_year}` to `{args.end_year}`",
        f"- Curve year workers: `{args.year_workers}`",
        f"- Jobs per year: `{args.n_jobs_per_year}`",
        f"- Combined residual dataset: `{combined_resid}`",
        f"- Combined params dataset: `{combined_params}`",
        "",
        "## Curve year status",
        "",
        pd.DataFrame(curve_results).to_markdown(index=False),
        "",
        "## Downstream reports",
        "",
        f"- `artifacts/discovery/6.0_target_report_{tag}.md`",
        f"- `artifacts/discovery/7.0_residual_sort_report_{tag}.md`",
        "",
    ]
    report_path.write_text("\n".join(report), encoding="utf-8")
    print("[WROTE]", report_path)
    print("[WROTE]", summary_path)

    if args.bundle:
        bundle = root / f"step8_1_history_logs_reports_{tag}_{utc_stamp()}.tar.gz"
        with tarfile.open(bundle, "w:gz") as tar:
            for relp in [
                "logs",
                "artifacts/discovery",
                "reports/figures",
                "configs",
                "scripts/8.1_curve_targets_baseline_history.py",
            ]:
                p = root / relp
                if p.exists():
                    tar.add(p, arcname=relp)
        print("[BUNDLE]", bundle)

    print("[DONE] full-history 5.0/6.0/7.0 pipeline complete")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
