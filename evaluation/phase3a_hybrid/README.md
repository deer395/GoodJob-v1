# Phase 3A hybrid matching evaluation

`human_review_blind.csv` is a blinded, stratified sample of 36 real job records.
It deliberately exposes only job facts needed for the user's judgment and does
not contain system scores, ranks, reasons, semantic results, or labels.

Please fill only:

- `human_priority`: `3` high priority, `2` worth attention, `1` neutral, `0` low relevance;
- `human_note` (optional): concise reason for the judgment.

Do not alter `case_id` or the job fact columns. After all 36 priorities are
provided, the evaluation runner will compare the same cases' frozen f782c59
n-gram baseline against the hybrid candidate using Spearman correlation, Top-10
and Top-20 precision, and false-high / false-low counts. No model may generate
or fill these labels.
