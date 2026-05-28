#!/usr/bin/env python
from __future__ import annotations

import argparse
import json
import math
import sys
import tarfile
import traceback
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import wrds

try:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
except Exception:
    plt = None


def utc_stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def iso_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def ensure_dirs(root: Path) -> dict[str, Path]:
    paths = {
        "logs": root / "logs",
        "disc": root / "artifacts" / "discovery",
        "processed": root / "artifacts" / "processed",
        "figures": root / "reports" / "figures",
    }
    for p in paths.values():
        p.mkdir(parents=True, exist_ok=True)
    return paths


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


def normalize_cusip(s: pd.Series) -> pd.Series:
    return s.astype(str).str.strip().str.upper().str.replace(r"[^A-Z0-9]", "", regex=True)


def table_to_markdown(df: pd.DataFrame, max_rows: int = 20) -> str:
    if df.empty:
        return "_empty_"
    sub = df.head(max_rows).copy()
    cols = list(sub.columns)
    lines = ["| " + " | ".join(cols) + " |", "| " + " | ".join(["---"] * len(cols)) + " |"]
    for _, row in sub.iterrows():
        vals = []
        for c in cols:
            v = row[c]
            if isinstance(v, float):
                if math.isnan(v):
                    vals.append("")
                else:
                    vals.append(f"{v:.6g}")
            else:
                vals.append(str(v))
        lines.append("| " + " | ".join(vals) + " |")
    return "\n".join(lines)


def describe_numeric(s: pd.Series) -> dict[str, Any]:
    x = pd.to_numeric(s, errors="coerce").dropna()
    if x.empty:
        return {}
    q = x.quantile([0.01, 0.05, 0.50, 0.95, 0.99])
    return {
        "count": int(x.shape[0]),
        "mean": float(x.mean()),
        "std": float(x.std(ddof=1)) if x.shape[0] > 1 else 0.0,
        "min": float(x.min()),
        "1%": float(q.loc[0.01]),
        "5%": float(q.loc[0.05]),
        "50%": float(q.loc[0.50]),
        "95%": float(q.loc[0.95]),
        "99%": float(q.loc[0.99]),
        "max": float(x.max()),
    }


def query_bond_returns(
    db: wrds.Connection,
    cusips: list[str],
    start_date: str,
    end_date: str,
    chunk_size: int,
) -> pd.DataFrame:
    frames: list[pd.DataFrame] = []
    total = len(cusips)

    for start in range(0, total, chunk_size):
        chunk = cusips[start : start + chunk_size]
        quoted = ",".join("'" + c.replace("'", "''") + "'" for c in chunk)

        sql = f"""
        SELECT
            date,
            cusip,
            ret_eom,
            ret_ldm,
            ret_l5m,
            price_eom,
            price_eom_flg,
            yield as bond_yield,
            duration,
            tmt,
            rating_num,
            rating_cat,
            t_volume,
            t_dvolume,
            t_spread,
            amount_outstanding
        FROM wrdsapps_bondret.bondret
        WHERE cusip IN ({quoted})
          AND date >= '{start_date}'
          AND date <= '{end_date}'
        """

        print(f"[WRDS] returns chunk {start:>7,}-{min(start+len(chunk), total):>7,} / {total:,}")
        try:
            got = db.raw_sql(sql, date_cols=["date"])
            if got is not None and len(got):
                frames.append(got)
                print(f"       rows={len(got):,}")
            else:
                print("       rows=0")
        except Exception as exc:
            print(f"[WRDS][WARN] chunk failed: {repr(exc)}")

    if not frames:
        return pd.DataFrame()

    out = pd.concat(frames, ignore_index=True)
    out["cusip"] = normalize_cusip(out["cusip"])
    out["return_month"] = pd.to_datetime(out["date"]) + pd.offsets.MonthEnd(0)

    numeric_cols = [
        "ret_eom",
        "ret_ldm",
        "ret_l5m",
        "price_eom",
        "bond_yield",
        "duration",
        "tmt",
        "rating_num",
        "t_volume",
        "t_dvolume",
        "t_spread",
        "amount_outstanding",
    ]
    for c in numeric_cols:
        if c in out.columns:
            out[c] = pd.to_numeric(out[c], errors="coerce")

    # One row per CUSIP-month. If WRDS already has one, this is a no-op.
    out = out.sort_values(["cusip", "return_month", "date"]).drop_duplicates(
        ["cusip", "return_month"], keep="last"
    )
    return out


