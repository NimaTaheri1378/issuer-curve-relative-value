PS C:\Users\Nima\Downloads\issuer_curve_rv_github_release_full2004_2025_c3000> Get-ChildItem -Recurse -Force |
>>   Where-Object {
>>     $_.Name -like "*.parquet" -or
>>     $_.Name -like "*.tar.gz" -or
>>     $_.Name -eq ".pgpass" -or
>>     $_.Name -like "*.pem" -or
>>     $_.Name -like "*.key"
>>   } |
>>   Select-Object FullName
PS C:\Users\Nima\Downloads\issuer_curve_rv_github_release_full2004_2025_c3000> Select-String -Path * -Pattern "password|pgpass|WRDS_PASSWORD" -Recurse -ErrorAction SilentlyContinue
Select-String : A parameter cannot be found that matches parameter name 'Recurse'.
At line:1 char:64
+ ... ing -Path * -Pattern "password|pgpass|WRDS_PASSWORD" -Recurse -ErrorA ...
+                                                          ~~~~~~~~
    + CategoryInfo          : InvalidArgument: (:) [Select-String], ParameterBindingException
    + FullyQualifiedErrorId : NamedParameterNotFound,Microsoft.PowerShell.Commands.SelectStringCommand

PS C:\Users\Nima\Downloads\issuer_curve_rv_github_release_full2004_2025_c3000> notepad README.md
PS C:\Users\Nima\Downloads\issuer_curve_rv_github_release_full2004_2025_c3000> Remove-Item scripts\*.bak* -Force -ErrorAction SilentlyContinue
PS C:\Users\Nima\Downloads\issuer_curve_rv_github_release_full2004_2025_c3000> Remove-Item scripts\__pycache__ -Recurse -Force -ErrorAction SilentlyContinue
PS C:\Users\Nima\Downloads\issuer_curve_rv_github_release_full2004_2025_c3000> Remove-Item artifacts\discovery\*pilot2024* -Force -ErrorAction SilentlyContinue
PS C:\Users\Nima\Downloads\issuer_curve_rv_github_release_full2004_2025_c3000> Remove-Item artifacts\discovery\*full2024* -Force -ErrorAction SilentlyContinue
PS C:\Users\Nima\Downloads\issuer_curve_rv_github_release_full2004_2025_c3000> Remove-Item reports\figures\*pilot2024* -Force -ErrorAction SilentlyContinue
PS C:\Users\Nima\Downloads\issuer_curve_rv_github_release_full2004_2025_c3000> Remove-Item reports\figures\*full2024* -Force -ErrorAction SilentlyContinue
PS C:\Users\Nima\Downloads\issuer_curve_rv_github_release_full2004_2025_c3000> git status --short
 M .gitignore
 M README.md
 D artifacts/discovery/4.1_trace_error_pilot2024_20260527T170647Z.json
 D artifacts/discovery/4.1_trace_errors_full2024.json
 D artifacts/discovery/4.1_trace_extraction_report_full2024.md
 D artifacts/discovery/4.1_trace_monthly_coverage_full2024.csv
 D artifacts/discovery/4.1_trace_summary_full2024.json
 D artifacts/discovery/5.0_curve_coverage_by_week_full2024.csv
 D artifacts/discovery/5.0_curve_coverage_by_week_pilot2024.csv
 D artifacts/discovery/5.0_curve_fit_report_full2024.md
 D artifacts/discovery/5.0_curve_fit_report_pilot2024.md
 D artifacts/discovery/5.0_curve_fit_summary_full2024.json
 D artifacts/discovery/5.0_curve_fit_summary_pilot2024.json
 D artifacts/discovery/5.0_issuer_week_group_sizes_full2024.csv
 D artifacts/discovery/5.0_issuer_week_group_sizes_pilot2024.csv
 D artifacts/discovery/6.0_monthly_target_coverage_full2024.csv
 D artifacts/discovery/6.0_monthly_target_coverage_pilot2024.csv
 D artifacts/discovery/6.0_target_report_full2024.md
 D artifacts/discovery/6.0_target_report_pilot2024.md
 D artifacts/discovery/6.0_target_summary_full2024.json
 D artifacts/discovery/6.0_target_summary_pilot2024.json
 D artifacts/discovery/7.0_residual_sort_report_full2024.md
 D artifacts/discovery/7.0_residual_sort_report_pilot2024.md
 D artifacts/discovery/7.0_residual_sort_summary_full2024.json
 D artifacts/discovery/7.0_residual_sort_summary_pilot2024.json
 D artifacts/discovery/7.1_largest_issuer_month_contributions_full2024.csv
 D artifacts/discovery/7.1_placebo_permutations_full2024.csv
 D artifacts/discovery/7.1_robustness_variants_full2024.csv
 D artifacts/discovery/7.1_smallest_issuer_month_contributions_full2024.csv
 D artifacts/discovery/7.1_validation_report_full2024.md
 D artifacts/discovery/7.1_validation_summary_full2024.json
 D reports/figures/4.1_trace_monthly_coverage_full2024.png
 D reports/figures/4.1_trace_monthly_coverage_full2024.svg
 D reports/figures/4.1_trace_yield_distribution_full2024.png
 D reports/figures/4.1_trace_yield_distribution_full2024.svg
 D reports/figures/5.0_curve_coverage_full2024.png
 D reports/figures/5.0_curve_coverage_full2024.svg
 D reports/figures/5.0_curve_coverage_pilot2024.png
 D reports/figures/5.0_curve_coverage_pilot2024.svg
 D reports/figures/5.0_example_issuer_curve_full2024.png
 D reports/figures/5.0_example_issuer_curve_full2024.svg
 D reports/figures/5.0_example_issuer_curve_pilot2024.png
 D reports/figures/5.0_example_issuer_curve_pilot2024.svg
 D reports/figures/5.0_residual_distribution_full2024.png
 D reports/figures/5.0_residual_distribution_full2024.svg
 D reports/figures/5.0_residual_distribution_pilot2024.png
 D reports/figures/5.0_residual_distribution_pilot2024.svg
 D reports/figures/6.0_signal_monotonicity_full2024.png
 D reports/figures/6.0_signal_monotonicity_full2024.svg
 D reports/figures/6.0_signal_monotonicity_pilot2024.png
 D reports/figures/6.0_signal_monotonicity_pilot2024.svg
 D reports/figures/6.0_target_coverage_full2024.png
 D reports/figures/6.0_target_coverage_full2024.svg
 D reports/figures/6.0_target_coverage_pilot2024.png
 D reports/figures/6.0_target_coverage_pilot2024.svg
 D reports/figures/7.0_issuer_spreads_full2024.png
 D reports/figures/7.0_issuer_spreads_full2024.svg
 D reports/figures/7.0_issuer_spreads_pilot2024.png
 D reports/figures/7.0_issuer_spreads_pilot2024.svg
 D reports/figures/7.0_residual_sort_cumulative_full2024.png
 D reports/figures/7.0_residual_sort_cumulative_full2024.svg
 D reports/figures/7.0_residual_sort_cumulative_pilot2024.png
 D reports/figures/7.0_residual_sort_cumulative_pilot2024.svg
 D reports/figures/7.0_residual_sort_monthly_full2024.png
 D reports/figures/7.0_residual_sort_monthly_full2024.svg
 D reports/figures/7.0_residual_sort_monthly_pilot2024.png
 D reports/figures/7.0_residual_sort_monthly_pilot2024.svg
 D reports/figures/7.1_placebo_distribution_full2024.png
 D reports/figures/7.1_robustness_variants_full2024.png
 D reports/figures/7.1_validation_cumulative_full2024.png
