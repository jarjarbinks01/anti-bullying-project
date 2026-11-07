"""Single selected-child dashboard client assembly.

The former legacy APP_JS/STYLES assembly was immediately overwritten. The
accepted client now has one readable source, with strict control insertion.
"""
from .static_controls import JS_SOURCE as CONTROLS_JS
from .selected_client_integration import assemble

HTML = r'''<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="robots" content="noindex,nofollow"><title>Study 2 Research Dashboard</title>
<link rel="stylesheet" href="styles.css"><script defer src="snapshot.js"></script><script defer src="scope-index.js"></script><script defer src="scope-engine.js"></script><script defer src="quality-ui.js"></script><script defer src="app.js"></script><script defer src="access.js"></script></head>
<body><a class="skip" href="#content">Skip to content</a>
<header><div class="identity"><span class="mark" aria-hidden="true">S2</span><div>
<p class="eyebrow">HKU · ANTI-BULLYING RESEARCH</p><h1>Study 2 Research Dashboard</h1></div></div>
<div class="edition"><span class="status"><i></i>Published aggregate snapshot</span><span id="published">Loading</span><button id="sign-out" class="quiet" hidden>Sign out of the research workspace</button></div></header>
<div class="shell"><div id="load-status" class="notice" role="status">Loading the aggregate snapshot. If no result appears, check that snapshot.js is complete.</div><div class="release"><details class="release-details"><summary>Release version and scope of use</summary>
<p id="banner" class="caption">Loading the static release. If this message stays, check that snapshot.js is complete.</p><p id="version" class="meta"></p></details>
<button id="download-snapshot" class="quiet">Download aggregate snapshot</button></div>
<nav id="nav" aria-label="Study 2 research pages"></nav><main id="content" tabindex="-1"></main>
<footer>HKU - Study 2 anti-bullying research　<span id="footer-version"></span><br>Read-only aggregate snapshot - no research database connection - no individual submission detail</footer></div>
<noscript><p>This interactive page needs JavaScript. All data comes only from the aggregate snapshot supplied with the page.</p></noscript></body></html>'''

CONTROL_RENDER = r'''
function controlStatus(){
 const host=section('Historical decisions and evidence holds','Captured release-wide control status. Analytical ON/OFF, sample, source and date filters do not change these totals. Counts use different units and must not be added.');
 let rows;try{rows=Study2Controls.rows(S.controls_status,S.release_id,S.release_context);}catch{notice(host,'Control-status evidence is unavailable or incompatible. Unavailable does not mean zero.');return;}
 const v=S.controls_status;
 const part=(title,name,note)=>{const box=el('div','panel');box.append(el('h3','',title));host.append(box);table(box,rows[name],{item:'Status',count:'Count',unit:'Unit'},'controls-'+name);notice(box,note);};
 part('Earlier decisions · unapplied candidate','historical','Recorded decisions remain local. A pending status does not request a new identity answer or grant approval.');
 part('Burst evidence · unapplied candidate','burst','Scopes and distinct submission records are separate units. Holds do not create new exclusions.');
 part('Carried closure status · applied to this release','applied_carry','These counts require the live-validated applied workload. Source-only holds are outside the raw target denominator.');
 part('Carried closure plan · unapplied candidate','candidate_carry','A proposed preservation is not an applied closure. Source-only holds are unavailable when this preview does not establish them.');
 const target=v.historical.target_release_id||v.burst.target_release_id||v.candidate_carry.target_release_id;
 host.append(el('p','notice controls-provenance',`Displayed release: ${v.release_id}. Candidate target: ${target||'Unavailable'}. Integrity revision: ${v.revision}. Revision hashes identify captured inputs; they are not independent approval.`));
}
'''

APP_JS, STYLES = assemble(CONTROLS_JS, CONTROL_RENDER)
