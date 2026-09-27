import { api } from '../services/api.js';
import { badge, esc, fmt, formValues, modal, niceDateTime, table, toast, withBusy } from '../components/ui.js';

const state = { tab: 'general' };
const TABS = [
  ['general', 'Automation', 'viewer'], ['backups', 'Backups', 'manager'], ['rules', 'Categories & rules', 'viewer'],
  ['users', 'Users', 'admin'], ['access', 'Access log', 'admin'], ['account', 'My account', 'viewer'], ['system', 'System', 'viewer'],
];
const RANK = { viewer: 0, manager: 1, admin: 2 };

export async function render(el, ctx) {
  const role = ctx.user.role;
  const tabs = TABS.filter(t => RANK[role] >= RANK[t[2]]);
  if (!tabs.find(t => t[0] === state.tab)) state.tab = 'general';
  el.innerHTML = `<div class="page-head"><h1>Settings</h1></div>
    <div class="tabs">${tabs.map(([k, l]) => `<button data-t="${k}" class="${state.tab === k ? 'on' : ''}">${l}</button>`).join('')}</div>
    <div id="tab"><p class="muted">Loading…</p></div>`;
  el.querySelectorAll('.tabs button').forEach(b => b.addEventListener('click', () => { state.tab = b.dataset.t; render(el, ctx); }));
  const box = el.querySelector('#tab');
  const views = { general, backups, rules, users, access, account, system };
  await views[state.tab](box, ctx, () => render(el, ctx));
}

// ------------------------------------------------------------------ automation settings
async function general(box, ctx, refresh) {
  const { values } = await api.get('/api/settings');
  const admin = ctx.user.role === 'admin';
  const f = (key, label, help, type = 'text') => `<label class="field">${esc(label)}<input name="${key}" type="${type}" value="${esc(values[key])}" ${admin ? '' : 'disabled'}>${help ? `<span class="muted">${esc(help)}</span>` : ''}</label>`;
  box.innerHTML = `<div class="card"><h2>Gmail</h2><div class="form-grid">
      ${f('sync_interval_minutes', 'Check Gmail every (minutes)', '', 'number')}
      ${f('gmail_lookback_days', 'Look back (days)', 'Covers time the desktop was off.', 'number')}
      ${f('gmail_query', 'Gmail search', 'Gmail search syntax; e.g. add subject:timesheet')}
      ${f('gmail_allowed_senders', 'Only accept from', 'Comma separated emails or @domain.com. Empty = anyone.')}
    </div></div>
    <div class="card"><h2>Backups & reports</h2><div class="form-grid">
      ${f('backup_interval_hours', 'Back up every (hours)', '', 'number')}
      ${f('backup_retention', 'Keep this many backups', '', 'number')}
      ${f('daily_report_time', 'Save daily report at (HH:MM)', '')}
      ${f('unusual_hours_threshold', 'Flag days with at least (hours)', '', 'number')}
    </div></div>
    <div class="card"><h2>Holidays</h2><p class="muted small">No timesheet is expected on these dates. Comma separated, YYYY-MM-DD.</p>
      <textarea name="holidays" ${admin ? '' : 'disabled'}>${esc(values.holidays)}</textarea></div>
    ${admin ? '<div class="card"><button class="primary" id="save">Save settings</button></div>' : '<p class="muted">Only administrators can change these settings.</p>'}`;
  box.querySelector('#save')?.addEventListener('click', (e) => withBusy(e.currentTarget, async () => {
    await api.put('/api/settings', formValues(box));
    toast('Settings saved. Schedules updated.');
  }).catch(err => toast(err.message, true)));
}

