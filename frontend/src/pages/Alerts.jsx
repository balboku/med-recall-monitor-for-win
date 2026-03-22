import { useMemo } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useNavigate, useSearchParams } from 'react-router-dom';
import { toast } from 'react-hot-toast';
import { api } from '../api';

const alertTypeLabels = {
  recall: '召回',
  adverse_event: '不良事件',
  standard_update: '標準更新',
  crawler_failure: '爬蟲失敗',
};

function severityColor(severity) {
  if (severity === 'high') return 'red';
  if (severity === 'warning') return 'amber';
  return 'blue';
}

function resolveAlertTarget(alert) {
  if (alert.alert_type === 'crawler_failure') return '/settings';
  if (alert.reference_table === 'standards') return '/standards';
  if (alert.reference_table === 'adverse_events' || alert.alert_type === 'adverse_event') return '/events';
  return '/recalls';
}

export default function Alerts() {
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const [searchParams, setSearchParams] = useSearchParams();

  const page = Math.max(Number(searchParams.get('page') || '1') || 1, 1);
  const isRead = searchParams.get('is_read') || '';
  const alertType = searchParams.get('alert_type') || '';
  const severity = searchParams.get('severity') || '';

  const { data: alertsData, isFetching } = useQuery({
    queryKey: ['alerts', { page, isRead, alertType, severity }],
    queryFn: () => api.getAlerts({
      page,
      page_size: 20,
      ...(isRead !== '' ? { is_read: isRead } : {}),
      ...(alertType ? { alert_type: alertType } : {}),
      ...(severity ? { severity } : {}),
    }),
    placeholderData: (previousData) => previousData,
  });

  const alerts = alertsData?.items || [];
  const total = alertsData?.total || 0;
  const pageSize = alertsData?.page_size || 20;
  const pages = Math.max(1, Math.ceil(total / pageSize));

  const summary = useMemo(() => ({
    unread: alerts.filter((item) => !item.is_read).length,
    crawlerFailures: alerts.filter((item) => item.alert_type === 'crawler_failure').length,
    standards: alerts.filter((item) => item.alert_type === 'standard_update').length,
  }), [alerts]);

  const markReadMutation = useMutation({
    mutationFn: (id) => api.markAlertRead(id),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['alerts'] });
      queryClient.invalidateQueries({ queryKey: ['dashboard'] });
    },
  });

  const updateParams = (updates, resetPage = true) => {
    const next = new URLSearchParams(searchParams);
    Object.entries(updates).forEach(([key, value]) => {
      if (value === '' || value === null || value === undefined) next.delete(key);
      else next.set(key, String(value));
    });
    if (resetPage) next.set('page', '1');
    setSearchParams(next);
  };

  const handleMarkRead = async (id) => {
    try {
      await markReadMutation.mutateAsync(id);
      toast.success('已標記為已讀');
    } catch (error) {
      toast.error(error.message || '標記失敗');
    }
  };

  return (
    <>
      <div className="section-title">
        <div>
          <h1 className="page-title">告警中心</h1>
          <p className="page-subtitle">集中檢視召回、不良事件、標準異動與爬蟲失敗告警</p>
        </div>
      </div>

      <div className="stat-grid">
        <div className="stat-card" data-color="amber">
          <div className="stat-label">目前頁面未讀</div>
          <div className="stat-value">{summary.unread}</div>
        </div>
        <div className="stat-card" data-color="red">
          <div className="stat-label">爬蟲失敗告警</div>
          <div className="stat-value">{summary.crawlerFailures}</div>
        </div>
        <div className="stat-card" data-color="blue">
          <div className="stat-label">標準異動告警</div>
          <div className="stat-value">{summary.standards}</div>
        </div>
      </div>

      <div className="search-bar" style={{ marginBottom: '16px' }}>
        <select
          className="form-select"
          style={{ width: 'auto', minWidth: 140 }}
          value={isRead}
          onChange={(e) => updateParams({ is_read: e.target.value })}
        >
          <option value="">全部狀態</option>
          <option value="0">未讀</option>
          <option value="1">已讀</option>
        </select>
        <select
          className="form-select"
          style={{ width: 'auto', minWidth: 160 }}
          value={alertType}
          onChange={(e) => updateParams({ alert_type: e.target.value })}
        >
          <option value="">全部類型</option>
          {Object.entries(alertTypeLabels).map(([value, label]) => (
            <option key={value} value={value}>{label}</option>
          ))}
        </select>
        <select
          className="form-select"
          style={{ width: 'auto', minWidth: 140 }}
          value={severity}
          onChange={(e) => updateParams({ severity: e.target.value })}
        >
          <option value="">全部等級</option>
          <option value="info">資訊</option>
          <option value="warning">警示</option>
          <option value="high">高風險</option>
        </select>
      </div>

      {isFetching && !alerts.length ? (
        <div className="loading-overlay"><div className="spinner"></div><span>載入告警中…</span></div>
      ) : alerts.length === 0 ? (
        <div className="glass-card">
          <div className="empty-state">
            <div className="empty-state-icon">🔕</div>
            <h3>目前沒有符合條件的告警</h3>
            <p>系統偵測到的新召回、事件、標準異動與失敗告警會顯示在這裡</p>
          </div>
        </div>
      ) : (
        <>
          <div className="table-container">
            <table className="data-table">
              <thead>
                <tr>
                  <th>狀態</th>
                  <th>類型</th>
                  <th>標題</th>
                  <th>來源</th>
                  <th>建立時間</th>
                  <th></th>
                </tr>
              </thead>
              <tbody>
                {alerts.map((alert) => (
                  <tr key={alert.id}>
                    <td>
                      <span className={`tag ${alert.is_read ? 'tag-green' : 'tag-amber'}`}>
                        {alert.is_read ? '已讀' : '未讀'}
                      </span>
                    </td>
                    <td>
                      <span className={`tag tag-${severityColor(alert.severity)}`}>
                        {alertTypeLabels[alert.alert_type] || alert.alert_type}
                      </span>
                    </td>
                    <td style={{ minWidth: 320 }}>
                      <div style={{ fontWeight: 600 }}>{alert.title}</div>
                      <div style={{ color: 'var(--text-secondary)', fontSize: '0.8rem', marginTop: '4px', whiteSpace: 'pre-wrap' }}>
                        {alert.message || '—'}
                      </div>
                    </td>
                    <td>{alert.source || '—'}</td>
                    <td style={{ whiteSpace: 'nowrap', color: 'var(--text-tertiary)' }}>
                      {alert.created_at ? new Date(alert.created_at).toLocaleString('zh-TW') : '—'}
                    </td>
                    <td>
                      <div style={{ display: 'flex', gap: '8px', justifyContent: 'flex-end' }}>
                        {!alert.is_read && (
                          <button className="btn btn-ghost btn-sm" onClick={() => handleMarkRead(alert.id)}>
                            標記已讀
                          </button>
                        )}
                        <button
                          className="btn btn-secondary btn-sm"
                          onClick={() => navigate(resolveAlertTarget(alert))}
                        >
                          前往處理
                        </button>
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          <div className="pagination">
            <button disabled={page <= 1} onClick={() => updateParams({ page: page - 1 }, false)}>‹</button>
            {Array.from({ length: pages }, (_, index) => index + 1)
              .slice(Math.max(0, page - 4), Math.max(0, page - 4) + 7)
              .map((value) => (
                <button
                  key={value}
                  className={value === page ? 'active' : ''}
                  onClick={() => updateParams({ page: value }, false)}
                >
                  {value}
                </button>
              ))}
            <button disabled={page >= pages} onClick={() => updateParams({ page: page + 1 }, false)}>›</button>
            <span style={{ marginLeft: 12, fontSize: '0.78rem', color: 'var(--text-tertiary)' }}>
              共 {total} 筆
            </span>
          </div>
        </>
      )}
    </>
  );
}
