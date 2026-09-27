import { api } from '../services/api.js';
import { bindRows, esc, fmt, niceDate, pct, rangeControl, sevBadge, signed, table, tiles } from '../components/ui.js';
import { categoryHeatmap, columnChart, hbars } from '../components/charts.js';
import { navigate } from '../src/app.js';

const state = { days: 30, employee_id: '' };

export async function render(el, ctx) {
  const [d, employees] = await Promise.all([
    api.get('/api/analytics', { days: state.days, employee_id: state.employee_id }),
    api.get('/api/employees'),
  ]);
  if (!ctx.isCurrent()) return;
  const s = d.summary;
  const short = (iso) => new Date(iso + 'T12:00:00').toLocaleDateString(undefined, { day: 'numeric', month: 'short' });

  el.innerHTML = `
    <div class="page-head"><h1>Analytics</h1>
      <div class="toolbar">
        <select id="emp"><option value="">All employees</option>${employees.map(e => `<option value="${e.id}" ${String(e.id) === String(state.employee_id) ? 'selected' : ''}>${esc(e.name)}</option>`).join('')}</select>
        ${rangeControl(state.days, (days) => { state.days = days; render(el, ctx); })}
      </div></div>
    <p class="muted small">${esc(niceDate(d.period.start))} – ${esc(niceDate(d.period.end))}. These figures describe what was written on timesheets; they are not a measure of anyone's overall performance.</p>

    ${tiles([
      { label: 'Total hours', value: fmt(s.total_hours, 2) },
      { label: 'Average daily hours', value: fmt(s.avg_daily_hours, 2), sub: `${s.days_submitted} employee-day(s)` },
      { label: 'Tasks', value: fmt(s.task_count) },
      { label: 'Completion rate', value: s.completion_rate === null ? '—' : pct(s.completion_rate), sub: `${s.completion_not_recorded} not recorded` },
      { label: 'Avg hours per task', value: fmt(s.avg_hours_per_task, 2) },
      { label: 'Administrative', value: pct(s.admin_pct), sub: 'of hours (est.)' },
      { label: 'Communication', value: pct(s.communication_pct), sub: 'of hours (est.)' },
      { label: 'Coordination', value: pct(s.coordination_pct), sub: 'of hours (est.)' },
      { label: 'Hours per feature', value: fmt(s.hours_per_feature, 2), sub: `${s.feature_total} features, ${fmt(s.feature_hours, 2)} h` },
    ])}

    <div class="grid cols-2">
      <div class="card"><h2>Work category distribution</h2>${hbars(d.categories.map(c => ({ label: c.category, value: c.percent, tip: `${c.category}: ${fmt(c.percent)}% · ${fmt(c.hours, 2)} h` })))}</div>
      <div class="card"><div class="card-head"><h2>Compared with previous period</h2><span class="muted small">${esc(niceDate(d.comparison.previous_period.start))} – ${esc(niceDate(d.comparison.previous_period.end))}</span></div>
        ${table([
          { label: 'Measure', render: r => esc(r.metric) },
          { label: 'This period', num: true, render: r => r.unit === '%' ? pct(r.current) : esc(fmt(r.current, 2)) },
          { label: 'Previous', num: true, render: r => r.unit === '%' ? pct(r.previous) : esc(fmt(r.previous, 2)) },
          { label: 'Change', num: true, render: r => esc(signed(r.change, r.unit === '%' ? ' pts' : '')) },
        ], d.comparison.rows)}
        ${d.category_shifts.length ? `<h3 style="margin-top:14px">Category shifts of 10+ points</h3>${table([
          { label: 'Category', render: r => esc(r.category) }, { label: 'Before', num: true, render: r => pct(r.previous_pct) },
          { label: 'Now', num: true, render: r => pct(r.current_pct) }, { label: 'Change', num: true, render: r => esc(signed(r.change, ' pts')) }], d.category_shifts)}` : ''}
      </div>
    </div>

    <div class="grid">
      <div class="card"><h2>Weekly hours</h2>${columnChart(d.weekly.map(x => ({ label: x.week, short: short(x.week), value: x.hours, tip: `Week of ${niceDate(x.week)}: ${fmt(x.hours, 2)} h, ${x.tasks} task(s)` })), { aria: 'Weekly hours' })}</div>
      <div class="card"><h2>Daily tasks</h2>${columnChart(d.daily.map(x => ({ label: x.date, short: short(x.date), value: x.tasks, tip: `${niceDate(x.date)}: ${x.tasks} task(s), ${x.completed} completed, ${x.incomplete} not` })), { aria: 'Daily tasks' })}</div>
    </div>

    <div class="card"><h2>Category share by week</h2>${categoryHeatmap(d.weekly)}</div>

    ${d.employees.length ? `<div class="card"><h2>By employee</h2><div id="emps">${table([
      { label: 'Employee', render: r => `<a href="#/employees/${r.employee_id}">${esc(r.employee)}</a>` },
      { label: 'Hours', key: 'hours', num: true }, { label: 'Avg hours/day', key: 'avg_daily_hours', num: true },
      { label: 'Tasks', key: 'tasks', num: true }, { label: 'Completed', key: 'completed', num: true }, { label: 'Incomplete', key: 'incomplete', num: true },
      { label: 'Completion', num: true, render: r => pct(r.completion_rate) }, { label: 'Avg hours/task', key: 'avg_hours_per_task', num: true },
      { label: 'Missing days', key: 'missing_days', num: true }, { label: 'Main category', render: r => esc(r.top_category || '—') },
    ], d.employees, { onRow: true })}</div></div>` : ''}

    <div class="grid cols-2">
      <div class="card"><h2>Repeated activities</h2><p class="muted small">Same wording on two or more days.</p>
        ${table([{ label: 'Activity', render: r => esc(r.activity) }, { label: 'Days', key: 'days', num: true }, { label: 'People', key: 'employees', num: true }, { label: 'Est. hours', key: 'est_hours', num: true }], d.repeated, { empty: 'No repeated activities.' })}</div>
      <div class="card"><h2>Unusual hours</h2><p class="muted small">Compared with each person's previous 20 submitted days.</p>
        ${table([{ label: 'Date', render: r => esc(niceDate(r.date)) }, { label: 'Employee', render: r => esc(r.employee) }, { label: 'Hours', key: 'hours', num: true },
          { label: 'Recent avg', key: 'recent_average', num: true }, { label: 'Note', render: r => esc(r.reason) }], d.anomalies, { empty: 'None found.' })}</div>
    </div>

    <div class="grid cols-2">
      <div class="card"><h2>Missing timesheets</h2>
        ${table([{ label: 'Date', render: r => esc(niceDate(r.date)) }, { label: 'Employee', render: r => `<a href="#/employees/${r.employee_id}">${esc(r.employee)}</a>` }], d.missing, { empty: 'None missing.' })}</div>
      <div class="card"><h2>Data quality</h2>
        ${table([{ label: 'Date', render: r => esc(r.date ? niceDate(r.date) : '—') }, { label: 'Employee', render: r => esc(r.employee || '—') },
          { label: 'Level', render: r => sevBadge(r.severity) }, { label: 'Issue', render: r => esc(r.message) }], d.data_quality.slice(0, 50), { empty: 'No data-quality warnings.' })}</div>
    </div>`;

  el.querySelector('#emp').addEventListener('change', (e) => { state.employee_id = e.target.value; render(el, ctx); });
  const emps = el.querySelector('#emps');
  if (emps) bindRows(emps, d.employees, r => navigate(`#/employees/${r.employee_id}`));
}