// ------------------------------------------------------------------ backups
async function backups(box, ctx, refresh) {
  const data = await api.get('/api/settings/backups');
  const admin = ctx.user.role === 'admin';
  box.innerHTML = `<div class="card"><div class="card-head"><h2>Database backups</h2>
      <button class="primary" id="now">Backup Now</button>
      ${admin ? '<label class="btn">Upload a backup…<input type="file" id="up" accept=".db" class="hidden"></label>' : ''}</div>
      <p class="muted small">Saved in <code>${esc(data.dir)}</code>. Copy this folder to another drive or cloud folder regularly: if the desktop's disk fails, backups on the same disk are lost too.</p>
      ${table([
        { label: 'File', render: b => `<code>${esc(b.name)}</code>` },
        { label: 'Type', render: b => badge(b.kind, b.kind === 'pre-restore' ? 'warning' : 'info') },
        { label: 'Saved', render: b => esc(niceDateTime(b.modified)) },
        { label: 'Size', num: true, render: b => `${fmt(b.size / 1024 / 1024, 2)} MB` },
        ...(admin ? [{ label: '', render: b => `<button class="link" data-restore="${esc(b.name)}">Restore…</button>` }] : []),
      ], data.backups, { empty: 'No backups yet.' })}</div>`;
  box.querySelector('#now').addEventListener('click', (e) => withBusy(e.currentTarget, async () => {
    const r = await api.post('/api/settings/backups');
    toast(`Backup saved: ${r.name}`);
    refresh();
  }).catch(err => toast(err.message, true)));
  box.querySelector('#up')?.addEventListener('change', async (e) => {
    try { const r = await api.upload('/api/settings/backups/upload', e.target.files[0]); toast(`Uploaded as ${r.name}. You can restore it from the list.`); refresh(); }
    catch (err) { toast(err.message, true); }
  });
  box.querySelectorAll('[data-restore]').forEach(b => b.addEventListener('click', () => restore(b.dataset.restore)));
}

async function restore(name) {
  let counts;
  try { counts = (await api.post('/api/settings/backups/validate', { name, confirm: '' })).counts; }
  catch (err) { toast(err.message, true); return; }
  const ok = await modal('Restore database?', `
    <div class="notice warn"><b>This replaces the current database</b> with <code>${esc(name)}</code>. Anything imported after that backup will be removed from the app (the original Excel files stay in the imports folder and can be uploaded again).</div>
    <p class="small" style="margin-top:10px">The backup checked out OK and contains ${fmt(counts.employees)} employee(s), ${fmt(counts.submissions)} submission(s), ${fmt(counts.timesheet_entries)} entries and ${fmt(counts.users)} user account(s).
    A safety copy of the current database is taken first. You will need to sign in again afterwards.</p>
    <label class="field">Type RESTORE to confirm<input name="confirm" autocomplete="off"></label>`, {
    actions: [{ label: 'Cancel' }, {
      label: 'Restore', cls: 'danger', onClick: async (root) => {
        const r = await api.post('/api/settings/backups/restore', { name, confirm: root.querySelector('[name=confirm]').value });
        toast(`Restored. Safety copy: ${r.safety_backup}`);
        return true;
      },
    }],
  });
  if (ok) setTimeout(() => location.reload(), 1200);
}

