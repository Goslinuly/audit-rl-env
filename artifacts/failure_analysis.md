20 episodes (train+dev); P/R from summed TP/FP/FN (the grader sets per-episode P=R=0 when an episode has no issues and no findings), F1/reward are per-episode means.

| Вариант | P (micro) | R (micro) | F1 (mean) | reward (mean) | TP | FP | FN | FP по типам | FN по типам |
|---|---:|---:|---:|---:|---:|---:|---:|---|---|
| Reconciler (full) | 1.000 | 1.000 | 1.000 | 0.960 | 95 | 0 | 0 | — | — |
| no_tz_period | 0.800 | 0.884 | 0.747 | 0.460 | 84 | 21 | 11 | cutoff 21 | cutoff 11 |
| no_tz_fx_date | 0.544 | 0.916 | 0.631 | 0.228 | 87 | 73 | 8 | fx 73 | fx 8 |
| no_weekend_fx_rule | 0.340 | 0.863 | 0.423 | -0.185 | 82 | 159 | 13 | fx 159 | fx 13 |
| loose_duplicates | 0.586 | 1.000 | 0.596 | 0.160 | 95 | 67 | 0 | dup 67 | — |
| flag_partial | 0.748 | 1.000 | 0.654 | 0.276 | 95 | 32 | 0 | alloc 32 | — |
| all_ablations | 0.167 | 0.684 | 0.237 | -0.557 | 65 | 324 | 30 | dup 67, alloc 30, fx 208, cutoff 19 | fx 18, cutoff 12 |

| Вариант | причины FP (grader finding_reasons) | источник FP (provenance) |
|---|---|---|
| Reconciler (full) | — | — |
| no_tz_period | affected_ids 14, no_issues 7 | boundary 11, not a distractor 7, recurring 3 |
| no_tz_fx_date | affected_ids 62, amount 5, no_issues 6 | boundary 4, not a distractor 55, partial_payment 4, recurring 6, refund 1, split_payment 3 |
| no_weekend_fx_rule | affected_ids 121, amount 4, no_issues 34 | boundary 4, not a distractor 95, partial_payment 5, prior_invoice 5, recurring 14, refund 2, split_payment 12, weekend_fx 22 |
| loose_duplicates | affected_ids 42, no_issues 22, type 3 | recurring 67 |
| flag_partial | affected_ids 20, no_issues 8, type 4 | partial_payment 32 |
| all_ablations | affected_ids 233, amount 8, no_issues 76, type 7 | boundary 17, not a distractor 138, partial_payment 37, prior_invoice 5, recurring 89, refund 3, split_payment 13, weekend_fx 22 |
