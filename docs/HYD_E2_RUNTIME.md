# Reloadable E2 shadow artifact

New E2 runs emit runtime.json alongside head.npz and report.json. The manifest
binds the encoder identifier/revision, normalization, ten-route criteria, input
partition hashes and SHA-256 hashes of head and report. Checksums detect content
changes relative to the manifest; they are not a signature or proof of origin.
Legacy heads without this manifest are intentionally unsupported by the loader.

`E2Runtime(Path(RUN)).predict([question])` lazily loads the pinned CPU encoder.
It validates head dimensions, finite parameters and normalized embeddings, then
returns probabilities, a label and an accepted flag. An unaccepted label remains
available for diagnostics; consumers must check accepted. Every result retains
SHADOW_ONLY and authority=false; this does not connect E2 to production routing.
Sentence-transformers remains an optional runtime dependency. This delivery did
not install it, download an encoder, or alter the active training environment.

The training script reloads the saved head, compares probability and acceptance
parity against the evaluation using existing test embeddings, and writes
runtime-parity.json only when those checks pass. A parity failure leaves the run
for diagnosis and raises an error; it does not promote it.
encoder_reload_verified=false explicitly distinguishes that check from complete
encoder reload, which still requires the real pinned model and dependency setup.

Local tests use artificial numeric fixtures only. They verify reload parity,
abstain_all, integrity rejection, invalid embeddings and shadow authority.
No real-corpus inference or new precision claim has been made. Before promotion:
verify full encoder reload and dependency versions, compare original/reloaded
embeddings and predictions on an immutable evaluation, and retain the evidence.
Next plan step is explicit adjudication and E3 evaluation of risk/context labels.
