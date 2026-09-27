// All browser <-> server communication goes through here. The browser never touches the database.

export class ApiError extends Error {
  constructor(status, message) { super(message); this.status = status; }
}

let onUnauthorized = () => {};
export function setUnauthorizedHandler(fn) { onUnauthorized = fn; }

async function request(method, path, { params, body, form } = {}) {
  let url = path;
  if (params) {
    const qs = new URLSearchParams();
    for (const [k, v] of Object.entries(params)) if (v !== undefined && v !== null && v !== '') qs.set(k, v);
    const s = qs.toString();
    if (s) url += (url.includes('?') ? '&' : '?') + s;
  }
  const headers = { 'X-Requested-With': 'timesheet-app' };
  let payload;
  if (form) payload = form;
  else if (body !== undefined) { headers['Content-Type'] = 'application/json'; payload = JSON.stringify(body); }
  const res = await fetch(url, { method, headers, body: payload, credentials: 'same-origin' });
  if (res.status === 401 && !path.startsWith('/api/auth/')) { onUnauthorized(); throw new ApiError(401, 'Please sign in again.'); }
  const type = res.headers.get('content-type') || '';
  const data = type.includes('application/json') ? await res.json() : await res.text();
  if (!res.ok) {
    let msg = typeof data === 'string' ? data : data.detail;
    if (Array.isArray(msg)) msg = msg.map(d => `${(d.loc || []).slice(-1)[0]}: ${d.msg}`).join('; ');
    throw new ApiError(res.status, msg || `Request failed (${res.status})`);
  }
  return data;
}

export const api = {
  get: (path, params) => request('GET', path, { params }),
  post: (path, body, params) => request('POST', path, { body, params }),
  put: (path, body) => request('PUT', path, { body }),
  del: (path) => request('DELETE', path),
  upload: (path, file) => { const f = new FormData(); f.append('file', file); return request('POST', path, { form: f }); },
};

// Downloads go through fetch too (so the CSRF header/cookies apply uniformly), then saved via a blob link.
export async function download(path, params, fallbackName) {
  const qs = params ? '?' + new URLSearchParams(params).toString() : '';
  const res = await fetch(path + qs, { credentials: 'same-origin' });
  if (!res.ok) throw new ApiError(res.status, `Download failed (${res.status})`);
  const blob = await res.blob();
  const cd = res.headers.get('content-disposition') || '';
  const m = cd.match(/filename="?([^";]+)"?/);
  const a = document.createElement('a');
  a.href = URL.createObjectURL(blob);
  a.download = m ? m[1] : fallbackName;
  document.body.appendChild(a); a.click(); a.remove();
  setTimeout(() => URL.revokeObjectURL(a.href), 5000);
}
