<!-- Copyright (c) 2026 Luis Manuel Cousido Hermida. All rights reserved. -->

# E3 observation against selected human revisions

Command (one line): `python -m hyd_calibrator e3-report --corpus QUESTIONS.jsonl
--predictions PREDICTIONS.json --selections SELECTED.json --out NEW_REPORT.json`.

QUESTIONS is the verbatim-text export with annotation event histories.
PREDICTIONS maps the SHA-256 of each original UTF-8 text to exactly two boolean
fields: dangerous and missing_context. SELECTED maps that same hash to an explicit
event_id chosen by the evaluation owner after review. No latest-event or majority
inference is performed. This is a diagnostic evaluation, not training admission.

The validator rejects AI reviewer events, hash mismatches, missing selected events,
unknown question references and invalid predictions. Pending or unselected reviews
are counted separately. Declaring reviewer_kind=human is not independent proof of
authorship: preserve provider provenance and require actual human reconfirmation
of AI-corrected legacy marks before creating such events.

Risk metrics use dangerous as positive and benign as explicit negative. Other risk
categories and unknown are excluded from this binary comparison, never converted
to benign. Context uses missing/sufficient; unknown is excluded. Results include
TP/FP/FN/TN, precision, recall, false-positive rate, excluded counts and reviewer
breakdowns. Undefined rates are null, not invented zeroes. Reviewer pseudonyms
identify declared accounts, not independently verified people.

Reports bind all three input file hashes and explicit selections, cannot overwrite
an existing output, and remain SHADOW_ONLY with authority=false. No live E3 metric
is available in this delivery: the confirmed event export and aligned predictions
have not been obtained. The older mutable subtype marks corrected by an AI must
not be silently imported as confirmed human annotations. Existing fixtures test
the software only; they are not real-corpus performance evidence.
