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
- [Stage purposes, inputs and outputs](docs/STAGES.md)
- [Data model and stable identifiers](docs/DATA_MODEL.md)
- [Reviewer instructions](docs/REVIEW_CARDS_COLLEAGUES.md)
- [Operator approval and application workflow](docs/REVIEW_CARDS_OPERATIONS.md)
- [Permanent child-family IDs, invitations and recovery](docs/DYAD_TRACKING_OPERATIONS.md)

The dashboard separates final sample counts from candidate comparisons. Program checks and synthetic tests verify implementation; they do not establish the accuracy of all real-world matches.

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
