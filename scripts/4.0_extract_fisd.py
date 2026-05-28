#!/usr/bin/env python
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
import wrds

try:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
except Exception:
    plt = None


ROOT = Path.cwd()
RUN_ID = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")

RAW = ROOT / "artifacts" / "raw"
INTERIM = ROOT / "artifacts" / "interim"
DISC = ROOT / "artifacts" / "discovery"
FIG = ROOT / "reports" / "figures"
LOGS = ROOT / "logs"

for p in [RAW, INTERIM, DISC, FIG, LOGS]:
    p.mkdir(parents=True, exist_ok=True)


TRUE_LIKE = {"1", "1.0", "y", "yes", "true", "t"}
FALSE_LIKE = {"0", "0.0", "n", "no", "false", "f", "", "none", "nan", "null"}


def norm_series(s: pd.Series) -> pd.Series:
    return s.astype("string").str.strip().str.lower()


def true_flag(s: pd.Series) -> pd.Series:
    """Return True where a FISD flag appears affirmatively true/Y/1."""
    z = norm_series(s)
    numeric = pd.to_numeric(s, errors="coerce")
    return (
        numeric.eq(1)
        | z.isin(TRUE_LIKE)
        | z.str.startswith("y", na=False)
    ).fillna(False)


def not_true_flag(s: pd.Series) -> pd.Series:
    """Keep rows that are not explicitly true. Missing values are kept."""
    return (~true_flag(s)).fillna(True)


def fixed_coupon_mask(s: pd.Series) -> pd.Series:
    """Best-effort fixed-rate screen. If WRDS uses unknown codes, caller may skip it."""
    z = norm_series(s)
    fixed = (
        z.isin(
            {
                "f",
                "fix",
                "fixed",
                "fixed rate",
                "fixed-rate",
                "fixed coupon",
                "straight",
                "plain vanilla",
            }
        )
        | z.str.contains("fixed", na=False)
    )
    floating_or_complex = z.str.contains(
        "float|variable|index|step|auction|inverse|linked|pik|pay", regex=True, na=False
    )
    return (fixed & ~floating_or_complex).fillna(False)


def has_text(s: pd.Series) -> pd.Series:
    z = s.astype("string").str.strip()
    return z.notna() & z.ne("") & z.str.lower().ne("nan")


def numeric_positive(s: pd.Series) -> pd.Series:
    return pd.to_numeric(s, errors="coerce").gt(0).fillna(False)


def apply_screen(
    df: pd.DataFrame,
    label: str,
    mask: pd.Series,
    waterfall: list[dict],
    *,
    min_keep: int = 1,
    allow_skip: bool = False,
) -> pd.DataFrame:
    before = len(df)
    mask = mask.reindex(df.index).fillna(False).astype(bool)
    keep = int(mask.sum())

    if allow_skip and keep < min_keep:
        waterfall.append(
            {
                "screen": label,
                "status": f"SKIPPED: only {keep:,} rows would remain",
                "rows_before": before,
                "rows_after": before,
                "rows_removed": 0,
                "pct_removed": 0.0,
            }
        )
        print(f"[FILTER][SKIP] {label}: only {keep:,} rows would remain; keeping {before:,}")
        return df

    out = df.loc[mask].copy()
    after = len(out)
    waterfall.append(
        {
            "screen": label,
            "status": "APPLIED",
            "rows_before": before,
            "rows_after": after,
            "rows_removed": before - after,
            "pct_removed": round(100.0 * (before - after) / before, 4) if before else 0.0,
        }
    )
    print(f"[FILTER] {label}: {before:,} -> {after:,}")
    return out


def value_profile(df: pd.DataFrame, columns: list[str], top_n: int = 25) -> pd.DataFrame:
    rows = []
    for col in columns:
        if col not in df.columns:
            rows.append({"column": col, "value": "__MISSING_COLUMN__", "count": None, "share": None})
            continue

        vc = df[col].astype("string").fillna("__NA__").value_counts(dropna=False).head(top_n)
        denom = max(len(df), 1)

        for value, count in vc.items():
            rows.append(
                {
                    "column": col,
                    "value": str(value),
                    "count": int(count),
                    "share": round(float(count) / denom, 6),
                }
            )
    return pd.DataFrame(rows)


def md_table(df: pd.DataFrame, max_rows: int = 40) -> str:
    if df.empty:
        return "_No rows._"

    d = df.head(max_rows).copy()
    cols = list(d.columns)
    lines = [
        "| " + " | ".join(cols) + " |",
        "| " + " | ".join(["---"] * len(cols)) + " |",
    ]

    for _, row in d.iterrows():
        vals = []
        for c in cols:
            v = row[c]
            vals.append(str(v).replace("|", "\\|"))
        lines.append("| " + " | ".join(vals) + " |")

    return "\n".join(lines)


