# Static researcher dashboard

The local Python exporter packages one complete published release into the existing protected, buildless Vercel application. The first tab uses the accepted exact scope engine and presenter. The remaining five tabs keep their existing published aggregate calculations and independent controls. No research matching, wave selection, adult selection or scoring runs during export.

## Input and compatibility contract

The exporter opens SQLite read-only without recovery writes. It pins the current database publication, CURRENT.json, any release-location mapping, the database summary, legacy source-count aggregates and every file it reads. Files include summary.json, analysis.parquet, descriptive_measurements.parquet, records.jsonl.gz, the actual parent_longitudinal.parquet, optional scope_flow_evidence.json, dyad_tracking.parquet and all five independent_parent artifacts. Missing optional files are pinned as absent. Required missing files, stale pointers, incompatible evidence and input changes fail before completion and retain the previous owned export.

The exact index requires complete published compressed records. Aggregated source counts cannot establish membership. Missing complete records leave the first feature explicitly unavailable while valid legacy analyses remain usable. Missing formal parent evidence leaves BD unavailable and omits the formal parent longitudinal analysis. Ordinary parent responses and independent-parent evidence never replace formal BD.

The application retains study2_static_v1 ownership for safe updates of existing exports. A separate study2_static_scope_export_v1 sidecar carries the exact index and immutable revision. Missing or incompatible sidecars show an explicit feature-unavailable message. No approximate first-tab counts are generated. Positive minimum-cell suppression disables the exact index entirely; the export cannot claim suppression while shipping exact counts.

Optional persisted flow evidence must be a closed envelope containing format study2_published_scope_flow_v1, the exact release_id, records_sha256 for records.jsonl.gz and the accepted engine's evidence object. The evidence object retains its revision and rows unchanged. Unavailable checkpoints remain unavailable.

## Scope and school evidence

The first tab's sources, questionnaire versions and inclusive Hong Kong day bounds query fixed published slots. Search changes option visibility only. Empty selection means none, and select-all includes hidden catalogue options. Claimed waves and selected waves stay distinct. Navigating away destroys the presenter; returning restores its own scope without changing the descriptive or independent-parent controls.

The default exporter supplies no school projection. School evidence remains unavailable or not reconciled. An optional locally trusted public school binding is limited to one exact normalized selection and immutable index revision. The exporter validates the accepted R03 public shape, release and raw margins. It does not authenticate provenance from aggregate counts or discover private review state. The caller must already have validated the projection against its exact local membership. This synthetic host contract is not a general real-data binding or disclosure approval. No school query, private record evidence, decisions, dictionary names or invitation actions are shipped.

## Presentation and scientific wording

Six tabs appear in this order: Data quality & progress, Descriptive statistics, Independent parent analysis, Matching evidence, Family tracking, Definitions & methods. English chrome, charts, errors, login and human download labels are separated from stable machine keys and original questionnaire values. Original survey labels and categorical answer labels remain unchanged. Unconfirmed instrument names use PHQ, SEC or stable variable identifiers. Accepted translation proposals and items requiring codebook confirmation keep their original uncertainty; integration does not confirm them.

## Packaging and failure recovery

Export into a separate empty folder, or an exporter-owned complete folder. Unrelated files and symlink inputs are rejected. Each asset is written into a sibling staging directory, with hashes in snapshot-manifest.json. Input pins are checked after construction and around the backup/install renames. Failure restores the entire preceding export, including its local Vercel association. Do not replace only snapshot.js or public/.

The complete application contains index.html, app.js, styles.css, snapshot.js, scope-index.js, scope-engine.js, quality-ui.js, access/login assets, middleware.js, api/auth.js, server/access-core.js, build.mjs, deployment verification scripts, package pins and vercel.json. All snapshot/index assets pass through the original authentication gate. CSP uses self-hosted scripts; data responses remain private and no-store. Credentials and session signing material are server runtime values and must never be added to artifacts or browser payloads.

## Release gates

1. Review the frozen synthetic code and evidence. The existing independent reviewer and leader decide acceptance.
2. Prepare a later code-only PR using repository path/content guards and the exact accepted dependencies. Synthetic handoff data and local runtime evidence do not belong in that PR.
3. Obtain separate authorization for a pinned real-data export and disclosure review. Reconcile exact sample counts, source/date policies, labels, school evidence and profile disclosure against that release. Small aggregate profiles can expose sensitive differences even without identifiers. Synthetic checks do not establish anonymity.
4. Republish research only if underlying research data or approved decisions changed. Presentation integration alone does not require rematching or new permanent IDs.
5. Obtain separate deployment authorization. Verify the complete application input, protected routes and manifest before deployment. Deploy the whole protected export folder. Verify unauthenticated data blocking, login, charts, downloads, logout and expiry against the deployed result before reporting a formal URL.