PS C:\Users\Nima\Downloads\issuer_curve_rv_github_release_full2004_2025_c3000> git add -A
warning: in the working copy of '.gitignore', LF will be replaced by CRLF the next time Git touches it
warning: in the working copy of 'README.md', LF will be replaced by CRLF the next time Git touches it
PS C:\Users\Nima\Downloads\issuer_curve_rv_github_release_full2004_2025_c3000> git status --short
M  README.md
D  artifacts/discovery/4.1_trace_error_pilot2024_20260527T170647Z.json
D  artifacts/discovery/4.1_trace_errors_full2024.json
D  artifacts/discovery/4.1_trace_extraction_report_full2024.md
D  artifacts/discovery/4.1_trace_monthly_coverage_full2024.csv
D  artifacts/discovery/4.1_trace_summary_full2024.json
D  artifacts/discovery/5.0_curve_coverage_by_week_full2024.csv
D  artifacts/discovery/5.0_curve_coverage_by_week_pilot2024.csv
D  artifacts/discovery/5.0_curve_fit_report_full2024.md
D  artifacts/discovery/5.0_curve_fit_report_pilot2024.md
D  artifacts/discovery/5.0_curve_fit_summary_full2024.json
D  artifacts/discovery/5.0_curve_fit_summary_pilot2024.json
D  artifacts/discovery/5.0_issuer_week_group_sizes_full2024.csv
D  artifacts/discovery/5.0_issuer_week_group_sizes_pilot2024.csv
D  artifacts/discovery/6.0_monthly_target_coverage_full2024.csv
D  artifacts/discovery/6.0_monthly_target_coverage_pilot2024.csv
D  artifacts/discovery/6.0_target_report_full2024.md
D  artifacts/discovery/6.0_target_report_pilot2024.md
D  artifacts/discovery/6.0_target_summary_full2024.json
D  artifacts/discovery/6.0_target_summary_pilot2024.json
D  artifacts/discovery/7.0_residual_sort_report_full2024.md
D  artifacts/discovery/7.0_residual_sort_report_pilot2024.md
D  artifacts/discovery/7.0_residual_sort_summary_full2024.json
D  artifacts/discovery/7.0_residual_sort_summary_pilot2024.json
D  artifacts/discovery/7.1_largest_issuer_month_contributions_full2024.csv
D  artifacts/discovery/7.1_placebo_permutations_full2024.csv
D  artifacts/discovery/7.1_robustness_variants_full2024.csv
D  artifacts/discovery/7.1_smallest_issuer_month_contributions_full2024.csv
D  artifacts/discovery/7.1_validation_report_full2024.md
D  artifacts/discovery/7.1_validation_summary_full2024.json
D  reports/figures/4.1_trace_monthly_coverage_full2024.png
D  reports/figures/4.1_trace_monthly_coverage_full2024.svg
D  reports/figures/4.1_trace_yield_distribution_full2024.png
D  reports/figures/4.1_trace_yield_distribution_full2024.svg
D  reports/figures/5.0_curve_coverage_full2024.png
D  reports/figures/5.0_curve_coverage_full2024.svg
D  reports/figures/5.0_curve_coverage_pilot2024.png
D  reports/figures/5.0_curve_coverage_pilot2024.svg
D  reports/figures/5.0_example_issuer_curve_full2024.png
D  reports/figures/5.0_example_issuer_curve_full2024.svg
D  reports/figures/5.0_example_issuer_curve_pilot2024.png
D  reports/figures/5.0_example_issuer_curve_pilot2024.svg
D  reports/figures/5.0_residual_distribution_full2024.png
D  reports/figures/5.0_residual_distribution_full2024.svg
D  reports/figures/5.0_residual_distribution_pilot2024.png
D  reports/figures/5.0_residual_distribution_pilot2024.svg
D  reports/figures/6.0_signal_monotonicity_full2024.png
D  reports/figures/6.0_signal_monotonicity_full2024.svg
D  reports/figures/6.0_signal_monotonicity_pilot2024.png
D  reports/figures/6.0_signal_monotonicity_pilot2024.svg
D  reports/figures/6.0_target_coverage_full2024.png
D  reports/figures/6.0_target_coverage_full2024.svg
D  reports/figures/6.0_target_coverage_pilot2024.png
D  reports/figures/6.0_target_coverage_pilot2024.svg
D  reports/figures/7.0_issuer_spreads_full2024.png
D  reports/figures/7.0_issuer_spreads_full2024.svg
D  reports/figures/7.0_issuer_spreads_pilot2024.png
D  reports/figures/7.0_issuer_spreads_pilot2024.svg
D  reports/figures/7.0_residual_sort_cumulative_full2024.png
D  reports/figures/7.0_residual_sort_cumulative_full2024.svg
D  reports/figures/7.0_residual_sort_cumulative_pilot2024.png
D  reports/figures/7.0_residual_sort_cumulative_pilot2024.svg
D  reports/figures/7.0_residual_sort_monthly_full2024.png
D  reports/figures/7.0_residual_sort_monthly_full2024.svg
D  reports/figures/7.0_residual_sort_monthly_pilot2024.png
D  reports/figures/7.0_residual_sort_monthly_pilot2024.svg
D  reports/figures/7.1_placebo_distribution_full2024.png
D  reports/figures/7.1_robustness_variants_full2024.png
D  reports/figures/7.1_validation_cumulative_full2024.png
PS C:\Users\Nima\Downloads\issuer_curve_rv_github_release_full2004_2025_c3000> git commit -m "Polish README and clean public release artifacts"
[main aeb7532] Polish README and clean public release artifacts
 69 files changed, 151 insertions(+), 133459 deletions(-)
 delete mode 100644 artifacts/discovery/4.1_trace_error_pilot2024_20260527T170647Z.json
 delete mode 100644 artifacts/discovery/4.1_trace_errors_full2024.json
 delete mode 100644 artifacts/discovery/4.1_trace_extraction_report_full2024.md
 delete mode 100644 artifacts/discovery/4.1_trace_monthly_coverage_full2024.csv
 delete mode 100644 artifacts/discovery/4.1_trace_summary_full2024.json
 delete mode 100644 artifacts/discovery/5.0_curve_coverage_by_week_full2024.csv
 delete mode 100644 artifacts/discovery/5.0_curve_coverage_by_week_pilot2024.csv
 delete mode 100644 artifacts/discovery/5.0_curve_fit_report_full2024.md
 delete mode 100644 artifacts/discovery/5.0_curve_fit_report_pilot2024.md
 delete mode 100644 artifacts/discovery/5.0_curve_fit_summary_full2024.json
 delete mode 100644 artifacts/discovery/5.0_curve_fit_summary_pilot2024.json
 delete mode 100644 artifacts/discovery/5.0_issuer_week_group_sizes_full2024.csv
 delete mode 100644 artifacts/discovery/5.0_issuer_week_group_sizes_pilot2024.csv
 delete mode 100644 artifacts/discovery/6.0_monthly_target_coverage_full2024.csv
 delete mode 100644 artifacts/discovery/6.0_monthly_target_coverage_pilot2024.csv
 delete mode 100644 artifacts/discovery/6.0_target_report_full2024.md
 delete mode 100644 artifacts/discovery/6.0_target_report_pilot2024.md
 delete mode 100644 artifacts/discovery/6.0_target_summary_full2024.json
 delete mode 100644 artifacts/discovery/6.0_target_summary_pilot2024.json
 delete mode 100644 artifacts/discovery/7.0_residual_sort_report_full2024.md
 delete mode 100644 artifacts/discovery/7.0_residual_sort_report_pilot2024.md
 delete mode 100644 artifacts/discovery/7.0_residual_sort_summary_full2024.json
 delete mode 100644 artifacts/discovery/7.0_residual_sort_summary_pilot2024.json
 delete mode 100644 artifacts/discovery/7.1_largest_issuer_month_contributions_full2024.csv
 delete mode 100644 artifacts/discovery/7.1_placebo_permutations_full2024.csv
 delete mode 100644 artifacts/discovery/7.1_robustness_variants_full2024.csv
 delete mode 100644 artifacts/discovery/7.1_smallest_issuer_month_contributions_full2024.csv
 delete mode 100644 artifacts/discovery/7.1_validation_report_full2024.md
 delete mode 100644 artifacts/discovery/7.1_validation_summary_full2024.json
 delete mode 100644 reports/figures/4.1_trace_monthly_coverage_full2024.png
 delete mode 100644 reports/figures/4.1_trace_monthly_coverage_full2024.svg
 delete mode 100644 reports/figures/4.1_trace_yield_distribution_full2024.png
 delete mode 100644 reports/figures/4.1_trace_yield_distribution_full2024.svg
 delete mode 100644 reports/figures/5.0_curve_coverage_full2024.png
 delete mode 100644 reports/figures/5.0_curve_coverage_full2024.svg
 delete mode 100644 reports/figures/5.0_curve_coverage_pilot2024.png
 delete mode 100644 reports/figures/5.0_curve_coverage_pilot2024.svg
 delete mode 100644 reports/figures/5.0_example_issuer_curve_full2024.png
 delete mode 100644 reports/figures/5.0_example_issuer_curve_full2024.svg
 delete mode 100644 reports/figures/5.0_example_issuer_curve_pilot2024.png
 delete mode 100644 reports/figures/5.0_example_issuer_curve_pilot2024.svg
 delete mode 100644 reports/figures/5.0_residual_distribution_full2024.png
 delete mode 100644 reports/figures/5.0_residual_distribution_full2024.svg
 delete mode 100644 reports/figures/5.0_residual_distribution_pilot2024.png
 delete mode 100644 reports/figures/5.0_residual_distribution_pilot2024.svg
 delete mode 100644 reports/figures/6.0_signal_monotonicity_full2024.png
 delete mode 100644 reports/figures/6.0_signal_monotonicity_full2024.svg
 delete mode 100644 reports/figures/6.0_signal_monotonicity_pilot2024.png
 delete mode 100644 reports/figures/6.0_signal_monotonicity_pilot2024.svg
 delete mode 100644 reports/figures/6.0_target_coverage_full2024.png
 delete mode 100644 reports/figures/6.0_target_coverage_full2024.svg
 delete mode 100644 reports/figures/6.0_target_coverage_pilot2024.png
 delete mode 100644 reports/figures/6.0_target_coverage_pilot2024.svg
 delete mode 100644 reports/figures/7.0_issuer_spreads_full2024.png
 delete mode 100644 reports/figures/7.0_issuer_spreads_full2024.svg
 delete mode 100644 reports/figures/7.0_issuer_spreads_pilot2024.png
 delete mode 100644 reports/figures/7.0_issuer_spreads_pilot2024.svg
 delete mode 100644 reports/figures/7.0_residual_sort_cumulative_full2024.png
 delete mode 100644 reports/figures/7.0_residual_sort_cumulative_full2024.svg
 delete mode 100644 reports/figures/7.0_residual_sort_cumulative_pilot2024.png
 delete mode 100644 reports/figures/7.0_residual_sort_cumulative_pilot2024.svg
 delete mode 100644 reports/figures/7.0_residual_sort_monthly_full2024.png
 delete mode 100644 reports/figures/7.0_residual_sort_monthly_full2024.svg
 delete mode 100644 reports/figures/7.0_residual_sort_monthly_pilot2024.png
 delete mode 100644 reports/figures/7.0_residual_sort_monthly_pilot2024.svg
 delete mode 100644 reports/figures/7.1_placebo_distribution_full2024.png
 delete mode 100644 reports/figures/7.1_robustness_variants_full2024.png
 delete mode 100644 reports/figures/7.1_validation_cumulative_full2024.png