def make_figures(waterfall: pd.DataFrame, eligible: pd.DataFrame) -> None:
    if plt is None:
        return

    try:
        fig, ax = plt.subplots(figsize=(10, 5))
        labels = waterfall["screen"].astype(str).tolist()
        vals = waterfall["rows_after"].astype(float).tolist()
        ax.barh(range(len(labels)), vals)
        ax.set_yticks(range(len(labels)))
        ax.set_yticklabels(labels, fontsize=8)
        ax.invert_yaxis()
        ax.set_xlabel("Rows remaining")
        ax.set_title("4.0 FISD universe filter waterfall")
        ax.grid(axis="x", alpha=0.25)
        fig.tight_layout()
        fig.savefig(FIG / "4.0_fisd_waterfall.png", dpi=220, bbox_inches="tight")
        fig.savefig(FIG / "4.0_fisd_waterfall.svg", bbox_inches="tight")
        plt.close(fig)
    except Exception as e:
        print("[FIG][WARN] waterfall figure failed:", repr(e))

    try:
        if "maturity" in eligible.columns and len(eligible):
            mat = pd.to_datetime(eligible["maturity"], errors="coerce")
            yrs = mat.dt.year.dropna()
            if len(yrs):
                fig, ax = plt.subplots(figsize=(10, 5))
                ax.hist(yrs, bins=50)
                ax.set_title("4.0 Eligible FISD bonds: maturity year distribution")
                ax.set_xlabel("Maturity year")
                ax.set_ylabel("Number of bonds")
                ax.grid(axis="y", alpha=0.25)
                fig.tight_layout()
                fig.savefig(FIG / "4.0_fisd_maturity_distribution.png", dpi=220, bbox_inches="tight")
                fig.savefig(FIG / "4.0_fisd_maturity_distribution.svg", bbox_inches="tight")
                plt.close(fig)
    except Exception as e:
        print("[FIG][WARN] maturity figure failed:", repr(e))