R04 performs only synthetic local integration. It does not approve real-data acceptance, publication, deployment or grade changes.

## Arbitrary source subsets

This capability changes published aggregate selection only. It does not choose
surveys, score answers, modify the research database or authorize publication.

`static_sources.JS_SOURCE` defines `Source`, composed after `Grade` by the UI.
`Source.choose(snapshot, context)` returns the selected view with grades already
applied. Do not run `Grade.pool` again. Context includes mode, role, mainstream,
group, grades and sources. Returned source capabilities must control downloads
and plots as well as visible tables.

Sources are the five fixed codes legacy_online, paperform, qualtrics,
school_batch and socialworkdream. Their union uses OR. School, child-group and
grade restrictions intersect it. Groups overlap and must never be added.

An explicit `['all']` resets the source restriction; `[]` selects no responses.
An empty source array never reaches the existing research service's empty tuple,
which means unrestricted. Unknown source codes and mixed All selections fail
closed. Duplicate selections are rejected. Selection order is canonical and
inputs are not modified.

The new `snapshot.source_selection` header is separate from the unchanged
`snapshot.sources` first-page count tables. It pins format, release, report and
dictionary versions, the minimum-zero researcher profile, five codes and the
presence of unidentified source responses. When residuals exist, every scope
also contains an `unknown` singleton projection. Selecting only the five known
codes then excludes residuals; All includes them. Without residuals, all five
codes resolve to the exact original All view. Old snapshots have no new header:
their All and singleton selections still work, arbitrary unions are unavailable.

### Statistics and fixed membership

Each source's existing grade cube partitions its published responses. Wave
counts, category numerators and valid denominators are added only across those
disjoint source/grade cells. Continuous moments combine N, mean and M2 using
the between-cell correction:

M2 = sum(M2_cell + N_cell × (mean_cell − combined_mean)²).

Sample SD is sqrt(M2 / (N − 1)) for N greater than one. Missing values remain
missing. Empty moments have null means, zero M2 and null SD. Source means and
SDs are never directly averaged. Multiselect category counts retain the existing
valid-respondent denominator and may exceed 100% in total.

Baseline source anchors remain fixed for formal longitudinal samples, including
the actual dedicated BD submissions and EF student baseline. Per-wave EF source
still comes from the displayed respondent, while its child grouping uses the
student. Independent parent branches retain their own baseline anchors. The
source layer never re-pairs a baseline with a different adult or source version.

### Overview paired matrix

Overview source unions cannot add singleton pair rows: a T0 Paperform response
and a T1 Qualtrics response belongs to neither singleton's complete intersection.
Minimum-zero exports therefore add `source_pairs` only to the All view in each
overview scope. The matrix partitions existing exact formal submission/version
slots by both displayed source anchors, separately for every child group and
school scope. A union includes a cell only if both endpoints are selected.

Each group contains the existing continuous-scale schema, per-source matched
row count and confirmed-adult gate, and a complete source × source grid.
Each group also records `detail_variables`, the metrics with published score
columns. Original missing-column detail stays not_provided, with null state
fields. It is never recast as measured all-missing data.

Nonempty cells carry pair counts, four validity states and complete-pair
N/mean/M2 for T0, T1 and T1 minus T0. Zero cells have null vectors. Parent PHQ
vectors are null unless both endpoint source scopes are confirmed by the
existing adult-continuity rule before dropping dangling slots. A union requires
all selected nonempty matched source scopes to be confirmed. An empty selected
source cannot establish or remove adult continuity.

All pair cells reconcile to original All details and the diagonals reconcile
to original singleton details. An original singleton may retain a PHQ inference
row with zero complete pairs and absent exploration detail; that absence remains
intact. The matrix may still support a genuine cross-source complete union.

### Capabilities and compatibility

All and singleton selections preserve the original statistical and inferential
rows. Packed tables, distributions, transitions and nested monthly statistics
are decoded without numerical changes. Custom grade rules remain unchanged.

New source unions support wave summaries and formal pair summaries. Overview
pair summaries require the matrix and All grades. New union p-values and
Cohen's dz are unavailable; no browser inference is fitted. Source-filtered
histograms, transitions and periods are unavailable. Missing overview pair
evidence leaves valid wave summaries visible but removes the paired block.
Custom grades remove overview paired output. No unfiltered result is used as
a fallback.

