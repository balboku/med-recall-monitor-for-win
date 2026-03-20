import { useState, useEffect } from 'react';
import { api } from '../api';

export default function Dashboard({ onUpdate }) {
  const [stats, setStats] = useState(null);
  const [alerts, setAlerts] = useState([]);
  const [loading, setLoading] = useState(true);

  const fetchData = async () => {
    try {
      const [dashData, alertData] = await Promise.all([
        api.getDashboard(),
        api.getAlerts({ page_size: 10 }),
      ]);
      setStats(dashData);
      setAlerts(alertData.items || []);
    } catch (e) {
      console.error(e);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => { fetchData(); }, []);

  const handleMarkRead = async (id) => {
    await api.markAlertRead(id);
    fetchData();
    onUpdate?.();
  };

  if (loading) {
    return <div className="loading-overlay"><div className="spinner"></div><span>載入中…</span></div>;
  }

  const statCards = [
    { label: '監控產品', value: stats?.active_products ?? 0, icon: '🔍', color: 'blue' },
    { label: '召回記錄', value: stats?.total_recalls ?? 0, icon: '🔔', color: 'red', sub: `近 7 天 +${stats?.new_recalls_7d ?? 0}` },
    { label: '不良事件', value: stats?.total_events ?? 0, icon: '⚠️', color: 'amber', sub: `近 7 天 +${stats?.new_events_7d ?? 0}` },
    { label: '追蹤標準', value: stats?.total_standards ?? 0, icon: '📋', color: 'cyan', sub: `${stats?.standards_with_updates ?? 0} 項有更新` },
    { label: '未讀提醒', value: stats?.unread_alerts ?? 0, icon: '📩', color: 'purple' },
  ];

  return (
    <>
      <h1 className="page-title">監控總覽</h1>
      <p className="page-subtitle">即時掌握醫療器材召回、不良事件與法規標準動態</p>

      {/* Stat cards */}
      <div className="stat-grid">
        {statCards.map((s) => (
          <div key={s.label} className="stat-card" data-color={s.color}>
            <span className="stat-icon">{s.icon}</span>
            <div className="stat-label">{s.label}</div>
            <div className="stat-value">{s.value}</div>
            {s.sub && <div className="stat-sub">{s.sub}</div>}
          </div>
        ))}
      </div>

      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 20 }}>
        {/* Latest Recalls */}
        <div className="glass-card">
          <div className="section-title">
            <h2>最新召回記錄</h2>
          </div>
          {(stats?.latest_recalls?.length ?? 0) === 0 ? (
            <div className="empty-state">
              <div className="empty-state-icon">📭</div>
              <h3>尚無召回記錄</h3>
              <p>設定產品監控後，系統將自動爬取相關資料</p>
            </div>
          ) : (
            <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
              {stats.latest_recalls.map((r) => (
                <div key={r.id} className="alert-item" style={{ borderRadius: 'var(--radius-sm)' }}>
                  <div className="alert-dot recall"></div>
                  <div className="alert-content">
                    <h4>{r.firm_name || '未知廠商'}</h4>
                    <p style={{ WebkitLineClamp: 2, overflow: 'hidden', display: '-webkit-box', WebkitBoxOrient: 'vertical' }}>
                      {r.reason || r.product_description || '—'}
                    </p>
                  </div>
                  <span className="alert-time">
                    <span className={`tag tag-${r.classification === 'Class I' ? 'red' : r.classification === 'Class II' ? 'amber' : 'green'}`}>
                      {r.classification || r.source}
                    </span>
                  </span>
                </div>
              ))}
            </div>
          )}
        </div>

        {/* Alerts */}
        <div className="glass-card">
          <div className="section-title">
            <h2>最新提醒</h2>
          </div>
          {alerts.length === 0 ? (
            <div className="empty-state">
              <div className="empty-state-icon">✅</div>
              <h3>沒有新提醒</h3>
              <p>所有提醒都已處理</p>
            </div>
          ) : (
            <div style={{ display: 'flex', flexDirection: 'column' }}>
              {alerts.map((a) => (
                <div
                  key={a.id}
                  className={`alert-item${a.is_read ? '' : ' unread'}`}
                  style={{ cursor: 'pointer' }}
                  onClick={() => !a.is_read && handleMarkRead(a.id)}
                >
                  <div className={`alert-dot ${a.alert_type}`}></div>
                  <div className="alert-content">
                    <h4>{a.title}</h4>
                    <p>{a.message}</p>
                  </div>
                  <span className="alert-time">
                    {new Date(a.created_at).toLocaleDateString('zh-TW')}
                  </span>
                </div>
              ))}
            </div>
          )}
        </div>
      </div>

      {/* Crawl Logs */}
      {stats?.latest_crawl_logs?.length > 0 && (
        <div className="glass-card" style={{ marginTop: 20 }}>
          <div className="section-title">
            <h2>最近爬蟲執行記錄</h2>
          </div>
          <div className="table-container" style={{ border: 'none' }}>
            <table className="data-table">
              <thead>
                <tr>
                  <th>爬蟲</th>
                  <th>狀態</th>
                  <th>找到</th>
                  <th>新增</th>
                  <th>完成時間</th>
                </tr>
              </thead>
              <tbody>
                {stats.latest_crawl_logs.map((log) => (
                  <tr key={log.id}>
                    <td>{log.crawler_name}</td>
                    <td>
                      <span className={`tag ${log.status === 'success' ? 'tag-green' : 'tag-red'}`}>
                        {log.status}
                      </span>
                    </td>
                    <td>{log.records_found}</td>
                    <td>{log.new_records}</td>
                    <td style={{ color: 'var(--text-tertiary)', fontSize: '0.8rem' }}>
                      {log.completed_at ? new Date(log.completed_at).toLocaleString('zh-TW') : '—'}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </>
  );
}
