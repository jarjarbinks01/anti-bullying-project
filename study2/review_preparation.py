"""Package-native, create-only review preparation; never applies or publishes."""
import argparse
from contextlib import ExitStack
import gc
import gzip
import json
from pathlib import Path
import sqlite3


def regular(path, directory=False):
    path = Path(path).absolute()
    if any(p.is_symlink() for p in (path, *path.parents)):
        raise ValueError('symlink input ancestor')
    if not (path.is_dir() if directory else path.is_file()):
        raise ValueError('existing regular input required')
    return path.resolve()


def pin(path, expected=None):
    from study2.common import file_hash
    path = regular(path)
    actual = file_hash(path)
    if expected is not None and actual != expected:
        raise ValueError('input pin changed: ' + str(path))
    return {'path': str(path), 'sha256': actual}


def save(path, value):
    from study2 import group_cleaning_operator as group
    group._write_new(path, value)
    Path(path).chmod(0o600)
    return pin(path)


def indexed(path, key):
    result = {}
    with gzip.open(path, 'rt', encoding='utf-8') as stream:
        for line in stream:
            row = json.loads(line)
            if row[key] in result:
                raise ValueError('duplicate input identity')
            result[row[key]] = row
    return result


def prepare(args):
    runtime = Path(__file__).resolve().parent.parent
    from study2 import group_cleaning_operator as group, manual_flags, review_groups, review_core
    from study2.ac_export import _verify_published_files
    from study2.analysis_eligibility import sha
    from study2.common import digest
    from study2.review import active_decisions

    config_pin = pin(args.config, args.config_sha256)
    cfg = json.loads(Path(config_pin['path']).read_text())
    state = regular(cfg['state_dir'], directory=True)
    source_pin = None
    source_meta = None
    source_state = state
    if args.source_bundle:
        if not args.source_sha256:
            raise ValueError('source bundle hash required')
        source_pin = pin(args.source_bundle, args.source_sha256)
        source_meta = json.loads(Path(source_pin['path']).read_text())
        _, source_config = group._read_file(source_meta['files']['config'])
        source_state = regular(json.loads(source_config)['state_dir'], directory=True)
    if args.source_evidence:
        if not args.source_evidence_sha256:
            raise ValueError('source evidence hash required')
        evidence_pin = pin(args.source_evidence, args.source_evidence_sha256)
    elif source_meta:
        evidence_pin = source_meta['files']['source_evidence']
        group._read_file(evidence_pin)
    else:
        raise ValueError('source evidence or source bundle required')
    root = regular(args.control_root, directory=True)
    release = regular(args.release_folder, directory=True)
    ledger = regular(args.flag_registry)
    protected = [state, source_state, root, release, runtime, ledger.parent]
    output = group._external_preview_path(args.output, protected)
    for asset in cfg.get('recovery_policy', {}).get('required_assets', []):
        if asset.get('kind') == 'directory' and output.is_relative_to(Path(asset['path']).resolve()):
            raise ValueError('output would enter a recovery asset')
    with ExitStack() as stack:
        for folder in sorted({state, source_state, root}, key=str):
            stack.enter_context(group._reader_control(folder))
        pin(args.config, args.config_sha256)
        if source_pin: pin(args.source_bundle, args.source_sha256)
        pin(ledger, args.registry_sha256)
        checks_pin = pin(release/'checksums.json', args.checksums_sha256)
        active = group.read_active(root)
        group.need(active is not None and active['pointer']['manifest_sha256'] == args.policy_head,
                   'expected_policy_head_changed')
        historical = 'decision_intents' not in active['proposal'] or bool(active['proposal']['partitions'])
        if historical:
            group.need(source_pin is not None, 'historical_source_bundle_required')
            group._load_intent_source(args.source_bundle, active)
        group._read_file(evidence_pin)
        # mode=ro transaction, never store.connect/recovery/immutable fallback.
        dbpath = regular(state/'study2.sqlite')
        db = sqlite3.connect(dbpath.as_uri()+'?mode=ro', uri=True)
        db.row_factory = sqlite3.Row
        try:
            db.execute('PRAGMA query_only=ON'); db.execute('BEGIN')
            row = db.execute('SELECT r.*,n.status FROM releases r JOIN runs n USING(run_id) WHERE release_id=?',
                             (args.release_id,)).fetchone()
            group.need(row is not None and row['status'] in {'validated','published'}, 'target_release_not_validated')
            registered = row['path']
            locations = state/'release_locations.json'
            if locations.exists():
                registered = json.loads(regular(locations).read_text()).get(args.release_id, registered)
            group.need(regular(registered, directory=True) == release, 'target_release_folder_mismatch')
            pub = db.execute('SELECT release_id FROM publication').fetchone()
            group.need(pub is not None and pub[0] == args.publication_id, 'source_publication_changed')
            decisions = active_decisions(db)
            labels = [dict(r) for r in db.execute('SELECT * FROM labels ORDER BY case_id')]
            revision = digest({'decisions': decisions, 'labels': labels})
            group.need(revision == args.main_revision, 'main_controls_changed')
        finally:
            db.rollback(); db.close()
        for name in ('summary.json','records.jsonl.gz','cases.jsonl.gz'):
            regular(release/name)
        _verify_published_files(release, ('summary.json','records.jsonl.gz','cases.jsonl.gz'))
        group.need(json.loads((release/'summary.json').read_text())['release_id'] == args.release_id,
                   'target_summary_identity_mismatch')
        records = indexed(release/'records.jsonl.gz', 'submission_id')
        cases = indexed(release/'cases.jsonl.gz', 'case_id')
        groups = review_groups.build_groups(records, cases, decisions, cfg.get('matching_policy'))
        compiled = manual_flags.compile_snapshot(ledger, manual_flags.Inventory.from_records(args.release_id, list(records.values())),
                                                operator=args.operator, persist=False)
        group.need(compiled['status'] == 'accepted', 'manual_flags_compile_blocked')
        values = dict(groups=groups, decisions=decisions, eric_manifest=compiled['manifest'],
                      authorization={**active['proposal']['authorization'], 'partition_groups': [], 'user_exclusion_groups': []},
                      partitions={}, user_exclusions={})
        # All output paths are new. Failure leaves an incomplete directory for
        # inspection; it is never resumed, replaced, or interpreted as approval.
        output.mkdir(mode=0o700)
        inputs = output/'inputs'; inputs.mkdir(mode=0o700)
        files = {k: save(inputs/(k+'.json'), v) for k,v in values.items()}
        files.update(config=config_pin, records=pin(release/'records.jsonl.gz'), cases=pin(release/'cases.jsonl.gz'),
                     source_evidence=evidence_pin)
        base = dict(format=group.BUNDLE_FORMAT, release_id=args.release_id, main_revision=revision,
                    rules_hash=review_core.rules_hash(cfg), files=files)
        base['revision'] = sha(base)
        bp = inputs/'base-bundle.json'; save(bp, base)
        # Native preparation reloads pinned inputs; release assembly payloads first.
        del records, cases, groups, values, compiled, decisions, labels
        gc.collect()
        if historical:
            result = group.prepare_intent_bundle(args.source_bundle, bp, root, output/'review')
            mode = 'historical_migration'
            for created in (output/'review').iterdir():
                created.chmod(0o600)
        else:
            # Already migrated: carry current accepted intents, not an old origin.
            _, data, options = group.load_bundle(bp)
            carry = group._carry_from_active(active, data, options)
            folder = output/'review'; folder.mkdir(mode=0o700)
            base['files']['carry'] = save(folder/'carry.json', carry)
            base['revision'] = sha({k:v for k,v in base.items() if k != 'revision'})
            target = folder/'bundle.json'; save(target, base)
            proposal = group.preview(target); save(folder/'proposal.json', proposal)
            from study2.group_intent_review import review_html
            review = folder/'review.html'
            with review.open('x', encoding='utf-8') as stream: stream.write(review_html(proposal))
            review.chmod(0o600)
            result = dict(bundle=str(target), proposal=str(folder/'proposal.json'), review=str(review))
            mode = 'current_intent_carry'
        if source_pin: pin(args.source_bundle, args.source_sha256)
        pin(args.config, args.config_sha256)
        group._read_file(evidence_pin)
        pin(ledger, args.registry_sha256); pin(release/'checksums.json', checks_pin['sha256'])
        group.need(group.read_active(root)['pointer'] == active['pointer'], 'policy_head_changed')
        report = dict(status='proposed_not_accepted_not_applied', mode=mode, release_id=args.release_id,
                      preparation=result, matching_invoked=False, publication_invoked=False)
        save(output/'result.json', report)
        return report


def parser():
    p = argparse.ArgumentParser(description=__doc__)
    for name in ('config','release-folder','control-root','flag-registry','output',
                 'config-sha256','checksums-sha256','registry-sha256','policy-head',
                 'release-id','publication-id','main-revision','operator'):
        p.add_argument('--'+name, required=True)
    for name in ('source-bundle','source-sha256','source-evidence','source-evidence-sha256'):
        p.add_argument('--'+name)
    return p


def main(argv=None):
    print(json.dumps(prepare(parser().parse_args(argv)), sort_keys=True))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
