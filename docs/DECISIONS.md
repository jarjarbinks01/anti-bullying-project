# Project decisions

Record consequential design and research-method choices here. Detailed current rules belong in their existing specification; implementation progress belongs in [PROJECT_STATE.md](PROJECT_STATE.md).

Each entry records the date, status, choice, reason, consequences and source. Status is **proposed**, **accepted**, **implemented** or **superseded**. Acceptance does not imply deployment. For a reversal, add an entry and link it from the superseded one. Do not copy participant-level adjudications, private evidence or conversation transcripts here.

Entries below were recorded on 2026-11-07 UTC. Where an older decision's original date was not established, that is stated rather than reconstructed.

## D001: Separate source, aggregate deployment and local research

- **Date/status:** Reaffirmed by the project owner on 2026-11-07; accepted.
- **Choice:** Maintain pipeline code, generic decision logic and algorithms in the public `anti-bullying-project` repository. Generate approved aggregate dashboard snapshots into the private `study2-dashboard-deployment` repository, then deploy that application to Vercel.
- **Reason:** Source changes should be reviewable and reusable without publishing research records. A code update and a research-data deployment have different consequences.
- **Consequences:** Raw data, databases, individual adjudications, local bindings and secrets remain private local assets. Public commit/push, snapshot creation, private commit/push and Vercel deployment are separately recorded stages.
- **Sources:** Project-owner workflow clarification; [repository boundary](REPOSITORY.md). The private deployment README/manifest records the actual snapshot, not this log.

## D002: Consolidate into one maintained package and client

- **Date/status:** Accepted on 2026-11-07; implemented in the source revision containing this page, not activated or deployed.
- **Choice:** Both `python -m study2` and the installed `study2` command use one public entry point. Native processing stays in `study2`; presentation-specific behavior has an explicit package boundary and one readable final client source. Machine paths and historical trust bindings come from private configuration.
- **Reason:** The code review found a CLI route that bypassed current coordination and an exporter that replaced its apparent client source with a frozen bundle. Parallel implementations made changes hard to reproduce and maintain.
- **Consequences:** Preserve historical records and compatibility without copying older matching/storage modules into the exporter. Reuse existing controls and focused regression tests; avoid another wrapper or approval system. Consolidation alone does not activate the package or resolve unrelated review findings.
- **Sources:** [entry point](../study2/entrypoint.py), [presentation boundary](presentation-boundary.md), [package-native helpers](portable-update-helpers.md), and the private code review.

## D003: Keep child pairing separate from adult continuity

- **Date/status:** Existing implemented design, recorded on 2026-11-07. Original acceptance date was not reconstructed; the consolidated package is not yet activated.
- **Choice:** The selected-child dashboard B/D view pairs the already selected parent T0/T1 responses for the same child, even when responding adults differ. Adult continuity remains explicit evidence for those exact responses. Paired parent PHQ requires confirmed same-adult continuity; per-wave PHQ remains available.
- **Reason:** A shared child and a shared responding adult answer different research questions. One must not be inferred from the other.
- **Consequences:** Native/historical same-adult BD outputs retain their meaning. New native runs can explicitly select the already-supported same-child policy; absent that setting, the legacy behavior and rule vector remain unchanged. A selected-child dashboard projection is labelled and does not rewrite a frozen scientific release. Excluding a selected response removes its pair without selecting a substitute.
- **Sources:** [matching and projection definitions](MATCHING_RULES.md), [selected-parent pairing](../study2/bd_pairing.py), [presentation boundary](presentation-boundary.md), and the verified private update guide.

## D004: Carry decisions only within their supported scope

- **Date/status:** Existing implemented design, recorded on 2026-11-07. Original acceptance date was not reconstructed; the consolidated package is not yet activated.
- **Choice:** Preserve decision intent with its subjects, relevant evidence and supported boundaries. Apply it to a later release only when the existing continuity and scope requirements are met. Changed evidence, missing subjects or unsupported comparisons stay held.
- **Reason:** Release-specific group IDs alone do not express what was decided. An earlier answer must neither disappear merely because grouping changed nor silently authorize newly added relationships.
- **Consequences:** Retain earlier decisions, exclusions, closures and review history. New parent edges do not inherit an old closure. Administrative carry-forward does not write a new identity decision, and activation can retain unresolved holds.
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
