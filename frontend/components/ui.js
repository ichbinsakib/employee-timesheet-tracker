// Small DOM helpers shared by every page.

export const esc = (v) => String(v ?? '').replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));

export function fmt(v, digits = 1) {
  if (v === null || v === undefined || v === '' || Number.isNaN(v)) return '—';
  if (typeof v === 'number') return Number.isInteger(v) ? v.toLocaleString() : v.toLocaleString(undefined, { maximumFractionDigits: digits });
  return String(v);
}
export const pct = (v) => (v === null || v === undefined ? '—' : `${fmt(v)}%`);
export const hrs = (v) => (v === null || v === undefined ? '—' : `${fmt(v, 2)} h`);
export const signed = (v, unit = '') => (v === null || v === undefined ? '—' : `${v > 0 ? '+' : ''}${fmt(v, 2)}${unit}`);

export function isoToday() { const d = new Date(); return new Date(d.getTime() - d.getTimezoneOffset() * 60000).toISOString().slice(0, 10); }
export function shiftDate(iso, days) { const d = new Date(iso + 'T12:00:00'); d.setDate(d.getDate() + days); return d.toISOString().slice(0, 10); }
export function niceDate(iso, opts = { weekday: 'short', day: 'numeric', month: 'short' }) {
  if (!iso) return '—';
  return new Date(iso.length === 10 ? iso + 'T12:00:00' : iso).toLocaleDateString(undefined, opts);
}
export function niceDateTime(iso) {
  if (!iso) return '—';
  return new Date(iso).toLocaleString(undefined, { day: 'numeric', month: 'short', hour: '2-digit', minute: '2-digit' });
}

export function tiles(items) {
  return `<div class="tiles">${items.map(t => `
    <div class="tile"><div class="label">${esc(t.label)}</div><div class="value">${t.html ?? esc(t.value)}</div>${t.sub ? `<div class="sub">${esc(t.sub)}</div>` : ''}</div>`).join('')}</div>`;
}

/** columns: [{key, label, num, render(row)}]; opts: {onRow(row), empty, rowAttr} */
export function table(columns, rows, opts = {}) {
  if (!rows || !rows.length) return `<div class="empty">${esc(opts.empty || 'Nothing to show.')}</div>`;
  const head = columns.map(c => `<th class="${c.num ? 'num' : ''}">${esc(c.label)}</th>`).join('');
  const body = rows.map((r, i) => `<tr data-i="${i}" class="${opts.onRow ? 'clickable' : ''}">${columns.map(c => {
    const v = c.render ? c.render(r) : esc(fmt(r[c.key]));
    return `<td class="${c.num ? 'num' : ''} ${c.cls || ''}">${v}</td>`;
  }).join('')}</tr>`).join('');
  return `<div class="table-wrap"><table><thead><tr>${head}</tr></thead><tbody>${body}</tbody></table></div>`;
}
export function bindRows(container, rows, onRow) {
  container.querySelectorAll('tbody tr[data-i]').forEach(tr => tr.addEventListener('click', (e) => {
    if (e.target.closest('a,button,input,select')) return;
    onRow(rows[Number(tr.dataset.i)]);
  }));
}

const SEV = { error: ['critical', '!'], warning: ['warning', '!'], info: ['info', 'i'], ok: ['good', '✓'] };
export function badge(text, kind = 'info') { return `<span class="badge ${esc(kind)}"><span class="dot"></span>${esc(text)}</span>`; }
export function sevBadge(sev) { return badge(sev, (SEV[sev] || SEV.info)[0]); }
export function statusBadge(status) {
  const map = { imported: ['Imported', 'good'], imported_with_warnings: ['Imported – check warnings', 'warning'], failed: ['Failed', 'critical'],
    duplicate: ['Duplicate – skipped', 'info'], superseded: ['Replaced by newer file', 'info'], ok: ['OK', 'good'], error: ['Error', 'critical'], running: ['Running', 'info'] };
  const [label, kind] = map[status] || [status, 'info'];
  return badge(label, kind);
}
export function completedLabel(v) { return v === true ? 'Yes' : v === false ? 'No' : '<span class="muted">Not recorded</span>'; }

