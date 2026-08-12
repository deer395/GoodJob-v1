# Independent blind evaluation: baseline + limited semantic adjustment

This 24-case set has no overlap with the original 36-case development set.
It intentionally contains mostly no-JD, sparse, and multi-role entries to
reflect the real pool. Do not add scores, ranks, model reasons, or any model-
generated label to this file.

Fill `human_priority` only: `3` high priority, `2` worth attention, `1`
neutral, `0` low relevance. `human_note` is optional. Keep the other columns
and every case id unchanged.

The frozen candidate uses the original n-gram/deterministic baseline plus a
bounded Python adjustment of at most 6 points from a structured career-track
signal. A clear single-role technical job cannot receive a positive adjustment.
Provider failure always produces adjustment 0 and retains the exact baseline.