// ------------------------------------------------------------------ categories & rules
async function rules(box, ctx, refresh) {
  const [cats, rs] = await Promise.all([api.get('/api/categories'), api.get('/api/settings/rules')]);
  const admin = ctx.user.role === 'admin';
  box.innerHTML = `
    <div class="card"><div class="card-head"><h2>How notes are categorised</h2>${admin ? '<button id="recl">Re-run on all past entries</button>' : ''}</div>
      <p class="small">Each line of a timesheet's notes is checked against the keywords below. When several match, the one with the highest priority wins. Lines with no match go to <b>Uncategorized</b>. After changing rules, re-run so past entries use them too.</p></div>
    <div class="grid cols-2">
      <div class="card"><div class="card-head"><h2>Categories</h2>${admin ? '<button id="addcat">Add</button>' : ''}</div>
        ${table([{ label: 'Name', render: c => esc(c.name) }, { label: 'Description', render: c => `<span class="small">${esc(c.description || '')}</span>` },
          ...(admin ? [{ label: '', render: c => `<button class="link" data-cat="${c.id}">Edit</button>` }] : [])], cats)}</div>
      <div class="card"><div class="card-head"><h2>Keyword rules</h2>${admin ? '<button id="addrule">Add rule</button>' : ''}</div>
        ${table([{ label: 'Keyword', render: r => `<code>${esc(r.keyword)}</code>` }, { label: 'Category', render: r => esc(r.category) },
          { label: 'Priority', key: 'priority', num: true }, { label: 'Active', render: r => r.active ? 'Yes' : 'No' },
          ...(admin ? [{ label: '', render: r => `<button class="link" data-rule="${r.id}">Edit</button>` }] : [])], rs)}</div>
    </div>`;
  const catOptions = (sel) => cats.map(c => `<option value="${c.id}" ${c.id === sel ? 'selected' : ''}>${esc(c.name)}</option>`).join('');
  const editRule = async (r) => {
    const saved = await modal(r ? 'Edit rule' : 'Add rule', `<div class="form-grid">
        <label class="field">Keyword or phrase<input name="keyword" value="${esc(r?.keyword || '')}"></label>
        <label class="field">Category<select name="category_id">${catOptions(r?.category_id)}</select></label>
        <label class="field">Priority (higher wins)<input name="priority" type="number" value="${esc(r?.priority ?? 50)}"></label>
        <label class="field">Active<select name="active"><option value="true">Yes</option><option value="false" ${r && !r.active ? 'selected' : ''}>No</option></select></label></div>`, {
      actions: [...(r ? [{ label: 'Delete', cls: 'danger', onClick: async () => { await api.del(`/api/settings/rules/${r.id}`); return true; } }] : []), { label: 'Cancel' }, {
        label: 'Save', cls: 'primary', onClick: async (root) => {
          const v = formValues(root);
          const body = { keyword: v.keyword, category_id: Number(v.category_id), priority: Number(v.priority), active: v.active === 'true' };
          if (r) await api.put(`/api/settings/rules/${r.id}`, body); else await api.post('/api/settings/rules', body);
          return true;
        },
      }],
    });
    if (saved) refresh();
  };
  const editCat = async (c) => {
    const saved = await modal(c ? 'Edit category' : 'Add category', `<div class="form-grid">
        <label class="field">Name<input name="name" value="${esc(c?.name || '')}"></label>
        <label class="field">Description<input name="description" value="${esc(c?.description || '')}"></label></div>`, {
      actions: [...(c ? [{ label: 'Delete', cls: 'danger', onClick: async () => { await api.del(`/api/settings/categories/${c.id}`); return true; } }] : []), { label: 'Cancel' }, {
        label: 'Save', cls: 'primary', onClick: async (root) => {
          const v = formValues(root);
          if (c) await api.put(`/api/settings/categories/${c.id}`, v); else await api.post('/api/settings/categories', v);
          return true;
        },
      }],
    });
    if (saved) refresh();
  };
  box.querySelector('#addrule')?.addEventListener('click', () => editRule(null));
  box.querySelector('#addcat')?.addEventListener('click', () => editCat(null));
  box.querySelectorAll('[data-rule]').forEach(b => b.addEventListener('click', () => editRule(rs.find(r => r.id === Number(b.dataset.rule)))));
  box.querySelectorAll('[data-cat]').forEach(b => b.addEventListener('click', () => editCat(cats.find(c => c.id === Number(b.dataset.cat)))));
  box.querySelector('#recl')?.addEventListener('click', (e) => withBusy(e.currentTarget, async () => {
    const r = await api.post('/api/settings/reclassify');
    toast(`Re-categorised ${r.activities} activity lines.`);
  }).catch(err => toast(err.message, true)));
}

// ------------------------------------------------------------------ users
async function users(box, ctx, refresh) {
  const list = await api.get('/api/settings/users');
  box.innerHTML = `<div class="card"><div class="card-head"><h2>Users</h2><button id="add" class="primary">Add user</button></div>
    <p class="muted small"><b>Administrator</b>: everything. <b>Manager</b>: view, import, sync, back up, edit employees. <b>Viewer</b>: view only.</p>
    ${table([{ label: 'Username', render: u => esc(u.username) }, { label: 'Role', render: u => esc(u.role) },
      { label: 'Active', render: u => u.active ? 'Yes' : 'No' }, { label: 'Last sign-in', render: u => esc(niceDateTime(u.last_login)) },
      { label: '', render: u => `<button class="link" data-u="${u.id}">Edit</button>` }], list)}</div>`;
  const edit = async (u) => {
    const saved = await modal(u ? `Edit ${u.username}` : 'Add user', `<div class="form-grid">
        <label class="field">Username<input name="username" value="${esc(u?.username || '')}" autocomplete="off"></label>
        <label class="field">Role<select name="role">${['admin', 'manager', 'viewer'].map(r => `<option ${u?.role === r || (!u && r === 'manager') ? 'selected' : ''}>${r}</option>`).join('')}</select></label>
        <label class="field">${u ? 'New password (leave empty to keep)' : 'Password'}<input name="password" type="password" autocomplete="new-password"></label>
        <label class="field">Active<select name="active"><option value="true">Yes</option><option value="false" ${u && !u.active ? 'selected' : ''}>No</option></select></label></div>`, {
      actions: [{ label: 'Cancel' }, { label: 'Save', cls: 'primary', onClick: async (root) => {
        const v = formValues(root);
        const body = { username: v.username, role: v.role, active: v.active === 'true', password: v.password || null };
        if (u) await api.put(`/api/settings/users/${u.id}`, body); else await api.post('/api/settings/users', body);
        return true;
      } }],
    });
    if (saved) refresh();
  };
  box.querySelector('#add').addEventListener('click', () => edit(null));
  box.querySelectorAll('[data-u]').forEach(b => b.addEventListener('click', () => edit(list.find(u => u.id === Number(b.dataset.u)))));
}