def make_figures(root: Path, tag: str, panel: pd.DataFrame, monthly_cov: pd.DataFrame) -> None:
    if plt is None:
        return

    fig_dir = root / "reports" / "figures"
    fig_dir.mkdir(parents=True, exist_ok=True)

    if not monthly_cov.empty:
        fig, ax = plt.subplots(figsize=(9.5, 4.5))
        plot_df = monthly_cov.copy()
        plot_df["target_month"] = pd.to_datetime(plot_df["target_month"])
        ax.plot(plot_df["target_month"], plot_df["rows_with_target"], marker="o", linewidth=2)
        ax.set_title("6.0 Target Coverage by Target Month")
        ax.set_xlabel("Target month")
        ax.set_ylabel("Rows with next-month returns")
        ax.grid(alpha=0.25)
        fig.tight_layout()
        fig.savefig(fig_dir / f"6.0_target_coverage_{tag}.png", dpi=220, bbox_inches="tight")
        fig.savefig(fig_dir / f"6.0_target_coverage_{tag}.svg", bbox_inches="tight")
        plt.close(fig)

    usable = panel.dropna(subset=["residual_yield_bps", "issuer_demeaned_ret_1m"]).copy()
    if len(usable) >= 20:
        # Bin by residual into deciles or as many as feasible.
        q = min(10, max(3, usable["residual_yield_bps"].nunique()))
        try:
            usable["residual_bin"] = pd.qcut(
                usable["residual_yield_bps"],
                q=q,
                labels=False,
                duplicates="drop",
            )
            binned = (
                usable.groupby("residual_bin", observed=True)
                .agg(
                    residual_yield_bps=("residual_yield_bps", "mean"),
                    issuer_demeaned_ret_1m=("issuer_demeaned_ret_1m", "mean"),
                    n=("issuer_demeaned_ret_1m", "size"),
                )
                .reset_index()
            )

            fig, ax = plt.subplots(figsize=(8.0, 4.7))
            ax.plot(
                binned["residual_yield_bps"],
                binned["issuer_demeaned_ret_1m"],
                marker="o",
                linewidth=2,
            )
            ax.axhline(0.0, linewidth=1, color="0.4")
            ax.set_title("6.0 Pilot Monotonicity: Residual Yield vs Future Issuer-Demeaned Return")
            ax.set_xlabel("Mean residual yield, bps")
            ax.set_ylabel("Mean next-month issuer-demeaned return")
            ax.grid(alpha=0.25)
            fig.tight_layout()
            fig.savefig(fig_dir / f"6.0_signal_monotonicity_{tag}.png", dpi=220, bbox_inches="tight")
            fig.savefig(fig_dir / f"6.0_signal_monotonicity_{tag}.svg", bbox_inches="tight")
            plt.close(fig)
        except Exception as exc:
            print(f"[PLOT][WARN] monotonicity plot failed: {repr(exc)}")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--project-root", default=".")
    parser.add_argument("--tag", default="pilot2024")
    parser.add_argument("--residuals", default="artifacts/processed/5.0_curve_residuals_pilot2024.parquet")
    parser.add_argument("--chunk-size", type=int, default=500)
    parser.add_argument("--bundle", action="store_true")
    args = parser.parse_args()

    root = Path(args.project_root).resolve()
    paths = ensure_dirs(root)
    run_id = utc_stamp()
    log_path = paths["logs"] / f"6.0_build_targets_{args.tag}_{run_id}.log"

    with log_path.open("w", encoding="utf-8") as log_fh:
        sys.stdout = Tee(sys.__stdout__, log_fh)
        sys.stderr = Tee(sys.__stderr__, log_fh)

        print("=" * 72)
        print("6.0 build return targets")
        print("UTC:", run_id)
        print("Project:", root)
        print("Tag:", args.tag)
        print("Log:", log_path)
        print("=" * 72)

        try:
            residual_path = root / args.residuals
            if not residual_path.exists():
                raise FileNotFoundError(f"Missing residual file: {residual_path}")

            print("[LOAD]", residual_path)
            r = pd.read_parquet(residual_path)
            print(f"[DATA] residual rows: {len(r):,}")

            required = {"cusip", "issuer_id", "week_end", "residual_yield_bps"}
            missing = sorted(required - set(r.columns))
            if missing:
                raise ValueError(f"Residual file missing required columns: {missing}")

            r = r.copy()
            r["cusip"] = normalize_cusip(r["cusip"])
            r["week_end"] = pd.to_datetime(r["week_end"])
            r["issuer_id"] = pd.to_numeric(r["issuer_id"], errors="coerce")
            r["feature_month"] = r["week_end"] + pd.offsets.MonthEnd(0)
            r["target_month"] = r["feature_month"] + pd.offsets.MonthEnd(1)

            # For a monthly return target, use the last curve signal for each CUSIP in each month.
            monthly_features = (
                r.sort_values(["cusip", "feature_month", "week_end"])
                .groupby(["cusip", "feature_month"], as_index=False)
                .tail(1)
                .reset_index(drop=True)
            )
            print(f"[DATA] monthly feature rows: {len(monthly_features):,}")
            print(f"[DATA] monthly feature CUSIPs: {monthly_features['cusip'].nunique():,}")

            cusips = sorted(monthly_features["cusip"].dropna().unique().tolist())
            min_target = pd.to_datetime(monthly_features["target_month"].min())
            max_target = pd.to_datetime(monthly_features["target_month"].max())

            start_date = min_target.strftime("%Y-%m-%d")
            end_date = max_target.strftime("%Y-%m-%d")
            print(f"[WRDS] target return window: {start_date} to {end_date}")
            print(f"[WRDS] target CUSIPs: {len(cusips):,}")

            db = wrds.Connection()
            try:
                returns = query_bond_returns(
                    db=db,
                    cusips=cusips,
                    start_date=start_date,
                    end_date=end_date,
                    chunk_size=args.chunk_size,
                )
            finally:
                try:
                    db.close()
                except Exception:
                    pass

            returns_path = paths["processed"] / f"6.0_return_rows_{args.tag}.parquet"
            returns.to_parquet(returns_path, index=False)
            print(f"[WROTE] {returns_path}")
            print(f"[DATA] return rows: {len(returns):,}")
            print(f"[DATA] return CUSIPs: {returns['cusip'].nunique() if len(returns) else 0:,}")

            if returns.empty:
                panel = monthly_features.copy()
                for c in [
                    "ret_eom",
                    "price_eom",
                    "bond_yield",
                    "duration",
                    "tmt",
                    "rating_num",
                    "rating_cat",
                    "t_volume",
                    "t_dvolume",
                    "t_spread",
                    "amount_outstanding",
                    "issuer_demeaned_ret_1m",
                    "issuer_ret_mean_ex_self",
                ]:
                    panel[c] = np.nan
                panel["has_target"] = False
            else:
                keep_cols = [
                    "cusip",
                    "return_month",
                    "ret_eom",
                    "ret_ldm",
                    "ret_l5m",
                    "price_eom",
                    "price_eom_flg",
                    "bond_yield",
                    "duration",
                    "tmt",
                    "rating_num",
                    "rating_cat",
                    "t_volume",
                    "t_dvolume",
                    "t_spread",
                    "amount_outstanding",
                ]
                keep_cols = [c for c in keep_cols if c in returns.columns]

                panel = monthly_features.merge(
                    returns[keep_cols],
                    left_on=["cusip", "target_month"],
                    right_on=["cusip", "return_month"],
                    how="left",
                    validate="m:1",
                )

                panel["target_ret_1m"] = pd.to_numeric(panel["ret_eom"], errors="coerce")
                panel["has_target"] = panel["target_ret_1m"].notna()

                g = panel.groupby(["issuer_id", "target_month"], dropna=False)["target_ret_1m"]
                panel["issuer_target_n"] = g.transform("count")
                panel["issuer_target_sum"] = g.transform("sum")
                panel["issuer_target_mean_all"] = g.transform("mean")

                panel["issuer_ret_mean_ex_self"] = np.where(
                    panel["issuer_target_n"] >= 2,
                    (panel["issuer_target_sum"] - panel["target_ret_1m"]) / (panel["issuer_target_n"] - 1),
                    np.nan,
                )
                panel["issuer_demeaned_ret_1m"] = panel["target_ret_1m"] - panel["issuer_ret_mean_ex_self"]
                panel["issuer_demeaned_ret_1m_allmean"] = panel["target_ret_1m"] - panel["issuer_target_mean_all"]

            # Signal ranks within issuer-month, after monthly feature construction.
            panel["signal_rank_pct_issuer_month"] = (
                panel.groupby(["issuer_id", "feature_month"])["residual_yield_bps"]
                .rank(pct=True, method="average")
            )
            panel["signal_n_issuer_month"] = (
                panel.groupby(["issuer_id", "feature_month"])["residual_yield_bps"]
                .transform("count")
            )

            out_path = paths["processed"] / f"6.0_model_panel_{args.tag}.parquet"
            panel.to_parquet(out_path, index=False)
            print(f"[WROTE] {out_path}")
            print(f"[DATA] model panel rows: {len(panel):,}")
            print(f"[DATA] rows with target ret_eom: {int(panel['has_target'].sum()):,}")
            print(f"[DATA] rows with issuer-demeaned target: {panel['issuer_demeaned_ret_1m'].notna().sum():,}")

            monthly_cov = (
                panel.groupby("target_month", dropna=False)
                .agg(
                    rows=("cusip", "size"),
                    rows_with_target=("has_target", "sum"),
                    unique_cusips=("cusip", "nunique"),
                    unique_issuers=("issuer_id", "nunique"),
                    rows_with_issuer_demeaned_target=("issuer_demeaned_ret_1m", lambda x: x.notna().sum()),
                )
                .reset_index()
            )
            cov_path = paths["disc"] / f"6.0_monthly_target_coverage_{args.tag}.csv"
            monthly_cov.to_csv(cov_path, index=False)
            print(f"[WROTE] {cov_path}")

            usable = panel.dropna(subset=["residual_yield_bps", "issuer_demeaned_ret_1m"]).copy()
            corr_pearson = None
            corr_spearman = None
            if len(usable) >= 3:
                corr_pearson = float(usable[["residual_yield_bps", "issuer_demeaned_ret_1m"]].corr().iloc[0, 1])
                corr_spearman = float(
                    usable[["residual_yield_bps", "issuer_demeaned_ret_1m"]]
                    .rank()
                    .corr()
                    .iloc[0, 1]
                )

            summary = {
                "run_utc": iso_now(),
                "tag": args.tag,
                "residual_rows": int(len(r)),
                "monthly_feature_rows": int(len(monthly_features)),
                "monthly_feature_cusips": int(monthly_features["cusip"].nunique()),
                "target_window_start": start_date,
                "target_window_end": end_date,
                "wrds_return_rows": int(len(returns)),
                "wrds_return_cusips": int(returns["cusip"].nunique()) if len(returns) else 0,
                "model_panel_rows": int(len(panel)),
                "rows_with_target_ret_eom": int(panel["has_target"].sum()),
                "rows_with_issuer_demeaned_target": int(panel["issuer_demeaned_ret_1m"].notna().sum()),
                "target_ret_1m_distribution": describe_numeric(panel.get("target_ret_1m", pd.Series(dtype=float))),
                "issuer_demeaned_ret_1m_distribution": describe_numeric(panel["issuer_demeaned_ret_1m"]),
                "residual_to_target_pearson": corr_pearson,
                "residual_to_target_spearman": corr_spearman,
            }
            summary_path = paths["disc"] / f"6.0_target_summary_{args.tag}.json"
            summary_path.write_text(json.dumps(summary, indent=2, sort_keys=True), encoding="utf-8")
            print(f"[WROTE] {summary_path}")

            make_figures(root, args.tag, panel, monthly_cov)

            preview_cols = [
                "issuer_id",
                "feature_month",
                "target_month",
                "cusip",
                "residual_yield_bps",
                "signal_rank_pct_issuer_month",
                "target_ret_1m",
                "issuer_ret_mean_ex_self",
                "issuer_demeaned_ret_1m",
                "issuer_target_n",
            ]
            preview_cols = [c for c in preview_cols if c in panel.columns]
            preview = panel[preview_cols].head(20)

            report = [
                f"# 6.0 Return target construction report ({args.tag})",
                "",
                f"- Run UTC: `{summary['run_utc']}`",
                f"- Residual rows loaded: `{summary['residual_rows']:,}`",
                f"- Monthly feature rows: `{summary['monthly_feature_rows']:,}`",
                f"- Monthly feature CUSIPs: `{summary['monthly_feature_cusips']:,}`",
                f"- Target return window: `{start_date}` to `{end_date}`",
                f"- WRDS return rows pulled: `{summary['wrds_return_rows']:,}`",
                f"- WRDS return CUSIPs: `{summary['wrds_return_cusips']:,}`",
                f"- Model panel rows: `{summary['model_panel_rows']:,}`",
                f"- Rows with `ret_eom`: `{summary['rows_with_target_ret_eom']:,}`",
                f"- Rows with self-excluded issuer-demeaned target: `{summary['rows_with_issuer_demeaned_target']:,}`",
                "",
                "## Signal-to-target quick correlations",
                "",
                f"- Pearson residual vs target: `{corr_pearson}`",
                f"- Spearman residual vs target: `{corr_spearman}`",
                "",
                "These are pilot diagnostics only. They are not final evidence because the TRACE pilot used a small random CUSIP sample.",
                "",
                "## Target distribution: next-month issuer-demeaned return",
                "",
                "```json",
                json.dumps(summary["issuer_demeaned_ret_1m_distribution"], indent=2),
                "```",
                "",
                "## Monthly coverage",
                "",
                table_to_markdown(monthly_cov, max_rows=24),
                "",
                "## Preview",
                "",
                table_to_markdown(preview, max_rows=20),
                "",
                "## Outputs",
                "",
                f"- `{out_path.relative_to(root)}`",
                f"- `{returns_path.relative_to(root)}`",
                f"- `{summary_path.relative_to(root)}`",
                f"- `{cov_path.relative_to(root)}`",
                f"- `reports/figures/6.0_target_coverage_{args.tag}.png`",
                f"- `reports/figures/6.0_signal_monotonicity_{args.tag}.png`",
                "",
                "## Next step",
                "",
                "Run `7.0_residual_sort_baseline.py` for a simple issuer-relative long-cheap/short-rich pilot backtest.",
            ]

            report_path = paths["disc"] / f"6.0_target_report_{args.tag}.md"
            report_path.write_text("\n".join(report) + "\n", encoding="utf-8")
            print(f"[WROTE] {report_path}")

            if args.bundle:
                bundle = root / f"step6_targets_logs_reports_{args.tag}_{run_id}.tar.gz"
                with tarfile.open(bundle, "w:gz") as tar:
                    for rel in [
                        "logs",
                        "artifacts/discovery/6.0_target_report_" + args.tag + ".md",
                        "artifacts/discovery/6.0_target_summary_" + args.tag + ".json",
                        "artifacts/discovery/6.0_monthly_target_coverage_" + args.tag + ".csv",
                        "reports/figures",
                        "configs",
                        "scripts/6.0_build_targets.py",
                    ]:
                        p = root / rel
                        if p.exists():
                            tar.add(p, arcname=rel)
                print(f"[BUNDLE] {bundle}")

            print("[DONE] 6.0 target construction complete.")
            return 0

        except Exception as exc:
            err_path = paths["disc"] / f"6.0_target_error_{args.tag}_{run_id}.json"
            err_path.write_text(
                json.dumps(
                    {"error": repr(exc), "traceback": traceback.format_exc(), "run_utc": iso_now()},
                    indent=2,
                ),
                encoding="utf-8",
            )
            print("[FATAL]", repr(exc))
            print(traceback.format_exc())
            print(f"[WROTE] {err_path}")
            return 2


if __name__ == "__main__":
    raise SystemExit(main())
