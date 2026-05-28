#!/usr/bin/env python
from __future__ import annotations

import argparse
import json
import math
import tarfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

try:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
except Exception:
    plt = None


def utc_stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def perf_stats(monthly: pd.DataFrame, ret_col: str = "strategy_ret") -> dict[str, Any]:
    if monthly is None or monthly.empty or ret_col not in monthly.columns:
        return {
            "n_months": 0,
            "mean_monthly": None,
            "std_monthly": None,
            "ann_sharpe": None,
            "t_stat_mean": None,
            "cumulative_return": None,
            "max_drawdown": None,
            "min_month": None,
            "max_month": None,
            "positive_month_share": None,
        }

    r = pd.to_numeric(monthly[ret_col], errors="coerce").dropna()
    n = int(len(r))
    if n == 0:
        return {
            "n_months": 0,
            "mean_monthly": None,
            "std_monthly": None,
            "ann_sharpe": None,
            "t_stat_mean": None,
            "cumulative_return": None,
            "max_drawdown": None,
            "min_month": None,
            "max_month": None,
            "positive_month_share": None,
        }

    mean = float(r.mean())
    std = float(r.std(ddof=1)) if n > 1 else 0.0
    ann_sharpe = float((mean / std) * math.sqrt(12)) if std > 0 else None
    t_stat = float(mean / (std / math.sqrt(n))) if std > 0 and n > 1 else None
    wealth = (1.0 + r).cumprod()
    dd = wealth / wealth.cummax() - 1.0

    return {
        "n_months": n,
        "mean_monthly": mean,
        "std_monthly": std,
        "ann_sharpe": ann_sharpe,
        "t_stat_mean": t_stat,
        "cumulative_return": float(wealth.iloc[-1] - 1.0),
        "max_drawdown": float(dd.min()),
        "min_month": float(r.min()),
        "max_month": float(r.max()),
        "positive_month_share": float((r > 0).mean()),
    }


def month_end_plus_one(x: pd.Series) -> pd.Series:
    return (pd.to_datetime(x) + pd.offsets.MonthEnd(1)).dt.normalize()


def prepare_panel(panel: pd.DataFrame) -> pd.DataFrame:
    p = panel.copy()

    for c in ["feature_month", "target_month"]:
        if c in p.columns:
            p[c] = pd.to_datetime(p[c]).dt.normalize()

    for c in [
        "residual_yield_bps",
        "signal_rank_pct_issuer_month",
        "issuer_demeaned_ret_1m",
        "target_ret_1m",
    ]:
        if c in p.columns:
            p[c] = pd.to_numeric(p[c], errors="coerce")

    # Conservative usable rows for long-short testing.
    required = ["issuer_id", "feature_month", "target_month", "cusip", "residual_yield_bps", "issuer_demeaned_ret_1m"]
    missing = [c for c in required if c not in p.columns]
    if missing:
        raise ValueError(f"Model panel missing required columns: {missing}")

    p = p.dropna(subset=required).copy()
    return p


