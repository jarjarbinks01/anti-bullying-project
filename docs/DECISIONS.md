# Project decisions

Record consequential design and research-method choices here. Detailed current rules belong in their existing specification; implementation progress belongs in [PROJECT_STATE.md](PROJECT_STATE.md).

Each entry records the date, status, choice, reason, consequences and source. Status is **proposed**, **accepted**, **implemented** or **superseded**. Acceptance does not imply deployment. For a reversal, add an entry and link it from the superseded one. Do not copy participant-level adjudications, private evidence or conversation transcripts here.

Initial entries were recorded on 2026-11-07 UTC; later entries carry their own dates. Where an older decision's original date was not established, that is stated rather than reconstructed.

## D001: Separate source, aggregate deployment and local research

- **Date/status:** Reaffirmed by the project owner on 2026-11-07; accepted.
- **Choice:** Maintain pipeline code, generic decision logic and algorithms in the public `anti-bullying-project` repository. Generate approved aggregate dashboard snapshots into the private `study2-dashboard-deployment` repository, then deploy that application to Vercel.
- **Reason:** Source changes should be reviewable and reusable without publishing research records. A code update and a research-data deployment have different consequences.
- **Consequences:** Raw data, databases, individual adjudications, local bindings and secrets remain private local assets. Public commit/push, snapshot creation, private commit/push and Vercel deployment are separately recorded stages.
- **Sources:** Project-owner workflow clarification; [repository boundary](REPOSITORY.md). The private deployment README/manifest records the actual snapshot, not this log.

## D002: Consolidate into one maintained package and client

