<!-- Copyright (c) 2026 Luis Manuel Cousido Hermida. All rights reserved. -->

# E2: strict input admission and pinned encoder

The E2 training CLI now requires `--encoder-revision` with a 40-character
lowercase commit SHA. The caller must obtain and review the real revision of
the configured encoder; no revision is fabricated here. SentenceTransformer
receives that revision explicitly. Existing output directories are rejected.

Before encoder imports/downloads, all three partitions require explicit consent,
declared verified rights, valid routes, correct training permissions, real/source
flags, declared person/family IDs and group IDs. Cross-partition overlap in any
of these grouping fields or normalized text fails; duplicated text also fails.
Each partition must contain all ten classes. Optional annotations are validated.
The report records all three input file hashes and the encoder revision.

Legacy datasets without provenance are intentionally rejected for new E2 runs.
Existing reports remain historical evidence; this change does not reconstruct
missing provenance or rerun the encoder. Account/person declarations are not
independent identity verification. Grouped splitting does not prove that the
family declarations are complete.

No new training was executed and no accuracy improvement is claimed. The current
calibration method still reuses calibration for C selection and temperature and
its threshold fallback is not a certified precision guarantee. Next work must
separate development selection, calibrate selective risk with coverage and
confidence intervals, and verify a complete reloadable runtime artifact before
promotion. E2 remains SHADOW_ONLY with authority=false.