def compute_strategy(
    panel: pd.DataFrame,
    *,
    quantile: float = 0.20,
    min_bonds: int = 3,
    target_col: str = "issuer_demeaned_ret_1m",
    signal_col: str = "residual_yield_bps",
    winsor_target: float | None = None,
    exclude_abs_target_gt: float | None = None,
    min_abs_side_residual_bps: float | None = None,
    randomize_signal: bool = False,
    rng: np.random.Generator | None = None,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """Compute issuer-month long-cheap / short-rich residual sort.

    Long side is highest residual_yield_bps, interpreted as cheap.
    Short side is lowest residual_yield_bps, interpreted as rich.
    """

    p = panel.copy()

    if exclude_abs_target_gt is not None:
        p = p[p[target_col].abs() <= exclude_abs_target_gt].copy()

    if winsor_target is not None and 0 < winsor_target < 0.5:
        lo = p[target_col].quantile(winsor_target)
        hi = p[target_col].quantile(1.0 - winsor_target)
        p[target_col] = p[target_col].clip(lo, hi)

    if randomize_signal:
        if rng is None:
            rng = np.random.default_rng(1729)
        # Shuffle signal within each issuer-month. This preserves issuer/month structure
        # while destroying the bond-specific cheap/rich ranking.
        p[signal_col] = p.groupby(["issuer_id", "feature_month"], group_keys=False)[signal_col].transform(
            lambda s: pd.Series(rng.permutation(s.to_numpy()), index=s.index)
        )

    issuer_rows: list[dict[str, Any]] = []
    position_rows: list[dict[str, Any]] = []

    group_cols = ["issuer_id", "feature_month", "target_month"]
    for (issuer_id, feature_month, target_month), g in p.groupby(group_cols, sort=False):
        g = g.dropna(subset=[signal_col, target_col]).copy()
        n = len(g)
        if n < min_bonds:
            continue

        # Stable sorting avoids arbitrary results for exact ties.
        g = g.sort_values([signal_col, "cusip"], ascending=[True, True]).reset_index(drop=True)
        k = max(1, int(math.floor(quantile * n)))
        if 2 * k > n:
            k = max(1, n // 2)
        if k <= 0:
            continue

        short = g.iloc[:k].copy()
        long = g.iloc[-k:].copy()

        long_mean_resid = float(long[signal_col].mean())
        short_mean_resid = float(short[signal_col].mean())

        if min_abs_side_residual_bps is not None:
            if max(abs(long_mean_resid), abs(short_mean_resid)) < min_abs_side_residual_bps:
                continue

        long_ret = float(long[target_col].mean())
        short_ret = float(short[target_col].mean())
        issuer_spread = long_ret - short_ret

        issuer_rows.append(
            {
                "issuer_id": issuer_id,
                "feature_month": feature_month,
                "target_month": target_month,
                "issuer_n": n,
                "k_each_side": k,
                "long_ret": long_ret,
                "short_ret": short_ret,
                "issuer_spread": issuer_spread,
                "long_mean_residual_bps": long_mean_resid,
                "short_mean_residual_bps": short_mean_resid,
            }
        )

        long_pos = long[["issuer_id", "feature_month", "target_month", "cusip", signal_col, target_col]].copy()
        short_pos = short[["issuer_id", "feature_month", "target_month", "cusip", signal_col, target_col]].copy()
        long_pos["side"] = "long"
        short_pos["side"] = "short"
        position_rows.append(long_pos)
        position_rows.append(short_pos)

    issuer_months = pd.DataFrame(issuer_rows)
    if issuer_months.empty:
        monthly = pd.DataFrame(columns=["target_month", "strategy_ret", "n_issuer_months", "avg_bonds_per_issuer", "avg_k_each_side", "long_ret", "short_ret"])
        positions = pd.DataFrame()
        return issuer_months, positions, monthly

    monthly = issuer_months.groupby("target_month").agg(
        strategy_ret=("issuer_spread", "mean"),
        n_issuer_months=("issuer_id", "count"),
        avg_bonds_per_issuer=("issuer_n", "mean"),
        avg_k_each_side=("k_each_side", "mean"),
        long_ret=("long_ret", "mean"),
        short_ret=("short_ret", "mean"),
    ).reset_index().sort_values("target_month")

    positions = pd.concat(position_rows, ignore_index=True) if position_rows else pd.DataFrame()
    return issuer_months, positions, monthly


def make_plots(root: Path, tag: str, base_monthly: pd.DataFrame, variants: pd.DataFrame, placebo: pd.DataFrame | None) -> list[str]:
    saved: list[str] = []
    if plt is None:
        return saved

    fig_dir = root / "reports" / "figures"
    fig_dir.mkdir(parents=True, exist_ok=True)

    if base_monthly is not None and not base_monthly.empty:
        m = base_monthly.copy()
        m["target_month"] = pd.to_datetime(m["target_month"])
        m["cum_ret"] = (1.0 + m["strategy_ret"]).cumprod() - 1.0

        fig, ax = plt.subplots(figsize=(9, 4.8))
        ax.plot(m["target_month"], m["cum_ret"] * 100.0, marker="o")
        ax.set_title(f"7.1 Validation: cumulative issuer-relative sort ({tag})")
        ax.set_ylabel("Cumulative return, %")
        ax.set_xlabel("Target month")
        ax.grid(alpha=0.25)
        fig.tight_layout()
        path = fig_dir / f"7.1_validation_cumulative_{tag}.png"
        fig.savefig(path, dpi=220, bbox_inches="tight")
        plt.close(fig)
        saved.append(str(path.relative_to(root)))

    if variants is not None and not variants.empty:
        top = variants.sort_values("mean_monthly", ascending=True).copy()
        labels = top["variant"].astype(str).tolist()
        vals = (top["mean_monthly"].astype(float) * 100.0).tolist()

        fig_h = max(4.0, 0.38 * len(labels) + 1.4)
        fig, ax = plt.subplots(figsize=(10, fig_h))
        ax.barh(labels, vals)
        ax.set_title(f"7.1 Robustness variants: mean monthly return ({tag})")
        ax.set_xlabel("Mean monthly return, %")
        ax.grid(axis="x", alpha=0.25)
        fig.tight_layout()
        path = fig_dir / f"7.1_robustness_variants_{tag}.png"
        fig.savefig(path, dpi=220, bbox_inches="tight")
        plt.close(fig)
        saved.append(str(path.relative_to(root)))

    if placebo is not None and not placebo.empty and "mean_monthly" in placebo.columns:
        fig, ax = plt.subplots(figsize=(8, 4.8))
        ax.hist(placebo["mean_monthly"] * 100.0, bins=40, alpha=0.75)
        actual = placebo.attrs.get("actual_mean_monthly")
        if actual is not None:
            ax.axvline(actual * 100.0, linestyle="--", linewidth=2)
        ax.set_title(f"7.1 Placebo distribution: shuffled within issuer-month ({tag})")
        ax.set_xlabel("Mean monthly return, %")
        ax.set_ylabel("Permutation count")
        ax.grid(alpha=0.2)
        fig.tight_layout()
        path = fig_dir / f"7.1_placebo_distribution_{tag}.png"
        fig.savefig(path, dpi=220, bbox_inches="tight")
        plt.close(fig)
        saved.append(str(path.relative_to(root)))

    return saved


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--project-root", required=True)
    parser.add_argument("--tag", default="full2024")
    parser.add_argument("--panel", default="artifacts/processed/6.0_model_panel_full2024.parquet")
    parser.add_argument("--baseline-monthly", default="artifacts/processed/7.0_residual_sort_monthly_full2024.csv")
    parser.add_argument("--n-permutations", type=int, default=500)
    parser.add_argument("--seed", type=int, default=1729)
    parser.add_argument("--bundle", action="store_true")
    args = parser.parse_args()

    root = Path(args.project_root).resolve()
    disc = root / "artifacts" / "discovery"
    processed = root / "artifacts" / "processed"
    logs = root / "logs"

    for p in [disc, processed, logs, root / "reports" / "figures"]:
        p.mkdir(parents=True, exist_ok=True)

    run_utc = datetime.now(timezone.utc).isoformat()
    tag = args.tag

    print("=" * 72)
    print(f"7.1 validation and robustness ({tag})")
    print("Run UTC:", run_utc)
    print("Project:", root)
    print("=" * 72)

    panel_path = root / args.panel
    if not panel_path.exists():
        raise FileNotFoundError(panel_path)

    print("[LOAD]", panel_path)
    panel_raw = pd.read_parquet(panel_path)
    panel = prepare_panel(panel_raw)

    baseline_monthly_path = root / args.baseline_monthly
    baseline_monthly = None
    if baseline_monthly_path.exists():
        baseline_monthly = pd.read_csv(baseline_monthly_path)
        if "target_month" in baseline_monthly.columns:
            baseline_monthly["target_month"] = pd.to_datetime(baseline_monthly["target_month"])
        print("[LOAD]", baseline_monthly_path)
    else:
        print("[WARN] Baseline monthly CSV not found; recomputing base strategy.")

    # Look-ahead and alignment checks
    alignment = {
        "input_panel_rows": int(len(panel_raw)),
        "usable_panel_rows": int(len(panel)),
        "feature_month_min": str(panel["feature_month"].min()),
        "feature_month_max": str(panel["feature_month"].max()),
        "target_month_min": str(panel["target_month"].min()),
        "target_month_max": str(panel["target_month"].max()),
        "target_after_feature_share": float((panel["target_month"] > panel["feature_month"]).mean()),
        "target_equals_feature_plus_one_month_share": float((panel["target_month"] == month_end_plus_one(panel["feature_month"])).mean()),
        "duplicate_cusip_feature_target_rows": int(panel.duplicated(["cusip", "feature_month", "target_month"]).sum()),
        "missing_residual_rows": int(panel_raw["residual_yield_bps"].isna().sum()) if "residual_yield_bps" in panel_raw.columns else None,
        "missing_target_rows": int(panel_raw["issuer_demeaned_ret_1m"].isna().sum()) if "issuer_demeaned_ret_1m" in panel_raw.columns else None,
    }

    print("[ALIGNMENT]")
    print(json.dumps(alignment, indent=2))

    # Recompute the baseline from model panel so variants are comparable.
    base_issuer, base_pos, base_monthly = compute_strategy(
        panel,
        quantile=0.20,
        min_bonds=3,
        target_col="issuer_demeaned_ret_1m",
        signal_col="residual_yield_bps",
    )

    base_perf = perf_stats(base_monthly)

    # Robustness grid
    variants_config: list[dict[str, Any]] = [
        {"variant": "base_q20_min3", "quantile": 0.20, "min_bonds": 3},
        {"variant": "q10_min3", "quantile": 0.10, "min_bonds": 3},
        {"variant": "q30_min3", "quantile": 0.30, "min_bonds": 3},
        {"variant": "q20_min5", "quantile": 0.20, "min_bonds": 5},
        {"variant": "q20_min8", "quantile": 0.20, "min_bonds": 8},
        {"variant": "q20_min10", "quantile": 0.20, "min_bonds": 10},
        {"variant": "q20_min5_winsor1pct", "quantile": 0.20, "min_bonds": 5, "winsor_target": 0.01},
        {"variant": "q20_min5_ex_abs_gt_10pct", "quantile": 0.20, "min_bonds": 5, "exclude_abs_target_gt": 0.10},
        {"variant": "q20_min5_ex_abs_gt_5pct", "quantile": 0.20, "min_bonds": 5, "exclude_abs_target_gt": 0.05},
        {"variant": "q20_min5_min_side_resid_5bps", "quantile": 0.20, "min_bonds": 5, "min_abs_side_residual_bps": 5.0},
        {"variant": "q20_min5_min_side_resid_10bps", "quantile": 0.20, "min_bonds": 5, "min_abs_side_residual_bps": 10.0},
    ]

    variant_rows: list[dict[str, Any]] = []
    for cfg in variants_config:
        label = cfg["variant"]
        kwargs = {k: v for k, v in cfg.items() if k != "variant"}
        im, pos, mon = compute_strategy(panel, target_col="issuer_demeaned_ret_1m", signal_col="residual_yield_bps", **kwargs)
        stats = perf_stats(mon)
        row = {
            "variant": label,
            "issuer_months": int(len(im)),
            "position_rows": int(len(pos)),
            **stats,
        }
        variant_rows.append(row)
        mon_out = processed / f"7.1_variant_monthly_{label}_{tag}.csv"
        mon.to_csv(mon_out, index=False)
        print("[VARIANT]", label, json.dumps(row, default=str))

    variants = pd.DataFrame(variant_rows)
    variants_path = disc / f"7.1_robustness_variants_{tag}.csv"
    variants.to_csv(variants_path, index=False)
    print("[WROTE]", variants_path)

    # Placebo test
    rng = np.random.default_rng(args.seed)
    placebo_rows: list[dict[str, Any]] = []
    n_perm = max(0, int(args.n_permutations))
    actual_mean = base_perf.get("mean_monthly")

    print(f"[PLACEBO] permutations={n_perm}")
    for i in range(n_perm):
        _, _, mon = compute_strategy(
            panel,
            quantile=0.20,
            min_bonds=3,
            target_col="issuer_demeaned_ret_1m",
            signal_col="residual_yield_bps",
            randomize_signal=True,
            rng=rng,
        )
        stats = perf_stats(mon)
        placebo_rows.append(
            {
                "perm": i,
                "mean_monthly": stats["mean_monthly"],
                "ann_sharpe": stats["ann_sharpe"],
                "cumulative_return": stats["cumulative_return"],
                "positive_month_share": stats["positive_month_share"],
            }
        )
        if (i + 1) % 50 == 0:
            print(f"  completed {i + 1}/{n_perm}")

    placebo = pd.DataFrame(placebo_rows)
    if not placebo.empty and actual_mean is not None:
        placebo["beats_actual_mean"] = placebo["mean_monthly"] >= actual_mean
        placebo["abs_beats_actual_mean"] = placebo["mean_monthly"].abs() >= abs(actual_mean)
        placebo_p = float(placebo["beats_actual_mean"].mean())
        placebo_twosided_p = float(placebo["abs_beats_actual_mean"].mean())
        placebo.attrs["actual_mean_monthly"] = actual_mean
    else:
        placebo_p = None
        placebo_twosided_p = None

    placebo_path = disc / f"7.1_placebo_permutations_{tag}.csv"
    placebo.to_csv(placebo_path, index=False)
    print("[WROTE]", placebo_path)

    # Contribution diagnostics
    contrib = base_issuer.copy()
    if not contrib.empty:
        contrib["abs_spread"] = contrib["issuer_spread"].abs()
        contrib = contrib.sort_values("abs_spread", ascending=False)
    contrib_path = disc / f"7.1_largest_issuer_month_contributions_{tag}.csv"
    contrib.head(200).to_csv(contrib_path, index=False)
    print("[WROTE]", contrib_path)

    # Target / signal tails
    tail_summary = {}
    for col in ["residual_yield_bps", "issuer_demeaned_ret_1m", "target_ret_1m"]:
        if col in panel.columns:
            s = pd.to_numeric(panel[col], errors="coerce").dropna()
            tail_summary[col] = {
                "count": int(s.shape[0]),
                "mean": float(s.mean()),
                "std": float(s.std(ddof=1)),
                "min": float(s.min()),
                "p001": float(s.quantile(0.001)),
                "p01": float(s.quantile(0.01)),
                "p05": float(s.quantile(0.05)),
                "median": float(s.quantile(0.50)),
                "p95": float(s.quantile(0.95)),
                "p99": float(s.quantile(0.99)),
                "p999": float(s.quantile(0.999)),
                "max": float(s.max()),
            }

    figures = make_plots(root, tag, base_monthly, variants, placebo)

    summary = {
        "run_utc": run_utc,
        "tag": tag,
        "alignment": alignment,
        "base_performance_recomputed": base_perf,
        "base_issuer_months": int(len(base_issuer)),
        "base_position_rows": int(len(base_pos)),
        "variant_count": int(len(variants)),
        "placebo_permutations": int(n_perm),
        "placebo_one_sided_p_mean_ge_actual": placebo_p,
        "placebo_two_sided_p_abs_mean_ge_actual": placebo_twosided_p,
        "tail_summary": tail_summary,
        "outputs": {
            "variants_csv": str(variants_path.relative_to(root)),
            "placebo_csv": str(placebo_path.relative_to(root)),
            "largest_contrib_csv": str(contrib_path.relative_to(root)),
            "figures": figures,
        },
    }

    summary_path = disc / f"7.1_validation_summary_{tag}.json"
    summary_path.write_text(json.dumps(summary, indent=2, sort_keys=True, default=str))
    print("[WROTE]", summary_path)

    # Markdown report
    def md_table(df: pd.DataFrame, n: int = 20) -> str:
        if df.empty:
            return "_No rows._"
        try:
            return df.head(n).to_markdown(index=False)
        except Exception:
            return df.head(n).to_string(index=False)

    report_lines = [
        f"# 7.1 Validation and robustness report ({tag})",
        "",
        f"- Run UTC: `{run_utc}`",
        f"- Input panel rows: `{len(panel_raw):,}`",
        f"- Usable rows: `{len(panel):,}`",
        f"- Recomputed base issuer-month groups: `{len(base_issuer):,}`",
        f"- Recomputed base position rows: `{len(base_pos):,}`",
        "",
        "## Alignment checks",
        "",
        "```json",
        json.dumps(alignment, indent=2),
        "```",
        "",
        "## Recomputed base performance",
        "",
        "```json",
        json.dumps(base_perf, indent=2),
        "```",
        "",
        "## Robustness variants",
        "",
        md_table(variants.sort_values("variant")),
        "",
        "## Placebo test",
        "",
        f"- Permutations: `{n_perm}`",
        f"- One-sided placebo p-value, shuffled mean >= actual mean: `{placebo_p}`",
        f"- Two-sided placebo p-value, abs(shuffled mean) >= abs(actual mean): `{placebo_twosided_p}`",
        "",
        "## Tail summary",
        "",
        "```json",
        json.dumps(tail_summary, indent=2),
        "```",
        "",
        "## Largest absolute issuer-month contributions",
        "",
        md_table(contrib, n=30),
        "",
        "## Outputs",
        "",
        f"- `{variants_path.relative_to(root)}`",
        f"- `{placebo_path.relative_to(root)}`",
        f"- `{contrib_path.relative_to(root)}`",
        f"- `{summary_path.relative_to(root)}`",
    ]

    for fig in figures:
        report_lines.append(f"- `{fig}`")

    report_path = disc / f"7.1_validation_report_{tag}.md"
    report_path.write_text("\n".join(report_lines) + "\n")
    print("[WROTE]", report_path)

    if args.bundle:
        bundle = root / f"step7_1_validation_logs_reports_{tag}_{utc_stamp()}.tar.gz"
        with tarfile.open(bundle, "w:gz") as tar:
            for rel in [
                "artifacts/discovery",
                "reports/figures",
                "logs",
                "configs",
                "scripts",
            ]:
                p = root / rel
                if p.exists():
                    tar.add(p, arcname=rel)
        print("[BUNDLE]", bundle)

    print("[DONE] 7.1 validation complete.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
