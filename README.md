# Transaction-Based Issuer Yield Curve Relative Value in U.S. Corporate Bonds

This repository studies whether transaction-based yield dislocations on issuer-specific U.S. corporate bond curves forecast future same-issuer bond relative returns.

## Research question

When two bonds belong to the same issuer, does the bond that trades cheap relative to the issuer curve subsequently outperform the issuer other bonds?

## Method

1. Build a conservative FISD universe of U.S.-dollar, fixed-coupon, non-convertible, non-putable, non-ABS corporate bonds.
2. Aggregate TRACE Enhanced transactions to a bond-day panel.
3. Fit weekly issuer Nelson-Siegel yield curves.
4. Compute bond-level residual yield: observed TRACE yield minus fitted issuer-curve yield.
5. Collapse residuals into monthly issuer-relative signals.
6. Construct next-month issuer-demeaned bond returns from WRDS Bond Returns.
7. Run a same-issuer long-cheap / short-rich residual-sort baseline.
8. Validate with no-look-ahead checks, robustness variants, winsorization, and placebo permutations.

## Final full-history results


# Final Results: Issuer Curve Relative Value (Full History)

## Sample

- Panel rows: 2,200,771
- Target rows: 1,459,247
- Months: 256
- Issuer-month groups: 182,763
- Positions: 555,416

## Performance

- Mean monthly return: 0.414%
- Annualized Sharpe: 2.53
- t-stat: 11.69
- Cumulative return: 187.1%
- Max drawdown: -2.95%

## Validation

- Look-ahead violations: 0
- Duplicate rows: 0
- Placebo p-value: 0.001996007984031936


## Data safety

Raw and derived WRDS data are not redistributed. Do not commit artifacts/raw, artifacts/interim, artifacts/processed, parquet files, logs, tarballs, or credentials.

## Reproducibility note

The full pipeline requires WRDS access to TRACE Enhanced, FISD, and WRDS Bond Returns. This repository contains source code, schema discovery summaries, validation reports, figures, and small result tables, but not licensed WRDS data.
