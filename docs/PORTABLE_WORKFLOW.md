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

## Review and process contracts

Active intent workload excludes a held decision only when every subject in its
original intent is excluded. Surviving edge endpoints alone do not establish that
scope; missing or changed subjects outside the current group can still require
review. Missing scope information retains the hold. This is a read-only workload
projection and does not erase decision or application history.

After undo restores an accepted policy, migration follows the immutable,
hash-verified restoration links to its original acceptance. An undo receipt does
not become new acceptance. Missing, changed or mismatched generations still fail
verification; the current source/input/authorization checks remain in force.

The owned reviewed-session protocol writes JSON replies to stdout. Child stdout
and stderr both inherit the session's stderr, so the owner has no unread output
pipes. A caller that captures session stderr must drain it or redirect it to an
intentional file, as with any child process. The stdin ownership channel remains
separate; no background logging service is required.

Browser tab clicks and hash/history changes use one navigation path. Back/Forward
updates the rendered tab while retaining filters and explicit exclusions OFF,
including during lazy loading. Re-selecting the same tab does not remount it.

## Recovery

Native checkpoints support DELETE journal mode for both main and review SQLite
databases. Under the existing read transactions, save checks each journal mode
before hashing source files or considering archive reuse. Other modes, including
WAL, are refused without changing the mode, deleting sidecars or replacing the
previous checkpoint. This keeps byte-based reuse consistent with the locked
snapshot. If a workspace uses another mode, resolve it through separately planned
maintenance; never remove WAL files to bypass the refusal.

Checkpoints include nested Python presentation adapters, browser assets and the
root entry bridge, not only top-level Python modules. A configured private trust
profile is captured with its pin and relocated during recovery. Configured
runtime environment paths must resolve to captured assets; uncaptured bindings
fail instead of quietly pointing back to the old workspace.

Restoring files is not automatic activation. Validate the restored workspace,
review its local selector/configuration and explicitly select it through the
existing workflow. Do not replace the running frozen installation merely because
a new source commit exists. Historical code may still be required by a recovery
inventory even when current science does not import it. Keep those assets and
release evidence until the intended recovery path has been demonstrated. A real
transition must coordinate the launcher, interpreter/package binding, working
directory, dispatcher/selector and configuration, not only an entrypoint pointer.

### One current recovery master

The opt-in lean `checkpoint_retention: single_master` policy uses the existing
checkpoint, object store and administrative ledger. It adds no backup database.
It validates the existing ledger against the held main snapshot, restores a new
candidate before promotion and preserves the previous master on failure. After
native journal retirement, the active ledger can point to the master's tracking
and compressed review snapshot. An unchanged save can finish deferred ledger
promotion without another scientific run.

Replacement refuses missing review workspaces, lost or conflicting append-only
review events, missing aliases, changed registration anchors or first publication,
and reactivated retired IDs. Legitimate new review events and nonretired lifecycle
changes remain allowed. Both the prior master and ledger protect review history
when journal ownership has deferred ledger promotion.

For preparation, `save_checkpoint(..., destination=new_directory)` uses the same
builder and one native isolated restore proof without changing live checkpoint
or ledger pointers, retention reports, pending markers, object storage or runtime
bindings. It holds the existing writer lock and read-only database snapshots,
refuses unfinished activation/transition journals, and requires the published
release's existing valid checksum/baseline evidence. It never repairs that
evidence in live state. Reused archives cannot change historical permissions.
Preparation does not qualify relocated launchers or authorize later deletion.

The retention report still cannot authorize deletion. Remove obsolete runtime
copies from a separately prepared current dependency inventory only after checking
actual consumers. Preserve current native databases, source identity mappings,
accepted decisions and exact evidence, including small older records still used
to authenticate a current decision. Generic source documentation is not a backup
of private research decisions or inputs. Keep unique historical evidence before
retiring old complete database images; a current checkpoint captures the current
release, not all historical external release directories.

### Source-only runtime updates

A performance-only source update need not create a new scientific release when
its actual scoped write authority, review rules and policy implementation remain
valid. Check those bindings against the installed candidate; unchanged release
IDs alone do not establish compatibility. Keep original scientific provenance
and historical source/profile evidence. Never rewrite an accepted certificate or
use the different-release publication/recovery route for a source-only switch.

Use the existing ordinary installation route with a versioned private
configuration and selector. Coordinate the editable package, launchers, working
directory and default configuration while consumers are quiesced and no
publication/recovery transition is pending; preserve the previous bindings for
rollback. An exact committed source archive may be the deployed artifact when the maintained checkout is unsuitable for reliable local
reads. It is not a second maintained implementation. Preserve historical recovery
assets and verify that the candidate configuration's recovery inventory covers
its actual runtime bindings. Retain security settings, qualify the actual
protected startup against the existing site's context and assets, and restore
the established scheduler last. A source-only update does not require export
when that site remains valid.

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

