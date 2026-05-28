#!/usr/bin/env python
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import tarfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd


DEFAULT_TAG = "full2004_2025_c3000"


def utc_stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    return json.loads(path.read_text())


def safe_float(x: Any, default: float = float("nan")) -> float:
    try:
        return float(x)
    except Exception:
        return default


def pct(x: Any, digits: int = 2) -> str:
    v = safe_float(x)
    if v != v:
        return "NA"
    return f"{100.0 * v:.{digits}f}%"


def num(x: Any) -> str:
    try:
        return f"{int(x):,}"
    except Exception:
        try:
            return f"{float(x):,.0f}"
        except Exception:
            return str(x)


def run(cmd: list[str], cwd: Path) -> tuple[int, str]:
    p = subprocess.run(cmd, cwd=str(cwd), text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    return p.returncode, p.stdout


def update_gitignore(root: Path) -> None:
    path = root / ".gitignore"
    old = path.read_text() if path.exists() else ""
    block = """
# --- WRDS / research artifact safety ---
# Never commit raw or derived WRDS data.
artifacts/raw/**
artifacts/interim/**
artifacts/processed/**
artifacts/model_runs/**
*.parquet
*.feather
*.h5
*.hdf5
*.duckdb
*.db
*.sqlite
*.pkl
*.pickle

# Keep only local logs out of GitHub.
logs/**
*.log

# Diagnostic bundles and tarballs are local.
*.tar.gz
*.zip

# Credentials
.pgpass
*.pgpass
*.pem
*.key
.env

# Allow reports, figures, configs, code, and small discovery summaries.
!artifacts/discovery/
!artifacts/discovery/*.md
!artifacts/discovery/*.json
!artifacts/discovery/*.csv
!reports/
!reports/figures/
!reports/tables/
!configs/
!scripts/
"""
    marker = "# --- WRDS / research artifact safety ---"
    if marker in old:
        old = old[: old.index(marker)].rstrip() + "\n"
    path.write_text(old.rstrip() + "\n\n" + block.lstrip())


def build_headline_tables(root: Path, tag: str) -> dict[str, Any]:
    disc = root / "artifacts" / "discovery"
    tables_dir = root / "reports" / "tables"
    tables_dir.mkdir(parents=True, exist_ok=True)

    v = read_json(disc / f"7.1_validation_summary_{tag}.json")
    b = read_json(disc / f"7.0_residual_sort_summary_{tag}.json")
    # 8.0 and 8.1 may be md only; use counts from parquet if available where safe locally.
    trace_path = root / "artifacts" / "interim" / f"4.1_trace_daily_agg_{tag}.parquet"
    resid_path = root / "artifacts" / "processed" / f"5.0_curve_residuals_{tag}.parquet"
    panel_path = root / "artifacts" / "processed" / f"6.0_model_panel_{tag}.parquet"
    monthly_path = root / "artifacts" / "processed" / f"7.0_residual_sort_monthly_{tag}.csv"

    counts = {}
    if trace_path.exists():
        x = pd.read_parquet(trace_path, columns=["cusip", "trade_date", "n_trades"])
        counts.update({
            "trace_rows": int(len(x)),
            "trace_cusips": int(x["cusip"].nunique()),
            "trace_date_min": str(x["trade_date"].min()),
            "trace_date_max": str(x["trade_date"].max()),
            "represented_trades": int(x["n_trades"].sum()),
        })
    if resid_path.exists():
        r = pd.read_parquet(resid_path, columns=["issuer_id", "cusip", "week_end", "residual_yield_bps"])
        counts.update({
            "residual_rows": int(len(r)),
            "residual_issuers": int(r["issuer_id"].nunique()),
            "residual_cusips": int(r["cusip"].nunique()),
            "residual_weeks": int(r["week_end"].nunique()),
        })
    if panel_path.exists():
        p = pd.read_parquet(panel_path)
        counts.update({
            "model_panel_rows": int(len(p)),
            "issuer_demeaned_target_rows": int(p["issuer_demeaned_ret_1m"].notna().sum()) if "issuer_demeaned_ret_1m" in p else None,
            "feature_month_min": str(p["feature_month"].min()) if "feature_month" in p else None,
            "feature_month_max": str(p["feature_month"].max()) if "feature_month" in p else None,
        })
    if monthly_path.exists():
        m = pd.read_csv(monthly_path)
        counts.update({
            "strategy_months": int(m["target_month"].nunique()) if "target_month" in m else int(len(m)),
            "strategy_mean_monthly": float(m["strategy_ret"].mean()) if "strategy_ret" in m else None,
            "strategy_min_month": float(m["strategy_ret"].min()) if "strategy_ret" in m else None,
            "strategy_max_month": float(m["strategy_ret"].max()) if "strategy_ret" in m else None,
        })
        # Save a small public monthly series (not proprietary row-level data)
        m.to_csv(tables_dir / f"monthly_strategy_returns_{tag}.csv", index=False)

    perf = v.get("base_performance_recomputed") or b.get("performance", {})
    alignment = v.get("alignment", {})
    placebo = {
        "placebo_permutations": v.get("placebo_permutations"),
        "placebo_one_sided_p": v.get("placebo_one_sided_p_mean_ge_actual"),
        "placebo_two_sided_p": v.get("placebo_two_sided_p_abs_mean_ge_actual"),
        "workers": v.get("workers"),
        "target_not_after_feature_rows": alignment.get("target_not_after_feature_rows"),
        "duplicate_cusip_feature_month_rows": alignment.get("duplicate_cusip_feature_month_rows"),
    }

    headline = {
        "tag": tag,
        **counts,
        "n_months": perf.get("n_months"),
        "mean_monthly": perf.get("mean_monthly"),
        "ann_sharpe": perf.get("ann_sharpe"),
        "cumulative_return": perf.get("cumulative_return"),
        "max_drawdown": perf.get("max_drawdown"),
        "t_stat_mean": perf.get("t_stat_mean"),
        "issuer_month_groups": perf.get("issuer_month_groups") or b.get("issuer_month_trades"),
        "position_rows": perf.get("position_rows") or b.get("position_rows"),
        **placebo,
    }

    pd.DataFrame([headline]).to_csv(tables_dir / f"headline_results_{tag}.csv", index=False)

    # Robustness table copy if available
    rob = disc / f"7.1_robustness_variants_{tag}.csv"
    if rob.exists():
        pd.read_csv(rob).to_csv(tables_dir / f"robustness_variants_{tag}.csv", index=False)

    return headline


def write_final_report(root: Path, tag: str, h: dict[str, Any]) -> Path:
    reports = root / "reports"
    reports.mkdir(exist_ok=True)
    out = reports / f"final_results_{tag}.md"

    lines = [
        f"# Final empirical results ({tag})",
        "",
        "This report is generated from local WRDS-derived outputs. It is safe to commit because it contains only aggregate summary statistics, not TRACE/FISD/return microdata.",
        "",
        "## Sample construction",
        "",
        f"- TRACE bond-day rows: `{num(h.get('trace_rows'))}`",
        f"- TRACE CUSIPs: `{num(h.get('trace_cusips'))}`",
        f"- Raw trades represented by daily aggregation: `{num(h.get('represented_trades'))}`",
        f"- TRACE date range: `{h.get('trace_date_min')}` to `{h.get('trace_date_max')}`",
        f"- Residual curve rows: `{num(h.get('residual_rows'))}`",
        f"- Residual issuers: `{num(h.get('residual_issuers'))}`",
        f"- Residual CUSIPs: `{num(h.get('residual_cusips'))}`",
        f"- Model panel rows: `{num(h.get('model_panel_rows'))}`",
        f"- Issuer-demeaned target rows: `{num(h.get('issuer_demeaned_target_rows'))}`",
        "",
        "## Baseline strategy",
        "",
        "Strategy: issuer-relative long-cheap / short-rich residual-yield sort, monthly rebalance, minimum 3 bonds per issuer-month, top/bottom 20% within issuer.",
        "",
        f"- Months: `{num(h.get('n_months'))}`",
        f"- Issuer-month groups: `{num(h.get('issuer_month_groups'))}`",
        f"- Position rows: `{num(h.get('position_rows'))}`",
        f"- Mean monthly return: `{pct(h.get('mean_monthly'), 3)}`",
        f"- Cumulative return: `{pct(h.get('cumulative_return'), 1)}`",
        f"- Annualized Sharpe: `{safe_float(h.get('ann_sharpe')):.2f}`",
        f"- Max drawdown: `{pct(h.get('max_drawdown'), 2)}`",
        f"- t-stat of mean monthly return: `{safe_float(h.get('t_stat_mean')):.2f}`",
        "",
        "## Validation",
        "",
        f"- Look-ahead violations: `{num(h.get('target_not_after_feature_rows'))}`",
        f"- Duplicate CUSIP-feature-month rows: `{num(h.get('duplicate_cusip_feature_month_rows'))}`",
        f"- Placebo permutations: `{num(h.get('placebo_permutations'))}`",
        f"- Placebo one-sided p-value: `{h.get('placebo_one_sided_p')}`",
        f"- Placebo two-sided p-value: `{h.get('placebo_two_sided_p')}`",
        "",
        "## Caveats",
        "",
        "- These are gross strategy returns before an explicit transaction-cost model.",
        "- The baseline is intentionally simple. Final repo development should add cost-aware backtests, Newey-West inference, and model comparisons.",
        "- WRDS-derived parquet artifacts remain local and are not committed.",
        "",
    ]
    out.write_text("\n".join(lines))
    return out


def update_readme(root: Path, tag: str, h: dict[str, Any]) -> None:
    readme = root / "README.md"
    old = readme.read_text() if readme.exists() else "# Transaction-Based Issuer Yield Curve Relative Value in U.S. Corporate Bonds\n"
    start = "<!-- RESULTS_START -->"
    end = "<!-- RESULTS_END -->"
    block = f"""
{start}
## Current headline results

Full-history tag: `{tag}`

| Metric | Value |
|---|---:|
| TRACE bond-day rows | {num(h.get('trace_rows'))} |
| TRACE CUSIPs | {num(h.get('trace_cusips'))} |
| Raw TRACE trades represented | {num(h.get('represented_trades'))} |
| Residual curve rows | {num(h.get('residual_rows'))} |
| Residual issuers | {num(h.get('residual_issuers'))} |
| Model panel rows | {num(h.get('model_panel_rows'))} |
| Issuer-demeaned target rows | {num(h.get('issuer_demeaned_target_rows'))} |
| Backtest months | {num(h.get('n_months'))} |
| Issuer-month groups | {num(h.get('issuer_month_groups'))} |
| Position rows | {num(h.get('position_rows'))} |
| Mean monthly return | {pct(h.get('mean_monthly'), 3)} |
| Cumulative return | {pct(h.get('cumulative_return'), 1)} |
| Annualized Sharpe | {safe_float(h.get('ann_sharpe')):.2f} |
| Max drawdown | {pct(h.get('max_drawdown'), 2)} |
| t-stat | {safe_float(h.get('t_stat_mean')):.2f} |
| Placebo permutations | {num(h.get('placebo_permutations'))} |
| Placebo p-value, one-sided | {h.get('placebo_one_sided_p')} |
| Look-ahead violations | {num(h.get('target_not_after_feature_rows'))} |

The reported strategy is a simple issuer-relative residual-yield sort: long bonds trading cheap to the fitted issuer curve and short bonds trading rich to the same issuer curve. WRDS-derived microdata are not committed to this repository.
{end}
"""
    if start in old and end in old:
        old = re.sub(f"{re.escape(start)}.*?{re.escape(end)}", block.strip(), old, flags=re.S)
    else:
        old = old.rstrip() + "\n\n" + block.strip() + "\n"
    readme.write_text(old)


def write_checklist(root: Path, tag: str) -> Path:
    out = root / "GITHUB_PUSH_CHECKLIST.md"
    out.write_text(f"""# GitHub push checklist

Tag: `{tag}`

## Commit allowed

- `README.md`
- `LICENSE`, `CITATION.cff`, `pyproject.toml`, `environment.yml`, `Makefile`
- `configs/*.yaml`
- `scripts/*.py` and `run_*.sh`
- `src/**`
- `tests/**`
- `reports/final_results_{tag}.md`
- `reports/tables/*.csv`
- `reports/figures/*.png`, `.svg`, `.pdf`
- `artifacts/discovery/*.md`, `.json`, `.csv` summary files only

## Never commit

- `artifacts/raw/**`
- `artifacts/interim/**`
- `artifacts/processed/**` parquet data
- `artifacts/interim/trace_parts_*`
- `logs/**`
- `*.tar.gz`
- `.pgpass`, credentials, keys

## Before push

```bash
git status --short
git ls-files | grep -E '(^artifacts/(raw|interim|processed)/|\\.parquet$|\\.pgpass|\\.pem|\\.key)' && echo "STOP: unsafe file tracked" || echo "Safe: no raw WRDS artifacts tracked"
git diff --stat
```

## Suggested commit

```bash
git add README.md GITHUB_PUSH_CHECKLIST.md .gitignore configs scripts src tests reports artifacts/discovery
git reset artifacts/raw artifacts/interim artifacts/processed logs 2>/dev/null || true
git commit -m "Build issuer curve relative-value research pipeline"
git push -u origin main
```
""")
    return out


def create_safe_bundle(root: Path, tag: str) -> Path:
    stamp = utc_stamp()
    out = root / f"step9_github_safe_results_{tag}_{stamp}.tar.gz"
    candidates: list[Path] = []

    patterns = [
        "README.md", "GITHUB_PUSH_CHECKLIST.md", ".gitignore",
        f"reports/final_results_{tag}.md",
        f"reports/tables/*{tag}*.csv",
        f"reports/figures/*{tag}*",
        f"artifacts/discovery/*{tag}*.md",
        f"artifacts/discovery/*{tag}*.json",
        f"artifacts/discovery/*{tag}*.csv",
        "configs/*.yaml",
        "scripts/*.py",
        "run_*.sh",
        "pyproject.toml", "environment.yml", "Makefile", "LICENSE", "CITATION.cff",
    ]
    for pat in patterns:
        candidates.extend(root.glob(pat))

    unsafe = re.compile(r"(artifacts/(raw|interim|processed)/)|(\.parquet$)|(\.pgpass)|(\.pem$)|(\.key$)")
    final = sorted({p for p in candidates if p.exists() and p.is_file() and not unsafe.search(str(p))})

    with tarfile.open(out, "w:gz") as tar:
        for p in final:
            tar.add(p, arcname=str(p.relative_to(root)))

    return out


def audit_git_safety(root: Path) -> str:
    lines = ["# Git safety audit", ""]
    rc, out = run(["git", "status", "--short"], root)
    lines += ["## git status --short", "", "```", out.strip(), "```", ""]
    rc, out = run(["git", "ls-files"], root)
    tracked = out.splitlines()
    bad = [x for x in tracked if re.search(r"(^artifacts/(raw|interim|processed)/|\.parquet$|\.pgpass|\.pem$|\.key$|\.tar\.gz$)", x)]
    lines += ["## Unsafe tracked files", ""]
    if bad:
        lines += ["```"] + bad + ["```", ""]
    else:
        lines += ["None detected.", ""]
    audit = "\n".join(lines)
    (root / "reports" / "git_safety_audit.md").write_text(audit)
    return audit


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--project-root", default=".")
    ap.add_argument("--tag", default=DEFAULT_TAG)
    ap.add_argument("--no-readme-update", action="store_true")
    ap.add_argument("--bundle", action="store_true")
    args = ap.parse_args()

    root = Path(args.project_root).resolve()
    tag = args.tag

    print("=" * 72)
    print("9.0 GitHub release preparation")
    print("Project:", root)
    print("Tag:", tag)
    print("=" * 72)

    update_gitignore(root)
    h = build_headline_tables(root, tag)
    report = write_final_report(root, tag, h)
    checklist = write_checklist(root, tag)
    if not args.no_readme_update:
        update_readme(root, tag, h)

    audit = audit_git_safety(root)

    print("[WROTE]", report)
    print("[WROTE]", checklist)
    print("[WROTE]", root / "reports" / "tables" / f"headline_results_{tag}.csv")
    print("[WROTE]", root / "reports" / "git_safety_audit.md")
    print("[UPDATED]", root / ".gitignore")
    if not args.no_readme_update:
        print("[UPDATED]", root / "README.md")

    if args.bundle:
        bundle = create_safe_bundle(root, tag)
        print("[BUNDLE]", bundle)

    print()
    print("Next:")
    print("  1. Inspect README.md and reports/final_results_*.md")
    print("  2. Run: git status --short")
    print("  3. Stage only safe code/config/report/figure files.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
