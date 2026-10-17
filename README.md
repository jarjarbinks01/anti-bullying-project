# Study 2 dashboard and research pipeline

Local Python / SQLite pipeline and Streamlit dashboard for the HKU anti-bullying Study 2 panel. It links responses about the same child, identifies the same adult across waves, selects eligible T0 / T1 responses, and supports controlled human review.

**This repository contains code, generic documentation, synthetic tests and a blank Excel layout. Research data stays local.** No participant responses, databases, filled review cards, source manifests, published results, screenshots or machine-specific settings are included.

## Install

Requires Python 3.12 or later. Run inside this repository:

```sh
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.lock.txt
.venv/bin/python -m pip install --no-deps -e .
git config core.hooksPath .githooks
```

Keep the checkout and live database outside folders that synchronize active files. On a Mac with a synchronized checkout, put the Python environment in a separate local runtime folder and link it as `.venv` instead. Data storage and source registration are separate from code installation.

## Connect private local data

The current input boundary is the four already-merged A / B / C / D workbooks from stage 2.1.2. Upstream paper-form and online collection continue separately. The pipeline does not automatically repeat upstream merging, send coupons or provide remote login.

On the existing research computer, keep `config.local.json` / `config.merged.json` and the existing SQLite state. **Do not initialize again or replace the source registry.** Both local configurations are ignored by Git. The Mac launchers continue to use the local configuration.

For a new research computer, obtain the private source workbooks, existing upstream scripts and school dictionary through the team's approved local transfer process. Initialize a fresh local workspace:

```sh
.venv/bin/python -m study2 init --source-scope merged_abcd --project '/path/to/private-study2-project' --state '/path/to/private-local-state'
```

`init` registers source columns, pins mapping versions, copies the local dictionary and refuses to overwrite existing settings or state. `config.example.json` documents the configuration shape with placeholder paths and empty column registries; it is not a ready-to-run source registration. Use initialization or a verified local configuration to register actual inputs.

## Run

```sh
.venv/bin/python -m study2 manifest
.venv/bin/python -m study2 watch
.venv/bin/python -m study2 dashboard
```

The dashboard opens at `http://127.0.0.1:8501` and reads only the published release. The CLI also supports validation, unpublished trial runs, controlled corrections, review-card export / receipt / approval, publication, rollback and backup restoration. Run `.venv/bin/python -m study2 --help` for the commands.

## Research rules and review

- [Matching, pairing and time rules](docs/MATCHING_RULES.md)
- [Code map and first reading path](docs/CODE_READING_GUIDE.md)
- [Stage purposes, inputs and outputs](docs/STAGES.md)
- [Data model and stable identifiers](docs/DATA_MODEL.md)
- [Reviewer instructions](docs/REVIEW_CARDS_COLLEAGUES.md)
- [Operator approval and application workflow](docs/REVIEW_CARDS_OPERATIONS.md)
- [Permanent child-family IDs, invitations and recovery](docs/DYAD_TRACKING_OPERATIONS.md)

The dashboard separates final sample counts from candidate comparisons. Program checks and synthetic tests verify implementation; they do not establish the accuracy of all real-world matches.

## Storage maintenance and recovery

New workspaces store processed record values once and retain per-run references. Review packages retain ordered task references and complete shared evidence components. Historical IDs, answers and scientific runs remain readable through the legacy interfaces.

The compact storage adapter also shares unchanged record projections, candidate payloads and family membership payloads. It preserves every per-run association and reconstructs the original SQL interfaces. Candidate exports use stable case ordering; final sample worksheet ordering remains unchanged.

```sh
.venv/bin/python -m study2 storage-report
.venv/bin/python -m study2 storage-migrate --destination /path/to/new-private-state
.venv/bin/python -m study2 checkpoint
.venv/bin/python -m study2 checkpoint-restore /path/to/CHECKPOINT --destination /path/to/new-private-state
.venv/bin/python -m study2 storage-gc
```

Migration builds and verifies a private copy. It does not activate that copy. Activation requires preservation and rule-compatibility proofs, a verified portable checkpoint, stopped clients and a durable journal for both databases. Interrupted activation restores the original pair before either database opens.

The checkpoint policy `{"latest_complete_only": true}` keeps one latest verified complete checkpoint. A replacement is recovered and checked before the previous checkpoint is removed. It contains main data, review history, administrative state, configuration, code and required source assets. Plain SQLite and gzip legacy archives remain supported when their files are retained. A pruned historical release still has scientific outputs but no standalone disaster-recovery file.

Checkpoint freshness uses the same asset inventory as capture, including the dashboard, dependency files, review template and retained release assets. Asset changes during capture reject the replacement. The administrative ledger is updated before deleting any recovery copy it may reference; retrying an unchanged checkpoint finishes interrupted retention cleanup. Private migration retries inspect persisted tables and views before trusting a schema version marker.

This policy also replaces older full review and administrative backup copies. Their history remains in the live databases and latest complete checkpoint. Retention receipts remain at the old paths. An unchanged main or review archive is reused during checkpoint replacement, and unchanged operations reuse the whole checkpoint. `dyad-backup` uses the complete checkpoint under this policy.

Use the path in the private state's `CURRENT_CHECKPOINT.json` for recovery. Restore into a new directory, then use its `config.restored.json`. Its `code` directory contains the saved implementation and mappings, and its `source_project` contains the exact input files. Install the saved dependencies in a separate environment and run from the restored `code` directory. Validate the current release and administrative history before redirecting operators or the scheduler to that configuration. Do not initialise a source registry during recovery.

`validate` checks retained scientific outputs, including the logical content of compressed legacy audit files. `rollback` changes the published scientific release and retains administrative history; source/rule and review safeguards still apply. `checkpoint-restore` recovers the complete main/review pair and the newer administrative overlay. A `backup.retention.json` or review retention receipt identifies a removed physical recovery copy. Use the latest complete checkpoint when that old copy is unavailable.

An operation can commit successfully while checkpoint creation fails, for example when the disk fills. Its result includes `checkpoint_warning` and the state has `CHECKPOINT_PENDING.json`. Retry `checkpoint` after resolving the cause. The previous verified checkpoint is retained throughout the failure. Storage format migration alone does not publish a new scientific release.

`storage-gc` is a dry run. Add `--apply` to remove only objects outside all retained run, source-version, package, task and checkpoint references. Neither mode deletes research records. Keep active databases and temporary recovery files outside synchronized folders. Storage reports identify cloud placeholders through metadata without downloading them.

## Develop and push safely

```sh
.venv/bin/python -m pytest tests
git add dashboard.py study2 tests
python3 tools/repository_guard.py --staged
git commit -m 'Describe the code change'
git push origin main
```

The ignore file uses an allowlist. The local hooks check the entire staged tree and the history being pushed. The guard rejects unapproved paths, data formats, real-record identifiers, user-specific paths and common credential patterns. The one workbook exception is a hash-pinned blank style template needed for review-card export.

Hooks are enabled for the initial local checkout. New clones must run `git config core.hooksPath .githooks`. An ignored file must not be forced into Git. Put new code or generic documents on the reviewed allowlist; do not add data exceptions.

See [repository and local-data boundaries](docs/REPOSITORY.md) for the included files and verification procedure. Existing private reports and review history remain local and are not removed by repository initialization.
