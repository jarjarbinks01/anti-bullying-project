# Project state

Updated: 2026-11-07 UTC. This page describes development status, not live research data. Check the working branch and linked sources before acting.

## Purpose and boundaries

Study 2 links responses about the same child, selects T0/T1 observations, preserves human review decisions and presents research summaries. The input boundary is the four already-merged A/B/C/D workbooks. Collection and upstream merging remain separate; no T2 workflow is included.

- **Public source:** [anti-bullying-project](https://github.com/jarjarbinks01/anti-bullying-project), containing reusable pipeline/dashboard code, generic decisions and methods, and synthetic tests.
- **Private deployment:** `jarjarbinks01/study2-dashboard-deployment`, containing the approved generated aggregate application and its snapshot manifest. Vercel deploys this repository.
- **Private local research:** source workbooks, databases, participant-level decisions, release evidence, machine configuration and credentials. These do not belong in either repository's published documentation or deployment bundle.

The [decision log](DECISIONS.md) explains consequential choices. Current method definitions remain in [matching rules](MATCHING_RULES.md), [data model](DATA_MODEL.md) and [descriptive analysis](DESCRIPTIVE_ANALYSIS.md). Do not duplicate those specifications here.

## Current milestone

**Portable source consolidation is complete in the Git revision containing this page, ready for pull-request review.**

- Branch: `refactor/portable-study2-20261108`, based on public `main` at `9bd6357f49bc0cb37f0e9d7d3f8eb6c7fa65f66f`. Newer main features were retained rather than replaced by the older local source tree.
- Native update/review helpers and the presentation boundary now share one maintained checkout. Module, installed console and isolated recovery bridge enter the same public route. Readable final client assets are authoritative; eligibility calculations have one implementation.
- Private paths and hash-pinned historical trust bindings are configured outside Git. Historical same-adult results retain their meaning; explicitly configured native same-child BD and labelled dashboard projection remain distinct. Paired parent PHQ still requires confirmed adult continuity.
- The normal export CLI defaults to exclusions ON. Review application also preserves its approved/waiting response when the newer owned lock reports actual contention.
- This source revision has not been activated against research state, used to regenerate a research snapshot, pushed or deployed. Earlier local activation/export checks belong to the previous installation and do not verify this package's live activation. Vercel and the private deployment's pinned delivery remain unchanged.

## Remaining work

1. Review the source-only PR, then track authorized source publication, local activation, snapshot preparation, private repository publication and Vercel verification as separate outcomes. Reuse valid artifacts; do not rematch for a presentation-only change.
2. Retain the separate review findings for follow-up: excluded groups counted as open intent work; acceptance lineage after undo; undrained owned-consumer output; conditional SQLite WAL/checkpoint compatibility; browser Back/Forward rendering. Consolidation does not claim these behavior fixes.
3. Before any real activation, review its actual private bindings and current native evidence. Source verification does not authorize a stale proposal, a replacement certificate or a production-state change.

## Verification and limits

- A stable Git-archive sweep exercised 2,307 cases plus 27 subtests. Its initial result was 2,142 passed, 138 failed, four setup errors and 23 skipped. All 142 nonpassing cases and all 23 skipped cases subsequently passed in targeted rechecks with corrected test contracts or their declared synthetic/browser setup.
- The failures were browser/fixture setup, stale localization/source-extraction harnesses, and the review-lock compatibility issue. Existing identity, privacy, suppression, precision and no-write assertions were retained. This was a full sweep followed by targeted rechecks, not a second full-suite run on the final revision.
- A final relocated editable checkout passed 32 focused entrypoint, wording, compatibility, checkpoint-asset and policy tests. Installed console, module and isolated bridge help matched. Independent source reviews covered the public/private boundary, current-main reconciliation, historical trust, recovery, source pins and shared projection logic.
- Repository audit passed for all 277 reviewed file versions; whitespace checks passed. Optional frozen-synthetic-fixture tests explicitly skip when not configured; skips are not passing coverage. Setup is documented in [README](../README.md#develop-and-prepare-a-pull-request) and [portable workflow](PORTABLE_WORKFLOW.md#focused-verification).
- Verification used macOS and synthetic records. No real scientific rerun, research export, live activation, deployment or cross-platform certification is claimed. Earlier interrupted runs and source-change refusals are not counted as successful verification.
- Implementation entry points: [portable workflow](PORTABLE_WORKFLOW.md), [presentation boundary](presentation-boundary.md), [update helpers](portable-update-helpers.md), and [code reading guide](CODE_READING_GUIDE.md).

## Where progress is recorded

The existing private `STUDY2_DATA_UPDATE_GUIDE.md` owns current local release/preview status and links to operational evidence. The private deployment repository's `README.md` and `snapshot-manifest.json` own its pinned delivery. Participant adjudications remain in native stores. These records must not be replaced by copies in this public repository.

The developer completing a material change updates this page at the checkpoint, including what finished, the exact verification limits and the next unfinished step. Update [DECISIONS.md](DECISIONS.md) when a consequential choice changes; use Git history for routine edits. Keep one current summary rather than adding a new dated status file for every session.

This record was bootstrapped from the existing method documents, inspected source, the private data-update guide, the code review and the project owner's confirmed repository workflow. Historical rationale or dates not supported by those sources remain unverified. If records disagree, inspect the relevant code/artifact and mark the discrepancy before changing the summary.
