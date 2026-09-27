// App shell: sign-in gate, sidebar and hash router.
import { api, setUnauthorizedHandler } from '../services/api.js';
import { esc, toast } from '../components/ui.js';
import { renderLogin } from '../pages/login.js';

const PAGES = [
  { path: 'dashboard', label: 'Dashboard', load: () => import('../pages/dashboard.js') },
  { path: 'employees', label: 'Employees', load: () => import('../pages/employees.js') },
  { path: 'timesheets', label: 'Timesheets', load: () => import('../pages/timesheets.js') },
  { path: 'analytics', label: 'Analytics', load: () => import('../pages/analytics.js') },
  { path: 'reports', label: 'Reports', load: () => import('../pages/reports.js') },
  { path: 'imports', label: 'Imports', load: () => import('../pages/imports.js') },
  { path: 'settings', label: 'Settings', load: () => import('../pages/settings.js') },
];

const root = document.getElementById('app');
export const session = { user: null };
let renderToken = 0;

function parseRoute() {
  const [path = 'dashboard', ...rest] = location.hash.replace(/^#\/?/, '').split('?')[0].split('/').filter(Boolean);
  const query = Object.fromEntries(new URLSearchParams(location.hash.split('?')[1] || ''));
  return { path, params: rest, query };
}

export function navigate(hash) { if (location.hash !== hash) location.hash = hash; else route(); }

function shell() {
  root.innerHTML = `
    <div class="shell">
      <aside class="sidebar">
        <div class="brand">Timesheet Tracker<small>Hosted on your desktop</small></div>
        <nav class="nav">${PAGES.map(p => `<a href="#/${p.path}" data-p="${p.path}">${p.label}</a>`).join('')}</nav>
        <div class="spacer"></div>
        <div class="who"><div>${esc(session.user.username)} · ${esc(session.user.role)}</div><button id="logout">Sign out</button></div>
      </aside>
      <main class="main" id="page"></main>
    </div>`;
  document.getElementById('logout').addEventListener('click', async () => {
    try { await api.post('/api/auth/logout'); } catch { /* ignore */ }
    session.user = null;
    start();
  });
}

async function route() {
  if (!session.user) return;
  if (!document.getElementById('page')) shell();
  const { path, params, query } = parseRoute();
  const page = PAGES.find(p => p.path === path) || PAGES[0];
  document.querySelectorAll('.nav a').forEach(a => a.classList.toggle('active', a.dataset.p === page.path));
  const el = document.getElementById('page');
  const token = ++renderToken;
  el.innerHTML = '<p class="muted">Loading…</p>';
  document.title = `${page.label} · Timesheet Tracker`;
  try {
    const mod = await page.load();
    if (token !== renderToken) return;
    await mod.render(el, { params, query, user: session.user, isCurrent: () => token === renderToken });
  } catch (err) {
    if (token !== renderToken || err.status === 401) return;
    el.innerHTML = `<div class="card"><h2>Something went wrong</h2><p>${esc(err.message)}</p></div>`;
  }
}

async function start() {
  try {
    session.user = await api.get('/api/auth/me');
  } catch {
    session.user = null;
  }
  if (!session.user) {
    renderLogin(root, (user) => { session.user = user; root.innerHTML = ''; route(); });
    return;
  }
  root.innerHTML = '';
  route();
}

setUnauthorizedHandler(() => {
  if (!session.user) return;
  session.user = null;
  toast('Your session ended. Please sign in again.', true);
  start();
});
window.addEventListener('hashchange', route);
start();
