<!-- Copyright (c) 2026 Luis Manuel Cousido Hermida. All rights reserved. -->
# scripts/

Herramientas operativas y de investigación. **No forman parte del paquete** `hydra` (no van en el wheel):
el código reutilizable vive en `hydra/`, y los scripts solo lo orquestan. Se ejecutan desde la raíz del
repositorio (`python -m scripts.<nombre>` o `python scripts/<nombre>.py`; los `.ps1` en PowerShell y los
`.sh` en bash).

Descripción tomada del docstring o de la cabecera de cada fichero.

| Script | Propósito |
|---|---|
| `audit_human_review_export.py` | Audit an exported review without modifying human decisions or frozen test data. |
| `audit_instruction_candidate.py` | Hash-bound local audit of 1.5B weights, curriculum and previous evaluation evidence. |
| `audit_training_program.py` *(sin versionar)* | Audit completeness against the agreed program; pilot integrity is not readiness. |
| `autobuild.sh` | AutoBuilder: benchmark runtime candidates on this machine and apply the winner to .env. |
| `bootstrap_3060ti.sh` | HYDRA workstation bootstrap (Linux): detect GPU -> build llama.cpp for its CUDA arch -> install HYDRA. |
| `bootstrap_windows.ps1` | HYDRA workstation bootstrap (Windows): venv + HYDRA + llama.cpp built for the local CUDA arch. |
| `build_gguf.sh` | HF/safetensors -> GGUF BF16 -> importance matrix (optional) -> llama-quantize (via the Model Factory DAG). |
| `build_hydra_local.ps1` | Keep the lock open: a concurrent invocation must not write to the same partial weights. |
| `calibrate_training_program.py` *(sin versionar)* | Fit classifier temperature on an explicitly reserved, artifact-bound split. |
| `check_instruction_certification.py` | Report eligibility; never deploy, promote or rewrite a model manifest. |
| `check_supplied_contamination.py` | Read HYDRA JSON/JSONL formats and report overlap without deleting source rows. |
| `check_training_program_release.py` *(sin versionar)* | Check evidence completeness; never deploy or approve automatically. |
| `collect_vllm_candidate_scores.py` | Run under a supported Linux/WSL vLLM environment. Does not install vLLM. |
| `compare_supplied_finetuning.py` | Identified raw GGUF inference with conservative scoring and separate human review. |
| `evaluate_external_holdout.py` | Real raw GGUF answers for user review; external cases are never training data. |
| `evaluate_program_direct.py` *(sin versionar)* | Record raw llama.cpp generations on known regressions and synthetic web fixtures. |
| `export_kev_reliability_patch.py` | Keep the ignored experimental Kev changes reproducible inside HYDRA. |
| `prepare_hydra.ps1` | Descarga reanudable y verificada por hash de la base y las herramientas de `config/recipes/hydra-pilot.json`. |
| `prepare_kev_cuda.ps1` | Prepara el entorno CUDA aislado de Kev (`runtime/kev-env`) con la wheel de torch fijada por hash. |
| `prepare_kev_reliability_fork.py` | Recreate the reviewed Kev fork from its pinned checkout and tracked patch. |
| `prepare_supplied_finetuning.py` | Import the audited package into a separate, reproducible v8 candidate. |
| `prepare_training_program_pilot.py` *(sin versionar)* | Preserve v8 regression/replay and append the explicitly synthetic web pilot. |
| `probe_proposed_evaluation.py` | Preserve review data and probe supplied questions without inventing human votes. |
| `query_kev_hydra_candidate.py` | Demonstrate Kev's typed decision plus HYDRA's actual generated response. |
| `register_instruction_candidate.py` | Import a completed candidate under a new alias without replacing deployed models. |
| `repair_web_pilot_encoding.py` *(sin versionar)* | Make an audited new copy of the synthetic fixtures; never mutate trained inputs. |
| `requirements-training.txt` | Use with the CUDA-enabled torch 2.5.1 installation; tested imports recorded in docs. |
| `revalidate_instruction_release.py` | Fresh versioned release assessment. Never overwrites reference evidence or promotes. |
| `run_api.sh` | Arranca la API runtime standalone; exige token si escucha fuera de loopback. |
| `run_studio_candidate.py` | Isolated Studio for the trained 1.5B GGUF and calibrated Kev shadow. |
| `run_studio_validated.py` | Local Studio using the current source and a calibrated shadow classifier. |
| `serve_kev_candidate.py` | Serve an explicitly selected completed local Kev experiment on CUDA. |
| `start_hydra.ps1` | Sirve un candidato HYDRA.gguf construido (comprueba `build-manifest.json`). |
| `start_hydra_direct.ps1` | Arranca llama-server CUDA fijado (b11146) con el GGUF v8 verificado por hash; con `-GroundedSpecialist` también el v5 (especialista con fuente) en 18092. |
| `start_kev_local.ps1` | Arranca Kev local desde el checkout aislado y la revisión fijada. |
| `start_llama_server.sh` | Start llama-server with the profile chosen by the AutoBuilder (.env) and HYDRA's gateway on top. |
| `train_instruction_v2_when_free.py` | Wait for free GPU memory, then run the pinned build without stopping other services. |
| `train_kev_hydra_v2_when_free.py` | Sequential CUDA training of a separate Kev candidate; no deployment or promotion. |
| `train_kev_windows.py` | Run upstream Kev training on Windows with an explicit RSS telemetry adapter. |
| `validate_hydra_direct.py` | Record real direct-runtime responses; never promote based on this smoke test. |
| `validate_instruction_stability.py` | Bounded 15-minute real GPU soak: no cache, identified GGUF, health and VRAM snapshots. |
| `validate_instruction_v4.py` | Compare GGUF candidate with deployed baseline; never promotes either model. |
| `validate_json_contract_live.py` | Uncached end-to-end JSON calls; expected answers are used only after inference. |
| `validate_kev_training_parity.py` | Tiny deterministic GPU check: the reliability patch must not alter SFT math. |
| `validate_public_web.py` | Prueba en vivo de las herramientas `web.search`/`web.read` y guarda la evidencia. |
| `validate_vision_gguf_local.py` | Real local smoke probes; these do not constitute a promotion benchmark. |
| `validate_web_chat.py` | Prueba en vivo del chat con contexto web contra un gateway en marcha. |
