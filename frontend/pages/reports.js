import { api, download } from '../services/api.js';
import { alertsList, esc, fmt, isoToday, niceDate, niceDateTime, pct, sevBadge, shiftDate, signed, table, tiles, toast, withBusy } from '../components/ui.js';
import { hbars } from '../components/charts.js';

const state = { date: null };

export async function render(el, ctx) {
  state.date = state.date || isoToday();
  const [r, saved] = await Promise.all([api.get('/api/reports/daily', { date: state.date }), api.get('/api/reports')]);
  if (!ctx.isCurrent()) return;
  const s = r.summary;
  const canGenerate = ctx.user.role !== 'viewer';

  el.innerHTML = `
    <div class="page-head"><h1>Daily report</h1>
      <div class="toolbar">
        <button id="prev" aria-label="Previous day">‹</button><input type="date" id="day" value="${esc(state.date)}" max="${isoToday()}"><button id="next" aria-label="Next day" ${state.date >= isoToday() ? 'disabled' : ''}>›</button>
        <button data-fmt="xlsx">Excel</button><button data-fmt="csv">CSV</button><button data-fmt="pdf">PDF</button>
        ${canGenerate ? '<button id="save" class="primary">Save to reports folder</button>' : ''}
      </div></div>
    <p class="muted small">${esc(niceDate(r.date, { weekday: 'long', day: 'numeric', month: 'long', year: 'numeric' }))}. A report is also saved automatically every day at the time set in Settings.</p>

    <div class="card"><h2>Submission status</h2>
      ${tiles([
        { label: 'Expected', value: fmt(s.employees_expected) }, { label: 'Received', value: fmt(s.employees_submitted) },
        { label: 'Missing', value: fmt(s.missing), sub: s.pending ? `${s.pending} not yet due` : '' },
        { label: 'Total hours', value: fmt(s.total_hours, 2), sub: s.avg_daily_hours_30d ? `30-day avg per person-day: ${fmt(s.avg_daily_hours_30d, 2)} h` : '' },
        { label: 'Tasks', value: fmt(s.tasks), sub: `${s.activities} activity lines` },
        { label: 'Completion', value: s.completion_rate === null ? '—' : pct(s.completion_rate), sub: `${s.completed} yes · ${s.incomplete} no · ${s.completion_not_recorded} not recorded` },
      ])}</div>

    <div class="card"><h2>Management attention</h2>${alertsList(r.attention, { empty: 'Nothing needs attention for this day.' })}</div>

    <div class="card"><h2>Employee summaries</h2>${table([
      { label: 'Employee', render: e => `<a href="#/employees/${e.employee_id}">${esc(e.employee)}</a>` },
      { label: 'Submitted', render: e => e.submitted ? 'Yes' : '<b>No</b>' },
      { label: 'Hours', key: 'hours', num: true }, { label: 'Tasks', key: 'tasks', num: true },
      { label: 'Completed', key: 'completed', num: true }, { label: 'Incomplete', key: 'incomplete', num: true },
      { label: 'Main categories', render: e => esc(e.main_categories || '—') },
      { label: 'Avg hours/day (30d)', key: 'avg_daily_hours_30d', num: true },
      { label: 'vs 30-day avg', num: true, render: e => esc(signed(e.hours_vs_30d, ' h')) },
    ], r.employees, { empty: 'No active employees.' })}</div>

    <div class="grid cols-2">
      <div class="card"><h2>Category distribution</h2>${hbars(r.categories.map(c => ({ label: c.category, value: c.percent, tip: `${c.category}: ${fmt(c.percent)}% · ${fmt(c.hours, 2)} h` })))}</div>
      <div class="card"><h2>Change vs last 30 days</h2>${table([
        { label: 'Category', render: c => esc(c.category) }, { label: 'This day', num: true, render: c => pct(c.today_pct) },
        { label: 'Last 30 days', num: true, render: c => pct(c.last_30d_pct) }, { label: 'Change', num: true, render: c => esc(signed(c.change, ' pts')) },
      ], r.category_changes.slice(0, 8), { empty: 'Not enough history yet.' })}</div>
    </div>

    <div class="grid cols-2">
      <div class="card"><h2>Unusual hours</h2>${table([{ label: 'Employee', render: a => esc(a.employee) }, { label: 'Hours', key: 'hours', num: true },
        { label: 'Recent average', key: 'recent_average', num: true }, { label: 'Note', render: a => esc(a.reason) }], r.anomalies, { empty: 'None.' })}</div>
      <div class="card"><h2>Data quality</h2>${table([{ label: 'Employee', render: q => esc(q.employee || '—') }, { label: 'Level', render: q => sevBadge(q.severity) },
        { label: 'Issue', render: q => esc(q.message) }], r.data_quality, { empty: 'No data-quality warnings.' })}</div>
    </div>

    <div class="card"><h2>Saved reports</h2>${table([
      { label: 'Report date', render: x => esc(niceDate(x.date)) }, { label: 'Format', render: x => esc(x.fmt.toUpperCase()) },
      { label: 'Created', render: x => esc(niceDateTime(x.created_at)) },
      { label: '', render: x => x.exists ? `<button class="link" data-id="${x.id}" data-name="daily_report_${x.date}.${x.fmt}">Download</button>` : '<span class="muted">file missing</span>' },
    ], saved.slice(0, 60), { empty: 'No reports saved yet.' })}</div>`;

  const go = (d) => { state.date = d; render(el, ctx); };
  el.querySelector('#day').addEventListener('change', e => e.target.value && go(e.target.value));
  el.querySelector('#prev').addEventListener('click', () => go(shiftDate(state.date, -1)));
  el.querySelector('#next').addEventListener('click', () => go(shiftDate(state.date, 1)));
  el.querySelectorAll('[data-fmt]').forEach(b => b.addEventListener('click', () => withBusy(b, () =>
    download('/api/reports/daily/export', { date: state.date, fmt: b.dataset.fmt }, `daily_report_${state.date}.${b.dataset.fmt}`)).catch(err => toast(err.message, true))));
  el.querySelectorAll('[data-id]').forEach(b => b.addEventListener('click', () =>
    download(`/api/reports/file/${b.dataset.id}`, null, b.dataset.name).catch(err => toast(err.message, true))));
  el.querySelector('#save')?.addEventListener('click', (e) => withBusy(e.currentTarget, async () => {
    const res = await api.post('/api/reports/generate', null, { date: state.date });
    toast(`Saved ${res.files.join(', ')}`);
    render(el, ctx);
  }).catch(err => toast(err.message, true)));
}
