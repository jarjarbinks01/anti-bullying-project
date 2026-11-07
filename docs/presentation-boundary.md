# Portable presentation boundary

`study2.static_export` is the single dashboard exporter. The normal CLI defaults
to analytical exclusions ON and selected-child B/D projection. ON requires a
validated current release context and accepted exclusion manifest. Legacy callers
of the Python API retain explicit opt-in parameters; the CLI can explicitly use
`--default-eligibility off --no-project-selected-bd` for a legacy export.

Native processing, matching, storage and scientific reporting remain in `study2`.
No older runner, store or matching implementation is loaded for presentation.
`study2.presentation` contains only the boundary that differs:

- `descriptives`: compatibility reexports of native cohorts, statistics and
  inference, with no duplicated calculation or validation. The native cohort
  validates explicit selected-child B/D adult-continuity metadata and preserves
  historical formal same-adult artifacts when that metadata is absent. A shared
  child is never evidence of a shared responding adult.
- `descriptive_spec`: one dashboard mode label over native definitions.
- `analysis_eligibility`: draft-scoped candidate validation and projections.
  Native accepted-manifest validation is not relaxed or monkey-patched.
- `assets`: readable accepted selected-child JavaScript and CSS. Assembly has one
  source instead of silently overriding a discarded legacy client. Exact accepted
  HTML, assembled JS and CSS hashes are covered by synthetic tests.

`study2.manual_exclusion_export` owns dashboard-only ON/OFF projection and validation.
Other unchanged helpers are ordinary imports from native modules. Semester/lazy
payloads, selected-child scope, controls, and access packaging are retained.

## Read-only controls capture

`python -m study2 controls-capture --code-revision` returns a deterministic hash
of the installed package's Python, JavaScript (including the protected launcher) and CSS sources, including nested
presentation assets. Paths and bytecode caches are excluded. Record this hash
only after reviewing the intended installed version; it is an integrity pin, not
an approval. Source changes require a newly reviewed pin.

A private request JSON must have exactly these fields:

- `code_revision`: that reviewed installed-code inventory hash.
- `config`: `{ "path": "...", "sha256": "..." }`, pinning the runtime config.
- `selection`: the same pin shape for the existing authorized launcher selector.
- `context`: the same pin shape for the validated current release context.
- `candidate`: null, or the same pin shape for a local review candidate.

Pass a pin for that request file as `--controls-request` to static export. To
capture aggregates directly, use `python -m study2 --config /path/to/private/config.json controls-capture` followed by
the JSON-encoded request pin. The public entry initializes any configured historical trust first and requires the request to name that same configuration. `--prepare-current-context` requires both `context`
and `candidate` to be null and returns context plus a manifest pin, not participant
rows. Consumers must save private output only to a private local destination.

The config must identify the existing `state_dir`. Capture requires the existing
regular `writer.lock`, managed flag binding, active group policy, published
release and matching current review-workload evidence. It validates the pinned
selector, config/state correspondence, active exclusions, control revisions and
candidate freshness before deriving aggregates. Missing or stale evidence fails
closed. No selector, database, approval or deployment is modified. Temporary
process environment bindings are restored even on failure. No external frozen
code directory or machine-specific import path is needed.

This consolidation has synthetic coverage only. It does not regenerate or
validate any participant snapshot, activate controls, push, or deploy.

## Open the protected formal dashboard

`study2 dashboard` routes to `study2.formal_dashboard.main`. It does not fall back
to the historical Streamlit surface or serve an unapplied candidate. The ignored
runtime configuration needs `dashboard_preview` with:

- `config`: path/SHA-256 pin of the protected launcher's `preview-config.json`.
- Optional `launcher`: path/SHA-256 pin of an external reviewed protected Node launcher.
  By default, use the included `presentation/assets/local-preview.mjs` source.
- `code_revision`: reviewed installed-code inventory hash described above.
- `selection`: path/SHA-256 pin of the active launcher selector, unless the caller
  supplies the explicit activation path.
- Optional `node` executable (default `node`) and `site_root` containing the site.

The included launcher receives the pinned preview config through explicit
`--config`. A configured external legacy launcher must load `preview-config.json`
adjacent to its own file. The pinned preview config contains the absolute `site`, manifest hash,
port and secret-file path. The adapter never reads secret contents. It checks
current native controls, formal ON provenance, selected-child B/D policy, all
manifest assets and the installed-source/launcher pin before invoking the protected launcher's
credential check. An already running different preview is not stopped or replaced.
Use `study2 dashboard --check` to validate without starting a server. Configuration
and secrets must remain private and are not provisioned by this code consolidation.
