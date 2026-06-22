// Base URL for API requests — same origin as the backend server
const BASE_URL = window.location.hostname === 'localhost' || window.location.hostname === '127.0.0.1'
  ? `http://${window.location.hostname}:8000`
  : '';

async function request(endpoint, options = {}) {
  const url = `${BASE_URL}${endpoint}`;
  const config = {
    headers: {
      'Content-Type': 'application/json',
      ...options.headers,
    },
    ...options,
  };

  const res = await fetch(url, config);
  if (!res.ok) {
    const body = await res.text().catch(() => '');
    throw new Error(`API ${res.status}: ${body || res.statusText}`);
  }

  const json = await res.json();

  // Auto-unwrap the {ok, data} envelope that all backend endpoints return.
  // This prevents callers from having to do response.data everywhere.
  if (json && typeof json === 'object' && 'ok' in json && 'data' in json) {
    return json.data;
  }
  return json;
}

export const api = {
  get: (endpoint) => request(endpoint, { method: 'GET' }),
  post: (endpoint, body) =>
    request(endpoint, {
      method: 'POST',
      body: body != null ? JSON.stringify(body) : undefined,
    }),
  put: (endpoint, body) =>
    request(endpoint, {
      method: 'PUT',
      body: body != null ? JSON.stringify(body) : undefined,
    }),
  delete: (endpoint) => request(endpoint, { method: 'DELETE' }),
};