export function alertsList(alerts, { limit = 50, empty = 'Nothing needs attention.' } = {}) {
  if (!alerts || !alerts.length) return `<div class="empty">${esc(empty)}</div>`;
  return `<div class="alerts">${alerts.slice(0, limit).map(a => `
    <div class="alert ${esc(a.severity)}"><div class="icon" aria-hidden="true">${a.severity === 'warning' ? '!' : 'i'}</div>
      <div><div class="title">${esc(a.title)}</div><div>${a.employee_id ? `<a href="#/employees/${a.employee_id}">${esc(a.message)}</a>` : esc(a.message)}</div></div></div>`).join('')}
    ${alerts.length > limit ? `<div class="muted small">+ ${alerts.length - limit} more</div>` : ''}</div>`;
}

let toastTimer;
export function toast(message, isError = false) {
  document.querySelector('.toast')?.remove();
  const el = document.createElement('div');
  el.className = 'toast' + (isError ? ' error' : '');
  el.setAttribute('role', 'status');
  el.textContent = message;
  document.body.appendChild(el);
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => el.remove(), isError ? 7000 : 3500);
}

export function modal(title, bodyHtml, { actions = [{ label: 'Close' }], wide = false } = {}) {
  return new Promise(resolve => {
    const bg = document.createElement('div');
    bg.className = 'modal-bg';
    bg.innerHTML = `<div class="modal" role="dialog" aria-modal="true" style="${wide ? 'width:min(1000px,100%)' : ''}"><h2>${esc(title)}</h2><div class="modal-body">${bodyHtml}</div>
      <div class="actions">${actions.map((a, i) => `<button data-a="${i}" class="${a.cls || ''}">${esc(a.label)}</button>`).join('')}</div></div>`;
    const close = (v) => { bg.remove(); document.removeEventListener('keydown', onKey); resolve(v); };
    const onKey = (e) => { if (e.key === 'Escape') close(null); };
    document.addEventListener('keydown', onKey);
    bg.addEventListener('click', (e) => { if (e.target === bg) close(null); });
    bg.querySelectorAll('[data-a]').forEach(b => b.addEventListener('click', async () => {
      const a = actions[Number(b.dataset.a)];
      if (a.onClick) {
        b.disabled = true;
        try { const r = await a.onClick(bg); if (r === false) { b.disabled = false; return; } close(r ?? a.value ?? true); }
        catch (err) { b.disabled = false; toast(err.message, true); }
      } else close(a.value ?? null);
    }));
    document.body.appendChild(bg);
    bg.querySelector('input,select,textarea,button')?.focus();
  });
}

export function formValues(root) {
  const out = {};
  root.querySelectorAll('[name]').forEach(el => { out[el.name] = el.type === 'checkbox' ? el.checked : el.value; });
  return out;
}

export async function withBusy(button, fn) {
  const label = button.innerHTML;
  button.disabled = true;
  button.innerHTML = 'Working…';
  try { return await fn(); }
  finally { button.disabled = false; button.innerHTML = label; }
}

export function rangeControl(days, onChange) {
  const id = 'rng' + Math.random().toString(36).slice(2, 7);
  setTimeout(() => document.getElementById(id)?.querySelectorAll('button').forEach(b => b.addEventListener('click', () => onChange(Number(b.dataset.d)))));
  return `<div class="seg" id="${id}" role="group" aria-label="Period">${[7, 30, 90, 365].map(d =>
    `<button data-d="${d}" class="${d === days ? 'on' : ''}">${d === 365 ? '12 mo' : d + ' days'}</button>`).join('')}</div>`;
}
