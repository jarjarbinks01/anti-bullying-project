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
