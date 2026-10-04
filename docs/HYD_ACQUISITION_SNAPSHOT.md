# Acquisition candidate snapshot

Command (one line): `python -m hyd_calibrator prepare-acquisition --root SOURCES
--inventory acquisition-source-review.json --out NEW_DIRECTORY`.

Only the finalized gzip files listed in the inventory are processed. Each path
must resolve within the source directory, occur once, and match the recorded
SHA-256 before output is created. Files are checked again after processing.
New downloads absent from that inventory do not silently enter the snapshot.
Existing outputs and output directories inside the acquisition tree are rejected.

The three deterministic gzip outputs contain wrappers around the original records:

- candidates.jsonl.gz: first complete occurrence of a normalized text.
- duplicates.jsonl.gz: further occurrences, with a reference to the first candidate.
- review.jsonl.gz: missing source metadata/origin URL/license, unversioned CC-BY
  declarations, empty texts or Unicode replacement characters. The original text
  and declarations remain untouched. A quarantined occurrence does not suppress
  a later complete candidate of that text.

Every wrapper preserves its original record, verbatim text hash, normalized text
hash and source file/line/hash. Every output row and the manifest declare
training_allowed=false and pending review. Candidate means eligible for further
review, not authorized training data, verified licensing or a quality guarantee.
The tool does not invent rights, consent, reviewer identity or token counts.
No near-duplicate, personal-data or contamination filtering is implied.

The complete manifest is written last, after checks pass, and records all input
and output hashes plus exact bucket/reason counts. If processing fails, partial
files may remain without a complete manifest; use a fresh output directory for
a retry and do not treat the partial directory as a completed corpus. This is
a local candidate snapshot, not a production training release.

The original acquisition files are never rewritten or deleted. All original
records remain represented in exactly one output bucket, including duplicates
and review cases, so provenance can be revisited without regenerating evidence.
The full corpus files stay local and are not committed to GitHub; only software,
tests, documentation and the manifest without original texts are deliverables.

Next steps are evidence-backed licensing review, source/domain/language balance,
privacy and near-duplicate filtering, token counting with the actual tokenizer,
then work/family-aware train/validation separation and explicit admission. The
existing base pretraining and active downloads are not changed by this command.
