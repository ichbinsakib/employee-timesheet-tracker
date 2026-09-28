import { api } from '../services/api.js';
import { alertsList, badge, bindRows, completedLabel, esc, fmt, formValues, hrs, modal, niceDate, pct, rangeControl, sevBadge, signed, table, tiles, toast } from '../components/ui.js';
import { columnChart, hbars } from '../components/charts.js';
import { navigate } from '../src/app.js';

const state = { days: 30 };

export async function render(el, ctx) {
  if (ctx.params[0]) return renderDetail(el, ctx, Number(ctx.params[0]));
  const list = await api.get('/api/employees');
  if (!ctx.isCurrent()) return;
  const canEdit = ctx.user.role !== 'viewer';
  el.innerHTML = `
    <div class="page-head"><h1>Employees</h1>${canEdit ? `<div class="toolbar">
        <label class="btn" title="CSV or Excel with a name column; email, department, designation and status are optional">Import employees…<input type="file" id="import" accept=".csv,.xlsx,.xlsm" class="hidden"></label>
        <button class="primary" id="add">Add employee</button></div>` : ''}</div>
    <div class="card">
      <p class="muted small">Employees are also added automatically when a timesheet arrives with a new name. Check their details afterwards.</p>
      <div id="tbl">${table([
        { label: 'Name', render: r => `<a href="#/employees/${r.id}">${esc(r.name)}</a> ${r.auto_created ? badge('added automatically', 'info') : ''} ${r.active ? '' : badge('inactive', 'warning')}` },
        { label: 'Email', render: r => esc(r.email || '—') },
        { label: 'Department', render: r => esc(r.department || '—') },
        { label: 'Job title', render: r => esc(r.job_title || '—') },
        { label: 'Hours/day', key: 'expected_daily_hours', num: true },
        { label: 'Working days', render: r => esc(r.working_days) },
        { label: 'Deadline', render: r => esc(r.submission_deadline) },
        ...(canEdit ? [{ label: '', render: () => '<button class="link" data-edit>Edit</button>' }] : []),
      ], list, { onRow: true, empty: 'No employees yet.' })}</div>
    </div>`;
  bindRows(el.querySelector('#tbl'), list, r => navigate(`#/employees/${r.id}`));
  el.querySelectorAll('[data-edit]').forEach((b) => b.addEventListener('click', async (e) => {
    const row = list[Number(e.target.closest('tr').dataset.i)];
    if (await editEmployee(row)) render(el, ctx);
  }));
  el.querySelector('#add')?.addEventListener('click', async () => { if (await editEmployee(null)) render(el, ctx); });
  el.querySelector('#import')?.addEventListener('change', async (e) => {
    const file = e.target.files[0];
    e.target.value = '';
    if (file && await importEmployees(file)) render(el, ctx);
  });
}

// Two steps: preview (nothing saved), then apply.
async function importEmployees(file) {
  let preview;
  try { preview = await api.upload('/api/employees/import?apply=false', file); }
  catch (err) { toast(err.message, true); return false; }
  const nothing = !preview.created.length && !preview.updated.length && !preview.deactivated.length && !preview.reactivated.length;
  const list = (title, items, render = esc) => items.length
    ? `<h3 style="margin-top:14px">${esc(title)} (${items.length})</h3><ul class="small">${items.map(i => `<li>${render(i)}</li>`).join('')}</ul>` : '';
  const body = `
    <p class="small muted">${esc(file.name)} · ${preview.rows} row(s) · columns found: ${esc(preview.columns.join(', '))}. Nothing has been saved yet.</p>
    ${nothing ? '<div class="notice">No changes: everyone in the file already matches the app.</div>' : ''}
    ${list('New employees', preview.created)}
    ${list('Updated', preview.updated, u => `<b>${esc(u.name)}</b>: ${esc(u.changes.join('; '))}`)}
    ${list('Will be marked inactive', preview.deactivated)}
    ${list('Will be reactivated', preview.reactivated)}
    ${list('Skipped rows', preview.skipped, s => `Row ${esc(s.row)}: ${esc(s.reason)}`)}
    ${preview.unchanged.length ? `<p class="small muted" style="margin-top:10px">Unchanged: ${esc(preview.unchanged.join(', '))}</p>` : ''}
    <p class="small muted" style="margin-top:10px">Working days, hours and deadlines are only changed if the file has those columns.</p>`;
  return modal('Import employees – preview', body, {
    wide: true,
    actions: [{ label: 'Cancel' }, ...(nothing ? [] : [{
      label: 'Apply import', cls: 'primary', onClick: async () => {
        const r = await api.upload('/api/employees/import?apply=true', file);
        toast(`Imported: ${r.created.length} added, ${r.updated.length} updated, ${r.deactivated.length} marked inactive.`);
        return true;
      },
    }])],
  });
}

