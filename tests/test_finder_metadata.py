from pathlib import Path
import os
import pytest
from study2 import lean_recovery as lean, group_cleaning_operator as group, checkpoints

def fixture(tmp_path):
    state=tmp_path/'state';state.mkdir();controls=tmp_path/'controls';controls.mkdir()
    (controls/'CURRENT.json').write_text('{}')
    return {'state_dir':str(state),'recovery_policy':{'mode':'lean','required_assets':[{'path':str(controls),'kind':'directory','restore_path':'dependencies/policy'}]}},controls

def test_exact_owned_finder_metadata_is_not_a_control_or_recovery_asset(tmp_path):
    cfg,root=fixture(tmp_path);(root/'.DS_Store').write_bytes(b'Finder metadata')
    assert group._control_root(root)==root
    assets=lean.recovery_assets(cfg)
    assert list(assets)==['dependencies/policy/CURRENT.json']
    (root/'.DS_Store').unlink();(root/'.DS_Store').write_bytes(b'recreated metadata')
    assert lean.recovery_assets(cfg)==assets

@pytest.mark.parametrize('kind',['symlink','directory','foreign_uid','hardlink'])
def test_unsafe_metadata_rejected(tmp_path,monkeypatch,kind):
    cfg,root=fixture(tmp_path);p=root/'.DS_Store'
    if kind=='symlink':p.symlink_to(root/'CURRENT.json')
    elif kind=='directory':p.mkdir()
    elif kind=='hardlink':os.link(root/'CURRENT.json',p)
    else:p.write_bytes(b'Finder');monkeypatch.setattr(lean.os,'getuid',lambda:os.stat(p).st_uid+1)
    with pytest.raises(Exception):group._control_root(root)
    with pytest.raises(Exception):lean.recovery_assets(cfg)

@pytest.mark.parametrize('name',['.DS_Store.extra','.OtherMetadata','unexpected.json'])
def test_other_unknown_files_remain_blocked(tmp_path,name):
    cfg,root=fixture(tmp_path);(root/name).write_text('{}')
    with pytest.raises(Exception,match='foreign_control_directory'):group._control_root(root)

def test_real_control_changes_remain_inventory_changes(tmp_path):
    cfg,root=fixture(tmp_path);before=lean.recovery_assets(cfg);(root/'gen_new').mkdir();(root/'gen_new/new.json').write_text('{}')
    assert lean.recovery_assets(cfg)!=before
    with pytest.raises(Exception,match='foreign_control_directory'):group._control_root(root)

def test_explicit_metadata_asset_is_still_captured(tmp_path):
    cfg,controls=fixture(tmp_path);p=controls/'.DS_Store';p.write_bytes(b'explicitly declared asset')
    cfg['recovery_policy']['required_assets'].append({'path':str(p),'kind':'file','restore_path':'dependencies/explicit/metadata'})
    assert lean.recovery_assets(cfg)['dependencies/explicit/metadata']==p


from test_lean_recovery import lean as lean_config

@pytest.mark.parametrize('exists_before',[False,True])
def test_actual_checkpoint_survives_finder_recreation(lean_config,tmp_path,monkeypatch,exists_before):
    root=tmp_path/'policy';root.mkdir();(root/'CURRENT.json').write_text('{"authority":"unchanged"}')
    lean_config['recovery_policy']['required_assets']=[{'path':str(root),'kind':'directory','restore_path':'dependencies/policy'}]
    if exists_before:(root/'.DS_Store').write_bytes(b'before')
    original=checkpoints._capture_assets
    def capture(*args,**kwargs):
        original(*args,**kwargs)
        (root/'.DS_Store').write_bytes(b'Finder recreated or changed this while capture ran')
    monkeypatch.setattr(checkpoints,'_capture_assets',capture)
    result=checkpoints.save_checkpoint(lean_config,force=True)
    assert result['verified_recovery'] is True
    manifest=checkpoints.checkpoint_manifest(result['path'])
    assert not any(Path(k).name=='.DS_Store' for k in manifest['files'])
    assert 'dependencies/policy/CURRENT.json' in manifest['files']
    assert (root/'CURRENT.json').read_text()=='{"authority":"unchanged"}'
