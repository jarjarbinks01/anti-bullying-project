# Portable source and local operation

## Repository boundary

The public `anti-bullying-project` repository contains application code, general
decision rules and algorithms, synthetic tests, a blank review layout, and
non-sensitive project decisions/documentation. It does not contain participant
or case decisions, identifiers, real input registries, filled review evidence,
local trust profiles, source workbooks, databases, generated snapshots, secrets,
or recovery copies. The default-deny Git ignore and repository guard enforce a
reviewed file list; content still needs human/code review.

The private `study2-dashboard-deployment` repository is the separate publication
target for reviewed, generated protected-dashboard files. Private repository
visibility is not a reason to commit passwords or server secrets. Vercel receives
the generated dashboard project, not the research checkout or databases.

Source commit, source push, snapshot generation, private-repository push,
Vercel deployment and local runtime activation are separate operations. A source
commit does not claim that any later operation occurred.

## One installed source tree

Use a source checkout with Python 3.12+ and the pinned requirements. The native updater uses POSIX file locks and atomic local filesystem operations; this consolidation was verified on macOS. Install it
editable as described in README. The root launchers and mapping scripts are part
of the checkout; moving the whole checkout is supported. This is not a claim
that a standalone wheel contains an operational research workspace.

- `study2` and `python -m study2` both enter `study2.entrypoint:main`.
- `local_update_entry.py` is the small `-I` subprocess bridge used by reviewed
  activation/recovery. It loads this checkout, not an external source snapshot.
- `study2.cli` is the internal scientific/review command implementation, not a
  second public launch interface.
- Native matching, data stores, review and scientific calculations remain in
  `study2`. The selected-child dashboard uses small explicit presentation
  adapters; it does not load a second, older matching or storage implementation.
- Final browser source and the protected local launcher are readable files in
  `study2/presentation/assets`. Changes must be tested against assembled output.

See [presentation boundary](presentation-boundary.md) and
[update helpers](portable-update-helpers.md) for their callable interfaces.

## Local configuration

Keep actual configuration outside version control. The normal entry accepts
`--config /path/to/private/config.json`; otherwise it uses this checkout's
ignored `config.local.json`. A fresh checkout's `--help` does not need any data.
Existing research workspaces must not be initialized again.

Two optional local fields replace machine-specific source constants:

```json
{
  "runtime_environment": {
    "STUDY2_FLAG_CONTROL": "/path/to/private/control.json",
    "STUDY2_GROUP_POLICY_POINTER": "/path/to/private/policy/CURRENT.json",
    "STUDY2_CURRENT_REVIEW_WORKLOAD": "/path/to/private/workload.json",
    "STUDY2_REVIEW_STATE_DIR": "/path/to/private/state"
  },
  "compatibility": {
    "profile_path": "/path/to/private/trusted-compatibility.json",
    "profile_sha256": "REPLACE_WITH_REVIEWED_FILE_SHA256"
  }
}
```

Only the five known Study 2 path variables are supported; the fifth is
`STUDY2_MANUAL_EXCLUSION_MANIFEST`. Managed controls resolve the current manifest
from the published release rather than treating a configured older path as
current. Existing environment-based local bindings remain supported. The public
entry restores temporary environment changes when it returns.

Compatibility is optional for generic intent carry. Historical special records
require their separately reviewed, hash-pinned trust file, configured before
native consumers are imported. A proposal or request cannot configure its own
trust. Initialization is once per process; run a new process to change a trusted
configuration. The historical verifier contract permits only the original
implementation identity for its exact accepted profile while retaining proof,
scope and receipt checks. New application still requires the current code.
This is read compatibility, not permission to apply a stale proposal or to
assert that changed science is equivalent.

The scoped administrative certificates retain exact source-pin checks. If a
code change invalidates one, the code refuses reuse; consolidation does not mint
replacement authority or silently approve a new certificate.

