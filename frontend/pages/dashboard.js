import { api } from '../services/api.js';
import { alertsList, bindRows, esc, fmt, hrs, isoToday, niceDate, niceDateTime, pct, rangeControl, shiftDate, table, tiles, toast, withBusy } from '../components/ui.js';
import { columnChart, hbars, codeHeatmap, codeBars } from '../components/charts.js';
import { navigate } from '../src/app.js';

const state = { date: null, days: 30, trend: 'daily' };

export async function render(el, ctx) {
  state.date = ctx.query.date || state.date || isoToday();
  const d = await api.get('/api/dashboard', { date: state.date, days: state.days });
  if (!ctx.isCurrent()) return;
  const t = d.today;
  const isToday = state.date === isoToday();
  const canSync = ctx.user.role !== 'viewer';

  el.innerHTML = `
    <div class="page-head">
      <h1>Dashboard</h1>
      <div class="toolbar">
        <button id="prev" aria-label="Previous day">‹</button>
        <input type="date" id="day" value="${esc(state.date)}" max="${isoToday()}">
        <button id="next" aria-label="Next day" ${isToday ? 'disabled' : ''}>›</button>
        ${!isToday ? '<button id="today">Today</button>' : ''}
        ${canSync ? '<button id="sync" class="primary">Sync Gmail Now</button>' : ''}
      </div>
    </div>
    <p class="muted small">${d.last_sync ? `Last Gmail check ${esc(niceDateTime(d.last_sync.at))} · ${d.last_sync.status === 'ok' ? 'OK' : 'problem – see Imports'}` : 'Gmail has not been checked yet.'}</p>

    <div class="card">
      <div class="card-head"><h2>${isToday ? 'Today' : esc(niceDate(state.date, { weekday: 'long', day: 'numeric', month: 'long', year: 'numeric' }))}</h2>${t.is_holiday ? '<span class="badge info">Holiday</span>' : ''}</div>
      ${tiles([
        { label: 'Employees expected', value: fmt(t.expected) },
        { label: 'Timesheets received', value: fmt(t.submitted) },
        { label: 'Missing', value: fmt(t.missing.length), sub: t.pending.length ? `${t.pending.length} not yet due` : (t.expected ? 'deadline passed' : 'none expected this day') },
        { label: 'Total hours', value: fmt(t.total_hours, 2) },
        { label: 'Tasks', value: fmt(t.tasks) },
        { label: 'Completed', value: fmt(t.completed) },
        { label: 'Incomplete', value: fmt(t.incomplete), sub: t.completion_not_recorded ? `${t.completion_not_recorded} not recorded` : '' },
      ])}
      ${t.missing.length || t.pending.length ? `<p class="small" style="margin-top:10px">
        ${t.missing.length ? `<b>Missing:</b> ${t.missing.map(m => `<a href="#/employees/${m.employee_id}">${esc(m.employee)}</a>`).join(', ')}` : ''}
        ${t.pending.length ? `${t.missing.length ? ' · ' : ''}<span class="muted">Not yet due: ${t.pending.map(m => `${esc(m.employee)} (by ${esc(m.deadline)})`).join(', ')}</span>` : ''}</p>` : ''}
    </div>

    <div class="grid cols-2">
      <div class="card"><div class="card-head"><h2>Needs attention</h2><span class="muted small">last 7 days</span></div>${alertsList(d.alerts, { limit: 8 })}</div>
      <div class="card"><div class="card-head"><h2>Hours by costing code</h2><span class="muted small">last ${d.period.days} days</span></div>
        ${codeBars(d.distribution)}</div>
    </div>

    <div class="card">
      <div class="card-head"><h2>Employee overview</h2>${rangeControl(state.days, (days) => { state.days = days; render(el, ctx); })}</div>
      <div id="emp-table">${table([
        { label: 'Employee', render: r => `<a href="#/employees/${r.employee_id}">${esc(r.employee)}</a>` },
        { label: 'Hours', key: 'hours', num: true },
        { label: 'Days submitted', key: 'days_submitted', num: true },
        { label: 'Avg hours/day', key: 'avg_daily_hours', num: true },
        { label: 'Tasks', key: 'tasks', num: true },
        { label: 'Completion', num: true, render: r => r.completion_rate === null ? '<span class="muted">not recorded</span>' : pct(r.completion_rate) },
        { label: 'Avg hours/task', key: 'avg_hours_per_task', num: true },
        { label: 'Missing days', num: true, render: r => r.missing_days ? `<b>${r.missing_days}</b>` : '0' },
        { label: 'Main costing code', render: r => esc(r.top_code || '—') },
      ], d.employees, { onRow: true, empty: 'No employees yet. They are added automatically from the first timesheet, or in Employees.' })}</div>
    </div>

    <div class="card">
      <div class="card-head"><h2>Trends</h2>
        <div class="seg" id="trend">${[['daily', 'Daily hours'], ['weekly', 'Weekly hours'], ['tasks', 'Tasks'], ['completion', 'Completion'], ['codes', 'Costing codes by week']]
          .map(([k, l]) => `<button data-k="${k}" class="${state.trend === k ? 'on' : ''}">${l}</button>`).join('')}</div></div>
      <div id="trend-body"></div>
    </div>`;

  bindRows(el.querySelector('#emp-table'), d.employees, r => navigate(`#/employees/${r.employee_id}`));
  const go = (date) => { state.date = date; navigate(`#/dashboard?date=${date}`); };
  el.querySelector('#day').addEventListener('change', e => e.target.value && go(e.target.value));
  el.querySelector('#prev').addEventListener('click', () => go(shiftDate(state.date, -1)));
  el.querySelector('#next').addEventListener('click', () => go(shiftDate(state.date, 1)));
  el.querySelector('#today')?.addEventListener('click', () => go(isoToday()));
  el.querySelector('#sync')?.addEventListener('click', (e) => withBusy(e.currentTarget, async () => {
    const r = await api.post('/api/imports/sync');
    toast(r.message || r.status, r.status !== 'ok');
    if (r.status === 'ok') render(el, ctx);
  }).catch(err => toast(err.message, true)));

  const drawTrend = () => {
    const body = el.querySelector('#trend-body');
    const short = (iso) => new Date(iso + 'T12:00:00').toLocaleDateString(undefined, { day: 'numeric', month: 'short' });
    if (state.trend === 'daily') {
      body.innerHTML = columnChart(d.daily.map(x => ({ label: x.date, short: short(x.date), value: x.hours,
        tip: `${niceDate(x.date)}<br>${fmt(x.hours, 2)} h · ${x.employees} employee(s) · ${x.tasks} task(s)` })), { aria: 'Total hours per day' });
    } else if (state.trend === 'weekly') {
      body.innerHTML = columnChart(d.weekly.map(x => ({ label: x.week, short: short(x.week), value: x.hours,
        tip: `Week of ${niceDate(x.week)}<br>${fmt(x.hours, 2)} h · ${x.tasks} task(s)` })), { aria: 'Total hours per week' });
    } else if (state.trend === 'tasks') {
      body.innerHTML = columnChart(d.daily.map(x => ({ label: x.date, short: short(x.date), value: x.tasks,
        tip: `${niceDate(x.date)}<br>${x.tasks} task(s): ${x.completed} completed, ${x.incomplete} not completed` })), { aria: 'Tasks per day' });
    } else if (state.trend === 'completion') {
      const withData = d.weekly.filter(x => x.completion_rate !== null);
      body.innerHTML = withData.length
        ? columnChart(d.weekly.map(x => ({ label: x.week, short: short(x.week), value: x.completion_rate ?? 0,
            tip: x.completion_rate === null ? `Week of ${niceDate(x.week)}: completion not recorded` : `Week of ${niceDate(x.week)}<br>${fmt(x.completion_rate)}% of tasks with a Yes/No were completed` })), { unit: '%', aria: 'Weekly completion rate' })
        : '<div class="empty">Completion (Yes/No) has not been recorded on timesheets in this period.</div>';
    } else {
      body.innerHTML = codeHeatmap(d.weekly, Object.fromEntries(d.distribution.map(c => [c.code, c.label])));
    }
  };
  el.querySelectorAll('#trend button').forEach(b => b.addEventListener('click', () => {
    state.trend = b.dataset.k;
    el.querySelectorAll('#trend button').forEach(x => x.classList.toggle('on', x === b));
    drawTrend();
  }));
  drawTrend();
}
