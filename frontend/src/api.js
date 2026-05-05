/** API 呼叫工具（v2: 含品保優化新端點） */
const BASE = import.meta.env.VITE_API_BASE_URL || '/api';

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

  // P2-2: 健康監控
  getHealth: () => request('/health'),
  getSystemInfo: () => request('/system-info'),

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

  // Reports（P1-3/P1-4: 含簽核狀態管理）
  getReports: () => request('/reports'),
  getReport: (id) => request(`/reports/${id}`),
  generateReport: (productId, data) => request(`/reports/generate/${productId}`, { method: 'POST', body: JSON.stringify(data) }),
  approveReport: (id, data) => request(`/reports/${id}/approve`, { method: 'PUT', body: JSON.stringify(data) }),
  deleteReport: (id) => request(`/reports/${id}`, { method: 'DELETE' }),
  analyzeRecord: (data) => request('/reports/analyze-record', { method: 'POST', body: JSON.stringify(data) }),

  // P3-2: 分析與趨勢
  getTrend: (period = '3months') => request(`/analytics/trend?period=${period}`),
  getCompetitorAnalysis: (fdaCode) => request(`/analytics/competitor?fda_code=${fdaCode}`),
  getMrmSummary: () => request('/analytics/mrm-summary'),

  // P1-2: 稽核日誌
  getAuditLog: (params) => request(`/analytics/audit-log?${new URLSearchParams(params)}`),

  // Crawl
  triggerCrawl: (name, options = {}) => request(`/crawl/${name}`, { method: 'POST', body: JSON.stringify({ historical: options.historical || false, product_ids: options.productIds || null }) }),
  getCrawlLogs: () => request('/crawl/logs'),
};
