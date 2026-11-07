# Source export / 导出说明

Snapshot of the existing local, non-git reason_jinja_codegen project. This is a source snapshot, not a claim that all recent validation jobs completed. The runtime-finish job 20261108-031834-6818b06 ended at 2026-11-08 03:39:43 JST; expert-system-batch2b 20261108-032247-698af16 was cancelled at 03:24:09 JST. A separate validation/check orchestrator was still running when the snapshot was prepared; it was not stopped. Selected source files were checked for active writers and compared by SHA256 before/after capture. Caches and check outputs are excluded.

## Contents
- Python engine, rule/code-generation/growth tools, standalone local chat HTML/JS/server/worker, related tests and documentation.
- packs/ contains rule packs, templates, algorithm-library code/metadata and synthetic stored regression problems.
- examples/ contains synthetic examples.
- evolution_library/versions contains only the two existing published public algorithm definitions (ascending bubble sort and per-element printing) plus finite independent validation summaries. Source prompts, session data, stage logs, timestamps and pending/limited candidates are not exported. Finite tests are not mathematical proofs. No algorithms or user input were executed to prepare this export.

## Dependencies and running
The local project uses Python 3.13.5; this export does not establish a minimum supported Python version. Create a fresh venv and install requirements.txt (Jinja2==3.1.6); use the existing README for CLI usage. Model-backed workflows also require an independently installed/authenticated Claude CLI and access to the configured haiku/sonnet models; credentials and global CLI configuration are intentionally absent. No credentials are needed merely to inspect rules/source.

Safe evolution requires Linux bubblewrap (bwrap), working unprivileged user/pid/network namespaces, prlimit and /usr/bin/python3, plus standard runtime paths used by evolution.py. A locked-down host or cloud environment may not support the sandbox; fail closed, never replace it with host execution. Some legacy offline growth/evaluation tools can execute candidate code; do not invoke these as an automatic import step. Tests can run code and cost/large regression suites may take a long time; model-backed commands can incur charges. Importing this archive must not start services, growth or real-model tests automatically.

Standalone chat.py serves the project's independent lightweight local chat (consult --help/README); do not expose it publicly without separate authentication. /workspace/webchat is a separate authenticated service and is NOT included. Its server model registration, event-stream adapter, persistence/authentication and frontend integration are external dependencies, not supplied by this archive. Existing absolute /workspace/reason_jinja_codegen paths in the source/tests may need adaptation after import; do not import the host's authentication, process/session data or relay settings.

## Excluded / initialization
No .env, authentication configs, key material, venv, caches, logs, pid/lock files, backup trees, generated outputs, report runs/profiles, user chat history, candidate prompts, pending queue or limited-draft history. reports/ is intentionally omitted; historical performance claims in original docs must not be treated as freshly verified results. benchmark_results.json and exercise_results.json are omitted as run data. Evolution runtime directories/lock are created by the current application as needed; missing user-specific learned drafts/history is expected. The sanitized versions can be revalidated in the required sandbox before deployment, never by executing candidates on the host.

## Repository import
Destination requested: https://github.com/phoenix-phi0/dsl_structure_v2.git . This export did not clone, initialize, commit, push or change that repository. The importing cloud agent must preserve existing remote work, inspect differences and use an ordinary branch/PR; do not force-push. Review the source and environment assumptions before running anything.

## Import adjustments after this snapshot
The confirmed import destination is https://github.com/phoenix-phi0/reason_jinja_codegen (not the earlier `dsl_structure_v2` URL above). The archive itself was not rewritten. After verifying the archive, these portable/public-safety edits were applied on the import branch only:

- `README.md` and `EXERCISES.md`: replace `cd /workspace/reason_jinja_codegen` with repository-root instructions. `README.md` also states that this tree is the 2026-11-08 03:42:51 JST snapshot and is not a claim that later batch work or a full acceptance run finished.
- `.gitignore`: also ignore virtualenvs, caches, secrets, generated outputs, logs, backups, evaluation run files, and evolution `candidates/` / `limited/` / `request.lock`. Published `evolution_library/versions/` stays tracked.

`EXPORT_MANIFEST.json` keeps `original_source_hashes` for the captured bytes. Its `files` entries for the three paths above match the imported tree. No algorithms were rewritten, and candidate execution still goes through the bwrap sandbox.
