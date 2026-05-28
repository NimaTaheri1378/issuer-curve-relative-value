#!/usr/bin/env python
from __future__ import annotations

import argparse
import json
import math
import os
import tarfile
from concurrent.futures import ProcessPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt


TAU_GRID = np.array([0.50, 0.75, 1.00, 1.50, 2.00, 3.00, 5.00, 7.50, 10.00, 15.00], dtype=float)


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def ns_loadings(maturity_years: np.ndarray, tau: float) -> np.ndarray:
    """Nelson-Siegel design matrix for one tau."""
    m = np.asarray(maturity_years, dtype=float)
    x = np.maximum(m / max(float(tau), 1e-6), 1e-10)
    l1 = (1.0 - np.exp(-x)) / x
    l2 = l1 - np.exp(-x)
    return np.column_stack([np.ones_like(m), l1, l2])


def fit_ns_grid(
    maturity_years: np.ndarray,
    yield_pct: np.ndarray,
    weights: np.ndarray,
    tau_grid: np.ndarray = TAU_GRID,
) -> dict[str, Any] | None:
    """Weighted Nelson-Siegel via a tau grid and closed-form WLS.

    Yields are in percentage points, not decimals.
    Residuals are returned in percentage points.
    """
    m = np.asarray(maturity_years, dtype=float)
    y = np.asarray(yield_pct, dtype=float)
    w = np.asarray(weights, dtype=float)

    ok = (
        np.isfinite(m)
        & np.isfinite(y)
        & np.isfinite(w)
        & (m > 0.05)
        & (m < 100.0)
        & (y > -10.0)
        & (y < 80.0)
        & (w > 0)
    )
    m, y, w = m[ok], y[ok], w[ok]

    if len(y) < 3:
        return None

    # Avoid one enormous block trade fully dominating the fit.
    w = np.sqrt(np.clip(w, 1.0, np.nanpercentile(w, 95) if len(w) >= 10 else np.max(w)))
    w = w / np.nanmean(w)

    best = None
    for tau in tau_grid:
        X = ns_loadings(m, float(tau))
        Xw = X * w[:, None]
        yw = y * w

        try:
            beta, *_ = np.linalg.lstsq(Xw, yw, rcond=None)
        except np.linalg.LinAlgError:
            continue

        fitted = X @ beta
        resid = y - fitted
        sse = float(np.average(resid * resid, weights=w))

        # Soft sanity penalties for pathological curves.
        penalty = 0.0
        if not (-20.0 <= beta[0] <= 40.0):
            penalty += 1000.0
        if abs(beta[1]) > 50.0 or abs(beta[2]) > 50.0:
            penalty += 1000.0

        objective = sse + penalty

        if best is None or objective < best["objective"]:
            best = {
                "tau": float(tau),
                "beta0": float(beta[0]),
                "beta1": float(beta[1]),
                "beta2": float(beta[2]),
                "fitted": fitted,
                "resid": resid,
                "rmse_bps": float(math.sqrt(max(sse, 0.0)) * 100.0),
                "objective": float(objective),
            }

    return best


def fit_one_group(payload: tuple[Any, Any, list[str], np.ndarray, np.ndarray, np.ndarray, np.ndarray]) -> tuple[list[dict[str, Any]], dict[str, Any] | None]:
    issuer_id, week_end, cusips, maturity_years, yld, weights, n_trades = payload
    fit = fit_ns_grid(maturity_years, yld, weights)

    if fit is None:
        return [], None

    rows = []
    for cusip, mat, obs, fitted, resid, w, nt in zip(
        cusips,
        maturity_years,
        yld,
        fit["fitted"],
        fit["resid"],
        weights,
        n_trades,
    ):
        rows.append(
            {
                "issuer_id": issuer_id,
                "week_end": week_end,
                "cusip": cusip,
                "maturity_years": float(mat),
                "yield_obs_pct": float(obs),
                "yield_fit_pct": float(fitted),
                "residual_yield_bps": float(resid * 100.0),
                "n_trades": float(nt),
                "weight": float(w),
                "ns_beta0_level": fit["beta0"],
                "ns_beta1_slope": fit["beta1"],
                "ns_beta2_curvature": fit["beta2"],
                "ns_tau": fit["tau"],
                "curve_rmse_bps": fit["rmse_bps"],
                "n_bonds_curve": int(len(cusips)),
            }
        )

    curve_row = {
        "issuer_id": issuer_id,
        "week_end": week_end,
        "n_bonds_curve": int(len(cusips)),
        "n_trades_curve": float(np.nansum(n_trades)),
        "ns_beta0_level": fit["beta0"],
        "ns_beta1_slope": fit["beta1"],
        "ns_beta2_curvature": fit["beta2"],
        "ns_tau": fit["tau"],
        "curve_rmse_bps": fit["rmse_bps"],
        "min_maturity_years": float(np.nanmin(maturity_years)),
        "max_maturity_years": float(np.nanmax(maturity_years)),
    }

    return rows, curve_row


