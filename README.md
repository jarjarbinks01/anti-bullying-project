# Study 2 dashboard and research pipeline

Local Python / SQLite pipeline and Streamlit dashboard for the HKU anti-bullying Study 2 panel. It links responses about the same child, identifies the same adult across waves, selects eligible T0 / T1 responses, and supports controlled human review.

The [descriptive analysis guide](docs/DESCRIPTIVE_ANALYSIS.md) explains the four analysis cohorts, T0/T1 comparisons, demographic tables, denominators and versioned 4.1 Excel reports.

**This repository contains code, generic documentation, synthetic tests and a blank Excel layout. Research data stays local.** No participant responses, databases, filled review cards, source manifests, published results, screenshots or machine-specific settings are included.

## Static dashboard for Vercel

After publishing a validated research release, run:

```sh
./.venv/bin/python -m study2 static-export
```

Alternatively, open `Export Static Dashboard.command`. The exporter reads the
current published release without writing the research databases. It creates
`static_dashboard/`, which is ignored by Git. Open its `index.html` to preview
locally. HTML, CSS, JavaScript and the aggregate snapshot are self-contained;
the research calculations and databases remain local. Web deployment now adds
Vercel Routing Middleware and a small authentication Function. A plain static
HTTP server does not enforce the access gate.

Deploy **only this generated directory**, never the research checkout:

```sh
cd static_dashboard
npx vercel
```

Use the **Other** framework preset, Node 24.x, `npm ci --ignore-scripts` for
installation, `npm run build` for the build and `public` as output.
`vercel.json` supplies these settings. Set `STUDY2_ACCESS_PASSWORD` (12–256
characters) and `STUDY2_SESSION_SECRET` (at least 32 random characters) as
server-only environment variables for Production and Preview before deployment.
Neither value is stored in the export or browser. Missing configuration fails
closed. The shared login lasts eight hours and includes logout. All routes,
including the snapshot and JSON files, pass through the access check.
The build copies only allowlisted browser assets into `public`; server code
stays outside that output directory. Deploy the entire generated project,
including its middleware and API, rather than the `public` subfolder alone.

Read the generated [deployment guide](static_dashboard/DEPLOYMENT.md) for
account linking, secret setup, preview checks, production deployment and updates.
Use `npx vercel --prod` when ready for a production deployment. A separate static
repository can be created from this directory if Git-based deployment is wanted;
the research repository intentionally does not track generated research outputs.
Publishing a new pipeline release does not update the website: export again and
redeploy. A local `.vercel` project association survives repeat exports.

The static version preserves the six navigation tabs, published sample counts,
stage purposes, source counts, formal descriptive cohorts, independent-parent
cohorts, mean/SD and categorical tables, paired changes, scale histograms and
calendar-month trends. Statistics reuse the existing shared calculation layer.
Available filters are role, cohort, mainstream/all schools, nine child groups and
one source. Histograms cover all sources; monthly trends cover the all-group,
all-source view and offer optional accepted batch dates. Month controls select
whole precomputed periods, not arbitrary daily ranges. Per-school and identity
rule filters, record-level evidence, invitation histories and review writes stay
in the local application. Aggregate CSV downloads describe the current view.

The static interface keeps sample filters in a separate analysis sidebar and
shows the selected cohort, wave counts and analysis basis above the results.
Research overviews offer grouped PHQ/FQOL/SEC/bullying comparison tables,
distributions and mean-score charts as separate views. Paired comparisons keep
formal and valid pair counts distinct. The homepage groups processing stages
by purpose and labels their units; differences between imported and selected
responses are not treated as invalid submissions. These layouts are part of
the export template and survive future exports.

Continuous scale tables also show a two-sided paired t-test, Cohen's dz
(mean individual T1 minus T0 change divided by its sample SD) and the actual
complete-pair N. These are unadjusted exploratory comparisons, not tests on
the difference between the displayed each-wave means. Each-wave overviews use
only exact submission/version intersections with formal AC/BD or EF membership;
both responses must pass the displayed filters. Parent PHQ still requires
confirmed adult continuity. Categorical outcomes do not receive t-tests.
Zero difference variance and insufficient pairs retain their descriptive values
without inventing a p-value or finite effect size. Missing counts remain in
the audit details and CSV rather than the main comparison table.

The period view combines the selected complete months into two points, T0 and
T1. Means are weighted by valid N; SD combines within-month and between-month
variation from the full-precision published summaries. The researcher export
does not suppress small aggregate cells or merge rare histogram bins. The
period view defaults to the full date range and includes every selected month,
including months with fewer than ten responses. Missing scores remain missing;
an undefined SD, p-value or effect size is not replaced with zero. The
two-point view compares responses within the selected period;
it does not imply individual change or supply a paired test. Monthly audit
details remain available. The y-axis offers full scale and labelled auto-zoom.
The comparison implementation is identified by `paired_t_dz_v1` in the snapshot.
Methods: [SciPy paired t-test](https://docs.scipy.org/doc/scipy/reference/generated/scipy.stats.ttest_rel.html)
and [Lakens on effect sizes for paired designs](https://doi.org/10.3389/fpsyg.2013.00863).

Only explicitly allowed aggregate fields reach the output. No submissions,
child/family IDs, schools, contacts, birthdays, local paths, source filenames,
raw answers or filled review packages are copied. The researcher version keeps
small aggregate counts and categories, and quality missing counts remain
visible. Histograms use fixed public scale bounds and common T0/T1 boundaries;
personal extremes and free-text missing-reason detail are excluded. Everything in a deployed
snapshot is downloadable by authenticated researchers. The server gate controls
new web requests; noindex and browser security headers alone are not authentication.

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
- [Independent parent panels and dashboard](docs/INDEPENDENT_PARENT_ANALYSIS.md)
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
