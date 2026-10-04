<!-- Copyright (c) 2026 Luis Manuel Cousido Hermida. All rights reserved. -->

# Persistent local Corpus queue

The offline app now includes authenticated list/create/cancel server functions
and a queue panel in /corpus. This implementation targets a local Node server
with durable shared filesystem storage. It is not a cloud database queue and
must not be configured on an ephemeral/serverless deployment as if it were one.
The next Lovable deployment needs a remote storage/queue adapter and worker
authentication; that bridge is not claimed in this delivery.

## Local operation

Configure HYD_CORPUS_QUEUE_DIR on the app server to an absolute persistent directory,
for example D:/HYDRA/runtime/corpus-download-queue. The example env file leaves it
empty; no real environment was altered. Empty configuration disables job creation
visibly, while portable plan export remains available. Source/rights review is
still required before a job can be queued.

The app server and worker must have access to that same protected directory.
After an authenticated user submits a reviewed plan, run (one shell line):
`python -m hyd_calibrator run-download-queue --root D:/HYDRA/runtime/corpus-download-queue --max-jobs 10`.
This processes one bounded batch and exits. It does not install or schedule a
background service, buy credits, provision storage or launch new real downloads
automatically. Keep the storage accessible only to trusted app/worker processes.

## Protocol and behavior

Each job is under a SHA-256 account namespace and a server-generated UUID.
The namespace is derived from the authenticated middleware context, never browser
input. List/cancel operations remain in that namespace. Pending directories are
published by rename after plan/request/queued files are complete, avoiding reads
of half-created jobs. The request binds the SHA-256 of the serialized plan.
No bearer token, service key or raw account email is written into jobs.

The worker atomically claims the queued marker by rename, checks namespace/job
identity and plan integrity, then runs the existing bounded raw downloader.
Successful results record actual bytes, file hash and the reviewed declaration;
failed and cancelled jobs get durable result.json states. A second run does not
repeat completed jobs. Original plans and results remain available after reload.
All downloads remain training_allowed=false. Rights are user-reviewed declarations,
not verified authorship or a legal adjudication.

Cancellation writes a durable request marker. Queued cancellation stops before
network access; active cancellation is checked between reads. It cannot instantly
interrupt a blocked network read (the per-operation timeout is 30 seconds).
A completion racing with cancellation may still finish. Partial downloads stay
unapproved; no successful asset manifest is produced by cancelled transfer.

The panel refreshes active job states every 10 seconds and permits manual refresh,
per-account cancellation and result export. It does not invent percentage progress.
A running marker is a claim, not a live-worker heartbeat. If the worker crashes,
the job stays claimed; automatic retry/resume and stale-worker recovery are not
implemented. Inspect the interrupted job before creating a separate retry; do
not delete or replay a running marker while another worker may still own it.
The app limits submission to 20 outstanding/500 total jobs per account; these are
application admission checks, not a transactional multi-server quota.

## Evidence and remaining integration

66 focused Python tests and 24 app tests passed, along with app types, changed-file
lint and client/server production build. Tests cover namespace isolation,
cross-account cancellation rejection, durable job files, plan validation, changed
plan rejection, single claim and cancellation before/during transfer.
An additional Bun-to-Python bridge check persisted an app-created request and
consumed it once in Python, using an HTTP fixture. Evidence is in
evidence/corpus-queue-bridge-20261004.json. No live OAuth, remote worker, real
source download or deployed Lovable integration was tested or claimed.

The incremental patch integrations/evaluator-app/corpus-queue.patch is based on
local app commit 6842c9e (Corpus workspace prerequisite). Adapt it against the
current exported Lovable source; do not blindly apply the offline baseline.
Next work is a remote durable queue adapter, authenticated agent access, heartbeat,
explicit recovery/resume, storage quotas and browser verification before deployment.
