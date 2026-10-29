"""Synthetic full-export browser integration through the existing access gate."""
import json
import os
from pathlib import Path
import shutil
import subprocess

import pandas as pd
import pytest

from study2.static_assets import APP_JS
from test_static_release_context import publication
from test_lazy_bootstrap import BROWSER


@pytest.fixture(scope='module')
def exported(tmp_path_factory):
    import study2.static_export as module
    # The generic release fixture intentionally lacks grade capability. Supply
    # it here so the browser exercises actual fine semester assets.
    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(module, 'GROUPS', {'all': 'All'})
        root=tmp_path_factory.mktemp('semester-current-release')
        value,manifest,context=publication(root/'inputs')
        path=value['folder']/'descriptive_measurements.parquet'
        measurements=pd.read_parquet(path)
        measurements['school_stage_status']='valid'
        measurements.to_parquet(path,index=False)
        site=root/'site'
        module.export_static(value['cfg'],site,manual_manifest=manifest,release_context=context,default_eligibility='on')
        yield value,manifest,context,site


def test_semester_panels_fetch_lazily_and_track_on_off_in_full_app(exported):
    value, _, _, site = exported
    assets = {'/' + p.name: p.read_text() for p in site.iterdir()
              if p.is_file() and p.suffix in {'.js', '.css', '.html', '.json'}}
    assets['/app.js'] = APP_JS
    marker = "await page.getByRole('button',{name:'Descriptive statistics',exact:true}).click();await page.locator('.sample-sidebar').waitFor();"
    assert BROWSER.count(marker) == 1
    # This fixture has semester assets. OFF now stays on the bootstrap, so a
    # snapshot download explicitly requests the full bundle for the inherited
    # fail/retry test. A mixed bundle is requested through the overview mode.
    old_failure = "failOnce=true;await page.locator('#manual-exclusion-enabled').click();await page.getByRole('button',{name:'Retry loading',exact:true}).waitFor();"
    new_failure = "await page.locator('#manual-exclusion-enabled').click();await page.locator('.manual-eligibility[data-mode=off]').waitFor();await page.locator('.s2-quality[data-state=ready]').waitFor();failOnce=true;await page.getByRole('button',{name:'Download aggregate snapshot',exact:true}).click();await page.getByRole('button',{name:'Retry loading',exact:true}).waitFor();"
    mixed_page = "await mixed.getByRole('button',{name:'Descriptive statistics',exact:true}).click();"
    assert BROWSER.count(old_failure) == 1 and BROWSER.count(mixed_page) == 1
    script = BROWSER.replace(old_failure, new_failure).replace(mixed_page, mixed_page + "await mixed.getByRole('button',{name:'Research overview',exact:true}).click();")
    checks = r'''
 await page.locator('.semester-panel').first().waitFor();
 await page.waitForFunction(()=>{const panels=[...document.querySelectorAll('.semester-panel')];return panels.length===2&&panels.every(panel=>panel.querySelector('table'));});
 assert.equal(await page.locator('.semester-panel').count(),2);
 assert(requests.includes('/period-semester-on-abcd-student.json'));
 assert(requests.includes('/period-semester-on-abcd-parent.json'));
 assert.equal((await fetch(base+'/period-semester-on-abcd-student.json')).status,401);
 assert(await page.getByLabel('T0',{exact:true}).isChecked());assert(await page.getByLabel('T1',{exact:true}).isChecked());
 const csvWait=page.waitForEvent('download');
 await page.locator('.semester-panel').first().getByRole('button',{name:'Download current table (CSV)',exact:true}).first().click();
 const csvText=fs.readFileSync(await (await csvWait).path(),'utf8');
 assert(csvText.includes('active_on_revision')&&csvText.includes('academic_years')&&csvText.includes('date_provenance'));
 await page.locator('#manual-exclusion-enabled').click();
 await page.locator('.manual-eligibility[data-state=ready][data-mode=off]').waitFor();
 await page.waitForFunction(()=>{const panels=[...document.querySelectorAll('.semester-panel')];return panels.length===2&&panels.every(panel=>panel.querySelector('table'));});
 assert(requests.includes('/period-semester-off-abcd-student.json'));
 assert(requests.includes('/period-semester-off-abcd-parent.json'));
 await page.locator('#manual-exclusion-enabled').click();
 await page.locator('.manual-eligibility[data-state=ready][data-mode=on]').waitFor();
 await page.waitForFunction(()=>{const panels=[...document.querySelectorAll('.semester-panel')];return panels.length===2&&panels.every(panel=>panel.querySelector('table'));});
'''
    script = script.replace(marker, marker + checks)
    modules = Path(os.environ.get('SOURCE_UI_NODE_MODULES', Path.home()/'.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules'))
    result = subprocess.run([shutil.which('node'), '--input-type=commonjs', '-e', script],
        input=json.dumps(dict(assets=assets,accessModule=(site/'server/access-core.js').as_uri(),
                              release=value['summary']['release_id'])), text=True, capture_output=True,
        env={**os.environ,'NODE_PATH':str(modules)},timeout=120)
    assert result.returncode == 0, result.stdout + result.stderr
    assert json.loads(result.stdout)['status'] == 'passed'