// ------------------------------------------------------------------ access log
async function access(box) {
  const [log, me] = await Promise.all([api.get('/api/settings/access-log', { limit: 300 }), api.get('/api/settings/whoami')]);
  box.innerHTML = `<div class="card"><h2>Sign-ins and remote access</h2>
    <p class="muted small">Sign-ins from anywhere, and every request that did not come from the desktop itself. You are connected via <b>${esc(me.via)}</b> from ${esc(me.ip)}${me.https ? ' over HTTPS' : ''}.</p>
    ${table([{ label: 'When', render: a => esc(niceDateTime(a.ts)) }, { label: 'User', render: a => esc(a.user || '—') },
      { label: 'Event', render: a => esc(a.event.replace('_', ' ')) }, { label: 'Via', render: a => esc(a.via) }, { label: 'IP', render: a => esc(a.ip) },
      { label: 'Request', render: a => `<span class="small">${esc(a.method || '')} ${esc(a.path || '')}</span>` }, { label: 'Status', key: 'status', num: true }], log, { empty: 'Nothing logged yet.' })}</div>`;
}

// ------------------------------------------------------------------ account
async function account(box) {
  box.innerHTML = `<div class="card"><h2>Change password</h2><div class="form-grid">
      <label class="field">Current password<input type="password" name="current_password" autocomplete="current-password"></label>
      <label class="field">New password<input type="password" name="new_password" autocomplete="new-password"></label>
      <label class="field">Repeat new password<input type="password" name="repeat" autocomplete="new-password"></label></div>
    <p class="muted small">At least 10 characters with upper- and lower-case letters and a number. Other devices will be signed out.</p>
    <button class="primary" id="pw">Change password</button></div>`;
  box.querySelector('#pw').addEventListener('click', (e) => withBusy(e.currentTarget, async () => {
    const v = formValues(box);
    if (v.new_password !== v.repeat) throw new Error('New passwords do not match.');
    await api.post('/api/auth/password', { current_password: v.current_password, new_password: v.new_password });
    toast('Password changed.');
    box.querySelectorAll('input').forEach(i => { i.value = ''; });
  }).catch(err => toast(err.message, true)));
}

// ------------------------------------------------------------------ system
async function system(box) {
  const { system: s } = await api.get('/api/settings');
  const labels = { gmail_sync: 'Gmail check', backup: 'Backup', daily_report: 'Daily report', cleanup: 'Clean-up', catch_up: 'Start-up catch-up' };
  box.innerHTML = `<div class="grid cols-2">
    <div class="card"><h2>Where your data lives (this desktop)</h2>${table([{ label: 'What', render: r => esc(r[0]) }, { label: 'Location', render: r => `<code>${esc(r[1])}</code>` }], [
      ['Database', s.database], ['Backups', s.backup_dir], ['Reports', s.reports_dir], ['Received Excel files', s.imports_dir], ['Logs', s.logs_dir],
      ['Database size', s.database_size ? `${fmt(s.database_size / 1024 / 1024, 2)} MB` : '—'], ['Free disk space', s.disk_free > 0 ? `${fmt(s.disk_free / 1024 ** 3, 1)} GB` : '—'],
      ['Web server', `${s.host}:${s.port}`]])}</div>
    <div class="card"><h2>Next scheduled runs</h2>${table([{ label: 'Job', render: r => esc(labels[r[0]] || r[0]) }, { label: 'Next run', render: r => esc(niceDateTime(r[1])) }],
      Object.entries(s.scheduler), { empty: 'The scheduler is not running.' })}
      <p class="muted small" style="margin-top:10px">These run inside the server on the desktop, whether or not a browser is open. If the desktop is off, nothing runs and the app is unreachable; missed work is caught up at the next start.</p></div></div>`;
}
