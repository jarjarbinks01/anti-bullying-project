# Package-native update helpers

These helpers share the installed `study2` runtime. They do not load a frozen
runtime from a machine-specific path or establish a second source of truth.
Historical scientific and policy receipts remain governed by native verification.

## Create-only review preparation

`study2.review_preparation.prepare(args)` and `main(argv=None)` accept the explicit
config, release, registry, policy head, publication, main revision and source
pins previously required by the reviewed preparation tool. `--runtime` is no
longer accepted. Run `python -m study2.review_preparation --help` for arguments.

Historical compatibility trust must be initialized by the validated entrypoint;
the standalone module never grants trust from bundle-supplied data.

Preparation holds the native reader locks, verifies registered release and
publication identities, checks pinned files, and writes only a new external
output directory. Existing output is never replaced or resumed. Historical
migration requires its source bundle; already-migrated controls carry current
accepted intents. Preparation does not accept, apply or publish a proposal.

## Completed-journal retirement

`study2.journal_retirement.retire_completed(cfg, *, expected_sha256,
expected_side, archive_directory, fault=None)` is called with the entrypoint's
validated local configuration. The entrypoint remains responsible for binding
activation/configuration and configuring compatibility trust before invocation.
The helper does not independently select an activation or install trust.

The helper retains the three native writer locks, no-follow directory bindings,
owner/inode/single-link checks, exact journal digest and outcome checks, two
native read-only completed-tuple verifications, and durable archive-before-unlink
ordering. The archive must already exist, be mode 0700 on the state volume, lie
under the configured review root, and be declared in recovery assets. An absent
journal retry verifies archived bytes only and never authorizes publication or
claims verification of the current tuple.

Atomic no-replace archive installation uses `renameatx_np(RENAME_EXCL)` on macOS
and `renameat2(RENAME_NOREPLACE)` on Linux. Unsupported platforms or unavailable
primitives fail closed. There is no ordinary replace-rename or hardlink fallback.
Tests run on synthetic temporary fixtures; Linux execution is not implied by a
macOS test run. These locks coordinate participating native writers, not an
arbitrary same-UID process deliberately ignoring locks.
