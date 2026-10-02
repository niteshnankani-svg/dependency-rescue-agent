'use strict';
const $ = id => document.getElementById(id);
let available = [], runs = [], selected = null, current = null, refreshing = false;
let submitting = false, deciding = false, activeTab = 'overview', historySignature = '', detailSignature = '';
let lastHealth = 0, pendingDecision = null, auditVersion = 0;
const labels = {awaiting_approval:'Awaiting review',completed:'Exported',needs_engineer:'Needs engineer',blocked:'Blocked',queued:'Queued',running:'Running',cancelled:'Cancelled',rejected:'Rejected',retry:'Retrying',approved:'Exporting'};
function notice(message, error = false) { $('notice').textContent = message; $('notice').dataset.error = String(error); }
async function api(path, options = {}) {
  const controller = new AbortController(), timer = setTimeout(() => controller.abort(), 20000);
  try {
    const response = await fetch(path, {...options, signal:controller.signal, headers:{'Content-Type':'application/json',...options.headers}});
    const body = await response.json().catch(() => ({}));
    if (!response.ok) {
      if (response.status === 401) $('login').hidden = false;
      throw new Error(typeof body.detail === 'string' ? body.detail : `Request failed (${response.status}). Please try again.`);
    }
    return body;
  } catch (error) {
    if (error.name === 'AbortError') throw new Error('The request timed out. Check the connection before trying again.');
    throw error;
  } finally { clearTimeout(timer); }
}
function metric(result) { return result ? `${result.passes} / ${result.tests}` : '—'; }
function workflow(id) { return available.find(item => item.id === id); }
function node(tag, text, className) { const element = document.createElement(tag); element.textContent = text; if (className) element.className = className; return element; }
function prettyTime(seconds) { return seconds ? new Date(seconds * 1000).toLocaleString(undefined,{month:'short',day:'numeric',hour:'2-digit',minute:'2-digit'}) : ''; }
function drawRuns() {
  $('count').textContent = runs.length;
  $('stat-review').textContent = runs.filter(run => run.status === 'awaiting_approval').length;
  $('stat-done').textContent = runs.filter(run => run.status === 'completed').length;
  const search = $('search').value.trim().toLowerCase(), filter = $('filter').value;
  const matches = runs.filter(run => {
    const c = workflow(run.case_id);
    return `${c?.repository || ''} ${c?.dependency || ''} ${run.id}`.toLowerCase().includes(search) &&
      (filter === 'all' || (filter === 'active' ? ['queued','running','retry','approved'].includes(run.status) : filter === 'attention' ? ['blocked','needs_engineer','rejected','cancelled'].includes(run.status) : run.status === filter));
  });
  const signature = JSON.stringify([matches,selected]);
  if (signature === historySignature) return;
  historySignature = signature; $('runs').replaceChildren();
  if (!matches.length) { $('runs').append(node('p', runs.length ? 'No matching runs. Try another search or filter.' : 'No repairs yet. Start your first workflow above.', 'list-empty')); return; }
  for (const run of matches) {
    const c = workflow(run.case_id), button = node('button','', 'run' + (run.id === selected ? ' selected' : ''));
    button.type = 'button'; button.setAttribute('aria-pressed', String(run.id === selected));
    button.append(node('b', c?.repository || run.case_id || 'Repair run'), node('small',labels[run.status] || run.status));
    const meta = node('span','','run-meta'); meta.append(node('span',run.id.slice(0,8),'run-id'),node('span',prettyTime(run.created))); button.append(meta);
    button.addEventListener('click', () => selectRun(run.id)); $('runs').append(button);
  }
}
async function selectRun(id) {
  selected = id; current = null; detailSignature = ''; drawRuns();
  $('detail').hidden = true; $('empty').hidden = false;
  try { const state = await api(`/api/runs/${id}`); if (selected === id) { render(state); if (activeTab === 'activity') loadAudit(); } }
  catch (error) { if (selected === id) notice(error.message, true); }
}
function renderPatch(patch) {
  $('diff').replaceChildren();
  if (!patch) { $('diff').textContent = 'A verified patch will appear here after successful validation.'; $('file-count').textContent = '0'; return; }
  const lines = patch.split('\n');
  $('file-count').textContent = lines.filter(line => line.startsWith('+++ b/')).length;
  // Large lockfiles remain complete in copy/download; bound the live DOM for responsiveness.
  const fragment = document.createDocumentFragment();
  for (const line of lines.slice(0,1500)) {
    const kind = /^(---|\+\+\+|@@)/.test(line) ? 'diff-header' : line.startsWith('+') ? 'diff-add' : line.startsWith('-') ? 'diff-remove' : '';
    fragment.append(node('span',line || ' ',`diff-line ${kind}`));
  }
  if (lines.length > 1500) fragment.append(node('span',`\nPreview limited to 1,500 of ${lines.length.toLocaleString()} lines. Copy or download the complete patch.`,'diff-header'));
  $('diff').append(fragment);
}
function render(state) {
  if (state.run_id !== selected) return;
  current = state;
  const signature = JSON.stringify(state);
  if (signature === detailSignature) return;
  detailSignature = signature;
  const c = workflow(state.case_id || runs.find(run => run.id === selected)?.case_id);
  $('empty').hidden = true; $('detail').hidden = false;
  $('run-title').textContent = c ? `${c.repository} / ${c.dependency}` : 'Repair run';
  $('run-context').textContent = `Run ${state.run_id.slice(0,12)}${state.model_usage?.model ? ' · '+state.model_usage.model : ''}`;
  $('status').textContent = (labels[state.status] || state.status).toUpperCase(); $('status').dataset.status = state.status;
  $('baseline').textContent = metric(state.baseline); $('broken').textContent = metric(state.broken); $('verified').textContent = metric(state.verification);
  const extra = state.verification?.additional_checks || [];
  $('additional-checks').textContent = extra.map(check => `${check.command?.join(' ').includes('tsd') ? 'TypeScript validation' : 'Additional validation'}: ${check.ok ? 'passed' : 'failed'}`).join(' · ');
  $('trace').replaceChildren();
  for (const event of state.events || []) {
    const row = node('li',''), content = node('div',''); content.append(node('strong',event.node),node('p',event.detail)); row.append(content); $('trace').append(row);
  }
  $('diagnosis').textContent = state.repair?.diagnosis || 'The agent will explain its diagnosis after reproducing the regression.';
  renderPatch(state.patch); $('copy-patch').disabled = !state.patch;
  $('review').hidden = state.status !== 'awaiting_approval';
  $('approve').disabled = deciding || !state.case_digest; $('reject').disabled = deciding;
  $('download').hidden = state.status !== 'completed'; $('download').href = `/api/runs/${state.run_id}/patch`;
  $('cancel').hidden = !['queued','running','awaiting_approval'].includes(state.status);
  $('failure').textContent = state.error || (state.status === 'awaiting_approval' && !state.case_digest ? 'This older run lacks current integrity evidence. Start a fresh repair before export.' : '');
}
async function health() {
  if (Date.now() - lastHealth < 30000) return;
  lastHealth = Date.now();
  try {
    const response = await fetch('/readyz',{signal:AbortSignal.timeout(10000)}), value = await response.json();
    $('connection').dataset.state = value.ready ? 'ready' : 'error';
    $('connection-text').textContent = value.ready ? 'Systems ready' : !value.model_ready ? 'Model unavailable' : !value.executor_ready ? 'Worker unavailable' : 'Setup required';
  } catch { $('connection').dataset.state = 'error'; $('connection-text').textContent = 'Connection unavailable'; }
}
async function refresh() {
  if (refreshing || deciding) return;
  refreshing = true;
  try {
    runs = await api('/api/runs'); drawRuns();
    if (!selected && runs.length) { selected = runs[0].id; drawRuns(); }
    if (selected) { const id = selected, state = await api(`/api/runs/${id}`); if (id === selected) render(state); }
  } catch (error) { notice(error.message,true); }
  finally { refreshing = false; }
}
function showCase() {
  const c = workflow($('case').value); if (!c) return;
  $('case-title').textContent = c.dependency+' compatibility repair'; $('repository').textContent = c.repository;
  $('case-scope').textContent = `${c.license} · ${c.scope}${c.ready ? '' : ' · Setup required'}`;
  $('from-version').textContent = `${c.dependency} ${c.from}`; $('to-version').textContent = c.to;
  $('start').disabled = submitting || !c.ready;
}
async function loadCases() {
  available = await api('/api/cases'); $('case').replaceChildren();
  for (const c of available) { const option = node('option',`${c.repository} / ${c.dependency}`); option.value = c.id; $('case').append(option); }
  $('case').disabled = !available.length; $('stat-cases').textContent = available.length; showCase();
}
async function loadAudit() {
  const id = selected, version = ++auditVersion; if (!id) return;
  $('audit').replaceChildren(node('li','Loading audit history…'));
  try {
    const entries = await api(`/api/runs/${id}/audit`);
    if (selected !== id || version !== auditVersion) return;
    $('audit').replaceChildren();
    for (const entry of entries) {
      const row = node('li',''), content = node('div','');
      content.append(node('strong',entry.action.replaceAll('_',' ')),node('p',`By ${entry.actor}`),node('time',prettyTime(entry.time))); row.append(content); $('audit').append(row);
    }
    if (!entries.length) $('audit').append(node('li','No audit events have been recorded for this run.'));
  } catch (error) { if (id === selected) $('audit').replaceChildren(node('li',error.message)); }
}
function selectTab(name, focus = false) {
  activeTab = name;
  document.querySelectorAll('[data-tab]').forEach(button => { const active = button.dataset.tab === name; button.setAttribute('aria-selected',String(active)); button.tabIndex = active ? 0 : -1; $(`panel-${button.dataset.tab}`).hidden = !active; if (active && focus) button.focus(); });
  if (name === 'activity') loadAudit();
}
document.querySelectorAll('[data-tab]').forEach(button => {
  button.addEventListener('click',() => selectTab(button.dataset.tab));
  button.addEventListener('keydown',event => { const tabs = ['overview','changes','activity']; let index = tabs.indexOf(activeTab); if (event.key === 'ArrowRight') index = (index+1)%3; else if (event.key === 'ArrowLeft') index = (index+2)%3; else if (event.key === 'Home') index=0; else if (event.key === 'End') index=2; else return; event.preventDefault(); selectTab(tabs[index],true); });
});
$('search').addEventListener('input',drawRuns); $('filter').addEventListener('change',drawRuns); $('case').addEventListener('change',showCase);
$('start').addEventListener('click',async () => {
  if (submitting) return; submitting = true; showCase(); notice('Queueing the selected workflow…');
  try { const result = await api('/api/runs',{method:'POST',body:JSON.stringify({case_id:$('case').value,idempotency_key:crypto.randomUUID()})}); notice('Repair queued. The agent will stop for your review.'); await selectRun(result.run_id); await refresh(); }
  catch (error) { notice(error.message,true); } finally { submitting = false; showCase(); }
});
function requestDecision(kind) {
  if (!current) return;
  pendingDecision = {kind,id:selected,digest:current.evidence_digest};
  $('decision-title').textContent = kind === 'approve' ? 'Approve this patch?' : kind === 'reject' ? 'Reject this repair?' : 'Cancel this run?';
  $('decision-description').textContent = kind === 'approve' ? 'This exports the exact verified patch for this run. It does not merge or deploy it. Confirm that you have reviewed the Changes tab.' : kind === 'reject' ? 'The proposed repair will be marked rejected and cannot be exported from this review.' : 'The agent will stop at the next cancellation checkpoint. The run and its evidence remain in your history.';
  $('confirm-decision').textContent = kind === 'approve' ? 'Approve export' : kind === 'reject' ? 'Reject repair' : 'Cancel run';
  $('decision-dialog').returnValue = '';
  $('decision-dialog').showModal();
}
$('approve').onclick = () => requestDecision('approve'); $('reject').onclick = () => requestDecision('reject'); $('cancel').onclick = () => requestDecision('cancel');
$('decision-dialog').addEventListener('close',async () => {
  const decision = pendingDecision; pendingDecision = null;
  if ($('decision-dialog').returnValue !== 'confirm' || !decision || deciding) return;
  deciding = true; $('approve').disabled = $('reject').disabled = true;
  try {
    if (decision.kind === 'cancel') await api(`/api/runs/${decision.id}/cancel`,{method:'POST'});
    else await api(`/api/runs/${decision.id}/decision`,{method:'POST',body:JSON.stringify({approve:decision.kind === 'approve',evidence_digest:decision.digest})});
    notice(decision.kind === 'approve' ? 'Review decision recorded. Check the run status for export completion.' : decision.kind === 'reject' ? 'Repair rejected.' : 'Cancellation requested.');
    detailSignature = '';
  } catch (error) { notice(error.message,true); }
  finally { deciding = false; detailSignature = ''; await refresh(); if (activeTab === 'activity') loadAudit(); }
});
$('copy-patch').addEventListener('click',async () => { try { await navigator.clipboard.writeText(current?.patch || ''); notice('Complete patch copied to clipboard.'); } catch { notice('Clipboard access is unavailable. Select the patch text, or download it after approval.',true); } });
$('login').addEventListener('submit',async event => {
  event.preventDefault();
  try { await api('/api/session',{method:'POST',headers:{Authorization:'Bearer '+$('access-token').value}}); $('access-token').value=''; $('login').hidden=true; notice('Signed in.'); await loadCases(); await refresh(); }
  catch (error) { notice(error.message,true); }
});
async function poll() { if (!document.hidden) { await refresh(); health(); } setTimeout(poll,5000); }
(async () => { if (document.body.dataset.hosted === 'standalone') { $('hosting-note').hidden=false; $('search').disabled=true; $('filter').disabled=true; $('connection-text').textContent='Backend not connected'; $('connection').dataset.state='error'; $('case').replaceChildren(node('option','Backend connection required')); $('repository').textContent='Connect a hosted API to load workflows'; $('runs').replaceChildren(node('p','No backend connected. Your runs will appear here after setup.','list-empty')); const docsLink=document.querySelector('a[href="/docs"]'); docsLink.href='https://github.com/niteshnankani-svg/dependency-rescue-agent'; docsLink.textContent='Project documentation ↗'; return; } try { await loadCases(); await refresh(); } catch (error) { notice(error.message,true); } health(); setTimeout(poll,5000); })();
