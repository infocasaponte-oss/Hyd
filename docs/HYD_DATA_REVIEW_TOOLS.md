<!-- Copyright (c) 2026 Luis Manuel Cousido Hermida. All rights reserved. -->

# Corpus acquisition and evaluation review tools

Implemented two non-destructive commands in the standalone calibrator.

## Evaluation duplicates

`python -m hyd_calibrator deduplicate-evaluation --source INPUT.json --out NEW_DIR
--text-field prompt --reference-field expected_response --evaluation-kind general-response`.
Run this as one shell line. JSON lists and JSONL are supported; routing exports
use text/expected and evaluation-kind hyd-routing. The explicit kind prevents
mistaking a general response benchmark for a routing benchmark.

Original rows and metadata are copied verbatim into original.json. Normalized
question equality groups duplicates; no fuzzy family matching is implied. A
deduplicated copy keeps the first original row only when all references agree.
Different references fail before writing output. --review-only instead creates
an inspection snapshot with all originals and all conflicting row groups, but
does not generate a usable deduplicated dataset or choose a reference. Indexes
are zero-based positions. Existing snapshots are rejected. Replacement Unicode
characters in questions/references are flagged for source review, not repaired.
All outputs retain pending review and training_allowed=false; no human approval,
authorship, independence or new accuracy is inferred.

Actual general HYDRA evaluation (external-evaluation-v2): 300 rows, 287 normalized
unique questions, 12 repeated groups and five groups with different references.
The inspection snapshot is local under .codex-artifacts/general-evaluation-review-20261004-v2.
No original question/reference was changed. Several completion prompts permit
different plausible answers; exact reference equality cannot resolve that policy.
Review the rubric explicitly rather than deleting inconvenient examples.
This is not evidence about the separate 50.2% Hyd routing test.

## Acquisition source report

`python -m hyd_calibrator acquisition-report --root SOURCES_DIR --out NEW_REPORT.json`.
The report streams all finalized jsonl.gz records, records file SHA-256 hashes
and compressed bytes, and counts rows, characters, empty texts, replacement
characters and normalized duplicates by declared category/source/license/language.
Duplicate totals reflect sorted file traversal; later groups receive the duplicate
count, so a source comparison must account for that ordering. Malformed data fails
visibly. No existing report is overwritten.

Declared categories are not verified domains: review legal/administrative sources
separately from spoken/general/divulgation material. The report does not assert
training admission, licensing approval, token yield or network transfer volume.
It is not transactional when acquisition is active. Freeze a snapshot and apply
quality/privacy/licensing/decontamination filters before measuring valid tokens
with the actual tokenizer and updating acquisition targets. Downloads already
running are not modified by these tools.

Executed acquisition scan: 102 files, 171,200 rows and 5,963 normalized duplicate
occurrences (about 3.48%). No empty texts were found. Downloads remained active;
these counts describe that enumerated set, not the eventual final acquisition.
Evidence is saved in evidence/acquisition-source-review-20261004.json. Most
duplicate occurrences are in EUR-Lex (3,193 legislation and 880 modern-language
rows); YouTube accounts for 1,020 occurrences out of 26,083 inspected rows.
This is exact normalized-text repetition, not a near-duplicate/family audit.
No originals were deleted and no new accuracy was computed.

Remaining plan: obtain the actual Hyd human routing benchmark and confirmed E3
annotation export, validate references and freeze independent partitions; audit
language/domain balance and tokenizer yield; then run real E2/E3 evaluation.
Combining specialists before these checks would not demonstrate the 90% goal.
