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


def performance_stats(monthly: pd.DataFrame) -> dict:
    if monthly.empty:
        return {}
    x = pd.to_numeric(monthly["strategy_ret"], errors="coerce").dropna()
    if x.empty:
        return {}
    mean = float(x.mean())
    std = float(x.std(ddof=1)) if len(x) > 1 else 0.0
    t_stat = float(mean / (std / math.sqrt(len(x)))) if std > 0 and len(x) > 1 else None
    ann_sharpe = float(math.sqrt(12) * mean / std) if std > 0 else None
    cum = (1.0 + x.fillna(0.0)).cumprod()
    peak = cum.cummax()
    dd = cum / peak - 1.0
    return {
        "n_months": int(len(x)),
        "mean_monthly": mean,
        "std_monthly": std,
        "t_stat_mean": t_stat,
        "ann_sharpe": ann_sharpe,
        "cumulative_return": float(cum.iloc[-1] - 1.0) if len(cum) else None,
        "max_drawdown": float(dd.min()) if len(dd) else None,
        "min_month": float(x.min()),
        "max_month": float(x.max()),
    }


def make_figures(root: Path, tag: str, monthly: pd.DataFrame, trades: pd.DataFrame) -> None:
    if plt is None:
        return
    fig_dir = root / "reports" / "figures"
    fig_dir.mkdir(parents=True, exist_ok=True)

    if not monthly.empty:
        m = monthly.copy()
        m["target_month"] = pd.to_datetime(m["target_month"])
        m["cumulative_return"] = (1.0 + m["strategy_ret"].fillna(0.0)).cumprod() - 1.0

        fig, ax = plt.subplots(figsize=(9.2, 4.7))
        ax.plot(m["target_month"], m["cumulative_return"], marker="o", linewidth=2)
        ax.axhline(0.0, linewidth=1, color="0.4")
        ax.set_title("7.0 Pilot Residual Sort: Cumulative Return")
        ax.set_xlabel("Target month")
        ax.set_ylabel("Cumulative return")
        ax.grid(alpha=0.25)
        fig.tight_layout()
        fig.savefig(fig_dir / f"7.0_residual_sort_cumulative_{tag}.png", dpi=220, bbox_inches="tight")
        fig.savefig(fig_dir / f"7.0_residual_sort_cumulative_{tag}.svg", bbox_inches="tight")
        plt.close(fig)

        fig, ax = plt.subplots(figsize=(9.2, 4.7))
        ax.bar(m["target_month"], m["strategy_ret"], width=20)
        ax.axhline(0.0, linewidth=1, color="0.4")
        ax.set_title("7.0 Pilot Residual Sort: Monthly Long-Short Return")
        ax.set_xlabel("Target month")
        ax.set_ylabel("Return")
        ax.grid(axis="y", alpha=0.25)
        fig.tight_layout()
        fig.savefig(fig_dir / f"7.0_residual_sort_monthly_{tag}.png", dpi=220, bbox_inches="tight")
        fig.savefig(fig_dir / f"7.0_residual_sort_monthly_{tag}.svg", bbox_inches="tight")
        plt.close(fig)

    if not trades.empty and trades["issuer_n"].nunique() > 1:
        fig, ax = plt.subplots(figsize=(7.5, 4.6))
        ax.scatter(trades["issuer_n"], trades["issuer_spread"], alpha=0.6)
        ax.axhline(0.0, linewidth=1, color="0.4")
        ax.set_title("7.0 Issuer-Month Spreads by Available Bond Count")
        ax.set_xlabel("Bonds in issuer-month")
        ax.set_ylabel("Issuer long-short spread")
        ax.grid(alpha=0.25)
        fig.tight_layout()
        fig.savefig(fig_dir / f"7.0_issuer_spreads_{tag}.png", dpi=220, bbox_inches="tight")
        fig.savefig(fig_dir / f"7.0_issuer_spreads_{tag}.svg", bbox_inches="tight")
        plt.close(fig)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--project-root", default=".")
    parser.add_argument("--tag", default="pilot2024")
    parser.add_argument("--panel", default="artifacts/processed/6.0_model_panel_pilot2024.parquet")
    parser.add_argument("--min-bonds-per-issuer-month", type=int, default=3)
    parser.add_argument("--quantile", type=float, default=0.20)
    parser.add_argument("--bundle", action="store_true")
    args = parser.parse_args()

    root = Path(args.project_root).resolve()
    paths = ensure_dirs(root)
    run_id = utc_stamp()
    log_path = paths["logs"] / f"7.0_residual_sort_baseline_{args.tag}_{run_id}.log"

    with log_path.open("w", encoding="utf-8") as log_fh:
        sys.stdout = Tee(sys.__stdout__, log_fh)
        sys.stderr = Tee(sys.__stderr__, log_fh)

        print("=" * 72)
        print("7.0 residual sort pilot baseline")
        print("UTC:", run_id)
        print("Project:", root)
        print("Tag:", args.tag)
        print("Log:", log_path)
        print("=" * 72)

        try:
            panel_path = root / args.panel
            if not panel_path.exists():
                raise FileNotFoundError(f"Missing model panel: {panel_path}")

            p = pd.read_parquet(panel_path)
            print(f"[LOAD] {panel_path}")
            print(f"[DATA] model panel rows: {len(p):,}")

            required = {
                "issuer_id",
                "feature_month",
                "target_month",
                "cusip",
                "residual_yield_bps",
                "issuer_demeaned_ret_1m",
            }
            missing = sorted(required - set(p.columns))
            if missing:
                raise ValueError(f"Panel missing required columns: {missing}")

            p = p.copy()
            p["feature_month"] = pd.to_datetime(p["feature_month"])
            p["target_month"] = pd.to_datetime(p["target_month"])
            p["residual_yield_bps"] = pd.to_numeric(p["residual_yield_bps"], errors="coerce")
            p["issuer_demeaned_ret_1m"] = pd.to_numeric(p["issuer_demeaned_ret_1m"], errors="coerce")

            usable = p.dropna(
                subset=["issuer_id", "feature_month", "target_month", "residual_yield_bps", "issuer_demeaned_ret_1m"]
            ).copy()
            print(f"[DATA] usable target rows: {len(usable):,}")

            issuer_month_rows = []
            position_rows = []

            for (issuer_id, feature_month, target_month), g in usable.groupby(
                ["issuer_id", "feature_month", "target_month"], dropna=False
            ):
                g = g.sort_values("residual_yield_bps").copy()
                n = len(g)
                if n < args.min_bonds_per_issuer_month:
                    continue

                k = max(1, int(math.floor(n * args.quantile)))
                rich = g.head(k).copy()   # low residual yield = rich; short it
                cheap = g.tail(k).copy()  # high residual yield = cheap; long it

                long_ret = float(cheap["issuer_demeaned_ret_1m"].mean())
                short_ret = float(rich["issuer_demeaned_ret_1m"].mean())
                spread = long_ret - short_ret

                issuer_month_rows.append(
                    {
                        "issuer_id": issuer_id,
                        "feature_month": feature_month,
                        "target_month": target_month,
                        "issuer_n": n,
                        "k_each_side": k,
                        "long_ret": long_ret,
                        "short_ret": short_ret,
                        "issuer_spread": spread,
                        "long_mean_residual_bps": float(cheap["residual_yield_bps"].mean()),
                        "short_mean_residual_bps": float(rich["residual_yield_bps"].mean()),
                    }
                )

                cheap_pos = cheap[["issuer_id", "feature_month", "target_month", "cusip", "residual_yield_bps", "issuer_demeaned_ret_1m"]].copy()
                cheap_pos["side"] = "LONG_CHEAP"
                cheap_pos["weight"] = 1.0 / k
                rich_pos = rich[["issuer_id", "feature_month", "target_month", "cusip", "residual_yield_bps", "issuer_demeaned_ret_1m"]].copy()
                rich_pos["side"] = "SHORT_RICH"
                rich_pos["weight"] = -1.0 / k
                position_rows.append(cheap_pos)
                position_rows.append(rich_pos)

            trades = pd.DataFrame(issuer_month_rows)
            positions = pd.concat(position_rows, ignore_index=True) if position_rows else pd.DataFrame()

            if trades.empty:
                monthly = pd.DataFrame(
                    columns=["target_month", "strategy_ret", "n_issuer_months", "avg_bonds_per_issuer"]
                )
            else:
                monthly = (
                    trades.groupby("target_month")
                    .agg(
                        strategy_ret=("issuer_spread", "mean"),
                        n_issuer_months=("issuer_spread", "size"),
                        avg_bonds_per_issuer=("issuer_n", "mean"),
                        avg_k_each_side=("k_each_side", "mean"),
                        long_ret=("long_ret", "mean"),
                        short_ret=("short_ret", "mean"),
                    )
                    .reset_index()
                    .sort_values("target_month")
                )

            trades_path = paths["processed"] / f"7.0_residual_sort_issuer_months_{args.tag}.parquet"
            positions_path = paths["processed"] / f"7.0_residual_sort_positions_{args.tag}.parquet"
            monthly_path = paths["processed"] / f"7.0_residual_sort_monthly_{args.tag}.csv"

            trades.to_parquet(trades_path, index=False)
            positions.to_parquet(positions_path, index=False)
            monthly.to_csv(monthly_path, index=False)

            stats = performance_stats(monthly)
            summary = {
                "run_utc": iso_now(),
                "tag": args.tag,
                "input_rows": int(len(p)),
                "usable_target_rows": int(len(usable)),
                "min_bonds_per_issuer_month": int(args.min_bonds_per_issuer_month),
                "quantile": float(args.quantile),
                "issuer_month_trades": int(len(trades)),
                "position_rows": int(len(positions)),
                "monthly_rows": int(len(monthly)),
                "performance": stats,
            }
            summary_path = paths["disc"] / f"7.0_residual_sort_summary_{args.tag}.json"
            summary_path.write_text(json.dumps(summary, indent=2, sort_keys=True), encoding="utf-8")

            make_figures(root, args.tag, monthly, trades)

            report = [
                f"# 7.0 Residual-sort pilot baseline report ({args.tag})",
                "",
                f"- Run UTC: `{summary['run_utc']}`",
                f"- Input model panel rows: `{summary['input_rows']:,}`",
                f"- Usable target rows: `{summary['usable_target_rows']:,}`",
                f"- Minimum bonds per issuer-month: `{summary['min_bonds_per_issuer_month']}`",
                f"- Side quantile: `{summary['quantile']}`",
                f"- Issuer-month long/short groups: `{summary['issuer_month_trades']:,}`",
                f"- Position rows: `{summary['position_rows']:,}`",
                f"- Monthly return rows: `{summary['monthly_rows']:,}`",
                "",
                "## Pilot performance",
                "",
                "```json",
                json.dumps(stats, indent=2),
                "```",
                "",
                "This is a pilot diagnostic, not a final result. The TRACE input was a small random CUSIP sample, so breadth is intentionally limited.",
                "",
                "## Monthly returns",
                "",
                table_to_markdown(monthly, max_rows=24),
                "",
                "## Largest issuer-month spreads",
                "",
                table_to_markdown(trades.sort_values("issuer_spread", ascending=False).head(15), max_rows=15) if not trades.empty else "_empty_",
                "",
                "## Smallest issuer-month spreads",
                "",
                table_to_markdown(trades.sort_values("issuer_spread", ascending=True).head(15), max_rows=15) if not trades.empty else "_empty_",
                "",
                "## Outputs",
                "",
                f"- `{trades_path.relative_to(root)}`",
                f"- `{positions_path.relative_to(root)}`",
                f"- `{monthly_path.relative_to(root)}`",
                f"- `{summary_path.relative_to(root)}`",
                f"- `reports/figures/7.0_residual_sort_cumulative_{args.tag}.png`",
                f"- `reports/figures/7.0_residual_sort_monthly_{args.tag}.png`",
                "",
                "## Next decision",
                "",
                "If the pilot has enough target rows, move to a larger TRACE extraction. If it is too sparse, increase the 4.1 sample size before interpreting performance.",
            ]

            report_path = paths["disc"] / f"7.0_residual_sort_report_{args.tag}.md"
            report_path.write_text("\n".join(report) + "\n", encoding="utf-8")

            print(f"[WROTE] {trades_path}")
            print(f"[WROTE] {positions_path}")
            print(f"[WROTE] {monthly_path}")
            print(f"[WROTE] {summary_path}")
            print(f"[WROTE] {report_path}")

            if args.bundle:
                bundle = root / f"step7_residual_sort_logs_reports_{args.tag}_{run_id}.tar.gz"
                with tarfile.open(bundle, "w:gz") as tar:
                    for rel in [
                        "logs",
                        "artifacts/discovery/7.0_residual_sort_report_" + args.tag + ".md",
                        "artifacts/discovery/7.0_residual_sort_summary_" + args.tag + ".json",
                        "artifacts/processed/7.0_residual_sort_monthly_" + args.tag + ".csv",
                        "reports/figures",
                        "configs",
                        "scripts/7.0_residual_sort_baseline.py",
                    ]:
                        pth = root / rel
                        if pth.exists():
                            tar.add(pth, arcname=rel)
                print(f"[BUNDLE] {bundle}")

            print("[DONE] 7.0 residual-sort baseline complete.")
            return 0

        except Exception as exc:
            err_path = paths["disc"] / f"7.0_residual_sort_error_{args.tag}_{run_id}.json"
            err_path.write_text(
                json.dumps({"error": repr(exc), "traceback": traceback.format_exc(), "run_utc": iso_now()}, indent=2),
                encoding="utf-8",
            )
            print("[FATAL]", repr(exc))
            print(traceback.format_exc())
            print(f"[WROTE] {err_path}")
            return 2


if __name__ == "__main__":
    raise SystemExit(main())
