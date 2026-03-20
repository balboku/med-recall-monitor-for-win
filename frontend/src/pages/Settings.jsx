import { useState, useEffect } from 'react';
import { api } from '../api';

export default function Settings() {
  const [crawlLogs, setCrawlLogs] = useState([]);
  const [crawling, setCrawling] = useState({});
  const [loading, setLoading] = useState(true);

  const fetchLogs = async () => {
    try {
      const data = await api.getCrawlLogs();
      setCrawlLogs(data);
    } catch (e) { console.error(e); }
    finally { setLoading(false); }
  };

  useEffect(() => { fetchLogs(); }, []);

  const handleCrawl = async (name, historical = false) => {
    const key = historical ? `${name}_hist` : name;
    setCrawling((prev) => ({ ...prev, [key]: true }));
    try {
      const res = await api.triggerCrawl(name, historical);
      // 因為後端現在是非同步，Res 會很快回來
      console.log('Crawl triggered:', res);
      // 延遲一下下重新抓取 Log，讓背景任務有機會寫入第一筆 Start Log
      setTimeout(fetchLogs, 1000);
      setTimeout(fetchLogs, 3000); // 3秒後再抓一次確認狀態
    } catch (e) { 
      console.error(e);
      alert(`啟動失敗: ${e.message}`);
    }
    finally { 
      setCrawling((prev) => ({ ...prev, [key]: false })); 
    }
  };

  const crawlers = [
    { name: 'fda_recall', label: 'FDA 召回爬蟲', icon: '🇺🇸', desc: '從 openFDA API 爬取醫療器材召回記錄', schedule: '每日 1 次' },
    { name: 'fda_maude', label: 'FDA MAUDE 爬蟲', icon: '⚠️', desc: '從 openFDA API 爬取 MAUDE 不良事件報告', schedule: '每日 1 次' },
    { name: 'tfda', label: 'TFDA 爬蟲', icon: '🇹🇼', desc: '從食藥署網站爬取安全警訊', schedule: '每日 1 次' },
    { name: 'standards', label: '標準版本爬蟲', icon: '📋', desc: '檢查 IEC/ISO 標準是否有新版本', schedule: '每週 1 次' },
  ];

  return (
    <>
      <h1 className="page-title">系統設定</h1>
      <p className="page-subtitle">管理爬蟲排程、手動觸發爬蟲</p>

      {/* Crawler Controls */}
      <div className="section-title" style={{ marginTop: 8 }}>
        <h2>爬蟲管理</h2>
        <button
          className="btn btn-primary btn-sm"
          onClick={() => handleCrawl('all')}
          disabled={crawling.all}
        >
          {crawling.all ? '爬取中…' : '🔄 全部執行'}
        </button>
      </div>

      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(280px, 1fr))', gap: 16, marginBottom: 28 }}>
        {crawlers.map((c) => (
          <div key={c.name} className="glass-card">
            <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: 10 }}>
              <span style={{ fontSize: '1.5rem' }}>{c.icon}</span>
              <div>
                <h3 style={{ fontSize: '0.95rem', fontWeight: 700 }}>{c.label}</h3>
                <span style={{ fontSize: '0.72rem', color: 'var(--text-tertiary)' }}>{c.schedule}</span>
              </div>
            </div>
            <p style={{ fontSize: '0.82rem', color: 'var(--text-secondary)', marginBottom: 14 }}>{c.desc}</p>
            <button
              className="btn btn-secondary btn-sm"
              onClick={() => handleCrawl(c.name)}
              disabled={crawling[c.name]}
              style={{ width: '100%', justifyContent: 'center' }}
            >
              {crawling[c.name] ? (
                <><span className="spinner" style={{ width: 14, height: 14 }}></span> 執行中…</>
              ) : '▶ 立即爬取'}
            </button>
            {(c.name === 'fda_maude' || c.name === 'fda_recall') && (
              <button
                className="btn btn-sm"
                onClick={() => handleCrawl(c.name, true)}
                disabled={crawling[`${c.name}_hist`]}
                style={{ 
                  width: '100%', 
                  marginTop: 8, 
                  justifyContent: 'center',
                  background: 'rgba(255, 255, 255, 0.05)',
                  border: '1px border var(--primary-color)',
                  color: 'var(--primary-color)'
                }}
              >
                {crawling[`${c.name}_hist`] ? (
                  <><span className="spinner" style={{ width: 14, height: 14 }}></span> 同步中…</>
                ) : '📥 歷史大量資料同步'}
              </button>
            )}
          </div>
        ))}
      </div>

      {/* Crawl Logs */}
      <div className="section-title">
        <h2>執行記錄</h2>
      </div>

      {loading ? (
        <div className="loading-overlay"><div className="spinner"></div><span>載入中…</span></div>
      ) : crawlLogs.length === 0 ? (
        <div className="glass-card">
          <div className="empty-state">
            <div className="empty-state-icon">📝</div>
            <h3>尚無執行記錄</h3>
            <p>手動執行爬蟲後，記錄將顯示於此</p>
          </div>
        </div>
      ) : (
        <div className="table-container">
          <table className="data-table">
            <thead>
              <tr>
                <th>爬蟲</th>
                <th>狀態</th>
                <th>找到記錄</th>
                <th>新增記錄</th>
                <th>錯誤</th>
                <th>開始時間</th>
                <th>完成時間</th>
              </tr>
            </thead>
            <tbody>
              {crawlLogs.map((log) => (
                <tr key={log.id}>
                  <td style={{ fontWeight: 600 }}>{log.crawler_name}</td>
                  <td>
                    <span className={`tag ${log.status === 'success' ? 'tag-green' : log.status === 'error' ? 'tag-red' : 'tag-amber'}`}>
                      {log.status}
                    </span>
                  </td>
                  <td>{log.records_found}</td>
                  <td>{log.new_records > 0 ? <strong style={{ color: 'var(--accent-green)' }}>+{log.new_records}</strong> : 0}</td>
                  <td style={{ maxWidth: 200, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', color: 'var(--accent-red)' }}>
                    {log.error_message || '—'}
                  </td>
                  <td style={{ fontSize: '0.78rem', color: 'var(--text-tertiary)', whiteSpace: 'nowrap' }}>
                    {log.started_at ? new Date(log.started_at).toLocaleString('zh-TW') : '—'}
                  </td>
                  <td style={{ fontSize: '0.78rem', color: 'var(--text-tertiary)', whiteSpace: 'nowrap' }}>
                    {log.completed_at ? new Date(log.completed_at).toLocaleString('zh-TW') : '—'}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {/* System Info */}
      <div className="glass-card" style={{ marginTop: 28 }}>
        <div className="section-title"><h2>系統資訊</h2></div>
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(200px, 1fr))', gap: 16 }}>
          <div>
            <div style={{ fontSize: '0.78rem', color: 'var(--text-tertiary)', marginBottom: 4 }}>版本</div>
            <div style={{ fontFamily: 'var(--font-mono)' }}>v1.0.0</div>
          </div>
          <div>
            <div style={{ fontSize: '0.78rem', color: 'var(--text-tertiary)', marginBottom: 4 }}>後端</div>
            <div style={{ fontFamily: 'var(--font-mono)' }}>Python FastAPI</div>
          </div>
          <div>
            <div style={{ fontSize: '0.78rem', color: 'var(--text-tertiary)', marginBottom: 4 }}>資料庫</div>
            <div style={{ fontFamily: 'var(--font-mono)' }}>SQLite (WAL mode)</div>
          </div>
          <div>
            <div style={{ fontSize: '0.78rem', color: 'var(--text-tertiary)', marginBottom: 4 }}>排程引擎</div>
            <div style={{ fontFamily: 'var(--font-mono)' }}>APScheduler</div>
          </div>
        </div>
      </div>
    </>
  );
}
