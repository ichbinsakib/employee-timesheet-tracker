// Dependency-free SVG/HTML charts. Single-series by design: magnitude is shown with one hue,
// category identity is carried by text labels (there are more categories than a safe palette has colours).
import { esc, fmt } from './ui.js';

// ---------- shared hover tooltip: any element with data-tip gets one
let tipEl;
function ensureTooltip() {
  if (tipEl) return;
  tipEl = document.createElement('div');
  tipEl.className = 'tooltip hidden';
  document.body.appendChild(tipEl);
  document.addEventListener('mousemove', (e) => {
    const t = e.target.closest?.('[data-tip]');
    if (!t) { tipEl.classList.add('hidden'); return; }
    tipEl.innerHTML = t.getAttribute('data-tip');
    tipEl.classList.remove('hidden');
    const pad = 14, w = tipEl.offsetWidth, h = tipEl.offsetHeight;
    let x = e.clientX + pad, y = e.clientY - h - pad;
    if (x + w > window.innerWidth - 8) x = e.clientX - w - pad;
    if (y < 8) y = e.clientY + pad;
    tipEl.style.left = x + 'px';
    tipEl.style.top = y + 'px';
  });
  document.addEventListener('scroll', () => tipEl.classList.add('hidden'), true);
}

function niceMax(v) {
  if (v <= 0) return 1;
  const p = Math.pow(10, Math.floor(Math.log10(v)));
  for (const m of [1, 1.2, 1.5, 2, 2.5, 3, 4, 5, 6, 8, 10]) if (m * p >= v) return m * p;
  return 10 * p;
}

/**
 * Vertical column chart.
 * data: [{label, value, tip, dim}]  opts: {height, unit, ref: {value, label}, labelEvery}
 */
export function columnChart(data, opts = {}) {
  ensureTooltip();
  if (!data.length) return '<div class="empty">No data for this period.</div>';
  const W = 720, H = opts.height || 200, L = 34, R = 8, T = 10, B = 24;
  const iw = W - L - R, ih = H - T - B;
  const maxV = niceMax(Math.max(...data.map(d => d.value || 0), opts.ref?.value || 0));
  const y = (v) => T + ih - (v / maxV) * ih;
  const step = iw / data.length;
  const bw = Math.max(Math.min(step - 2, 28), 1.5); // 2px surface gap between adjacent bars
  const ticks = [0, maxV / 2, maxV];
  const every = opts.labelEvery || Math.ceil(data.length / 10);
  let s = `<svg viewBox="0 0 ${W} ${H}" role="img" aria-label="${esc(opts.aria || 'Chart')}">`;
  for (const t of ticks) s += `<line class="grid-line" x1="${L}" x2="${W - R}" y1="${y(t)}" y2="${y(t)}"/><text x="${L - 6}" y="${y(t) + 4}" text-anchor="end">${fmt(t)}</text>`;
  data.forEach((d, i) => {
    const x = L + i * step + (step - bw) / 2;
    const v = Math.max(d.value || 0, 0);
    const h = (v / maxV) * ih;
    const r = Math.min(4, bw / 2, h);
    // rounded data-end, square at the baseline
    if (h > 0) s += `<path class="bar${d.dim ? ' dim' : ''}" d="M${x},${T + ih} V${T + ih - h + r} Q${x},${T + ih - h} ${x + r},${T + ih - h} H${x + bw - r} Q${x + bw},${T + ih - h} ${x + bw},${T + ih - h + r} V${T + ih} Z"/>`;
    s += `<rect class="hit" x="${L + i * step}" y="${T}" width="${step}" height="${ih}" data-tip="${esc(d.tip || `${d.label}: ${fmt(v)}${opts.unit || ''}`)}"/>`;
    if (i % every === 0) s += `<text x="${L + i * step + step / 2}" y="${H - 6}" text-anchor="middle">${esc(d.short ?? d.label)}</text>`;
  });
  s += `<line class="axis-line" x1="${L}" x2="${W - R}" y1="${T + ih}" y2="${T + ih}"/>`;
  if (opts.ref && opts.ref.value) {
    const ry = y(opts.ref.value);
    s += `<line class="ref-line" x1="${L}" x2="${W - R}" y1="${ry}" y2="${ry}"/><text class="ref-label" x="${W - R}" y="${ry - 4}" text-anchor="end">${esc(opts.ref.label)}</text>`;
  }
  return `<div class="chart">${s}</svg></div>`;
}

/** Horizontal bars with a text label per row. items: [{label, value, display, tip}] */
export function hbars(items, { unit = '%', max } = {}) {
  ensureTooltip();
  if (!items.length) return '<div class="empty">No data for this period.</div>';
  const top = max || Math.max(...items.map(i => i.value || 0), 1);
  return `<div class="hbars">${items.map(i => `
    <div class="hbar" data-tip="${esc(i.tip || `${i.label}: ${fmt(i.value)}${unit}`)}">
      <div>${esc(i.label)}</div>
      <div class="track"><div class="fill" style="width:${Math.max(0, (i.value || 0) / top * 100).toFixed(1)}%"></div></div>
      <div class="val">${esc(i.display ?? fmt(i.value) + unit)}</div>
    </div>`).join('')}</div>`;
}

/** Category share per week, as a sequential-blue heatmap table (one hue, light -> dark). */
export function categoryHeatmap(weeks) {
  ensureTooltip();
  const weeksWithData = weeks.filter(w => Object.keys(w.category_pct || {}).length);
  if (!weeksWithData.length) return '<div class="empty">No data for this period.</div>';
  const totals = {};
  weeksWithData.forEach(w => Object.entries(w.categories).forEach(([k, v]) => { totals[k] = (totals[k] || 0) + v; }));
  const cats = Object.keys(totals).sort((a, b) => totals[b] - totals[a]);
  const shown = weeksWithData.slice(-12);
  const level = (p) => (p === null || p === undefined || p === 0) ? 0 : Math.min(6, 1 + Math.floor(p / 10));
  const cellStyle = (lvl) => `background:var(--seq-${lvl});color:${lvl >= 4 ? '#fff' : 'var(--text)'}`;
  const head = shown.map(w => `<th class="num">${esc(new Date(w.week + 'T12:00:00').toLocaleDateString(undefined, { day: 'numeric', month: 'short' }))}</th>`).join('');
  const rows = cats.map(c => `<tr><td>${esc(c)}</td>${shown.map(w => {
    const p = w.category_pct[c];
    const lvl = level(p);
    return `<td class="cell" style="${cellStyle(lvl)}" data-tip="${esc(`${c}, week of ${w.week}: ${p ? fmt(p) + '% (' + fmt(w.categories[c], 2) + ' h est.)' : 'none'}`)}">${p ? fmt(Math.round(p)) : ''}</td>`;
  }).join('')}</tr>`).join('');
  const legend = `<div class="legend-row">Share of the week's hours:${[1, 2, 3, 4, 5, 6].map(l => `<span><span class="sw" style="background:var(--seq-${l})"></span>${l === 6 ? '50%+' : `${(l - 1) * 10}–${l * 10}%`}</span>`).join('')}</div>`;
  return `${legend}<div class="table-wrap heat"><table><thead><tr><th>Category</th>${head}</tr></thead><tbody>${rows}</tbody></table></div>`;
}