For an already selected workspace, the public entry honors the configured
`coordinated_update.selection_path`, or a selector adjacent to its canonical
config. A selector pointing at another installation is refused, not redirected
silently. Existing `reviewed-publish`, `reviewed-session` and `reviewed-recover`
retain native plan acceptance, ownership, locking and recovery requirements.
Source identities in new reviewed plans are derived from this installed
checkout's exact bytes; changing those bytes invalidates that plan.

## Routine commands

```sh
python -m study2 --help
python -m study2 --config /path/to/private/config.json --runtime-info
python -m study2 review-prepare --help
python -m study2 static-export --help
python -m study2 dashboard --help
```

`review-prepare` writes a new unaccepted external packet using native APIs. It
never approves, publishes or exports. Ordinary update commands retire only an
already completed, freshly verified journal using the native locks and existing
archive-before-unlink ordering. Pending or ambiguous transitions require native
recovery; there is no automatic publication or retry.

`static-export` uses the formal exporter. Its CLI defaults to exclusions ON and
selected-child B/D; current manifest, release context and controls-request pins
are still required. An explicit OFF selection is distinct from permission to
supply a stale manifest. The paired PHQ restriction still requires confirmed
same-adult continuity.

`dashboard` serves the protected formal HTML/JavaScript output. It verifies
current controls, formal identity, selected-child projection and file hashes
before starting or opening the configured local preview. It does not export or
change a selector. Its ignored `dashboard_preview` config and code-pin contract
are described in the presentation document. Passwords remain in a separate
private secret file read only by the launcher at runtime. No secrets are embedded
in the generated browser assets or source code.

## Recovery

Checkpoints include nested Python presentation adapters, browser assets and the
root entry bridge, not only top-level Python modules. A configured private trust
profile is captured with its pin and relocated during recovery. Configured
runtime environment paths must resolve to captured assets; uncaptured bindings
fail instead of quietly pointing back to the old workspace.

Restoring files is not automatic activation. Validate the restored workspace,
review its local selector/configuration and explicitly select it through the
existing workflow. Do not replace the running frozen installation merely because
a new source commit exists.

## Focused verification

The relevant consolidation checks cover entry-point parity, exact historical
trust boundaries, current managed manifest rejection, generic decision carry,
coordinated publication/recovery, the package's recovery inventory, assembled
browser assets, protected preview and authentication. Run checks against a
stable tree: native tests intentionally reject source files changing mid-run.

Historical deployment-only test copies that depended on absent `transition.py`,
`activation/dispatcher.py` or `base_overlay` directories were not imported as
working portable tests. Their public routing coverage is replaced by portable
entry tests; native coordinated update/recovery suites remain. Two tests that
compared external historical checkout copies now compare synthetic
unprepared/eager and prepared/deferred results, and do not claim old-source
parity. The normal public suite does not require retained private fixture folders. The optional manual-exclusion validation matrix and frozen-fixture manual-exclusion UI/schema/Streamlit and paired-table UI tests skip unless their required synthetic bindings are explicitly supplied (validation: `STUDY2_MANUAL_FIXTURE_ROOT` for r1; manual UI: `MANUAL_UI_HASH_JS` and `MANUAL_UI_EVIDENCE_DIR`, plus `MANUAL_UI_CORE_FIXTURE_DIR` pointing to core_r2 for core-generated UI/schema and Streamlit eligibility checks and `MANUAL_UI_ORIGINAL_CORE_FIXTURE_DIR` pointing to core_r1 for empty/all-excluded schema checks; paired table: `PAIRED_TABLE_BASELINE_ASSET` and `PAIRED_TABLE_EVIDENCE_DIR`, with `PAIRED_TABLE_FROZEN_SD=1` for raw-SD parity); those skips are not passing checks.

Some review findings are independent follow-up work, including browser-history
navigation, excluded-intent workload counts, undo acceptance lineage, undrained
owned-consumer output and the conditional WAL checkpoint contract. Consolidation
does not claim these unrelated behavior fixes or an exhaustive full-suite pass.