The returned `source_status` is all, single, pooled, empty or unavailable.
`source_capabilities` separately names statistics, paired_summaries, inference,
distributions and monthly_trends. Empty has zero counts and no rows; unavailable
has null counts and no rows. Neither is an estimate or a suppression rule.
Positive-minimum legacy exports keep their original All/single behavior, and
cannot use new unions. This does not introduce small-sample masking into the
minimum-zero researcher export.

Validation checks shape, unique/completed partitions, finite moments,
availability counts, metadata, pins, All reconciliation and singleton diagonals
before client pooling. The new export contains no row identifiers or raw answers.
Scientific eligibility is never inferred from a label or a sample name.

### Integration

Compose Grade then Source; call Source.choose once; retain source_selection and
grade metadata in CSV. Respect capabilities rather than looking for a retained
grade cube on a pooled result. The pooled result intentionally carries only
selected aggregates. No authentication, research-policy or deployment changes
belong to this module. Use synthetic tests before regenerating a separately
authorized research export.

## Reversible manual flag exclusion

The optional exclusion setting is an analytical view of fixed published
membership. OFF is the default. ON removes accepted exact submission/version
keys without selecting another baseline, follow-up, adult or identity group.
An unflagged individual response remains in its original single-wave sample.
AC and BD require their own original two responses, E and F their own dyad,
and EF all four original responses. BD and independent-parent branches can
use different follow-ups and must retain their own membership.

Keep three counts separate: flagged review-file rows, distinct mapped
submission IDs, and removed analytical responses or composite units. Raw
intake and historical processing remain visible as reference facts. Active
excluded/retained intake and all nine sample deltas are separate aggregates.
Administrative tracking and identity decisions are not changed by this view.

Mapping is a private operator step. Accept only a reviewed manifest bound to
the exact release, complete inventory, content versions and explicit copy
policy. Missing, stale, ambiguous, conflicting or unaccepted evidence makes
ON unavailable; OFF remains usable. Questionnaire email may be stored under
`contact_03.1`; never infer missing email data from a missing literal `Email`
column or silently substitute a different review-file field. Do not propagate
flags through a shared contact, child ID, source profile or school.

The Python entry point is programmatic:

```python
from study2.static_export import export_static

result = export_static(
    cfg,
    destination,
    minimum=0,
    manual_manifest=accepted_manifest,
)
```

`cfg`, `destination` and the accepted private manifest are supplied by the
local operator. The static-export CLI has no new manifest flag. The weekly
flag tool below runs only when explicitly invoked by the operator.

For the local Streamlit dashboard, supply the accepted manifest's private path
through `STUDY2_MANUAL_EXCLUSION_MANIFEST`. Its session selector uses the same
core projection and prepares original cohorts before applying exclusions.
Existing filters retain their canonical options and grouping anchors. Invalid
requested ON blocks analysis while leaving OFF selectable. Without an explicit
manifest path the OFF adapter reads no manifest or raw-record inputs. Active
CSV, Excel and JSON downloads include eligibility and release metadata; fixed
original 4.1 workbooks are unavailable under ON.

Legacy parquet without a version column requires full agreement with the
same release's canonical data and provenance before its exact inventory versions
are attached in memory. Existing conflicting versions are rejected; published
files and source records are not rewritten.

The published sample catalogue also supports the supplementary same-child
parent cross-wave count. It is updated from its original B/D members and stays
separate from the nine primary sample deltas. Declared source and grade options
remain available when their active count becomes zero.

The exporter keeps the original OFF snapshot once and writes the optional
complete ON aggregates into authenticated `manual-exclusion.js`. The wrapper
binds both snapshots and scope indexes to the release and an opaque mapping
revision. It contains no private IDs, mapping entries, contacts, reasons or
source paths. Typed float and UTF16 revision hashing preserves Python/browser
agreement without rounding scientific values.

ON validation requires the complete original view catalogue and closed table
schemas, with immutable metric labels checked against trusted OFF. Recomputing
a content hash does not authorize extra fields or replacement labels. Original
questionnaire labels and the existing suppression policy remain unchanged.

Choose a complete validated bundle before applying existing filters and
Source/Grade calculations. Recompute statistics, complete-pair means/SD,
inference, distributions and periods from surviving native members. Preserve
the existing same-adult PHQ restrictions and unsupported source/grade cases.
Downloads identify the active exclusion mode and revision. Switching OFF
restores the original results without mutating the published data.

Deploy the complete protected export folder only after separate authorization.
The new aggregate asset follows the same middleware and no-store policy as
the other data assets. Local candidate validation is not publication or
deployment, and the exclusion setting does not modify live research state.

