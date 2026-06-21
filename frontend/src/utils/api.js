const BASE_URL = 'http://localhost:8000';

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
  return res.json();
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