The five robustness fixes above have focused regression coverage and independent
source review. [Project state](PROJECT_STATE.md#robustness-follow-up) records the
counts and limits. Targeted verification is not an exhaustive final full-suite
pass or proof of compatibility with the active private installation.


### Exact administrative historical reads

An optional `administrative_read` object in the independently hash-pinned startup
compatibility profile admits one unchanged administrative workload as historical evidence only.
The original profile and accepted certificates remain retained. This is a separately reviewed
read contract requiring independent authority, not an assertion that an
old acceptance report accepted a new implementation.

The closed contract names `study2_administrative_historical_read_v1`, the accepted
`scope_sha256`, original `workload_pin`, current `reader_rules_hash`, scoped
`reader_code_sha256`, full-package `reader_revision` from
`controls_capture.code_revision()`, `recovery_manifest` pin, `recovery_root`, an
explicit original-path-to-restored-relative `path_map`, and `original_code`
module-to-restored-relative paths. Recovery bytes must match both their original
pins and the native checkpoint manifest's restored-byte hashes. Path mappings
must be reviewed against the original asset inventory; the manifest alone does
not authenticate an earlier pre-capture path. No signed path is rewritten.

The reader authenticates exact workload bytes, original scope and code, current
publication and disposition pointer, main/decision/admin revisions, release
inputs, canonical cases, and original native closure projection. It admits only
the exact no-new-holds projection; drift fails rather than preparing a changed
workload. Current reader identity remains separate from historical authority.

`validate_workload`, `load_summary`, `resolve_current`, `guarded_current` and
ordinary guarded consumers remain strict by default. Explicit read call sites for runtime information, control capture, protected dashboard validation and static export opt into the configured contract. The preparatory `manifest`, `review-prepare` and `run --no-publish` routes may authenticate this exact OLD tuple without granting publication authority. Without one, those entrypoints retain their normal strict
behavior. Policy/workload staging and coordinated publication/recovery may authenticate their actual OLD tuple using the contract. TARGET validation and proposal application remain strict. A historical staged pointer is accepted only when equal to actual CURRENT; full publication, byte and evidence checks still apply. Downstream policy/scientific-rules checks and snapshot
verification are unchanged and can independently refuse export. Read success
therefore does not authorize a write-capable runtime cutover or scheduled update.

### Different-release writer transition

Use a genuine new scientific release, never a fabricated same-release migration.
The startup profile's `administrative_read.scope_sha256` authenticates historical
OLD scope bytes; `administrative_scope_sha256` independently pins the genuinely
accepted current-source TARGET scope. Original closure bindings and events remain
unchanged. Current scope acceptance must have real current evidence and review;
changing old certificate hashes is not acceptance. TARGET staging also requires
current bundle/proposal, rules, source, controls and target inventory.

The existing coordinated plan retains different OLD/TARGET release IDs and
independent acceptance. Before publication, OLD is authenticated as history;
after publication TARGET is strictly validated. Recovery follows actual SQLite
publication, allowing historical admission only on OLD. Retaining the historical
profile after success does not force new readers through OLD: exact workload
identity selects historical admission, otherwise reads remain strict.

Source changes invalidate the read contract's full reader revision and current
write preparation. Freeze source and independently review fresh bindings before
operational preparation. Source tests do not activate databases, selectors,
launchers or scheduled work. Same-release writer migration remains unsupported.


### Publication verification cost

The performance implementation streams the existing canonical tracking format and
compares pre/post-publication rows without retaining two full histories. Its
pre-write reader is closed before SQLite commit, including refusal paths.
Repeated release checks still authenticate current artifact and backup bytes;
only a successful full backup integrity result is reused within the current
coordinated operation. Independent operations start fresh, changed content must authenticate again,
and failed verification is never cached. Compressed bytes are tied to the verified logical
backup digest, not a filename or modification time.

Completed-journal retirement retains both native verification calls and its
final mutable-tuple, ownership and exact-archive checks. The shared operation
scope avoids repeating identical backup integrity scans across those calls.
Existing saved-backup JSON parsing and some recovery comparisons remain
materialized. The focused synthetic memory benchmark describes only streaming
tracking digests/comparisons, not whole-publication memory or live update timing.
Installing or committing this optimization does not activate it, republish data,
change current runtime bindings or deploy the dashboard.
