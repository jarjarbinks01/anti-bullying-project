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
