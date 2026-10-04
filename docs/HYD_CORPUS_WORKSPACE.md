# Corpus tab and bounded downloader

The offline evaluator app now has an authenticated /corpus route, with links from
the main panel and evaluator page. It imports acquisition-source-review/1 JSON,
shows real imported source/language/licence counts, and exports the complete
imported report. It starts empty and does not invent progress, token counts or
completed jobs. Imported reports are declarations; file integrity against the raw
corpus is checked by the local Python tools, not by this browser view.
Data stays in page memory until exported, not in a shared database. Closing the
page loses the imported view. A persistent local job queue has since been added;
see HYD_CORPUS_QUEUE.md. The remote Lovable queue/agent bridge remains pending.
The tab also imports individual hyd-corpus-download-result/1 manifests, displays
actual recorded bytes and hashes, and exports the collection of imported results.
It never presents those imports as live job monitoring or training approval.

The source catalogue includes Wikipedia, OPUS/OpenSubtitles, BOE, Congreso,
El País, El Mundo, RTVE, Gutenberg and Cervantes. Every source is initially pending
review or permission. The proposed blanket assertion of compatible licences is
not adopted:

- [Wikimedia terms](https://foundation.wikimedia.org/wiki/Policy%3ATerms_of_Use/en)
  specify CC BY-SA text conditions. This requires review against the project's
  existing no-share-alike corpus policy; no conclusion about trained-weight
  licensing is inferred here.
- [El País terms](https://elpais.com/info/aviso-legal/) reserve reuse rights and
  require authorization. An RSS feed does not supply that authorization.
- [Gutenberg's policy](https://www.gutenberg.org/policy/license.html) distinguishes
  US copyright status, local territory and individual copyrighted works. Review
  the specific work/edition/translation, rather than approving the entire site.
- The OpenSubtitles URL supplied in the proposal was not retrievable in the
  source check. No training permission is verified for that source. BOE,
  Congreso, RTVE and Cervantes also require actual document/source evidence.

The tab exports hyd-corpus-download-plan/1 with an exact HTTPS asset URL and a
1–1024 MiB byte cap. New plans explicitly set rights.verified=false and leave
licence/evidence empty; the user must review and document these declarations
before running them locally. Exporting a plan never starts a hidden download.

Local command: `python -m hyd_calibrator download-asset --plan PLAN.json --out NEW_DIR`.
The raw downloader validates the plan, exact configured official host, reviewed
rights declaration, licence policy and budget. Wikipedia/OpenSubtitles and the
permission-required newspapers are not enabled in that worker. No arbitrary
host, credentials in URLs, redirect-following or executable content is accepted.
It records the raw file hash, actual received bytes and original reviewed plan
hash. Downloads remain training_allowed=false. A failure leaves failed.json and
possibly a partial asset, never a completed manifest. Resume is not implemented;
retry in a new directory. No new external download was launched in this delivery.

## Review of the proposed modules

Folder organization is useful: use corpus/raw/<source>/<job>/ for assets and
metadata, then separate derived cleaned/dedup/tokenized directories with manifests.
Preserve original text and source evidence. Never run the proposed HTML regex
cleaner on human calibration questions or code/math: it can delete meaningful
text, and whitespace rewriting would break annotation hashes. Use format-aware
extractors only in derived pretraining data.

The proposed Rust fragment is a function, not a complete standalone rustc CLI,
and its blake3 crate needs a package dependency. The current streaming Python
snapshot already preserves provenance and does not load the entire corpus in RAM.
No Rust compilation or new toolchain is needed for this delivery.

HYDRA Base currently has a 32,000-piece tokenizer. Switching to the proposed
64,000 vocabulary changes the model/tokenizer contract and cannot be applied to
the existing checkpoint. Count and tokenize with the exact recorded tokenizer;
train a new tokenizer only as a separate architecture stage. An RTVE JSON API
also needs a JSON adapter, not an RSS parser. Avoid blind recursive wget crawls:
the implemented worker downloads one reviewed, bounded asset per plan.

## Real candidate preparation completed

The frozen 102-file acquisition inventory produced 115,971 first complete
candidates, 4,073 candidate duplicates and 51,156 review records (171,200 total).
Reasons overlap: 51,154 missing origin URLs, 1,743 unversioned licence declarations
and 6 texts with replacement characters. Source originals are intact. The
snapshot is local at .codex-artifacts/acquisition-candidate-snapshot-20261004.
All buckets retain original data and provenance; none is approved for training.
Its manifest is committed as evidence/acquisition-candidate-snapshot-20261004.json;
the corpus itself is not uploaded to GitHub.

The incremental app patch is integrations/evaluator-app/corpus-workspace.patch,
based on local app commit fee2543 (the annotation integration prerequisite).
It needs adaptation to the current exported Lovable source. No live app/database
change or remote downloader agent was deployed. The subsequent local queue
delivery adds authenticated submission and worker cancellation. Remote durable
storage, agent authentication, recovery and resume remain separate pending work.

Validation: 62 focused Python tests passed; 22 app tests passed; app TypeScript,
changed-file lint and client/server production build passed. Downloader tests use
an in-memory HTTP response fixture; no licensed-source download was claimed.
The authenticated /corpus UI has not been visually checked in a logged-in browser
and has not been applied to the live Lovable project.
