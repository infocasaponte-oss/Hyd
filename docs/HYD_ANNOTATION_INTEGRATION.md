# Annotation integration delivery

Implemented locally on the evaluator app baseline `b479a78`; app commit `fee2543`.
The incremental patch is `integrations/evaluator-app/annotation-integration.patch`.
It contains no credentials or corpus data. It is not a complete application and
must be adapted against the current Lovable source rather than applied blindly.

## Behavior

- Evaluator cards expose explicit risk, context and abstention review, including
  benign examples needed for false-alarm measurement. Opening a card loads its
  own last 20 events; full history remains exportable.
- Authenticated server handlers restrict reads and writes to the record owner.
  The server hashes the original UTF-8 text; the proposed database policy checks
  that hash, ownership and consent. Each submission appends an event.
- Training JSONL includes the exact annotation contract without changing route
  labels. Reviewer IDs are hashed account pseudonyms, not verified person IDs.
  Existing normalized deduplication retains only the selected record's events;
  the full archive retains all record IDs and all histories.
- Portable archive version 2 adds annotation events and their count. Export
  fails visibly if the new table cannot be read; it does not silently omit it.
- Unknown values remain unknown. No automatic selection of a final human label
  and no inference of agreement or reviewer independence is implemented.

## Deployment status and required checks

**Not applied to Lovable or a live database.** Lovable is paused for credits.
The local SQL migration has not been executed against PostgreSQL; RLS behavior
therefore remains unverified. Local TypeScript and production build passed;
19 Vitest tests passed, including annotation validation and archive preservation.

1. Export and retain the current source, data, existing subtype marks and any
   available audit trail before deployment. Do not rewrite existing marks.
2. Adapt the incremental patch to the exported source. The previous local
   development-metadata migration supplies the immutable-question prerequisite;
   reconcile that prerequisite with the live schema before applying either.
3. Review and apply the additive annotation migration, regenerate database types,
   and check two different authenticated accounts plus an anonymous client:
   own read/insert works; cross-account access, update/delete, hash mismatch and
   missing consent fail. Check the deployed app's actual UI as well.
4. Round-trip JSONL through Hyd's annotation validator, then compare full archive
   counts and event IDs with the database, including histories over 20 entries.
5. Previously AI-corrected marks must remain identified as AI proposals pending
   human reconfirmation. This delivery does not relabel them as human events.

Next plan work: person/family grouping, reproducible E2 admission, and measured
E3 evaluation with explicit adjudication. No new accuracy claim is made here.
