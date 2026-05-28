#!/usr/bin/env python
from __future__ import annotations

import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
import wrds


PROJECT_ROOT = Path.cwd()
RUN_ID = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
DISC = PROJECT_ROOT / "artifacts" / "discovery"
DESC = DISC / "descriptions"
LOGS = PROJECT_ROOT / "logs"
CONFIGS = PROJECT_ROOT / "configs"
for p in [DISC, DESC, LOGS, CONFIGS]:
    p.mkdir(parents=True, exist_ok=True)

TARGET_TABLES = {
    "trace_enhanced_trades": ("trace_enhanced", "trace_enhanced"),
    "trace_standard_trades": ("trace_standard", "trace"),
    "fisd_issue": ("fisd_fisd", "fisd_issue"),
    "fisd_issuer": ("fisd_fisd", "fisd_issuer"),
    "fisd_common_issue_issuer": ("fisd_common", "issue_issuer"),
    "wrds_bondret": ("wrdsapps_bondret", "bondret"),
    "wrds_bondret_std": ("wrdsapps_bondret", "bondret_std"),
    "wrds_trace_enhanced_clean": ("wrdsapps_bondret", "trace_enhanced_clean"),
    "contrib_bond_returns": ("contrib_corporate_bond_returns", "bonds"),
    "contrib_bond_firms": ("contrib_corporate_bond_returns", "firms"),
    "bond_firm_link": ("contrib_bond_firm_link", "fang_link"),
}

ALIASES = {
    "trace": {
        "cusip": ["cusip_id", "cusip", "complete_cusip", "cusip9"],
        "trade_date": ["trd_exctn_dt", "trd_rpt_dt", "trade_dt", "date", "trd_dt"],
        "trade_time": ["trd_exctn_tm", "trd_rpt_tm", "trade_tm", "time"],
        "trade_price": ["rptd_pr", "price", "trd_price", "trade_price", "px"],
        "trade_yield": ["yld_pt", "yield", "yld", "trd_yld", "trade_yield"],
        "trade_size": ["entrd_vol_qt", "volume", "vol", "size", "quantity", "trade_size"],
        "side_code": ["rpt_side_cd", "side_cd", "side", "buy_sell_cd"],
        "counterparty_type": ["contra_party_type", "cntra_mp_id", "contra_mp_id", "counterparty_type"],
        "trade_status": ["trc_st", "status", "trade_status"],
        "sale_condition": ["sale_cndtn_cd", "sale_condition", "sale_cond_cd"],
        "correction_flag": ["trd_mod_4", "correction_flag", "cancel_correct_cd", "asof_cd"],
    },
    "fisd": {
        "cusip": ["complete_cusip", "cusip", "cusip_id"],
        "issuer_id": ["issuer_id", "issuerid", "issuer_cusip", "issuer_cusip_id"],
        "issuer_name": ["issuer_name", "company_name", "name"],
        "offering_date": ["offering_date", "offering_dt", "dated_date", "issue_date"],
        "maturity_date": ["maturity", "maturity_date", "maturity_dt"],
        "coupon": ["coupon", "coupon_rate", "coupon_rate_pct"],
        "coupon_type": ["coupon_type", "coupon_type_cd", "cpn_typ"],
        "issue_size": ["principal_amt", "amount", "offering_amt", "issue_size", "amt_outstanding"],
        "currency": ["foreign_currency", "currency", "currency_cd", "curr"],
        "callable_flag": ["callable", "callable_flag", "call_flg"],
        "putable_flag": ["putable", "putable_flag", "put_flg"],
        "convertible_flag": ["convertible", "convertible_flag", "conv_flg"],
        "asset_backed_flag": ["asset_backed", "asset_backed_flag", "abs_flg"],
        "rule144a_flag": ["rule_144a", "rule144a", "private_placement", "144a"],
        "security_level": ["security_level", "security_type", "seniority", "debt_type"],
        "rating": ["rating", "moodys_rating", "snp_rating", "fitch_rating"],
    },
    "returns": {
        "cusip": ["cusip", "cusip_id", "complete_cusip"],
        "date": ["date", "caldt", "trd_dt", "month", "mdate"],
        "bond_return": ["ret", "return", "bond_ret", "bondret", "totret", "total_return"],
        "excess_return": ["exret", "excess_ret", "excess_return", "bond_exret"],
        "price": ["price", "prc", "clean_price", "dirty_price"],
        "yield": ["yield", "yld", "ytm"],
    },
    "link": {
        "cusip": ["cusip", "complete_cusip", "cusip_id"],
        "issuer_id": ["issuer_id", "issuerid", "issuer_cusip"],
        "gvkey": ["gvkey"],
        "permno": ["permno"],
        "permco": ["permco"],
        "start_date": ["linkdt", "start_date", "begdt", "from_date"],
        "end_date": ["linkenddt", "end_date", "enddt", "thru_date"],
    },
}


