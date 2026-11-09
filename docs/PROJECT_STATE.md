# Project state

Updated: 2026-11-09 UTC. This page describes development status, not live research data. Check the working branch and linked sources before acting.

## Purpose and boundaries

Study 2 links responses about the same child, selects T0/T1 observations, preserves human review decisions and presents research summaries. The input boundary is the four already-merged A/B/C/D workbooks. Collection and upstream merging remain separate; no T2 workflow is included.

- **Public source:** [anti-bullying-project](https://github.com/jarjarbinks01/anti-bullying-project), containing reusable pipeline/dashboard code, generic decisions and methods, and synthetic tests.
- **Private deployment:** `jarjarbinks01/study2-dashboard-deployment`, containing the approved generated aggregate application and its snapshot manifest. Vercel deploys this repository.
- **Private local research:** source workbooks, databases, participant-level decisions, release evidence, machine configuration and credentials. These do not belong in either repository's published documentation or deployment bundle.

The [decision log](DECISIONS.md) explains consequential choices. Current method definitions remain in [matching rules](MATCHING_RULES.md), [data model](DATA_MODEL.md) and [descriptive analysis](DESCRIPTIVE_ANALYSIS.md). Do not duplicate those specifications here.

## Current milestone

**Portable source consolidation, robustness fixes and the different-release writer transition are implemented and adopted locally. Remote publication remains separate.**

- Branch: `refactor/portable-study2-20261108`, based on public `main` at `9bd6357f49bc0cb37f0e9d7d3f8eb6c7fa65f66f`. Newer main features were retained rather than replaced by the older local source tree.
- Native update/review helpers and the presentation boundary now share one maintained checkout. Module, installed console and isolated recovery bridge enter the same public route. Readable final client assets are authoritative; eligibility calculations have one implementation.
- Private paths and hash-pinned historical trust bindings are configured outside Git. Historical same-adult results retain their meaning; explicitly configured native same-child BD and labelled dashboard projection remain distinct. Paired parent PHQ still requires confirmed adult continuity.
- The normal export CLI defaults to exclusions ON. Review application also preserves its approved/waiting response when the newer owned lock reports actual contention.
- The follow-up fixes remove fully excluded original intent scopes from active workload, resolve original acceptance through authenticated undo restoration links, route child diagnostics to stderr, reject unsupported checkpoint journal modes before reuse, and restore browser Back/Forward rendering. Decision history and scientific definitions are unchanged.
- A genuine new-data release was published locally, its completed journal retired, and the full formal dashboard rendered. The installed package, launchers and default binding now use the frozen consolidated source. Protected startup passed current-context validation and all 67 asset hashes.
- The existing 15-minute queued-batch scheduler was restored; its first actual invocation exited successfully with no ready batches. Browser visual QA awaits user login and is not claimed as passed. No source push, private-repository publication or Vercel deployment is included in this local adoption.

## Isolated publication-performance follow-up

Implemented on `perf/publication-verification-20261109`, separately from the adopted runtime. Tracking revisions, backup output and publication comparisons stream the existing canonical rows instead of retaining multiple complete histories. Successful backup integrity results are reused only within one operation after authenticating current content. Both retirement verification boundaries and all mutable-state checks remain.

- Frozen-source selection: 174 focused synthetic cases passed, with the explicitly opt-in memory benchmark skipped in that selection and passed separately. Coverage includes canonical digest parity, malformed/changed history refusal, cache invalidation, real interrupted publication/retirement, changed-input recovery and historical-to-current writer transition. After retaining the final dynamic tracking recheck, 80 focused recovery/retirement cases passed and a new concurrent-WAL-publication refusal regression passed separately. The compressed-backup restore recheck also passed; the other three compressed cases passed in earlier focused checks.
- Native synthetic instrumentation reduced full release-backup integrity scans from nine to two per publication and eight to two per retirement. This measures scan count, not an end-to-end live speedup.
- A separate 500,000-event digest/comparison benchmark used 17,489 bytes peak traced Python allocation and 96.75 seconds with tracing enabled. It excludes existing saved-JSON parsing, recovery dictionaries, SQLite-native buffers and whole-process RSS. The earlier equivalent streaming benchmark also passed.
- Independent review caught and resolved malformed non-list backup tables hashing as empty arrays. Their original authentication semantics are now preserved and tested. Review found no remaining blocker. Initial source-change refusals, source-tree read stalls and interrupted checks are not counted as passing; final checks used a frozen temporary source copy.
- No live source, runtime configuration, scheduler, research state or deployment was changed. A local source commit is not activation. New applicable source/runtime bindings are still required before adopting this optimization.

## Remaining work

1. Complete authenticated browser visual QA after user login. Track source review/publication, private repository publication and Vercel verification separately from the completed local adoption. Reuse valid artifacts; do not rematch for a presentation-only change.
2. Before future changes or activation, review actual private bindings and current native evidence. Source changes invalidate prepared proposals and source-pinned certificates where those identities apply; source verification does not authorize their reuse or manufacture replacement authority.
3. Keep historical recovery assets and release evidence until a separately authorized transition proves the required recovery path. A portable source tree does not free assets named by existing recovery inventories. Launcher, interpreter/package binding, working directory, selector and configuration must agree at transition.

## Verification and limits

### Historical transition preparation, before local adoption

These preparation-stage findings describe the earlier blocker, not the current local installation. The completed adoption above used fresh target authority and a genuine new release.

- Private isolated current-state checkpoint and relocated restore passed; historical recovery assets and the existing scientific result/snapshot were retained. This is recovery verification, not live activation.
- At that stage, administrative carry refused the consolidated source because its accepted scope pinned an earlier implementation. A bounded read-only comparison found unchanged correction evidence and original closure projection, but it does not grant new source authority.
- The proposed next step was narrowly reviewed historical-read compatibility within existing administrative validation, with authenticated relocation and strict current-source checks retained for new writes. No global rule alias, changed accepted evidence or new closure events were introduced. The resulting source contract is documented below; later local adoption is recorded above.
- At that stage, a fresh snapshot was planned after native control admission, retaining the old snapshot until replacement checks passed. No export, live switch, repository publication or deployment occurred in this preparation.
- The private data-update guide owns exact identities, evidence, outcomes and the scoped resolution assessment; these are not copied into this public record.

### Robustness follow-up

- Focused synthetic suites passed: 109 decision/undo tests, 55 owned-consumer/recovery tests, and 39 assembled browser/history tests. Independent read-only review found no remaining blocker in the five fixes; it caught and resolved an intermediate exclusion bug involving a third original subject outside the current edge.
- Workload filtering uses the complete original intent scope, not just surviving edge endpoints. Unknown scope remains held. Undo tests cover repeated restoration and missing/tampered acceptance; output tests exercise noisy children through the JSON session protocol; checkpoint tests retain uncheckpointed WAL changes while refusing save/reuse; browser tests cover filters and in-flight lazy loading through Back/Forward.
- Checkpoints support DELETE journal mode only. The refusal happens under existing read transactions before main-file hashing or archive reuse, without changing journal mode or deleting sidecars. This resolves the inconsistent contract; it does not add WAL support.
- Browser tests required approved Chromium execution outside the macOS process sandbox. An earlier broad checkpoint run was interrupted after a concurrent-source-change refusal; its exact failing case passed with frozen source. Neither that incomplete run nor the initial browser-startup failure is counted as passing coverage.
- A relocated archive passed an editable-install check, console/module/isolated-bridge help parity, and 27 focused entrypoint, historical-trust, BD-policy and undo tests. The public-source audit passed for all 278 file versions; whitespace checks passed. Public main was rechecked at the unchanged base above.
- This follow-up used targeted checks, not another full-suite run or a real research update. See the prior consolidation baseline below and the [runtime contracts](PORTABLE_WORKFLOW.md#review-and-process-contracts).

### Prior consolidation baseline

- A stable Git-archive sweep exercised 2,307 cases plus 27 subtests. Its initial result was 2,142 passed, 138 failed, four setup errors and 23 skipped. All 142 nonpassing cases and all 23 skipped cases subsequently passed in targeted rechecks with corrected test contracts or their declared synthetic/browser setup.
- The failures were browser/fixture setup, stale localization/source-extraction harnesses, and the review-lock compatibility issue. Existing identity, privacy, suppression, precision and no-write assertions were retained. This was a full sweep followed by targeted rechecks, not a second full-suite run on the final revision.
- A final relocated editable checkout passed 32 focused entrypoint, wording, compatibility, checkpoint-asset and policy tests. Installed console, module and isolated bridge help matched. Independent source reviews covered the public/private boundary, current-main reconciliation, historical trust, recovery, source pins and shared projection logic.
- The consolidation repository audit passed for all 277 reviewed file versions; whitespace checks passed. Optional frozen-synthetic-fixture tests explicitly skip when not configured; skips are not passing coverage. Setup is documented in [README](../README.md#develop-and-prepare-a-pull-request) and [portable workflow](PORTABLE_WORKFLOW.md#focused-verification).
- Verification used macOS and synthetic records. No real scientific rerun, research export, live activation, deployment or cross-platform certification is claimed. Earlier interrupted runs and source-change refusals are not counted as successful verification.
- Implementation entry points: [portable workflow](PORTABLE_WORKFLOW.md), [presentation boundary](presentation-boundary.md), [update helpers](portable-update-helpers.md), and [code reading guide](CODE_READING_GUIDE.md).

## Historical OLD and current TARGET transition

The isolated historical-read candidate is now integrated with a narrow different-release writer transition. Independently pinned historical evidence authenticates only the exact OLD workload. TARGET requires a separately accepted current-source scope, fresh bundle/proposal and independently reviewed publication plan. Original decisions, exclusions, closures and holds retain their existing meaning; no certificate is rewritten, rule alias widened or same-release recovery assumption removed.

- Public manifest, review preparation and `run --no-publish` can authenticate historical OLD. Default run and scheduled mutation remain strict. OLD publication/recovery checks may use the exact historical contract; TARGET always uses strict current-source validation.
- Retaining the historical profile after transition does not block current readers: the exact current workload selects the historical lane, otherwise readers validate strictly.
- Recovery repairs a stale derived path even when its release ID is already correct, using the existing relocation-aware native lookup. Invalid effective paths fail before writing.
- Independent source review found no remaining blocker. Focused synthetic verification and exact limits are recorded below. Source completion does not establish operational admission, scientific-run completion, local activation, snapshot export, publication or deployment; the private guide owns those outcomes.
- Same-scientific-release writer migration remains unsupported. A genuinely new release supplies the distinct TARGET required by the existing coordinated plan and recovery contract.

### Transition verification

The final migration/historical-read/compatibility/entrypoint selection passed 72 synthetic cases. Coverage includes current-target staging/publication without re-closing decisions, OLD/TARGET interrupted recovery, strict stale-authority refusal, immutable evidence and relocation, public preparation admission, post-TARGET reads with the historical profile retained, and pointer repair/no-op/refusal. The existing current-carry/coordinated selection passed all 55 cases on frozen source, including process-death recovery. Together these selections passed 127 cases; this is focused coverage, not a full-suite or operational certification.

An initial pass exposed a stale test assumption that historical and current scope pins must be identical; the updated test now tampers the historical scope itself. A child-process test initially timed out importing synchronized cached bytecode; an isolated temporary bytecode cache resolved imports, and all three process-death cases passed on recheck. Initial interrupted import probes and failed intermediate checks are not counted as passing verification. No research data, launcher, selector, live runtime or deployment was changed by these source checks.

## Where progress is recorded

The existing private `STUDY2_DATA_UPDATE_GUIDE.md` owns current local release/preview status and links to operational evidence. The private deployment repository's `README.md` and `snapshot-manifest.json` own its pinned delivery. Participant adjudications remain in native stores. These records must not be replaced by copies in this public repository.

The developer completing a material change updates this page at the checkpoint, including what finished, the exact verification limits and the next unfinished step. Update [DECISIONS.md](DECISIONS.md) when a consequential choice changes; use Git history for routine edits. Keep one current summary rather than adding a new dated status file for every session.

This record was bootstrapped from the existing method documents, inspected source, the private data-update guide, the code review and the project owner's confirmed repository workflow. Historical rationale or dates not supported by those sources remain unverified. If records disagree, inspect the relevant code/artifact and mark the discrepancy before changing the summary.
