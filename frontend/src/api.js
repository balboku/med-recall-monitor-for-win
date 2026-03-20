/** API 呼叫工具 */
const BASE = '/api';

async function request(path, options = {}) {
  const res = await fetch(`${BASE}${path}`, {
    headers: { 'Content-Type': 'application/json', ...options.headers },
    ...options,
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: res.statusText }));
    throw new Error(err.detail || res.statusText);
  }
  return res.json();
}

export const api = {
  // Dashboard
  getDashboard: () => request('/dashboard'),
  getAlerts: (params) => request(`/alerts?${new URLSearchParams(params)}`),
  markAlertRead: (id) => request(`/alerts/${id}/read`, { method: 'PUT' }),
  markAllAlertsRead: () => request('/alerts/read-all', { method: 'PUT' }),

  // Products
  getProducts: () => request('/products'),
  getProduct: (id) => request(`/products/${id}`),
  createProduct: (data) => request('/products', { method: 'POST', body: JSON.stringify(data) }),
  updateProduct: (id, data) => request(`/products/${id}`, { method: 'PUT', body: JSON.stringify(data) }),
  deleteProduct: (id) => request(`/products/${id}`, { method: 'DELETE' }),

  // Recalls
  getRecalls: (params) => request(`/recalls?${new URLSearchParams(params)}`),
  getRecallStats: () => request('/recalls/stats'),

  // Adverse Events
  getEvents: (params) => request(`/events?${new URLSearchParams(params)}`),
  getEventStats: () => request('/events/stats'),

  // Standards
  getStandards: () => request('/standards'),
  createStandard: (data) => request('/standards', { method: 'POST', body: JSON.stringify(data) }),
  updateStandard: (id, data) => request(`/standards/${id}`, { method: 'PUT', body: JSON.stringify(data) }),
  deleteStandard: (id) => request(`/standards/${id}`, { method: 'DELETE' }),

  // Reports
  getReports: () => request('/reports'),
  getReport: (id) => request(`/reports/${id}`),
  generateReport: (productId, data) => request(`/reports/generate/${productId}`, { method: 'POST', body: JSON.stringify(data) }),
  analyzeRecord: (data) => request('/reports/analyze-record', { method: 'POST', body: JSON.stringify(data) }),

  // Crawl
  triggerCrawl: (name, historical = false) => request(`/crawl/${name}${historical ? '?historical=true' : ''}`, { method: 'POST' }),
  getCrawlLogs: () => request('/crawl/logs'),
};
