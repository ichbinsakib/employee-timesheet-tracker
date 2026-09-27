import { api, download } from '../services/api.js';
import { badge, bindRows, esc, fmt, modal, niceDate, niceDateTime, sevBadge, statusBadge, table, toast, withBusy } from '../components/ui.js';

const state = { status: '' };

export async function render(el, ctx) {
  const [gmail, subs, jobs] = await Promise.all([
    api.get('/api/imports/gmail-status'),
    api.get('/api/imports/submissions', { status: state.status, limit: 200 }),
    api.get('/api/imports/jobs', { limit: 30 }),
  ]);
  if (!ctx.isCurrent()) return;
  const canImport = ctx.user.role !== 'viewer';
  const isAdmin = ctx.user.role === 'admin';

  el.innerHTML = `
    <div class="page-head"><h1>Imports</h1>
      <div class="toolbar">${canImport ? `<button id="sync" class="primary">Sync Gmail Now</button>
        <label class="btn">Upload Excel…<input type="file" id="file" accept=".xlsx,.xlsm" class="hidden" multiple></label>` : ''}</div></div>

    <div class="grid cols-2">
      <div class="card"><h2>Gmail connection</h2>
        <p>${gmail.connected ? badge('Connected', 'good') : badge('Not connected', 'warning')}</p>
        ${gmail.error ? `<p class="small">${esc(gmail.error)}</p>` : ''}
        ${!gmail.connected ? `<div class="notice small">To connect: on the desktop, put the Google OAuth file in the <b>secrets</b> folder as <code>${esc(gmail.credentials_file)}</code>, then run <code>scripts\\gmail_auth.bat</code>. See docs/GMAIL_SETUP.md.</div>` : ''}
        <p class="small muted" style="margin-top:10px">Last check: ${gmail.last_run ? `${esc(niceDateTime(gmail.last_run.at))} – ${esc(gmail.last_run.message || gmail.last_run.status)}` : 'never'}<br>
          Last successful check: ${esc(niceDateTime(gmail.last_success))} · Next automatic check: ${esc(niceDateTime(gmail.next_run))}<br>
          Emails looked at so far: ${fmt(gmail.messages_seen)}</p>
      </div>
      <div class="card"><h2>How imports work</h2>
        <p class="small">Every few minutes the desktop checks Gmail for emails with an Excel attachment, reads the timesheet, checks it, and stores it. Each email is processed once. An identical file sent again is skipped. A <b>different</b> file for the same person and date replaces the earlier one (a corrected timesheet).</p>
        <p class="small muted">If the desktop was off, anything that arrived in the last few days is picked up when it starts again.</p>
      </div>
    </div>

    <div class="card">
      <div class="card-head"><h2>Received timesheets</h2>
        <select id="status">${[['', 'All'], ['imported', 'Imported'], ['imported_with_warnings', 'With warnings'], ['failed', 'Failed'], ['duplicate', 'Duplicates'], ['superseded', 'Replaced']]
          .map(([v, l]) => `<option value="${v}" ${state.status === v ? 'selected' : ''}>${l}</option>`).join('')}</select></div>
      <div id="subs">${table([
        { label: 'Received', render: s => esc(niceDateTime(s.email_time || s.imported_at)) },
        { label: 'Employee', render: s => s.employee_id ? `<a href="#/employees/${s.employee_id}">${esc(s.employee)}</a>` : '<span class="muted">unknown</span>' },
        { label: 'Work date', render: s => esc(niceDate(s.work_date)) },
        { label: 'File', render: s => `${esc(s.filename)}<div class="muted small">${esc(s.source === 'gmail' ? (s.sender || '') : 'uploaded')}</div>` },
        { label: 'Status', render: s => statusBadge(s.status) + (s.error ? `<div class="small">${esc(s.error)}</div>` : '') },
        { label: 'Issues', render: s => Object.entries(s.issue_counts || {}).filter(([k]) => k !== 'info').map(([k, n]) => `${n} ${k}`).join(', ') || '—' },
        { label: 'Rows', key: 'entries', num: true },
        { label: 'Hours', key: 'hours', num: true },
      ], subs, { onRow: true, empty: 'No timesheets received yet.' })}</div>
    </div>

    <div class="card"><h2>Background activity</h2>${table([
      { label: 'When', render: j => esc(niceDateTime(j.started_at)) },
      { label: 'Job', render: j => esc({ gmail_sync: 'Gmail check', backup: 'Backup', daily_report: 'Daily report' }[j.job] || j.job) },
      { label: 'Started by', render: j => esc(j.trigger) },
      { label: 'Result', render: j => statusBadge(j.status) },
      { label: 'Details', render: j => `<span class="small">${esc(j.message || '')}</span>` },
    ], jobs, { empty: 'Nothing has run yet.' })}</div>`;

  el.querySelector('#status').addEventListener('change', (e) => { state.status = e.target.value; render(el, ctx); });
  bindRows(el.querySelector('#subs'), subs, (s) => showSubmission(s.id, isAdmin, () => render(el, ctx)));
  el.querySelector('#sync')?.addEventListener('click', (e) => withBusy(e.currentTarget, async () => {
    const r = await api.post('/api/imports/sync');
    toast(r.message || r.status, r.status !== 'ok');
    render(el, ctx);
  }).catch(err => toast(err.message, true)));
  el.querySelector('#file')?.addEventListener('change', async (e) => {
    const files = [...e.target.files];
    const results = [];
    for (const f of files) {
      try { results.push(...await api.upload('/api/imports/upload', f)); }
      catch (err) { results.push({ filename: f.name, status: 'failed', error: err.message, issues: [] }); }
    }
    await modal('Upload results', results.map(r => `
      <div class="card"><div class="card-head"><h2>${esc(r.filename)}</h2>${statusBadge(r.status)}</div>
        ${r.employee ? `<p class="small">${esc(r.employee)} · ${esc(niceDate(r.work_date))} · ${fmt(r.entries)} row(s) · ${fmt(r.hours, 2)} h</p>` : ''}
        ${r.error ? `<p class="small">${esc(r.error)}</p>` : ''}
        ${issueTable(r.issues)}</div>`).join(''), { wide: true });
    render(el, ctx);
  });
}