## Weekly manual flag ledger

Keep one private ledger outside the code checkout and research databases.
`python -m study2.manual_flags` previews and imports a review CSV, then exports
an accepted manifest for an explicitly named published release. A later CSV
adds evidence to the same ledger. Omitting an earlier row never clears its
flag. The tool does not run on a schedule.

The CSV projection is limited to `Email`, `Survey`, `建立時間`, `contact_01`,
`contact_02`, `student_demographics_06`, `contact_03.1`,
`adult_demographics_03` and `Review`. Each required header must occur once.
`Review` must contain the case-sensitive literal substring
`suspected fake case`; surrounding text is allowed. The seven match fields
exclude `Email` and `Review`. They use NFKC, trimming and integral
representation for native numeric values. Numeric-looking strings retain
leading zeros, `.0` and exponent spelling. Present blanks compare as blanks.
Email case, dates and telephone punctuation are not rewritten.
Multiple matching IDs require the explicit identical-copy policy, equal
roles and verified full raw-content hashes.

Strict mode requires all seven keys. Published merged questionnaires retain
different columns by role, so pass `--merged-role-structural-blanks` explicitly
on both preview and import. It permits only absent `contact_03.1` and
`adult_demographics_03` on student records, or absent
`student_demographics_06` on parent records, to contribute empty comparison
slots. Present values and full raw hashes remain unchanged. Missing common
or own-role keys remain unindexable; nonblank CSV values cannot match these
structural blanks. The projection choice is part of the batch fingerprint.

Run these commands with the project Python and integrated code checkout.
Replace every angle-bracket value with an operator-supplied local value.
Reports and manifests contain private IDs and must stay outside Git and the
online export.

Create the dedicated ledger once. Its parent must already exist; `init`
refuses an existing file, including an unrelated or empty SQLite file.

```bash
PYTHONPATH="<CODE_CHECKOUT>" "<PROJECT_PYTHON>" -m study2.manual_flags init \
  --registry "<PRIVATE_LEDGER>" --operator "<OPERATOR>"
```

An existing approved flag set can be preserved with `seed --registry ...
--manifest ... --release-folder ... --operator ... --reason ...`. Seed
validates the exact inventory and complete identical-copy sets. It cannot
silently restore a removed flag or approve a changed content version.

For each weekly batch, first preview the exact CSV against the exact
published release folder. That folder's `summary.json` and
`records.jsonl.gz` are the inputs; the tool does not consult CURRENT or a
research database. An explicit versioned inventory JSON is also supported
through `--inventory` instead of `--release-folder`.

```bash
PYTHONPATH="<CODE_CHECKOUT>" "<PROJECT_PYTHON>" -m study2.manual_flags preview \
  --csv "<WEEKLY_CSV>" --release-folder "<EXACT_RELEASE_FOLDER>" \
  --copy-policy all_byte_identical_copies --merged-role-structural-blanks \
  --report "<NEW_PRIVATE_PREVIEW>"

PYTHONPATH="<CODE_CHECKOUT>" "<PROJECT_PYTHON>" -m study2.manual_flags import \
  --registry "<PRIVATE_LEDGER>" --csv "<WEEKLY_CSV>" \
  --release-folder "<EXACT_RELEASE_FOLDER>" \
  --copy-policy all_byte_identical_copies --merged-role-structural-blanks \
  --expected-csv-sha256 "<CSV_SHA256_FROM_PREVIEW>" --operator "<OPERATOR>" \
  --report "<NEW_PRIVATE_IMPORT_REPORT>"

PYTHONPATH="<CODE_CHECKOUT>" "<PROJECT_PYTHON>" -m study2.manual_flags export \
  --registry "<PRIVATE_LEDGER>" --release-folder "<EXACT_RELEASE_FOLDER>" \
  --operator "<OPERATOR>" --output "<NEW_VERSIONED_PRIVATE_MANIFEST>" \
  --report "<NEW_PRIVATE_SNAPSHOT_REPORT>"
```

Inspect the preview and import reports. Valid mappings may enter the ledger
alongside unresolved observations, but unresolved or ambiguous evidence,
changed versions, missing active IDs and incomplete copy sets block accepted
manifest export. For `export`, exit 0 means accepted, 2 means blocked with no manifest
written, and 1 means an input or operation error. An earlier different output
file is never overwritten. A successful manifest supplies the same static
export API or Streamlit environment setting documented above.

Reimporting the same CSV/release/inventory/rule/policy creates no flags or
history. Repeating the same-state export preserves its approval, timestamp,
revision and bytes. Retain the ledger, immutable manifests and private reports
as the provenance for each analytical export.