def norm(x: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", str(x).lower())


def safe_name(x: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]+", "_", x)


def column_names(desc: pd.DataFrame) -> list[str]:
    if desc is None or desc.empty:
        return []
    lower = {str(c).lower(): c for c in desc.columns}
    for k in ["name", "column_name", "variable", "varname", "field", "column"]:
        if k in lower:
            vals = desc[lower[k]].dropna().astype(str).str.strip()
            vals = [v for v in vals if v]
            if vals:
                return vals
    vals = desc.iloc[:, 0].dropna().astype(str).str.strip()
    return [v for v in vals if v]


def choose(cols: list[str], aliases: list[str]) -> str | None:
    by_norm = {norm(c): c for c in cols}
    for a in aliases:
        if norm(a) in by_norm:
            return by_norm[norm(a)]
    for a in aliases:
        na = norm(a)
        for c in cols:
            nc = norm(c)
            if na and (na in nc or nc in na):
                return c
    return None


def yaml_value(x):
    if x is None:
        return "null"
    return '"' + str(x).replace('"', '\\"') + '"'


def mapping_block(title: str, mapping: dict[str, str | None]) -> list[str]:
    out = [f"  {title}:"]
    for k, v in mapping.items():
        out.append(f"    {k}: {yaml_value(v)}")
    return out


def main() -> int:
    print("=" * 72)
    print("3.0 schema mapping")
    print("UTC:", RUN_ID)
    print("Project:", PROJECT_ROOT)
    print("=" * 72)

    schemas: dict[str, dict] = {}
    db = wrds.Connection()

    try:
        for key, (lib, tab) in TARGET_TABLES.items():
            full = f"{lib}.{tab}"
            print(f"[DESCRIBE] {full}")
            try:
                desc = db.describe_table(library=lib, table=tab)
                if not isinstance(desc, pd.DataFrame):
                    desc = pd.DataFrame(desc)
                desc = desc.astype(object).where(pd.notnull(desc), None)
                cols = column_names(desc)
                out_csv = DESC / f"3.0_{safe_name(lib)}__{safe_name(tab)}.csv"
                desc.to_csv(out_csv, index=False)
                schemas[key] = {
                    "library": lib,
                    "table": tab,
                    "columns": cols,
                    "description_csv": str(out_csv.relative_to(PROJECT_ROOT)),
                    "error": None,
                }
                print(f"  columns={len(cols)} saved={out_csv}")
            except Exception as e:
                schemas[key] = {"library": lib, "table": tab, "columns": [], "error": repr(e)}
                print(f"  ERROR {repr(e)}")
    finally:
        db.close()

    trace_cols = schemas["trace_enhanced_trades"]["columns"]
    fisd_cols = schemas["fisd_issue"]["columns"]
    ret_cols = schemas["wrds_bondret"]["columns"]
    link_cols = schemas["bond_firm_link"]["columns"]

    trace_map = {k: choose(trace_cols, v) for k, v in ALIASES["trace"].items()}
    fisd_map = {k: choose(fisd_cols, v) for k, v in ALIASES["fisd"].items()}
    ret_map = {k: choose(ret_cols, v) for k, v in ALIASES["returns"].items()}
    link_map = {k: choose(link_cols, v) for k, v in ALIASES["link"].items()}

    schema_map = {
        "run_utc": datetime.now(timezone.utc).isoformat(),
        "tables": TARGET_TABLES,
        "columns": {"trace": trace_map, "fisd": fisd_map, "returns": ret_map, "link": link_map},
        "schemas": schemas,
    }

    (DISC / "3.0_schema_mapping.json").write_text(json.dumps(schema_map, indent=2, sort_keys=True), encoding="utf-8")

    yaml_lines = [
        "# Auto-generated by scripts/3.0_schema_mapping.py",
        "# Review missing/null fields before running 4.x extraction.",
        "",
        "libraries:",
        '  trace_primary: "trace_enhanced"',
        '  trace_fallback: "trace_standard"',
        '  fisd_issue_master: "fisd_fisd"',
        '  fisd_common: "fisd_common"',
        '  bond_returns_primary: "wrdsapps_bondret"',
        '  bond_returns_fallback: "contrib_corporate_bond_returns"',
        '  bond_firm_link: "contrib_bond_firm_link"',
        "",
        "tables:",
        '  trace_trades: "trace_enhanced.trace_enhanced"',
        '  trace_fallback_trades: "trace_standard.trace"',
        '  fisd_issues: "fisd_fisd.fisd_issue"',
        '  fisd_issuer: "fisd_fisd.fisd_issuer"',
        '  fisd_common_issue_issuer: "fisd_common.issue_issuer"',
        '  bond_returns: "wrdsapps_bondret.bondret"',
        '  bond_returns_std: "wrdsapps_bondret.bondret_std"',
        '  trace_enhanced_clean: "wrdsapps_bondret.trace_enhanced_clean"',
        '  bond_returns_fallback: "contrib_corporate_bond_returns.bonds"',
        '  bond_firm_link: "contrib_bond_firm_link.fang_link"',
        "",
        "columns:",
    ]
    yaml_lines += mapping_block("trace", trace_map)
    yaml_lines += mapping_block("fisd", fisd_map)
    yaml_lines += mapping_block("returns", ret_map)
    yaml_lines += mapping_block("link", link_map)
    (CONFIGS / "schema_map.yaml").write_text("\n".join(yaml_lines) + "\n", encoding="utf-8")

    def missing(m: dict[str, str | None], needed: list[str]) -> list[str]:
        return [k for k in needed if not m.get(k)]

    critical = {
        "trace": missing(trace_map, ["cusip", "trade_date", "trade_price", "trade_yield", "trade_size"]),
        "fisd": missing(fisd_map, ["cusip", "issuer_id", "maturity_date", "coupon", "currency"]),
        "returns": missing(ret_map, ["cusip", "date", "bond_return"]),
    }

    md = [
        "# 3.0 Schema mapping report",
        "",
        f"- Run UTC: `{RUN_ID}`",
        "- Input table discovery: `artifacts/discovery/step02_tables.json`",
        "- Output config: `configs/schema_map.yaml`",
        "- Output JSON: `artifacts/discovery/3.0_schema_mapping.json`",
        "",
        "## Selected primary tables",
        "",
        "| Role | Table |",
        "|---|---|",
        "| TRACE trades | `trace_enhanced.trace_enhanced` |",
        "| FISD issues | `fisd_fisd.fisd_issue` |",
        "| Returns | `wrdsapps_bondret.bondret` |",
        "| Link table | `contrib_bond_firm_link.fang_link` |",
        "",
        "## Critical missing fields",
        "",
        "```json",
        json.dumps(critical, indent=2),
        "```",
        "",
        "## Mapped columns",
        "",
        "```json",
        json.dumps({"trace": trace_map, "fisd": fisd_map, "returns": ret_map, "link": link_map}, indent=2),
        "```",
        "",
    ]
    (DISC / "3.0_schema_report.md").write_text("\n".join(md), encoding="utf-8")

    print("\n[PRIMARY TABLES]")
    print("TRACE   trace_enhanced.trace_enhanced")
    print("FISD    fisd_fisd.fisd_issue")
    print("RETURNS wrdsapps_bondret.bondret")
    print("LINK    contrib_bond_firm_link.fang_link")
    print("\n[CRITICAL MISSING]")
    print(json.dumps(critical, indent=2))
    print("\n[WROTE]")
    print(CONFIGS / "schema_map.yaml")
    print(DISC / "3.0_schema_mapping.json")
    print(DISC / "3.0_schema_report.md")

    if any(critical.values()):
        print("\n[WARN] Some critical fields are null. This is not fatal; send me the report before running 4.x.")
        return 0
    print("\n[DONE] 3.0 complete. Schema map is ready for 4.x extraction.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