def main() -> int:
    print("=" * 72)
    print("4.0 FISD extraction - clean replacement")
    print("UTC:", RUN_ID)
    print("Project:", ROOT)
    print("=" * 72)

    print("[WRDS] connecting")
    db = wrds.Connection()

    try:
        print("[WRDS] pulling fisd_fisd.fisd_issue")
        df = db.get_table(library="fisd_fisd", table="fisd_issue")
    finally:
        try:
            db.close()
        except Exception:
            pass

    print(f"[DATA] raw rows: {len(df):,}; columns: {len(df.columns):,}")

    raw_path = RAW / "4.0_fisd_issue_master.parquet"
    df.to_parquet(raw_path, index=False)
    print("[WROTE]", raw_path)

    profile_cols = [
        "foreign_currency",
        "coupon_type",
        "convertible",
        "putable",
        "asset_backed",
        "redeemable",
        "announced_call",
        "defaulted",
        "perpetual",
        "private_placement",
        "bond_type",
        "security_level",
        "complete_cusip",
        "maturity",
        "principal_amt",
        "offering_amt",
    ]
    profiles = value_profile(df, profile_cols)
    profiles_path = DISC / "4.0_fisd_value_profiles.csv"
    profiles.to_csv(profiles_path, index=False)
    print("[WROTE]", profiles_path)

    waterfall: list[dict] = [{"screen": "raw_fisd_issue", "status": "START", "rows_before": len(df), "rows_after": len(df), "rows_removed": 0, "pct_removed": 0.0}]

    eligible = df.copy()

    # Required identifiers and economics.
    eligible = apply_screen(
        eligible,
        "complete_cusip present",
        has_text(eligible["complete_cusip"]) if "complete_cusip" in eligible.columns else pd.Series(False, index=eligible.index),
        waterfall,
    )

    eligible = apply_screen(
        eligible,
        "maturity present",
        eligible["maturity"].notna() if "maturity" in eligible.columns else pd.Series(False, index=eligible.index),
        waterfall,
    )

    if "maturity" in eligible.columns:
        maturity = pd.to_datetime(eligible["maturity"], errors="coerce")
        eligible = apply_screen(
            eligible,
            "maturity >= 2004-01-01",
            maturity.ge(pd.Timestamp("2004-01-01")),
            waterfall,
        )

    size_masks = []
    for c in ["principal_amt", "offering_amt"]:
        if c in eligible.columns:
            size_masks.append(numeric_positive(eligible[c]))
    if size_masks:
        size_mask = size_masks[0]
        for m in size_masks[1:]:
            size_mask = size_mask | m
        eligible = apply_screen(eligible, "principal_amt or offering_amt > 0", size_mask, waterfall, allow_skip=True, min_keep=1000)

    # Robust FISD design filters.
    if "foreign_currency" in eligible.columns:
        eligible = apply_screen(
            eligible,
            "not explicitly foreign_currency",
            not_true_flag(eligible["foreign_currency"]),
            waterfall,
            allow_skip=True,
            min_keep=1000,
        )

    if "coupon_type" in eligible.columns:
        eligible = apply_screen(
            eligible,
            "fixed coupon_type if recognizable",
            fixed_coupon_mask(eligible["coupon_type"]),
            waterfall,
            allow_skip=True,
            min_keep=1000,
        )

    for col, label in [
        ("convertible", "not explicitly convertible"),
        ("putable", "not explicitly putable"),
        ("asset_backed", "not explicitly asset_backed"),
        ("defaulted", "not explicitly defaulted"),
        ("perpetual", "not explicitly perpetual"),
    ]:
        if col in eligible.columns:
            eligible = apply_screen(
                eligible,
                label,
                not_true_flag(eligible[col]),
                waterfall,
                allow_skip=True,
                min_keep=1000,
            )

    # Keep callable/redeemable bonds for now. We need TRACE coverage first; callable exclusion will be a robustness test.
    eligible["cusip"] = eligible["complete_cusip"].astype("string").str.strip()

    if "maturity" in eligible.columns and "offering_date" in eligible.columns:
        eligible["maturity"] = pd.to_datetime(eligible["maturity"], errors="coerce")
        eligible["offering_date"] = pd.to_datetime(eligible["offering_date"], errors="coerce")

    if "principal_amt" in eligible.columns:
        eligible["principal_amt"] = pd.to_numeric(eligible["principal_amt"], errors="coerce")
    if "offering_amt" in eligible.columns:
        eligible["offering_amt"] = pd.to_numeric(eligible["offering_amt"], errors="coerce")

    waterfall_df = pd.DataFrame(waterfall)
    waterfall_path = DISC / "4.0_fisd_filter_waterfall.csv"
    waterfall_df.to_csv(waterfall_path, index=False)
    print("[WROTE]", waterfall_path)

    eligible_path = INTERIM / "4.0_fisd_eligible_bonds.parquet"
    eligible.to_parquet(eligible_path, index=False)
    print("[WROTE]", eligible_path)

    missingness = (
        eligible.isna()
        .mean()
        .sort_values(ascending=False)
        .rename("missing_share")
        .reset_index()
        .rename(columns={"index": "column"})
    )
    missing_path = DISC / "4.0_fisd_missingness.csv"
    missingness.to_csv(missing_path, index=False)
    print("[WROTE]", missing_path)

    n_issuers = int(eligible["issuer_id"].nunique()) if "issuer_id" in eligible.columns else None
    n_cusips = int(eligible["cusip"].nunique()) if "cusip" in eligible.columns else None

    summary = {
        "run_utc": datetime.now(timezone.utc).isoformat(),
        "raw_rows": int(len(df)),
        "eligible_rows": int(len(eligible)),
        "eligible_issuers": n_issuers,
        "eligible_cusips": n_cusips,
        "raw_path": str(raw_path),
        "eligible_path": str(eligible_path),
        "waterfall_path": str(waterfall_path),
        "profiles_path": str(profiles_path),
        "note": "Callable/redeemable bonds retained for v1; optionality exclusion should be robustness after TRACE coverage is known.",
    }
    summary_path = DISC / "4.0_fisd_summary.json"
    summary_path.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print("[WROTE]", summary_path)

    make_figures(waterfall_df, eligible)

    report = [
        "# 4.0 FISD extraction report",
        "",
        f"- Run UTC: `{summary['run_utc']}`",
        f"- Raw rows: `{summary['raw_rows']:,}`",
        f"- Eligible rows: `{summary['eligible_rows']:,}`",
        f"- Eligible issuers: `{summary['eligible_issuers']}`",
        f"- Eligible CUSIPs: `{summary['eligible_cusips']}`",
        "",
        "## Filter waterfall",
        "",
        md_table(waterfall_df, max_rows=50),
        "",
        "## Flag/value profiles used for debugging",
        "",
        "Full file: `artifacts/discovery/4.0_fisd_value_profiles.csv`",
        "",
        md_table(profiles[profiles["column"].isin(["foreign_currency", "coupon_type", "convertible", "putable", "asset_backed"])], max_rows=50),
        "",
        "## Outputs",
        "",
        "- `artifacts/raw/4.0_fisd_issue_master.parquet`",
        "- `artifacts/interim/4.0_fisd_eligible_bonds.parquet`",
        "- `artifacts/discovery/4.0_fisd_filter_waterfall.csv`",
        "- `artifacts/discovery/4.0_fisd_value_profiles.csv`",
        "- `artifacts/discovery/4.0_fisd_missingness.csv`",
        "- `reports/figures/4.0_fisd_waterfall.png`",
        "- `reports/figures/4.0_fisd_maturity_distribution.png`",
        "",
    ]
    report_path = DISC / "4.0_fisd_extraction_report.md"
    report_path.write_text("\n".join(report), encoding="utf-8")
    print("[WROTE]", report_path)

    print(f"[DATA] eligible rows: {len(eligible):,}; issuers: {n_issuers}; CUSIPs: {n_cusips}")
    print("[DONE] 4.0 complete. Send the report and waterfall before running 4.1.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