PS C:\Users\Nima\Downloads\issuer_curve_rv_github_release_full2004_2025_c3000> git push
Enumerating objects: 13, done.
Counting objects: 100% (13/13), done.
Delta compression using up to 32 threads
Compressing objects: 100% (7/7), done.
Writing objects: 100% (7/7), 2.20 KiB | 2.21 MiB/s, done.
Total 7 (delta 2), reused 0 (delta 0), pack-reused 0 (from 0)
remote: Resolving deltas: 100% (2/2), completed with 2 local objects.
To https://github.com/NimaTaheri1378/issuer-curve-relative-value.git
   720e948..aeb7532  main -> main
PS C:\Users\Nima\Downloads\issuer_curve_rv_github_release_full2004_2025_c3000> cmd /c del "\\?\C:\Users\Nima\Downloads\issuer_curve_rv_github_release_full2004_2025_c3000\scripts\02_wrds_schema_discovery.py."
Could Not Find \\?\C:\Users\Nima\Downloads\issuer_curve_rv_github_release_full2004_2025_c3000\scripts\02_wrds_schema_discovery.py.
PS C:\Users\Nima\Downloads\issuer_curve_rv_github_release_full2004_2025_c3000> git add -A
PS C:\Users\Nima\Downloads\issuer_curve_rv_github_release_full2004_2025_c3000> Get-ChildItem -Recurse -Force |
>>   Where-Object {
>>     $_.Name -like "*.parquet" -or
>>     $_.Name -like "*.tar.gz" -or
>>     $_.Name -eq ".pgpass" -or
>>     $_.Name -like "*.pem" -or
>>     $_.Name -like "*.key"
>>   } |
>>   Select-Object FullName
PS C:\Users\Nima\Downloads\issuer_curve_rv_github_release_full2004_2025_c3000> Select-String -Path * -Pattern "WRDS_PASSWORD|password|pgpass" -Recurse -ErrorAction SilentlyContinue
Select-String : A parameter cannot be found that matches parameter name 'Recurse'.
At line:1 char:64
+ ... ing -Path * -Pattern "WRDS_PASSWORD|password|pgpass" -Recurse -ErrorA ...
+                                                          ~~~~~~~~
    + CategoryInfo          : InvalidArgument: (:) [Select-String], ParameterBindingException
    + FullyQualifiedErrorId : NamedParameterNotFound,Microsoft.PowerShell.Commands.SelectStringCommand

PS C:\Users\Nima\Downloads\issuer_curve_rv_github_release_full2004_2025_c3000>
