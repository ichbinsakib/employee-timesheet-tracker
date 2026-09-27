import { api } from '../services/api.js';
import { esc } from '../components/ui.js';

export async function renderLogin(root, onSuccess) {
  let status = { setup_required: false, can_setup_here: false };
  try { status = await api.get('/api/auth/status'); } catch { /* server unreachable: show plain login */ }

  if (status.setup_required && !status.can_setup_here) {
    root.innerHTML = `<div class="login-wrap"><div class="login"><h1>Not set up yet</h1>
      <p>No administrator account exists. Open <b>http://localhost:${esc(location.port || '8000')}</b> on the desktop that runs this app to create one.</p></div></div>`;
    return;
  }
  const setup = status.setup_required;
  root.innerHTML = `
    <div class="login-wrap"><form class="login" autocomplete="on">
      <h1>${setup ? 'Create the administrator account' : 'Sign in'}</h1>
      <p class="muted small">${setup ? 'First run. This account can manage everything; you can add more users later in Settings.' : 'Timesheet Tracker'}</p>
      <label class="field">Username<input name="username" autocomplete="username" required minlength="3"></label>
      <label class="field">Password<input name="password" type="password" autocomplete="${setup ? 'new-password' : 'current-password'}" required></label>
      ${setup ? '<label class="field">Repeat password<input name="password2" type="password" autocomplete="new-password" required></label><p class="muted small">At least 10 characters, with upper- and lower-case letters and a number.</p>' : ''}
      <div class="error-text" role="alert"></div>
      <button class="primary" type="submit">${setup ? 'Create account' : 'Sign in'}</button>
      ${status.channel && status.channel !== 'local' && !status.https ? '<p class="muted small">You are connected without HTTPS. For access from outside this network use the Tailscale HTTPS address.</p>' : ''}
    </form></div>`;
  const form = root.querySelector('form');
  const err = form.querySelector('.error-text');
  form.addEventListener('submit', async (e) => {
    e.preventDefault();
    err.textContent = '';
    const fd = Object.fromEntries(new FormData(form));
    if (setup && fd.password !== fd.password2) { err.textContent = 'Passwords do not match.'; return; }
    const btn = form.querySelector('button');
    btn.disabled = true;
    try {
      const user = await api.post(setup ? '/api/auth/setup' : '/api/auth/login', { username: fd.username, password: fd.password });
      onSuccess(user);
    } catch (ex) {
      err.textContent = ex.message;
      btn.disabled = false;
    }
  });
  form.querySelector('input').focus();
}