If a new publication has no new review CSV, export the existing ledger against
that exact release. Unchanged permanent IDs and content versions carry
forward; changed or missing pins require explicit resolution before export.

Corrections require the registry path, operator and a nonblank reason:

| Command | Effect |
|---|---|
| `remove --submission-id ID` | Remove a flag with a persistent tombstone and history. A later CSV cannot reactivate it. |
| `restore --submission-id ID --release-folder ...` | Explicitly restore the exact current ID/version/content/role. |
| `rebind --submission-id ID --release-folder ...` | Approve a changed pin for an active flag; it cannot restore a removed flag. |
| `dismiss --observation-id ID` | Resolve pending CSV evidence without guessing an ID or removing a flag. |
| `ack-absent --submission-id ID --release-folder ...` | Explicitly omit an absent active flag for this release/inventory/content pin while retaining its global flag and history. |

Repeat the ID option for multiple IDs. Removing only one member of an
identical-copy set can still block export. A corrected CSV does not erase an
earlier unresolved observation. Use `status --registry ... --history --report
<NEW_PRIVATE_REPORT>` to retain current flags, pending evidence and events.
Completed held-observation resolutions retain their explicit decision
reference and remain closed after later version approvals. New observations
still require their own resolution; original candidates and history stay saved.

An optional report write can fail after an import has committed. Retrying the
identical import is an idempotent no-op. The ledger rejects pending SQLite
journal/WAL/SHM sidecars with `registry_recovery_required`; preserve those
files for explicit local recovery. This ledger is separate from research
decisions and does not change identity, wave selection or published samples.

## Fresh analytical release and current group-review workload

Calculate and independently reconcile a new isolated analytical release before
export. A later export timestamp does not make an older analytical run current.
Keep original native and independent-parent members; analytical exclusion masks
them without choosing replacements. OFF is retained exactly; the accepted
composed manifest supplies ON.

Explicitly supply both private JSON inputs. Neither the ledger nor record-level
evidence belongs in the output.

```bash
PYTHONPATH="<REVIEWED_CODE>" "<PROJECT_PYTHON>" -m study2.static_export \
  --config "<ISOLATED_FRESH_RELEASE_CONFIG>" --output "<NEW_EXPORT_DIRECTORY>" \
  --manual-manifest "<EXACT_ACCEPTED_COMPOSED_MANIFEST>" \
  --release-context "<RECONCILED_AGGREGATE_RELEASE_CONTEXT>" --default-eligibility on
```

The closed `study2_dashboard_release_context_v1` identifies the selected
release/run, stored run fingerprint and calculation program hash; group
control/proposal/implementation and review-control revisions; composed flag
manifest/inventory revisions and original/group/overlap/union counts; and current
child/phone/held groups, correction comparisons/bundles and adult comparisons.
All revisions are SHA256 and counts are nonnegative integers. Its `revision`
uses `analysis_eligibility.sha` over the input without `revision`. The constants
and validator in `study2.static_release_context` define the exact closed schema.

The calculation owner constructs these aggregates from actual current controls;
the independent reviewer reconciles that evidence. Schema/hash validation alone
does not approve invented work counts. The exporter binds the input to its
selected recorded run, summary and exact accepted flag manifest; checks union
counts and grouping arithmetic; and requires a complete valid ON/OFF export.
Invalid metadata or drift before installation preserves the previous site. It
does not discover private controls or approve changed source versions. Only the
closed aggregate context, export code hash and fixed workload scope go online.

The explicit `--default-eligibility on` option requests ON for this export only;
the default remains OFF, including when a context is supplied without that option.
An ON request requires the validated context and manifest. Browser validation failure shows
requested-ON unavailable; a user may deliberately choose OFF. OFF remains the
original corrected analytical release, not an older run. Exports without this
context retain their prior OFF default.

Current review work is separate from historical candidate inventory. Phone/held
groups partition open child groups. Correction bundles and their comparisons
describe the same work at different levels, and records may overlap between
categories. Do not add groups, bundles, comparisons or participants. Workload is
release-wide under its pinned applied controls; analytical ON/OFF and sample,
source, date and grade filters do not change it. Historical candidate status is
a discovery audit, never a substitute for current researcher work.

Snapshot JSON, scoped first-tab JSON and CSVs retain release/control/flag
provenance alongside existing eligibility and filter metadata. The deployment
manifest also carries the aggregate context. IDs, contacts, paths, workbooks,
decision/correction rows, ledgers, configuration and credentials stay local.
Preserve the complete protected export and authentication assets for the
deployment owner's separate checks.