def markdown_table(df: pd.DataFrame, max_rows: int = 20) -> str:
    """Safe markdown table without depending on optional tabulate."""
    if df.empty:
        return "_empty_"
    show = df.head(max_rows).copy()
    cols = list(show.columns)
    lines = ["| " + " | ".join(cols) + " |", "| " + " | ".join(["---"] * len(cols)) + " |"]
    for _, row in show.iterrows():
        vals = []
        for c in cols:
            v = row[c]
            if isinstance(v, float):
                vals.append(f"{v:,.4g}")
            else:
                vals.append(str(v))
        lines.append("| " + " | ".join(vals) + " |")
    return "\n".join(lines)


def weighted_average(values: pd.Series, weights: pd.Series) -> float:
    v = pd.to_numeric(values, errors="coerce")
    w = pd.to_numeric(weights, errors="coerce")
    ok = v.notna() & w.notna() & (w > 0)
    if ok.sum() == 0:
        return float(v.mean())
    return float(np.average(v[ok], weights=w[ok]))


def build_weekly_panel(trace: pd.DataFrame, fisd: pd.DataFrame) -> pd.DataFrame:
    trace = trace.copy()
    fisd = fisd.copy()

    trace["cusip"] = trace["cusip"].astype(str).str.strip()
    fisd["cusip"] = fisd["cusip"].astype(str).str.strip()

    trace["trade_date"] = pd.to_datetime(trace["trade_date"], errors="coerce")
    fisd["maturity"] = pd.to_datetime(fisd["maturity"], errors="coerce")

    trace = trace.dropna(subset=["cusip", "trade_date", "yield_mean"])
    fisd = fisd.dropna(subset=["cusip", "issuer_id", "maturity"])

    # A week ending Friday gives a stable curve date and reduces daily TRACE sparsity.
    trace["week_end"] = trace["trade_date"].dt.to_period("W-FRI").dt.end_time.dt.normalize()

    # Aggregate bond-day panel to bond-week panel.
    weekly = (
        trace.groupby(["cusip", "week_end"], observed=True)
        .apply(
            lambda g: pd.Series(
                {
                    "yield_obs_pct": weighted_average(g["yield_mean"], g["n_trades"].clip(lower=1)),
                    "price_obs": weighted_average(g["price_mean"], g["n_trades"].clip(lower=1)),
                    "n_trade_days": g["trade_date"].nunique(),
                    "n_trades": pd.to_numeric(g["n_trades"], errors="coerce").sum(),
                    "size_sum": pd.to_numeric(g["size_sum"], errors="coerce").sum(),
                }
            ),
            include_groups=False,
        )
        .reset_index()
    )

    keep_cols = [
        "cusip",
        "issuer_id",
        "prospectus_issuer_name",
        "maturity",
        "offering_date",
        "principal_amt",
        "offering_amt",
        "coupon_type",
        "security_level",
        "bond_type",
        "rule_144a",
        "redeemable",
        "announced_call",
    ]
    keep_cols = [c for c in keep_cols if c in fisd.columns]

    merged = weekly.merge(fisd[keep_cols].drop_duplicates("cusip"), on="cusip", how="inner")

    merged["maturity_years"] = (
        (merged["maturity"] - merged["week_end"]).dt.days.astype(float) / 365.25
    )

    merged = merged[
        merged["issuer_id"].notna()
        & merged["maturity_years"].between(0.25, 60.0)
        & pd.to_numeric(merged["yield_obs_pct"], errors="coerce").between(-5.0, 50.0)
    ].copy()

    merged["issuer_id"] = merged["issuer_id"].astype("Int64").astype(str)
    merged["curve_weight"] = np.log1p(pd.to_numeric(merged["n_trades"], errors="coerce").fillna(0.0))
    merged["curve_weight"] = merged["curve_weight"].clip(lower=1.0)

    return merged


