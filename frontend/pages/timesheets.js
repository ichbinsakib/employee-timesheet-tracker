import { api } from '../services/api.js';
import { bindRows, completedLabel, esc, fmt, isoToday, modal, niceDate, shiftDate, table } from '../components/ui.js';

const state = { start: null, end: null, employee_id: '', category_id: '', completed: '', q: '', page: 1 };

export async function render(el, ctx) {
  if (ctx.query.employee_id) state.employee_id = ctx.query.employee_id;
  state.end = state.end || isoToday();
  state.start = state.start || shiftDate(state.end, -29);
  const [employees, categories] = await Promise.all([api.get('/api/employees'), api.get('/api/categories')]);
  if (!ctx.isCurrent()) return;

  el.innerHTML = `
    <div class="page-head"><h1>Timesheets</h1></div>
    <div class="card">
      <form class="toolbar" id="filters">
        <label class="field">From<input type="date" name="start" value="${esc(state.start)}"></label>
        <label class="field">To<input type="date" name="end" value="${esc(state.end)}"></label>
        <label class="field">Employee<select name="employee_id"><option value="">All employees</option>${employees.map(e => `<option value="${e.id}" ${String(e.id) === String(state.employee_id) ? 'selected' : ''}>${esc(e.name)}</option>`).join('')}</select></label>
        <label class="field">Category<select name="category_id"><option value="">All categories</option>${categories.map(c => `<option value="${c.id}" ${String(c.id) === String(state.category_id) ? 'selected' : ''}>${esc(c.name)}</option>`).join('')}</select></label>
        <label class="field">Completed<select name="completed">${[['', 'Any'], ['yes', 'Yes'], ['no', 'No'], ['unknown', 'Not recorded']].map(([v, l]) => `<option value="${v}" ${state.completed === v ? 'selected' : ''}>${l}</option>`).join('')}</select></label>
        <label class="field">Search notes / code<input name="q" value="${esc(state.q)}" placeholder="e.g. kanban, P4627"></label>
        <label class="field">&nbsp;<button class="primary" type="submit">Apply</button></label>
      </form>
    </div>
    <div class="card"><div id="results"><p class="muted">Loading…</p></div></div>`;

  el.querySelector('#filters').addEventListener('submit', (e) => {
    e.preventDefault();
    Object.assign(state, Object.fromEntries(new FormData(e.target)), { page: 1 });
    load(el);
  });
  await load(el);
}

async function load(el) {
  const box = el.querySelector('#results');
  const { start, end, employee_id, category_id, completed, q, page } = state;
  const d = await api.get('/api/timesheets', { start, end, employee_id, category_id, completed, q, page, page_size: 50 });
  const pages = Math.max(1, Math.ceil(d.total / d.page_size));
  box.innerHTML = `
    <div class="card-head"><h2>${fmt(d.total)} entr${d.total === 1 ? 'y' : 'ies'} · ${fmt(d.total_hours, 2)} hours</h2>
      <span class="muted small">Click a row to see how its notes were categorised</span></div>
    ${table([
      { label: 'Date', render: r => esc(niceDate(r.date)) },
      { label: 'Employee', render: r => `<a href="#/employees/${r.employee_id}">${esc(r.employee)}</a>` },
      { label: 'Costing code', render: r => esc(r.costing_code || '—') },
      { label: 'Notes', cls: 'notes', render: r => esc(r.notes || '') },
      { label: 'File type', render: r => esc(r.file_type || '—') },
      { label: 'Category', render: r => esc(r.category || '—') },
      { label: 'Completed', render: r => completedLabel(r.completed) },
      { label: 'Features', key: 'features', num: true },
      { label: 'Hours', key: 'hours', num: true },
    ], d.items, { onRow: true, empty: 'No entries match these filters.' })}
    ${pages > 1 ? `<div class="toolbar" style="margin-top:12px"><button id="pp" ${page <= 1 ? 'disabled' : ''}>Previous</button><span class="muted">Page ${page} of ${pages}</span><button id="np" ${page >= pages ? 'disabled' : ''}>Next</button></div>` : ''}`;
  bindRows(box, d.items, showEntry);
  box.querySelector('#pp')?.addEventListener('click', () => { state.page--; load(el); });
  box.querySelector('#np')?.addEventListener('click', () => { state.page++; load(el); });
}

async function showEntry(row) {
  const e = await api.get(`/api/timesheets/${row.id}`);
  modal(`${e.employee} · ${niceDate(e.date)}`, `
    <p class="muted small">From “${esc(e.file)}”, Excel row ${esc(e.excel_row ?? '—')} · costing code ${esc(e.costing_code || '—')} · ${fmt(e.hours, 2)} h · completed: ${completedLabel(e.completed)}</p>
    ${e.title ? `<p><b>${esc(e.title)}</b></p>` : ''}
    <p class="small muted">The entry's hours are split evenly across its note lines to estimate time per category.</p>
    ${table([
      { label: 'Activity', render: a => esc(a.text) },
      { label: 'Category', render: a => esc(a.category || '—') },
      { label: 'Matched keyword', render: a => a.keyword ? `<code>${esc(a.keyword)}</code>` : '<span class="muted">none</span>' },
      { label: 'Est. hours', key: 'hours', num: true },
    ], e.activities)}`, { wide: true });
}