export async function editEmployee(emp) {
  const e = emp || { name: '', aliases: '', email: '', department: '', job_title: '', expected_daily_hours: 8, expected_weekly_hours: 40,
    working_days: 'Mon,Tue,Wed,Thu,Fri', submission_deadline: '18:00', tracking_start: '', active: true };
  const days = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun'];
  const on = new Set((e.working_days || '').split(',').map(s => s.trim()));
  const body = `<div class="form-grid">
      <label class="field">Name (as written on timesheets)<input name="name" value="${esc(e.name)}" required></label>
      <label class="field">Other spellings (comma separated)<input name="aliases" value="${esc(e.aliases || '')}"></label>
      <label class="field">Email<input name="email" type="email" value="${esc(e.email || '')}"></label>
      <label class="field">Department<input name="department" value="${esc(e.department || '')}"></label>
      <label class="field">Job title<input name="job_title" value="${esc(e.job_title || '')}"></label>
      <label class="field">Expected hours per day<input name="expected_daily_hours" type="number" step="0.25" min="0" max="24" value="${esc(e.expected_daily_hours)}"></label>
      <label class="field">Expected hours per week<input name="expected_weekly_hours" type="number" step="0.5" min="0" max="168" value="${esc(e.expected_weekly_hours)}"></label>
      <label class="field">Timesheet due by (HH:MM)<input name="submission_deadline" value="${esc(e.submission_deadline)}" pattern="[0-2][0-9]:[0-5][0-9]"></label>
      <label class="field">Track missing timesheets from<input name="tracking_start" type="date" value="${esc(e.tracking_start || '')}"></label>
    </div>
    <p class="small" style="margin-top:12px">Working days: ${days.map(d => `<label style="margin-right:10px"><input type="checkbox" data-day="${d}" ${on.has(d) ? 'checked' : ''}> ${d}</label>`).join('')}</p>
    <p class="small"><label><input type="checkbox" name="active" ${e.active ? 'checked' : ''}> Active (expected to submit timesheets)</label></p>`;
  return modal(emp ? `Edit ${emp.name}` : 'Add employee', body, {
    actions: [{ label: 'Cancel' }, {
      label: 'Save', cls: 'primary', onClick: async (root) => {
        const v = formValues(root);
        v.working_days = [...root.querySelectorAll('[data-day]')].filter(c => c.checked).map(c => c.dataset.day).join(',');
        v.expected_daily_hours = Number(v.expected_daily_hours);
        v.expected_weekly_hours = Number(v.expected_weekly_hours);
        v.tracking_start = v.tracking_start || null;
        if (emp) await api.put(`/api/employees/${emp.id}`, v); else await api.post('/api/employees', v);
        toast('Saved');
        return true;
      },
    }],
  });
}