def make_figures(root: Path, panel: pd.DataFrame, residuals: pd.DataFrame, curves: pd.DataFrame, tag: str) -> None:
    fig_dir = root / "reports" / "figures"
    fig_dir.mkdir(parents=True, exist_ok=True)

    plt.rcParams.update(
        {
            "figure.dpi": 130,
            "savefig.dpi": 230,
            "font.family": "DejaVu Sans",
            "font.size": 10,
            "axes.spines.top": False,
            "axes.spines.right": False,
            "axes.grid": True,
            "grid.alpha": 0.25,
        }
    )

    # Coverage plot
    if not panel.empty:
        coverage = (
            panel.groupby("week_end")
            .agg(
                curve_ready_bonds=("cusip", "nunique"),
                curve_ready_issuers=("issuer_id", "nunique"),
            )
            .reset_index()
        )
        if not curves.empty:
            c2 = curves.groupby("week_end").agg(fitted_issuer_curves=("issuer_id", "nunique")).reset_index()
            coverage = coverage.merge(c2, on="week_end", how="left")
        else:
            coverage["fitted_issuer_curves"] = 0

        fig, ax = plt.subplots(figsize=(10, 5))
        ax.plot(coverage["week_end"], coverage["curve_ready_bonds"], label="Curve-ready bonds")
        ax.plot(coverage["week_end"], coverage["curve_ready_issuers"], label="Curve-ready issuers")
        ax.plot(coverage["week_end"], coverage["fitted_issuer_curves"], label="Fitted issuer curves")
        ax.set_title("5.0 Pilot Coverage: Weekly Curve Universe")
        ax.set_xlabel("Week")
        ax.set_ylabel("Count")
        ax.legend()
        fig.tight_layout()
        for ext in ["png", "svg"]:
            fig.savefig(fig_dir / f"5.0_curve_coverage_{tag}.{ext}", bbox_inches="tight")
        plt.close(fig)

    # Residual distribution
    if not residuals.empty:
        fig, ax = plt.subplots(figsize=(9, 5))
        x = residuals["residual_yield_bps"].replace([np.inf, -np.inf], np.nan).dropna()
        lo, hi = np.nanpercentile(x, [1, 99]) if len(x) else (-100, 100)
        x = x.clip(lo, hi)
        ax.hist(x, bins=50)
        ax.axvline(0.0, linewidth=1.3)
        ax.set_title("5.0 Pilot: Issuer-Curve Residual Yield Distribution")
        ax.set_xlabel("Observed yield minus fitted issuer curve, bps")
        ax.set_ylabel("Bond-week observations")
        fig.tight_layout()
        for ext in ["png", "svg"]:
            fig.savefig(fig_dir / f"5.0_residual_distribution_{tag}.{ext}", bbox_inches="tight")
        plt.close(fig)

        # Example curve: largest issuer-week
        ex_key = (
            residuals.groupby(["issuer_id", "week_end"])
            .size()
            .sort_values(ascending=False)
            .head(1)
        )
        if len(ex_key):
            issuer_id, week_end = ex_key.index[0]
            ex = residuals[(residuals["issuer_id"] == issuer_id) & (residuals["week_end"] == week_end)].copy()
            ex = ex.sort_values("maturity_years")

            grid = np.linspace(max(0.25, ex["maturity_years"].min() * 0.8), ex["maturity_years"].max() * 1.1, 200)
            b0 = float(ex["ns_beta0_level"].iloc[0])
            b1 = float(ex["ns_beta1_slope"].iloc[0])
            b2 = float(ex["ns_beta2_curvature"].iloc[0])
            tau = float(ex["ns_tau"].iloc[0])
            curve = ns_loadings(grid, tau) @ np.array([b0, b1, b2])

            fig, ax = plt.subplots(figsize=(9, 5.5))
            ax.plot(grid, curve, label="Fitted Nelson-Siegel issuer curve")
            sizes = np.clip(ex["n_trades"].astype(float), 1, np.nanpercentile(ex["n_trades"].astype(float), 95))
            sizes = 25 + 90 * (sizes / max(sizes.max(), 1.0))
            ax.scatter(ex["maturity_years"], ex["yield_obs_pct"], s=sizes, alpha=0.85, label="Observed weekly TRACE yield")
            for _, r in ex.iterrows():
                ax.vlines(r["maturity_years"], r["yield_fit_pct"], r["yield_obs_pct"], linewidth=0.7, alpha=0.6)
            ax.set_title(f"5.0 Pilot Example Issuer Curve: issuer {issuer_id}, week {pd.Timestamp(week_end).date()}")
            ax.set_xlabel("Residual maturity, years")
            ax.set_ylabel("Yield, %")
            ax.legend()
            fig.tight_layout()
            for ext in ["png", "svg"]:
                fig.savefig(fig_dir / f"5.0_example_issuer_curve_{tag}.{ext}", bbox_inches="tight")
            plt.close(fig)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--trace-panel", required=True)
    parser.add_argument("--fisd-panel", required=True)
    parser.add_argument("--tag", default="pilot")
    parser.add_argument("--min-bonds-per-issuer-week", type=int, default=3)
    parser.add_argument("--n-jobs", type=int, default=max(1, min(32, os.cpu_count() or 1)))
    args = parser.parse_args()

    root = Path.cwd()
    disc = root / "artifacts" / "discovery"
    processed = root / "artifacts" / "processed"
    disc.mkdir(parents=True, exist_ok=True)
    processed.mkdir(parents=True, exist_ok=True)

    print("=" * 72)
    print("5.0 fit issuer curves")
    print("UTC:", utc_now())
    print("Trace panel:", args.trace_panel)
    print("FISD panel:", args.fisd_panel)
    print("Tag:", args.tag)
    print("n_jobs:", args.n_jobs)
    print("=" * 72)

    trace = pd.read_parquet(args.trace_panel)
    fisd = pd.read_parquet(args.fisd_panel)

    print(f"[LOAD] TRACE rows={len(trace):,}, cusips={trace['cusip'].nunique():,}")
    print(f"[LOAD] FISD rows={len(fisd):,}, cusips={fisd['cusip'].nunique():,}, issuers={fisd['issuer_id'].nunique():,}")

    panel = build_weekly_panel(trace, fisd)
    print(f"[PANEL] curve-ready bond-weeks={len(panel):,}, cusips={panel['cusip'].nunique():,}, issuers={panel['issuer_id'].nunique():,}")

    panel_path = processed / f"5.0_curve_ready_panel_{args.tag}.parquet"
    panel.to_parquet(panel_path, index=False)
    print("[WROTE]", panel_path)

    group_sizes = (
        panel.groupby(["issuer_id", "week_end"], observed=True)
        .size()
        .reset_index(name="n_bonds")
        .sort_values("n_bonds", ascending=False)
    )
    group_sizes.to_csv(disc / f"5.0_issuer_week_group_sizes_{args.tag}.csv", index=False)

    eligible_groups = group_sizes[group_sizes["n_bonds"] >= args.min_bonds_per_issuer_week]
    print(
        f"[GROUPS] issuer-weeks total={len(group_sizes):,}; "
        f"with >= {args.min_bonds_per_issuer_week} bonds={len(eligible_groups):,}"
    )

    payloads = []
    if not eligible_groups.empty:
        eligible_keys = set(zip(eligible_groups["issuer_id"].astype(str), pd.to_datetime(eligible_groups["week_end"])))
        for (issuer_id, week_end), g in panel.groupby(["issuer_id", "week_end"], observed=True):
            if (str(issuer_id), pd.Timestamp(week_end)) not in eligible_keys:
                continue
            g = g.sort_values("maturity_years")
            payloads.append(
                (
                    str(issuer_id),
                    pd.Timestamp(week_end),
                    g["cusip"].astype(str).tolist(),
                    g["maturity_years"].to_numpy(float),
                    g["yield_obs_pct"].to_numpy(float),
                    g["curve_weight"].to_numpy(float),
                    g["n_trades"].to_numpy(float),
                )
            )

    residual_rows: list[dict[str, Any]] = []
    curve_rows: list[dict[str, Any]] = []

    if payloads:
        n_jobs = max(1, min(int(args.n_jobs), len(payloads)))
        print(f"[FIT] fitting {len(payloads):,} issuer-week curves with {n_jobs} workers")

        if n_jobs == 1:
            for p in payloads:
                rows, curve = fit_one_group(p)
                residual_rows.extend(rows)
                if curve is not None:
                    curve_rows.append(curve)
        else:
            with ProcessPoolExecutor(max_workers=n_jobs) as ex:
                futures = [ex.submit(fit_one_group, p) for p in payloads]
                done = 0
                for fut in as_completed(futures):
                    rows, curve = fut.result()
                    residual_rows.extend(rows)
                    if curve is not None:
                        curve_rows.append(curve)
                    done += 1
                    if done % 100 == 0 or done == len(futures):
                        print(f"[FIT] completed {done:,}/{len(futures):,}")

    residuals = pd.DataFrame(residual_rows)
    curves = pd.DataFrame(curve_rows)

    if not residuals.empty:
        residuals["week_end"] = pd.to_datetime(residuals["week_end"])
        residuals["residual_z_issuer_week"] = residuals.groupby(
            ["issuer_id", "week_end"], observed=True
        )["residual_yield_bps"].transform(
            lambda s: (s - s.mean()) / s.std(ddof=0) if s.std(ddof=0) > 0 else 0.0
        )
        residuals["residual_rank_pct_issuer_week"] = residuals.groupby(
            ["issuer_id", "week_end"], observed=True
        )["residual_yield_bps"].rank(pct=True)

    if not curves.empty:
        curves["week_end"] = pd.to_datetime(curves["week_end"])

    residual_path = processed / f"5.0_curve_residuals_{args.tag}.parquet"
    curves_path = processed / f"5.0_issuer_curve_params_{args.tag}.parquet"
    residuals.to_parquet(residual_path, index=False)
    curves.to_parquet(curves_path, index=False)

    print("[WROTE]", residual_path)
    print("[WROTE]", curves_path)
    print(f"[RESULT] residual rows={len(residuals):,}; curves={len(curves):,}")

    summary: dict[str, Any] = {
        "run_utc": utc_now(),
        "tag": args.tag,
        "inputs": {
            "trace_panel": args.trace_panel,
            "fisd_panel": args.fisd_panel,
        },
        "trace_rows": int(len(trace)),
        "trace_cusips": int(trace["cusip"].nunique()),
        "fisd_rows": int(len(fisd)),
        "fisd_cusips": int(fisd["cusip"].nunique()),
        "fisd_issuers": int(fisd["issuer_id"].nunique()),
        "curve_ready_bond_weeks": int(len(panel)),
        "curve_ready_cusips": int(panel["cusip"].nunique()) if not panel.empty else 0,
        "curve_ready_issuers": int(panel["issuer_id"].nunique()) if not panel.empty else 0,
        "issuer_weeks_total": int(len(group_sizes)),
        "issuer_weeks_min_bonds": int(len(eligible_groups)),
        "min_bonds_per_issuer_week": int(args.min_bonds_per_issuer_week),
        "fitted_curves": int(len(curves)),
        "residual_rows": int(len(residuals)),
        "outputs": {
            "curve_ready_panel": str(panel_path),
            "curve_residuals": str(residual_path),
            "issuer_curve_params": str(curves_path),
        },
    }

    if not residuals.empty:
        summary["residual_bps_distribution"] = {
            k: float(v)
            for k, v in residuals["residual_yield_bps"].describe(percentiles=[0.01, 0.05, 0.5, 0.95, 0.99]).items()
        }
        summary["curve_rmse_bps_distribution"] = {
            k: float(v)
            for k, v in curves["curve_rmse_bps"].describe(percentiles=[0.01, 0.05, 0.5, 0.95, 0.99]).items()
        } if not curves.empty else {}

    summary_path = disc / f"5.0_curve_fit_summary_{args.tag}.json"
    summary_path.write_text(json.dumps(summary, indent=2, default=str), encoding="utf-8")

    coverage_by_week = pd.DataFrame()
    if not panel.empty:
        coverage_by_week = panel.groupby("week_end").agg(
            curve_ready_bonds=("cusip", "nunique"),
            curve_ready_issuers=("issuer_id", "nunique"),
            bond_weeks=("cusip", "size"),
        ).reset_index()
        if not curves.empty:
            fitted_by_week = curves.groupby("week_end").agg(fitted_curves=("issuer_id", "nunique")).reset_index()
            coverage_by_week = coverage_by_week.merge(fitted_by_week, on="week_end", how="left")
        coverage_by_week["fitted_curves"] = coverage_by_week.get("fitted_curves", 0)
        coverage_by_week.to_csv(disc / f"5.0_curve_coverage_by_week_{args.tag}.csv", index=False)

    make_figures(root, panel, residuals, curves, args.tag)

    md_lines = [
        "# 5.0 Issuer curve fit pilot report",
        "",
        f"- Run UTC: `{summary['run_utc']}`",
        f"- Tag: `{args.tag}`",
        f"- TRACE input rows: `{summary['trace_rows']:,}`",
        f"- TRACE input CUSIPs: `{summary['trace_cusips']:,}`",
        f"- FISD eligible rows: `{summary['fisd_rows']:,}`",
        f"- Curve-ready bond-weeks after FISD join/maturity filters: `{summary['curve_ready_bond_weeks']:,}`",
        f"- Curve-ready CUSIPs: `{summary['curve_ready_cusips']:,}`",
        f"- Curve-ready issuers: `{summary['curve_ready_issuers']:,}`",
        f"- Issuer-weeks with at least `{args.min_bonds_per_issuer_week}` bonds: `{summary['issuer_weeks_min_bonds']:,}`",
        f"- Fitted issuer-week curves: `{summary['fitted_curves']:,}`",
        f"- Residual bond-week rows: `{summary['residual_rows']:,}`",
        "",
        "## Outputs",
        "",
        f"- `{panel_path}`",
        f"- `{residual_path}`",
        f"- `{curves_path}`",
        f"- `{summary_path}`",
        f"- `reports/figures/5.0_curve_coverage_{args.tag}.png`",
        f"- `reports/figures/5.0_residual_distribution_{args.tag}.png`",
        f"- `reports/figures/5.0_example_issuer_curve_{args.tag}.png`",
        "",
    ]

    if not residuals.empty:
        md_lines.extend(
            [
                "## Residual distribution, bps",
                "",
                "```json",
                json.dumps(summary["residual_bps_distribution"], indent=2),
                "```",
                "",
            ]
        )

    md_lines.extend(
        [
            "## Largest issuer-week groups",
            "",
            markdown_table(group_sizes.head(15)),
            "",
            "## Interpretation",
            "",
        ]
    )

    if len(residuals) == 0:
        md_lines.append(
            "No issuer-week groups had enough traded bonds for curve fitting. Increase the TRACE CUSIP sample or run the full 4.1 extraction before continuing."
        )
    else:
        md_lines.append(
            "The pilot successfully estimated issuer-week curves and residual-yield signals. Next step is to extract a larger TRACE panel or proceed to 6.0 target construction using WRDS bond returns."
        )

    report_path = disc / f"5.0_curve_fit_report_{args.tag}.md"
    report_path.write_text("\n".join(md_lines) + "\n", encoding="utf-8")
    print("[WROTE]", summary_path)
    print("[WROTE]", report_path)
    print("[DONE] 5.0 curve pilot finished")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
