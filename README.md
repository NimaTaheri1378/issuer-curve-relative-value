# Transaction-Based Issuer Yield Curve Relative Value in U.S. Corporate Bonds

This repository builds a transaction-based fixed-income relative-value research pipeline for U.S. corporate bonds.

The core idea is simple: within the same issuer, bonds that trade cheap relative to an issuer-specific TRACE-implied yield curve should subsequently outperform bonds that trade rich.

## Headline Result

Sample tag: `full2004_2025_c3000`

| Metric                             |     Value |
| ---------------------------------- | --------: |
| Panel rows                         | 2,200,771 |
| Issuer-demeaned target rows        | 1,459,247 |
| Monthly observations               |       256 |
| Issuer-month groups                |   182,763 |
| Position rows                      |   555,416 |
| Mean monthly return                |    0.414% |
| Annualized Sharpe                  |      2.53 |
| t-stat                             |     11.69 |
| Cumulative return                  |    187.1% |
| Max drawdown                       |    -2.95% |
| Look-ahead violations              |         0 |
| Duplicate CUSIP-feature-month rows |         0 |
| Placebo p-value                    |  0.001996 |

## Key Figures

### Cumulative Residual-Sort Performance

![Cumulative residual-sort performance](reports/figures/7.0_residual_sort_cumulative_full2004_2025_c3000.png)

### Placebo Validation

![Placebo validation](reports/figures/7.1_placebo_distribution_full2004_2025_c3000.png)

### Robustness Variants

![Robustness variants](reports/figures/7.1_robustness_variants_full2004_2025_c3000.png)

### Signal Monotonicity

![Signal monotonicity](reports/figures/6.0_signal_monotonicity_full2004_2025_c3000.png)

### FISD Universe Construction

![FISD universe construction](reports/figures/4.0_fisd_waterfall.png)

## Research Question

When two bonds belong to the same issuer, does the bond that trades cheap relative to the issuer's transaction-implied yield curve subsequently outperform the issuer's other bonds?

## Method

1. Build a conservative FISD universe of U.S.-dollar, fixed-coupon, non-convertible, non-putable, non-ABS corporate bonds.
2. Aggregate TRACE Enhanced transactions to a bond-day panel.
3. Fit weekly issuer Nelson-Siegel yield curves.
4. Compute residual yield: observed TRACE yield minus fitted issuer-curve yield.
5. Collapse weekly residuals into monthly issuer-relative signals.
6. Construct next-month issuer-demeaned bond returns from WRDS Bond Returns.
7. Run a same-issuer long-cheap / short-rich residual-sort baseline.
8. Validate with no-look-ahead checks, robustness variants, winsorization, and placebo permutations.

## Repository Structure

```text
configs/                 Schema and project configuration
scripts/                 Ordered pipeline scripts
reports/                 Final result tables and figures
artifacts/discovery/     Safe aggregate audit summaries
artifacts/raw/           Local WRDS-derived data; not committed
artifacts/interim/       Local WRDS-derived data; not committed
artifacts/processed/     Local WRDS-derived data; not committed
```

## Main Outputs

```text
reports/final_results_full2004_2025_c3000.md
reports/tables/headline_results_full2004_2025_c3000.csv
reports/tables/monthly_strategy_returns_full2004_2025_c3000.csv
reports/tables/robustness_variants_full2004_2025_c3000.csv
artifacts/discovery/7.1_validation_report_full2004_2025_c3000.md
```

## Data Safety and Reproducibility

Raw and derived WRDS data are not redistributed.

This repository contains code, configurations, aggregate reports, validation summaries, and figures. Reproducing the full result requires WRDS access to TRACE Enhanced, FISD, and WRDS Bond Returns.

Do not commit:

```text
artifacts/raw/
artifacts/interim/
artifacts/processed/
*.parquet
logs/
*.tar.gz
.pgpass
*.pem
*.key
```

## Notes

This repository is designed as a research and reproducibility scaffold, not as a redistribution of licensed data. The public files include source code, configuration files, figures, and aggregate result summaries. Licensed WRDS-derived datasets remain local and are excluded through `.gitignore`.
