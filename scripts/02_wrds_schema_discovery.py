from __future__ import annotations

import argparse
import json
import os
import re
import sys
import tarfile
import traceback
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd

try:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
except Exception:
    plt = None

import wrds


TARGET_LIBRARIES = [
    "trace_enhanced",
    "trace_standard",
    "fisd_fisd",
    "fisd_common",
    "wrdsapps_bondret",
    "contrib_corporate_bond_returns",
    "contrib_bond_firm_link",
    "contrib_bond_dickerson",
    "wrdsapps_link_crsp_bond",
]

ROLE_KEYWORDS = {
    "trace_trades": [
        "trace", "trade", "trd", "trans", "transaction", "cusip", "rpt", "report",
        "date", "time", "price", "yield", "yld", "volume", "size", "side", "buy", "sell",
        "contra", "counter", "cancel", "correct", "asof", "dissemination",
    ],
    "fisd_issues": [
        "fisd", "issue", "issuer", "cusip", "complete", "maturity", "matur", "coupon",
        "currency", "offering", "offer", "amount", "principal", "call", "put", "convert",
        "asset", "144a", "rating", "seniority", "security", "industry",
    ],
    "bond_returns": [
        "bondret", "return", "returns", "ret", "exret", "excess", "cusip", "date", "price",
        "yield", "duration", "spread", "month", "daily", "monthly",
    ],
    "links": [
        "link", "gvkey", "permno", "permco", "cusip", "issuer", "firm", "company", "crsp",
        "compustat", "isin", "cik",
    ],
}

ROLE_LIBRARY_BOOSTS = {
    "trace_trades": {"trace_enhanced": 100, "trace_standard": 65},
    "fisd_issues": {"fisd_fisd": 100, "fisd_common": 60},
    "bond_returns": {
        "wrdsapps_bondret": 100,
        "contrib_corporate_bond_returns": 90,
        "contrib_bond_dickerson": 40,
    },
    "links": {
        "contrib_bond_firm_link": 100,
        "wrdsapps_link_crsp_bond": 80,
        "fisd_common": 25,
    },
}


def stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def safe_name(x: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]+", "_", str(x))


def json_default(obj: Any) -> Any:
    try:
        import numpy as np
        if isinstance(obj, np.generic):
            return obj.item()
    except Exception:
        pass
    try:
        if pd.isna(obj):
            return None
    except Exception:
        pass
    return str(obj)


