"""Synthetic startup trust and historical-verifier compatibility contract."""
from copy import deepcopy
import hashlib
import json

import pytest

from study2 import compatibility_profiles as trust, continuity_integration as integration
from study2.analysis_eligibility import sha
from test_intent_continuity_compat import build_fixture, TARGET


@pytest.fixture(autouse=True)
def isolated_trust(monkeypatch):
    monkeypatch.setattr(trust, 'CONTINUITY_PROFILES', {})
    monkeypatch.setattr(trust, 'ADMINISTRATIVE_PREVIEW', {})
    monkeypatch.setattr(trust, '_HISTORICAL_VERIFIERS', {})
    monkeypatch.setattr(trust, '_SCOPE_SHA256', None)
    monkeypatch.setattr(trust, '_CONFIGURED_SHA256', None)


def document(profile=None, old='a'*64):
    profiles = {} if profile is None else {profile['target_release_id']: profile}
    return dict(format=trust.FORMAT, continuity_profiles=profiles, administrative_preview=None,
                administrative_scope_sha256=None, historical_verifiers=[] if profile is None else [
                    dict(contract=trust.VERIFIER_CONTRACT, profile_revision=sha(profile),
                         implementation_revisions=[old])])


def write(tmp_path, value):
    path = tmp_path/'synthetic-trust.json'
    raw = json.dumps(value).encode()
    path.write_bytes(raw)
    return path, hashlib.sha256(raw).hexdigest()


def test_default_does_not_trust_caller_claims():
    profile = {'target_release_id': 'SYNTHETIC'}
    assert trust.CONTINUITY_PROFILES == {}
    assert not trust.accepts_historical_implementation(profile, 'a'*64, 'b'*64)
    assert trust.accepts_historical_implementation(profile, 'b'*64, 'b'*64)
    assert trust.administrative_scope_sha256() is None


def test_pinned_configuration_is_atomic_idempotent_and_not_replaceable(tmp_path):
    profile = {'target_release_id': 'SYNTHETIC'}
    path, pin = write(tmp_path, document(profile))
    with pytest.raises(ValueError, match='file_hash_changed'):
        trust.configure_trust(path, 'f'*64)
    assert not trust.CONTINUITY_PROFILES
    trust.configure_trust(path, pin)
    trust.configure_trust(path, pin)
    assert trust.accepts_historical_implementation(profile, 'a'*64, 'b'*64)
    assert not trust.accepts_historical_implementation({**profile, 'changed': True}, 'a'*64, 'b'*64)
    path, other = write(tmp_path, document())
    with pytest.raises(ValueError, match='already_configured'):
        trust.configure_trust(path, other)
    assert trust.CONTINUITY_PROFILES == {'SYNTHETIC': profile}


@pytest.mark.parametrize('change', ['contract', 'profile_revision', 'implementation_revisions'])
def test_unrecognized_or_unbound_contract_is_rejected(tmp_path, change):
    value = document({'target_release_id': 'SYNTHETIC'})
    value['historical_verifiers'][0][change] = [] if change == 'implementation_revisions' else 'unknown'
    path, pin = write(tmp_path, value)
    with pytest.raises(ValueError, match='compatibility_'):
        trust.configure_trust(path, pin)
    assert not trust.CONTINUITY_PROFILES and trust._CONFIGURED_SHA256 is None


def test_historical_identity_keeps_full_proof_and_receipt_checks(tmp_path, monkeypatch):
    data, opts, profile, *_ = build_fixture(monkeypatch)
    proposal = integration.bound_proposal(data, opts)
    old_revision = proposal['base']['implementation_revision']
    policy = {'policy_active': True, 'release_id': TARGET,
              'proposal_revision': proposal['revision'],
              'historical_continuity_revision': proposal['historical_continuity']['revision'],
              'partitions': proposal['partitions'], 'inventory_revision': profile['target_inventory_revision'],
              'main_revision': opts['main_revision']}
    receipt = {'review': {'accepted': True, 'proposal_revision': proposal['revision']}}
    monkeypatch.setattr(integration, 'implementation_revision', lambda: 'b'*64)
    with pytest.raises(Exception, match='continuity_generation_binding_changed'):
        integration.check_generation(policy, proposal, receipt)
    trust.configure_trust(*write(tmp_path, document(profile, old_revision)))
    integration.check_generation(policy, proposal, receipt)
    bad = deepcopy(receipt); bad['review']['accepted'] = False
    with pytest.raises(Exception, match='continuity_generation_review_missing'):
        integration.check_generation(policy, proposal, bad)
    bad = deepcopy(proposal); bad['historical_continuity']['proof']['scientific_identity_changed'] = True
    with pytest.raises(Exception, match='continuity_generation_binding_changed'):
        integration.check_generation(policy, bad, receipt)
    with pytest.raises(Exception, match='continuity_proposal_or_context_changed'):
        # Historical identity is not permission to submit changed evidence.
        integration.validate_bound(bad, data, opts)