function issueTable(issues) {
  if (!issues || !issues.length) return '';
  return table([{ label: 'Level', render: i => sevBadge(i.severity) }, { label: 'Row', render: i => esc(i.excel_row ?? '') },
    { label: 'Detail', render: i => esc(i.message) }], issues);
}

async function showSubmission(id, isAdmin, refresh) {
  const s = await api.get(`/api/imports/submissions/${id}`);
  const actions = [{ label: 'Close' }];
  if (s.has_file) actions.unshift({ label: 'Download original file', onClick: async () => { await download(`/api/imports/submissions/${id}/file`, null, s.filename); return false; } });
  if (isAdmin && s.status !== 'duplicate') actions.unshift({
    label: 'Remove this import', cls: 'danger', onClick: async () => {
      if (!confirm('Remove this timesheet and its rows from the database? The original file stays in the imports folder.')) return false;
      await api.del(`/api/imports/submissions/${id}`);
      toast('Removed');
      refresh();
      return true;
    },
  });
  modal(s.filename, `
    <p>${statusBadge(s.status)} ${s.duplicate_status !== 'unique' ? badge(s.duplicate_status.replace('_', ' '), 'info') : ''}</p>
    <p class="small">${s.source === 'gmail' ? `From ${esc(s.sender || '—')} · “${esc(s.subject || '')}” · ${esc(niceDateTime(s.email_time))}` : 'Uploaded manually'}<br>
      Employee: ${esc(s.employee || '—')} · Work date: ${esc(niceDate(s.work_date))} · ${fmt(s.entries)} row(s) · ${fmt(s.hours, 2)} h${s.declared_total !== null ? ` (sheet total says ${fmt(s.declared_total, 2)} h)` : ''}</p>
    ${s.error ? `<p class="error-text">${esc(s.error)}</p>` : ''}
    ${issueTable(s.issues) || '<p class="muted">No issues found.</p>'}`, { actions, wide: true });
}