- **Date/status:** Accepted on 2026-11-07; implemented and adopted locally on 2026-11-09. Remote publication remains separate.
- **Choice:** Both `python -m study2` and the installed `study2` command use one public entry point. Native processing stays in `study2`; presentation-specific behavior has an explicit package boundary and one readable final client source. Machine paths and historical trust bindings come from private configuration.
- **Reason:** The code review found a CLI route that bypassed current coordination and an exporter that replaced its apparent client source with a frozen bundle. Parallel implementations made changes hard to reproduce and maintain.
- **Consequences:** Preserve historical records and compatibility without copying older matching/storage modules into the exporter. Reuse existing controls and focused regression tests; avoid another wrapper or approval system. Consolidation alone does not activate the package. The five separately authorized review findings were resolved in the subsequent source follow-up; see [current verification](PROJECT_STATE.md#robustness-follow-up).
- **Sources:** [entry point](../study2/entrypoint.py), [presentation boundary](presentation-boundary.md), [package-native helpers](portable-update-helpers.md), and the private code review.

## D003: Keep child pairing separate from adult continuity

- **Date/status:** Existing implemented design, recorded on 2026-11-07. Original acceptance date was not reconstructed; the consolidated package was adopted locally on 2026-11-09.
- **Choice:** The selected-child dashboard B/D view pairs the already selected parent T0/T1 responses for the same child, even when responding adults differ. Adult continuity remains explicit evidence for those exact responses. Paired parent PHQ requires confirmed same-adult continuity; per-wave PHQ remains available.
- **Reason:** A shared child and a shared responding adult answer different research questions. One must not be inferred from the other.
- **Consequences:** Native/historical same-adult BD outputs retain their meaning. New native runs can explicitly select the already-supported same-child policy; absent that setting, the legacy behavior and rule vector remain unchanged. A selected-child dashboard projection is labelled and does not rewrite a frozen scientific release. Excluding a selected response removes its pair without selecting a substitute.
- **Sources:** [matching and projection definitions](MATCHING_RULES.md), [selected-parent pairing](../study2/bd_pairing.py), [presentation boundary](presentation-boundary.md), and the verified private update guide.

## D004: Carry decisions only within their supported scope

- **Date/status:** Existing implemented design, recorded on 2026-11-07. Original acceptance date was not reconstructed; the consolidated package was adopted locally on 2026-11-09.
- **Choice:** Preserve decision intent with its subjects, relevant evidence and supported boundaries. Apply it to a later release only when the existing continuity and scope requirements are met. Changed evidence, missing subjects or unsupported comparisons stay held.
- **Reason:** Release-specific group IDs alone do not express what was decided. An earlier answer must neither disappear merely because grouping changed nor silently authorize newly added relationships.
- **Consequences:** Retain earlier decisions, exclusions, closures and review history. New parent edges do not inherit an old closure. Administrative carry-forward does not write a new identity decision, and activation can retain unresolved holds. The 2026-11-08 source follow-up removes a held intent from active workload only when its complete original subject scope is excluded; incomplete scope remains held. Undo migration resolves the original acceptance through immutable, hash-verified restoration links rather than treating the undo event as new acceptance.
- **Sources:** [decision intent implementation](../study2/group_decision_intents.py), [review presentation](../study2/group_intent_review.py), and the verified private update guide.

## D005: Reuse completed work across explicit update stages

- **Date/status:** Existing operational design, recorded on 2026-11-07; accepted and used by the prior local update. Original acceptance date was not reconstructed.
- **Choice:** Keep input preparation, native matching, review preparation, coordinated activation/recovery and dashboard rendering distinct. Use parameterized helpers and the existing native controls rather than a new release-specific script. The normal dashboard CLI defaults to exclusions ON.
- **Reason:** A presentation change or interrupted tool connection does not inherently invalidate a completed scientific run. Clear stage outcomes support recovery without redundant computation or extra layers of checks.
- **Consequences:** Inspect durable outcomes before retrying; reuse unchanged valid evidence. Prepare a fresh artifact only when its inputs or behavior require it. An unresolved research hold is not automatically a reason to rerun matching or invent an answer. Record tests and limits for the actual changed scope.
- **Sources:** [portable workflow](PORTABLE_WORKFLOW.md), [helper contracts](portable-update-helpers.md), [presentation defaults](presentation-boundary.md), and the private data-update guide.

## D006: Keep a small, versioned project record

- **Date/status:** Accepted and documented on 2026-11-07.
- **Choice:** Use [PROJECT_STATE.md](PROJECT_STATE.md) for current development status, this file for consequential choices, and [AGENTS.md](../AGENTS.md) as the read-first pointer. Reuse the private local guide and deployment manifest for operational details.
- **Reason:** Development must remain consistent when conversation context is unavailable. Existing detailed guides need a clear entry point and an explicit current milestone.
- **Consequences:** The developer doing the work maintains the affected record at meaningful checkpoints. Git supplies code history; native stores/evidence supply research history. This adds documentation, not a parallel task tracker, new approval gate or new test framework.
- **Sources:** Project-owner request and approval; [record ownership and current milestone](PROJECT_STATE.md).

## D007: Keep byte-based checkpoints on DELETE-mode SQLite

- **Date/status:** Implemented on 2026-11-08 as part of the authorized robustness fixes; included in local adoption on 2026-11-09.
- **Choice:** Refuse checkpoint creation or reuse when either native database uses a journal mode other than DELETE. Check the mode inside the existing held read transaction before hashing main-file bytes. Do not change live modes or delete SQLite sidecars automatically.
- **Reason:** Checkpoint reuse is keyed to main-file bytes. WAL may contain committed changes without changing those bytes; supporting it correctly would require a different snapshot/reuse contract. An explicit restriction fits the existing local checkpoint design without another storage abstraction.
- **Consequences:** A refused attempt preserves the previous checkpoint and live data. An operator must plan any journal-mode maintenance separately. Synthetic regressions cover main/review databases, forced/non-forced saves, and an existing checkpoint with newer committed WAL data. This is not a claim of WAL support or live activation compatibility.
- **Sources:** [checkpoint implementation](../study2/checkpoints.py), [checkpoint regressions](../tests/test_checkpoints.py), [recovery contract](PORTABLE_WORKFLOW.md#recovery), and the independently reviewed robustness follow-up.

## D008: Separate exact historical reads from current write authority

- **Date/status:** Integrated on 2026-11-09 with OLD-only transition admission; source review found no blocker. Synthetic verification and the separately completed local adoption are recorded in project state. Remote publication remains separate.
- **Choice:** Extend the existing startup-pinned compatibility profile with an optional exact administrative historical-read contract. It pins the unchanged workload and accepted scope, the current reader implementation and rules, and original source/evidence bytes through an independently pinned recovery manifest and explicit relocation mapping. Existing profiles remain valid without this optional contract.
- **Reason:** Relocating and reading an accepted historical workload must not turn its old source certificate into authority for new writes. Reuse the existing canonical-case and native closure checks, preserving original signed paths and identities.
- **Consequences:** Shared validators remain strict by default. Runtime information, control capture, protected dashboard validation and static snapshot export opt into an exact configured read contract. Preparation and coordinated transition may authenticate only their actual OLD tuple through that contract. Any workload, publication, control, evidence, history or reader drift fails; no new holds, closures or workloads are derived. Policy rules and snapshot verification remain mandatory. The optional profile is separate read authority requiring its own exact review; earlier acceptance does not approve it. A genuinely different TARGET requires a separately accepted current-source administrative scope, fresh bundle/proposal and independently reviewed publication tuple. The retained historical scope is not rewritten or promoted into write authority. Recovery chooses OLD or TARGET by actual SQLite publication; only OLD can use historical admission. Default run and scheduled update routes stay strict.
- **Sources:** [administrative validator](../study2/administrative_carry_current.py), [compatibility profile](../study2/compatibility_profiles.py), [historical-read regressions](../tests/test_administrative_historical_read.py), and [read contract](PORTABLE_WORKFLOW.md#exact-administrative-historical-reads).


## D009: Stream tracking and reuse authenticated backup integrity

- **Date/status:** Implemented in an isolated performance branch on 2026-11-09; local activation and publication remain separate.
- **Choice:** Preserve the existing tracking JSON/hash contract while streaming table rows for revision checks, backup output and pre-commit comparisons. Compare against a pinned pre-write SQLite reader and close it before commit. Share successful backup integrity results only within one coordinated operation, authenticating current bytes on every use.
- **Reason:** Repeated full SQLite integrity scans and multiple materialized tracking histories added avoidable publication cost without changing the scientific result.
- **Consequences:** Keep both journal-retirement verification boundaries and all mutable tuple, source, manifest, ownership and archive checks. Final tracking validation is retained because its expected history depends on a fresh publication read, even when tracking rows use a pinned snapshot. No persistent cache, metadata-only identity, changed approval authority or scientific rerun is introduced. Independent operations start fresh. Legacy recovery still parses saved tracking JSON, so the entire publication path is not claimed to use bounded memory. Source changes still require fresh applicable runtime bindings before activation.
- **Sources:** [tracking streams](../study2/dyad_operator.py), [backup verification](../study2/store.py), [coordinated update](../study2/coordinated_update.py), and their focused synthetic regressions.
