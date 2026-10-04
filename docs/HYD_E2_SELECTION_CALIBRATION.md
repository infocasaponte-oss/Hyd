<!-- Copyright (c) 2026 Luis Manuel Cousido Hermida. All rights reserved. -->

# Separate E2 selection and calibration

Build a new dataset with `python -m hyd_calibrator build --corpus SOURCE.jsonl
--out NEW_SNAPSHOT --grouped --development` (one shell line). Nominal allocation
is 60/10/15/15 train/development/calibration/test; connected components remain
intact. Real person/family declarations are required, never synthesized.

E2 now requires development.jsonl and validates all four files before encoder
loading. C selection uses development only. Logistic fitting uses train only.
Calibration groups are deterministically divided into temperature fitting and
threshold selection; inconsistent person/family group IDs are rejected. Test
embeddings are produced only after all selections are fixed.

Threshold selection uses confidence and top-two probability margin, minimum
coverage and a diagnostic 95% Wilson lower bound. If no point meets the requested
target, the artifact declares abstain_all=true. The test report applies that flag
and records accepted count, correct count, coverage and Wilson bound separately
from overall routing accuracy. Head files preserve thresholds and abstain_all.

CLI controls: --target (default .95), --min-coverage (default .1). These are
diagnostic selection criteria, not a production precision guarantee: selecting
among intervals introduces selection bias, and correlated samples within groups
invalidate a simple independent-Bernoulli interpretation. The report explicitly
retains this limitation and SHADOW_ONLY status. Independent test and subsequent
external confirmation remain necessary. No new real-corpus results were measured.

Remaining work: package a reloadable E2 runtime with the encoder/head manifest,
verify runtime parity, assess class coverage in each calibration subpartition,
then evaluate E3 and specialist combination on independent evidence. Small or
single-group calibration fails rather than inventing extra observations.