async function renderDetail(el, ctx, id) {
  const d = await api.get(`/api/employees/${id}`, { days: state.days });
  if (!ctx.isCurrent()) return;
  const e = d.employee, s = d.summary;
  const canEdit = ctx.user.role !== 'viewer';
  const short = (iso) => new Date(iso + 'T12:00:00').toLocaleDateString(undefined, { day: 'numeric', month: 'short' });
  const alerts = [
    ...d.missing.map(m => ({ severity: 'warning', title: 'Missing timesheet', message: `No timesheet for ${niceDate(m.date)}.` })),
    ...d.anomalies.map(a => ({ severity: 'info', title: 'Unusual hours', message: a.recent_average !== null
      ? `${fmt(a.hours, 2)} hours on ${niceDate(a.date)}. Recent average: ${fmt(a.recent_average, 2)} hours.` : `${fmt(a.hours, 2)} hours on ${niceDate(a.date)} (${a.reason}).` })),
    ...d.category_shifts.map(c => ({ severity: 'info', title: 'Category change', message: `${c.category} work ${c.change > 0 ? 'increased' : 'decreased'} from ${fmt(c.previous_pct)}% to ${fmt(c.current_pct)}% compared with the previous period.` })),
  ];

  el.innerHTML = `
    <div class="page-head">
      <h1>${esc(e.name)}</h1>
      <div class="toolbar">${rangeControl(state.days, (days) => { state.days = days; renderDetail(el, ctx, id); })}
        ${canEdit ? '<button id="edit">Edit details</button>' : ''}<a class="btn" href="#/employees">All employees</a></div>
    </div>
    <p class="muted small">${[e.job_title, e.department, e.email].filter(Boolean).map(esc).join(' · ') || 'No job details yet.'}
      · Expected ${fmt(e.expected_daily_hours)} h/day on ${esc(e.working_days)} · ${esc(niceDate(d.period.start))} – ${esc(niceDate(d.period.end))}</p>

    ${tiles([
      { label: 'Total hours', value: fmt(s.total_hours, 2) },
      { label: 'Average daily hours', value: fmt(s.avg_daily_hours, 2), sub: `${s.days_submitted} day(s) submitted` },
      { label: 'Tasks', value: fmt(s.task_count), sub: s.zero_hour_rows ? `${s.zero_hour_rows} row(s) with 0 hours not counted` : `${s.activity_count} activity line(s)` },
      { label: 'Completion', value: s.completion_rate === null ? '—' : pct(s.completion_rate), sub: `${s.completed_tasks} yes · ${s.incomplete_tasks} no · ${s.completion_not_recorded} not recorded` },
      { label: 'Average hours per task', value: fmt(s.avg_hours_per_task, 2) },
      { label: 'Hours per feature', value: fmt(s.hours_per_feature, 2), sub: s.feature_total ? `${s.feature_total} features on ${s.feature_tasks} task(s)` : 'no feature counts recorded' },
    ])}

    <div class="card"><div class="card-head"><h2>Daily hours</h2><span class="muted small">dashed line: expected ${fmt(e.expected_daily_hours)} h</span></div>
      ${columnChart(d.daily.map(x => ({ label: x.date, short: short(x.date), value: x.hours, tip: `${niceDate(x.date)}: ${fmt(x.hours, 2)} h, ${x.tasks} task(s)` })),
        { ref: { value: e.expected_daily_hours, label: 'expected' }, aria: 'Daily hours', height: 180 })}</div>

    <div class="grid cols-2">
      <div class="card"><div class="card-head"><h2>Work distribution</h2><span class="muted small">estimated from notes</span></div>
        ${hbars(d.categories.map(c => ({ label: c.category, value: c.percent, tip: `${c.category}: ${fmt(c.percent)}% · ${fmt(c.hours, 2)} h` })))}</div>
      <div class="card"><h2>Alerts</h2>${alertsList(alerts, { empty: 'No alerts for this period.' })}</div>
    </div>

    <div class="card"><div class="card-head"><h2>Compared with previous period</h2><span class="muted small">${esc(niceDate(d.comparison.previous_period.start))} – ${esc(niceDate(d.comparison.previous_period.end))}</span></div>
      ${table([
        { label: 'Measure', key: 'metric', render: r => esc(r.metric) },
        { label: 'This period', num: true, render: r => r.unit === '%' ? pct(r.current) : esc(fmt(r.current, 2)) },
        { label: 'Previous', num: true, render: r => r.unit === '%' ? pct(r.previous) : esc(fmt(r.previous, 2)) },
        { label: 'Change', num: true, render: r => esc(signed(r.change, r.unit === '%' ? ' pts' : '')) },
      ], d.comparison.rows)}</div>

    <div class="card"><div class="card-head"><h2>Recent timesheet entries</h2><a href="#/timesheets?employee_id=${id}">All entries</a></div>
      <div id="entries">${table([
        { label: 'Date', render: r => esc(niceDate(r.date)) },
        { label: 'Costing code', render: r => esc(r.costing_code || '—') },
        { label: 'Notes', cls: 'notes', render: r => esc(r.notes || '') },
        { label: 'Category', render: r => esc(r.category || '—') },
        { label: 'Completed', render: r => completedLabel(r.completed) },
        { label: 'Features', key: 'features', num: true },
        { label: 'Hours', key: 'hours', num: true },
      ], d.recent_entries, { empty: 'No timesheet entries yet.' })}</div></div>

    <div class="grid cols-2">
      <div class="card"><h2>Repeated activities</h2><p class="muted small">Same wording on two or more days in this period.</p>
        ${table([{ label: 'Activity', render: r => esc(r.activity) }, { label: 'Days', key: 'days', num: true }, { label: 'Est. hours', key: 'est_hours', num: true }], d.repeated, { empty: 'No repeated activities.' })}</div>
      <div class="card"><h2>Data quality</h2>
        ${table([{ label: 'Date', render: r => esc(r.date ? niceDate(r.date) : '—') }, { label: 'Level', render: r => sevBadge(r.severity) },
          { label: 'Issue', render: r => esc(r.message) + (r.excel_row ? ` <span class="muted">(row ${r.excel_row})</span>` : '') }], d.data_quality, { empty: 'No data-quality notes.' })}</div>
    </div>`;
  el.querySelector('#edit')?.addEventListener('click', async () => { if (await editEmployee(e)) renderDetail(el, ctx, id); });
}
