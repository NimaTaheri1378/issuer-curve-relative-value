
#!/usr/bin/env python
from __future__ import annotations

import argparse
import json
import math
import multiprocessing as mp
import os
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
except Exception:  # pragma: no cover
    plt = None

_GLOBAL_GROUPS: list[tuple[int, np.ndarray, int]] = []
_GLOBAL_N_MONTHS: int = 0


def utc_stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def ensure_dir(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    return path


def perf_from_monthly(monthly_returns: pd.Series | np.ndarray) -> dict[str, Any]:
    arr = np.asarray(monthly_returns, dtype=float)
    arr = arr[np.isfinite(arr)]
    if arr.size == 0:
        return {
            "n_months": 0,
            "mean_monthly": None,
            "std_monthly": None,
            "t_stat_mean": None,
            "ann_sharpe": None,
            "cumulative_return": None,
            "max_drawdown": None,
            "min_month": None,
            "max_month": None,
        }
    mean = float(arr.mean())
    std = float(arr.std(ddof=1)) if arr.size > 1 else 0.0
    t_stat = float(mean / (std / math.sqrt(arr.size))) if std > 0 and arr.size > 1 else None
    sharpe = float(mean / std * math.sqrt(12.0)) if std > 0 else None
    wealth = np.cumprod(1.0 + arr)
    peak = np.maximum.accumulate(wealth)
    dd = wealth / peak - 1.0
    return {
        "n_months": int(arr.size),
        "mean_monthly": mean,
        "std_monthly": std,
        "t_stat_mean": t_stat,
        "ann_sharpe": sharpe,
        "cumulative_return": float(wealth[-1] - 1.0),
        "max_drawdown": float(dd.min()),
        "min_month": float(arr.min()),
        "max_month": float(arr.max()),
    }


def winsorize_series(x: pd.Series, lo: float, hi: float) -> pd.Series:
    qlo = x.quantile(lo)
    qhi = x.quantile(hi)
    return x.clip(qlo, qhi)


def compute_strategy(
    panel: pd.DataFrame,
    min_bonds: int = 3,
    quantile: float = 0.20,
    winsor: tuple[float, float] | None = None,
) -> tuple[pd.DataFrame, pd.DataFrame, dict[str, Any]]:
    required = [
        "issuer_id",
        "feature_month",
        "target_month",
        "cusip",
        "residual_yield_bps",
        "issuer_demeaned_ret_1m",
    ]
    missing = [c for c in required if c not in panel.columns]
    if missing:
        raise ValueError(f"Missing required columns: {missing}")

    df = panel.loc[
        panel["issuer_id"].notna()
        & panel["feature_month"].notna()
        & panel["target_month"].notna()
        & panel["residual_yield_bps"].notna()
        & panel["issuer_demeaned_ret_1m"].notna(),
        required,
    ].copy()

    df["feature_month"] = pd.to_datetime(df["feature_month"])
    df["target_month"] = pd.to_datetime(df["target_month"])
    df["issuer_id"] = df["issuer_id"].astype(str)

    if winsor is not None:
        df["issuer_demeaned_ret_1m"] = winsorize_series(
            df["issuer_demeaned_ret_1m"].astype(float), winsor[0], winsor[1]
        )

    rows: list[dict[str, Any]] = []
    position_rows: list[dict[str, Any]] = []

    for (issuer_id, feature_month, target_month), g in df.groupby(
        ["issuer_id", "feature_month", "target_month"], sort=False
    ):
        n = len(g)
        if n < min_bonds:
            continue
        k = int(math.floor(n * quantile))
        k = max(1, k)
        if 2 * k > n:
            k = max(1, n // 2)
        if k < 1:
            continue

        ordered = g.sort_values("residual_yield_bps")
        short = ordered.head(k)
        long = ordered.tail(k)
        long_ret = float(long["issuer_demeaned_ret_1m"].mean())
        short_ret = float(short["issuer_demeaned_ret_1m"].mean())
        spread = long_ret - short_ret
        rows.append(
            {
                "issuer_id": issuer_id,
                "feature_month": feature_month,
                "target_month": target_month,
                "issuer_n": int(n),
                "k_each_side": int(k),
                "long_ret": long_ret,
                "short_ret": short_ret,
                "issuer_spread": spread,
                "long_mean_residual_bps": float(long["residual_yield_bps"].mean()),
                "short_mean_residual_bps": float(short["residual_yield_bps"].mean()),
            }
        )
        for side, sub in [("long", long), ("short", short)]:
            for r in sub.itertuples(index=False):
                position_rows.append(
                    {
                        "issuer_id": issuer_id,
                        "feature_month": feature_month,
                        "target_month": target_month,
                        "cusip": r.cusip,
                        "side": side,
                        "residual_yield_bps": float(r.residual_yield_bps),
                        "issuer_demeaned_ret_1m": float(r.issuer_demeaned_ret_1m),
                    }
                )

    issuer_months = pd.DataFrame(rows)
    positions = pd.DataFrame(position_rows)

    if issuer_months.empty:
        monthly = pd.DataFrame(
            columns=["target_month", "strategy_ret", "n_issuer_months", "avg_bonds_per_issuer", "avg_k_each_side", "long_ret", "short_ret"]
        )
        perf = perf_from_monthly(np.array([]))
        return issuer_months, monthly, perf

    monthly = (
        issuer_months.groupby("target_month")
        .agg(
            strategy_ret=("issuer_spread", "mean"),
            n_issuer_months=("issuer_spread", "count"),
            avg_bonds_per_issuer=("issuer_n", "mean"),
            avg_k_each_side=("k_each_side", "mean"),
            long_ret=("long_ret", "mean"),
            short_ret=("short_ret", "mean"),
        )
        .reset_index()
        .sort_values("target_month")
    )
    perf = perf_from_monthly(monthly["strategy_ret"].to_numpy())
    perf["issuer_month_groups"] = int(len(issuer_months))
    perf["position_rows"] = int(len(positions))
    return issuer_months, monthly, perf


def build_placebo_groups(panel: pd.DataFrame, min_bonds: int, quantile: float) -> tuple[list[tuple[int, np.ndarray, int]], list[pd.Timestamp]]:
    df = panel.loc[
        panel["issuer_id"].notna()
        & panel["feature_month"].notna()
        & panel["target_month"].notna()
        & panel["residual_yield_bps"].notna()
        & panel["issuer_demeaned_ret_1m"].notna(),
        ["issuer_id", "feature_month", "target_month", "issuer_demeaned_ret_1m"],
    ].copy()
    df["feature_month"] = pd.to_datetime(df["feature_month"])
    df["target_month"] = pd.to_datetime(df["target_month"])
    months = sorted(pd.to_datetime(df["target_month"].dropna().unique()))
    month_to_i = {m: i for i, m in enumerate(months)}
    groups: list[tuple[int, np.ndarray, int]] = []
    for (_, _, target_month), g in df.groupby(["issuer_id", "feature_month", "target_month"], sort=False):
        n = len(g)
        if n < min_bonds:
            continue
        k = max(1, int(math.floor(n * quantile)))
        if 2 * k > n:
            k = max(1, n // 2)
        if k < 1:
            continue
        y = g["issuer_demeaned_ret_1m"].astype(float).to_numpy(copy=True)
        groups.append((month_to_i[pd.Timestamp(target_month)], y, k))
    return groups, months


def _init_pool(groups: list[tuple[int, np.ndarray, int]], n_months: int) -> None:
    global _GLOBAL_GROUPS, _GLOBAL_N_MONTHS
    _GLOBAL_GROUPS = groups
    _GLOBAL_N_MONTHS = n_months


def _one_placebo(seed: int) -> dict[str, Any]:
    rng = np.random.default_rng(seed)
    sums = np.zeros(_GLOBAL_N_MONTHS, dtype=float)
    counts = np.zeros(_GLOBAL_N_MONTHS, dtype=np.int64)
    for month_i, y, k in _GLOBAL_GROUPS:
        n = y.size
        order = rng.permutation(n)
        short_idx = order[:k]
        long_idx = order[-k:]
        spread = float(y[long_idx].mean() - y[short_idx].mean())
        sums[month_i] += spread
        counts[month_i] += 1
    monthly = np.divide(sums, counts, out=np.full_like(sums, np.nan), where=counts > 0)
    perf = perf_from_monthly(monthly)
    return {
        "mean_monthly": perf["mean_monthly"],
        "ann_sharpe": perf["ann_sharpe"],
        "cumulative_return": perf["cumulative_return"],
        "max_drawdown": perf["max_drawdown"],
    }


def run_placebo(panel: pd.DataFrame, n_perm: int, workers: int, min_bonds: int, quantile: float, seed: int) -> tuple[pd.DataFrame, dict[str, Any]]:
    groups, months = build_placebo_groups(panel, min_bonds=min_bonds, quantile=quantile)
    print(f"[PLACEBO] groups={len(groups):,}, months={len(months)}, permutations={n_perm}, workers={workers}", flush=True)
    if not groups or n_perm <= 0:
        return pd.DataFrame(), {"n_groups": len(groups), "n_months": len(months)}

    seeds = [seed + i * 104729 for i in range(n_perm)]
    workers = max(1, int(workers))
    rows: list[dict[str, Any]] = []
    if workers == 1:
        _init_pool(groups, len(months))
        for i, s in enumerate(seeds, 1):
            rows.append(_one_placebo(s))
            if i % 25 == 0 or i == n_perm:
                print(f"[PLACEBO] completed {i}/{n_perm}", flush=True)
    else:
        ctx = mp.get_context("fork") if "fork" in mp.get_all_start_methods() else mp.get_context()
        with ctx.Pool(processes=workers, initializer=_init_pool, initargs=(groups, len(months))) as pool:
            for i, row in enumerate(pool.imap_unordered(_one_placebo, seeds, chunksize=max(1, n_perm // (workers * 8))), 1):
                rows.append(row)
                if i % 25 == 0 or i == n_perm:
                    print(f"[PLACEBO] completed {i}/{n_perm}", flush=True)
    placebo = pd.DataFrame(rows)
    placebo.insert(0, "perm_id", np.arange(len(placebo)))
    meta = {"n_groups": len(groups), "n_months": len(months)}
    return placebo, meta


def make_figures(fig_dir: Path, monthly: pd.DataFrame, variants: pd.DataFrame, placebo: pd.DataFrame, actual_mean: float, tag: str) -> None:
    if plt is None:
        return
    ensure_dir(fig_dir)
    if not monthly.empty:
        m = monthly.copy()
        m["target_month"] = pd.to_datetime(m["target_month"])
        m["wealth"] = (1.0 + m["strategy_ret"]).cumprod() - 1.0
        fig, ax = plt.subplots(figsize=(9, 4.8))
        ax.plot(m["target_month"], m["wealth"] * 100.0, marker="o")
        ax.set_title(f"Validation: cumulative residual-sort return ({tag})")
        ax.set_ylabel("Cumulative return, %")
        ax.set_xlabel("Target month")
        ax.grid(alpha=0.25)
        fig.tight_layout()
        fig.savefig(fig_dir / f"7.1_validation_cumulative_{tag}.png", dpi=220, bbox_inches="tight")
        plt.close(fig)

    if not variants.empty:
        v = variants.sort_values("mean_monthly")
        fig, ax = plt.subplots(figsize=(10, max(4, 0.35 * len(v) + 1)))
        ax.barh(v["variant"], v["mean_monthly"] * 100.0)
        ax.set_title(f"Robustness variants ({tag})")
        ax.set_xlabel("Mean monthly return, %")
        ax.grid(axis="x", alpha=0.25)
        fig.tight_layout()
        fig.savefig(fig_dir / f"7.1_robustness_variants_{tag}.png", dpi=220, bbox_inches="tight")
        plt.close(fig)

    if not placebo.empty and "mean_monthly" in placebo:
        fig, ax = plt.subplots(figsize=(8.5, 4.8))
        ax.hist(placebo["mean_monthly"].dropna() * 100.0, bins=40, alpha=0.85)
        ax.axvline(actual_mean * 100.0, linestyle="--", linewidth=2.0, label="Actual")
        ax.set_title(f"Placebo distribution: shuffled residual ranks ({tag})")
        ax.set_xlabel("Mean monthly return, %")
        ax.set_ylabel("Permutation count")
        ax.legend()
        ax.grid(alpha=0.2)
        fig.tight_layout()
        fig.savefig(fig_dir / f"7.1_placebo_distribution_{tag}.png", dpi=220, bbox_inches="tight")
        plt.close(fig)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--project-root", required=True)
    parser.add_argument("--tag", default="full2024")
    parser.add_argument("--panel", default="artifacts/processed/6.0_model_panel_full2024.parquet")
    parser.add_argument("--baseline-monthly", default="artifacts/processed/7.0_residual_sort_monthly_full2024.csv")
    parser.add_argument("--n-permutations", type=int, default=int(os.environ.get("N_PERMUTATIONS", "500")))
    parser.add_argument("--workers", type=int, default=int(os.environ.get("N_WORKERS", str(min(32, os.cpu_count() or 1)))))
    parser.add_argument("--min-bonds", type=int, default=3)
    parser.add_argument("--quantile", type=float, default=0.20)
    parser.add_argument("--seed", type=int, default=1729)
    parser.add_argument("--bundle", action="store_true")
    args = parser.parse_args()

    root = Path(args.project_root).resolve()
    disc = ensure_dir(root / "artifacts" / "discovery")
    processed = ensure_dir(root / "artifacts" / "processed")
    figs = ensure_dir(root / "reports" / "figures")
    logs = ensure_dir(root / "logs")
    run_id = utc_stamp()

    print("=" * 72, flush=True)
    print("7.1 parallel validation and robustness", flush=True)
    print(f"Project: {root}", flush=True)
    print(f"Tag: {args.tag}", flush=True)
    print(f"Permutations: {args.n_permutations}", flush=True)
    print(f"Workers: {args.workers}", flush=True)
    print("=" * 72, flush=True)

    panel_path = root / args.panel
    panel = pd.read_parquet(panel_path)
    print(f"[LOAD] panel rows={len(panel):,} from {panel_path}", flush=True)

    for col in ["feature_month", "target_month"]:
        if col in panel.columns:
            panel[col] = pd.to_datetime(panel[col])

    alignment = {
        "panel_rows": int(len(panel)),
        "rows_with_target": int(panel.get("target_ret_1m", pd.Series(dtype=float)).notna().sum()) if "target_ret_1m" in panel else None,
        "rows_with_issuer_demeaned_target": int(panel["issuer_demeaned_ret_1m"].notna().sum()) if "issuer_demeaned_ret_1m" in panel else None,
        "feature_month_min": str(panel["feature_month"].min()) if "feature_month" in panel else None,
        "feature_month_max": str(panel["feature_month"].max()) if "feature_month" in panel else None,
        "target_month_min": str(panel["target_month"].min()) if "target_month" in panel else None,
        "target_month_max": str(panel["target_month"].max()) if "target_month" in panel else None,
        "target_not_after_feature_rows": int((panel["target_month"] <= panel["feature_month"]).sum()) if {"target_month", "feature_month"}.issubset(panel.columns) else None,
        "duplicate_cusip_feature_month_rows": int(panel.duplicated(["cusip", "feature_month"]).sum()) if {"cusip", "feature_month"}.issubset(panel.columns) else None,
    }
    print("[ALIGNMENT]", json.dumps(alignment, indent=2), flush=True)

    issuer_months, monthly, base_perf = compute_strategy(panel, min_bonds=args.min_bonds, quantile=args.quantile)
    actual_mean = float(base_perf["mean_monthly"] or 0.0)
    print("[BASE]", json.dumps(base_perf, indent=2), flush=True)

    monthly.to_csv(processed / f"7.1_recomputed_monthly_{args.tag}.csv", index=False)
    issuer_months.to_parquet(processed / f"7.1_recomputed_issuer_months_{args.tag}.parquet", index=False)

    variants_spec = [
        ("base_min3_q20", 3, 0.20, None),
        ("min5_q20", 5, 0.20, None),
        ("min8_q20", 8, 0.20, None),
        ("min10_q20", 10, 0.20, None),
        ("min3_q10", 3, 0.10, None),
        ("min3_q30", 3, 0.30, None),
        ("winsor_1_99", 3, 0.20, (0.01, 0.99)),
        ("winsor_5_95", 3, 0.20, (0.05, 0.95)),
    ]
    variant_rows = []
    for name, mb, q, win in variants_spec:
        print(f"[ROBUST] {name}", flush=True)
        im, mon, perf = compute_strategy(panel, min_bonds=mb, quantile=q, winsor=win)
        variant_rows.append({"variant": name, "min_bonds": mb, "quantile": q, "winsor": str(win), **perf})
    variants = pd.DataFrame(variant_rows)
    variants.to_csv(disc / f"7.1_robustness_variants_{args.tag}.csv", index=False)

    placebo, placebo_meta = run_placebo(
        panel,
        n_perm=args.n_permutations,
        workers=args.workers,
        min_bonds=args.min_bonds,
        quantile=args.quantile,
        seed=args.seed,
    )
    placebo.to_csv(disc / f"7.1_placebo_permutations_{args.tag}.csv", index=False)

    if placebo.empty:
        p_one = None
        p_two = None
    else:
        pvals = placebo["mean_monthly"].dropna().to_numpy(dtype=float)
        p_one = float((1 + np.sum(pvals >= actual_mean)) / (len(pvals) + 1))
        p_two = float((1 + np.sum(np.abs(pvals) >= abs(actual_mean))) / (len(pvals) + 1))

    largest = issuer_months.sort_values("issuer_spread", ascending=False).head(25) if not issuer_months.empty else pd.DataFrame()
    smallest = issuer_months.sort_values("issuer_spread", ascending=True).head(25) if not issuer_months.empty else pd.DataFrame()
    if not largest.empty:
        largest.to_csv(disc / f"7.1_largest_issuer_month_contributions_{args.tag}.csv", index=False)
    if not smallest.empty:
        smallest.to_csv(disc / f"7.1_smallest_issuer_month_contributions_{args.tag}.csv", index=False)

    make_figures(figs, monthly, variants, placebo, actual_mean, args.tag)

    summary = {
        "run_utc": datetime.now(timezone.utc).isoformat(),
        "tag": args.tag,
        "alignment": alignment,
        "base_performance_recomputed": base_perf,
        "placebo_permutations": int(len(placebo)),
        "placebo_meta": placebo_meta,
        "placebo_one_sided_p_mean_ge_actual": p_one,
        "placebo_two_sided_p_abs_mean_ge_actual": p_two,
        "workers": int(args.workers),
        "n_permutations_requested": int(args.n_permutations),
        "robustness_variants": variant_rows,
    }
    (disc / f"7.1_validation_summary_{args.tag}.json").write_text(json.dumps(summary, indent=2, sort_keys=True, default=str))

    def md_table(df: pd.DataFrame, max_rows: int = 20) -> str:
        if df.empty:
            return "_No rows._"
        try:
            return df.head(max_rows).to_markdown(index=False)
        except Exception:
            return df.head(max_rows).to_string(index=False)

    report = [
        f"# 7.1 Validation report ({args.tag})",
        "",
        f"- Run UTC: `{summary['run_utc']}`",
        f"- Panel rows: `{alignment['panel_rows']:,}`",
        f"- Rows with issuer-demeaned target: `{alignment['rows_with_issuer_demeaned_target']:,}`",
        f"- Permutations: `{len(placebo):,}`",
        f"- Workers: `{args.workers}`",
        "",
        "## Alignment checks",
        "",
        "```json",
        json.dumps(alignment, indent=2, default=str),
        "```",
        "",
        "## Base performance recomputed",
        "",
        "```json",
        json.dumps(base_perf, indent=2, default=str),
        "```",
        "",
        "## Placebo test",
        "",
        f"- One-sided p-value, placebo mean >= actual mean: `{p_one}`",
        f"- Two-sided p-value, |placebo mean| >= |actual mean|: `{p_two}`",
        "",
        "## Robustness variants",
        "",
        md_table(variants, max_rows=30),
        "",
        "## Recomputed monthly returns",
        "",
        md_table(monthly, max_rows=30),
        "",
        "## Largest issuer-month contributions",
        "",
        md_table(largest, max_rows=15),
        "",
        "## Smallest issuer-month contributions",
        "",
        md_table(smallest, max_rows=15),
        "",
        "## Outputs",
        "",
        f"- `artifacts/discovery/7.1_validation_summary_{args.tag}.json`",
        f"- `artifacts/discovery/7.1_robustness_variants_{args.tag}.csv`",
        f"- `artifacts/discovery/7.1_placebo_permutations_{args.tag}.csv`",
        f"- `reports/figures/7.1_validation_cumulative_{args.tag}.png`",
        f"- `reports/figures/7.1_robustness_variants_{args.tag}.png`",
        f"- `reports/figures/7.1_placebo_distribution_{args.tag}.png`",
    ]
    (disc / f"7.1_validation_report_{args.tag}.md").write_text("\n".join(report) + "\n")

    if args.bundle:
        bundle = root / f"step7_1_validation_parallel_logs_reports_{args.tag}_{run_id}.tar.gz"
        with tarfile.open(bundle, "w:gz") as tar:
            for rel in ["logs", "artifacts/discovery", "reports/figures"]:
                path = root / rel
                if path.exists():
                    tar.add(path, arcname=rel)
        print(f"[BUNDLE] {bundle}", flush=True)

    print(f"[WROTE] {disc / f'7.1_validation_report_{args.tag}.md'}", flush=True)
    print("[DONE] 7.1 parallel validation complete.", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