def get_column_names(desc: pd.DataFrame) -> list[str]:
    if desc is None or desc.empty:
        return []

    lower_map = {str(c).lower(): c for c in desc.columns}
    preferred = ["name", "column_name", "variable", "varname", "field", "column"]

    for key in preferred:
        if key in lower_map:
            vals = desc[lower_map[key]].dropna().astype(str).tolist()
            vals = [v.strip() for v in vals if v.strip()]
            if vals:
                return vals

    for c in desc.columns:
        vals = desc[c].dropna().astype(str).tolist()
        vals = [v.strip() for v in vals if v.strip()]
        if vals and len(vals) >= max(1, min(3, len(desc) // 2)):
            return vals

    return [str(x) for x in desc.index.tolist()]


def score_candidate(library: str, table: str, columns: list[str], role: str) -> int:
    lib_l = library.lower()
    table_l = table.lower()
    col_text = " ".join(columns).lower()
    full = f"{lib_l} {table_l} {col_text}"

    score = ROLE_LIBRARY_BOOSTS.get(role, {}).get(lib_l, 0)

    for kw in ROLE_KEYWORDS[role]:
        if kw in table_l:
            score += 18
        elif kw in col_text:
            score += 7
        elif kw in full:
            score += 2

    if role == "trace_trades" and any(x in table_l for x in ["trace", "trade", "trans", "trd"]):
        score += 40
    if role == "fisd_issues" and any(x i
        score += 40
    i
        score += 45
    if role == "links" and any(x in table_
        score += 35

   


def write_summary(path: P
  

    lines.append("# Step 02 WRDS schema discovery summary")
    lines.append("
    lines.append(f"Run UTC: `{inventory['run_utc'
    lines.append("")
    lines.app

    lines.appen
    lines.a

    for 
        i
        li
            f"
        )

    l
    lines.append("## Top table candidat
    lines.append("")

  
        for role in RO

                "sc


   
            lines.app
            lines.append(
            lines.append("|---:|---

            for 
              

           


    else:
        li
        lines.append(

    lines.append("##
    lines.append
    lines.append("
    lines.append("")

 


def make_candidate_plots(root: Path
    if plt is None or candida
        return

    fig_dir =
    fig_dir.mkdir(parents=True



            "scor
        ).head(10)

 
            continue

        labels = [f"{r.library}.{r.table}" for r in sub.iter
        scores = sub["score"].astype(float).to_list()

        fig_h = max(4.0, 0.45 * le
        fig, ax = plt.subplots(figsize=(11.0, fig_h))

        ax.barh(ran
      
        ax.set_ytick
        ax.invert_yaxis()
        ax.set_xlabel("Candidate score")
        ax.set_titl
        ax.grid(axis="x", alpha=0.25)

        fig.tight_layout()

        stem = fig_dir
        fig.savefig(stem.with_suffix(".png"), dpi=220, bbox_inches="tig
      
        plt.close(fig


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--proj
    parser.add_argument(
        "--max-tables-per-library",
      
      
    )
    args

    root = Path(args.project_root).resolve()
    logs_dir = root / "logs"
    discovery_d
    desc_dir = discovery_dir / "des

    l
 


    run_stamp = stamp(
    log_path = logs_dir / f"step02_schema_discovery_{run_stamp}.lo

    class Tee:
        def __init__(self, *files):
     

        def write(se
            for f in self.files:
                f.write(data)
               

        def flush(self):
           
      

    with log_
        sys.stdout = Tee(sys.__stdout_
        sys.stderr = Tee(sys.__stderr_

        print("=" * 72)
 
      
 


        print("=" *

        inventory: dict[str, Any] = {
            "run_utc": da


            "target_libraries
            "libraries": {},
            "tables": 


        }

        candidate_rows: list[dic
        table_rows: list[d

        db = None

        try:
      
            db = wrds.Connect

            all_libs
            

       
                json.dum
                encodin
            )

      

           
                act


                inventory["libraries"][wanted] = {
   
                    "actual_name":
                 


                if not present:
                    prin
                    continue

                try:
                    tables = s

                    if le
                        prin
                            f"[WRDS][WARN] {actual} has {len(tables)}
                            f"limiting to first {args.max
                    
                        tab

                    invent
                    inventory["libraries"][wanted]["

                    print(f"[WRDS] {actual}: {len(ta

                    for table in tables:
                      

                except

                        "stage": "list_tables",



                    inventory["errors"].append(err)
                    print("[WRDS

            pd.DataFrame(t
                discovery_d
                index=False,
           

            for row in table_rows:
      

                key = f"{lib}.{table}"

                try


                    desc = db.des
                    if no
                       

                    desc = 
                    co

                    des
                    de

                    inventory["schemas"][key] = {
                        "library": lib,
      
                   
                        "column_names": 
                   
     

                  
                        score = score_cand

                  

   


                         

 

                                    "role": role,
         
                  
                                    "table": tabl
                    
             

               

          

        
         
          
              
         

     

            candidates = pd.DataFrame(

            if not 

  
                    as


            candid


   

            inventor
            inventory_pat
                json.dumps(inventor

            )

 
              

           


         

         
            print("[O

            print("[
            prin

        except Ex
            inventor

 


                }
            )

  
                json.dumps(in
              


            
            print(traceback.fo



            if db
                tr

 
                    

        bundle_path = root / f"step02_schema_discovery_bundl

        with tarfile.open(bundle_path, "w:gz") as ta

                "logs",
          
                "reports/figures",
                "c

                "RE
      
            ]:
     
                if path.e
                    tar.add(path, arcnam

        print("[BU
        print("[DONE] Step 02 complet

        return 0


if __na

