import React, { useState, useEffect } from 'react';
import { api } from '../api';

export default function Recalls() {
  const [recalls, setRecalls] = useState([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [pages, setPages] = useState(1);
  const [search, setSearch] = useState('');
  const [source, setSource] = useState('');
  const [classification, setClassification] = useState('');
  const [loading, setLoading] = useState(true);
  const [stats, setStats] = useState(null);
  const [expandedId, setExpandedId] = useState(null);
  const [aiInsights, setAiInsights] = useState({});

  const handleAnalyzeRecord = async (type, record) => {
    if (aiInsights[record.id] && aiInsights[record.id] !== '分析錯誤，請重試') return;
    setAiInsights(prev => ({ ...prev, [record.id]: '<div class="spinner" style="display:inline-block;width:14px;height:14px;border-width:2px;border-color:var(--primary-color) transparent transparent transparent"></div> 分析中...' }));
    try {
      const res = await api.analyzeRecord({ record_type: type, record_id: record.id });
      setAiInsights(prev => ({ ...prev, [record.id]: res.html }));
    } catch (e) {
      setAiInsights(prev => ({ ...prev, [record.id]: '<span class="text-status-error">分析錯誤，請重試</span>' }));
    }
  };

  const fetchRecalls = async () => {
    setLoading(true);
    try {
      const params = { page, page_size: 15 };
      if (search) params.search = search;
      if (source) params.source = source;
      if (classification) params.classification = classification;

      const [data, statsData] = await Promise.all([
        api.getRecalls(params),
        page === 1 ? api.getRecallStats() : Promise.resolve(stats),
      ]);
      setRecalls(data.items || []);
      setTotal(data.total);
      setPages(data.pages || 1);
      if (page === 1) setStats(statsData);
    } catch (e) { console.error(e); }
    finally { setLoading(false); }
  };

  useEffect(() => { fetchRecalls(); }, [page, source, classification]);

  const handleSearch = (e) => {
    e.preventDefault();
    setPage(1);
    fetchRecalls();
  };

  const classColor = (c) => {
    if (c === 'Class I') return 'red';
    if (c === 'Class II') return 'amber';
    if (c === 'Class III') return 'green';
    return 'blue';
  };

  return (
    <>
      <h1 className="page-title">召回記錄</h1>
      <p className="page-subtitle">FDA 及 TFDA 醫療器材召回紀錄查詢</p>

      {/* Stats */}
      {stats && (
        <div className="stat-grid" style={{ marginBottom: 24 }}>
          <div className="stat-card" data-color="red">
            <div className="stat-label">召回總數</div>
            <div className="stat-value">{stats.total}</div>
            <div className="stat-sub">近 30 天 +{stats.recent_30d}</div>
          </div>
          {Object.entries(stats.by_classification || {}).map(([k, v]) => (
            <div key={k} className="stat-card" data-color={classColor(k)}>
              <div className="stat-label">{k}</div>
              <div className="stat-value">{v}</div>
            </div>
          ))}
        </div>
      )}

      {/* Filters */}
      <form className="search-bar" onSubmit={handleSearch}>
        <div className="search-input-wrapper">
          <span className="search-icon">🔍</span>
          <input
            className="form-input"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder="搜尋產品描述、原因、廠商…"
          />
        </div>
        <select className="form-select" style={{ width: 'auto', minWidth: 140 }}
          value={source} onChange={(e) => { setSource(e.target.value); setPage(1); }}>
          <option value="">所有來源</option>
          <option value="FDA">FDA</option>
          <option value="TFDA">TFDA</option>
        </select>
        <select className="form-select" style={{ width: 'auto', minWidth: 140 }}
          value={classification} onChange={(e) => { setClassification(e.target.value); setPage(1); }}>
          <option value="">所有等級</option>
          <option value="Class I">Class I</option>
          <option value="Class II">Class II</option>
          <option value="Class III">Class III</option>
        </select>
        <button className="btn btn-secondary btn-sm" type="submit">搜尋</button>
      </form>

      {/* Table */}
      {loading ? (
        <div className="loading-overlay"><div className="spinner"></div><span>載入中…</span></div>
      ) : recalls.length === 0 ? (
        <div className="glass-card">
          <div className="empty-state">
            <div className="empty-state-icon">📭</div>
            <h3>尚無召回記錄</h3>
            <p>系統會依據您設定的監控產品自動爬取相關召回資料</p>
          </div>
        </div>
      ) : (
        <>
          <div className="table-container">
            <table className="data-table">
              <thead>
                <tr>
                  <th>召回編號</th>
                  <th>廠商</th>
                  <th>產品描述</th>
                  <th>原因</th>
                  <th>等級</th>
                  <th>來源</th>
                  <th>日期</th>
                  <th></th>
                </tr>
              </thead>
              <tbody>
                {recalls.map((r) => (
                  <React.Fragment key={r.id}>
                  <tr style={{ cursor: 'pointer' }} onClick={() => setExpandedId(expandedId === r.id ? null : r.id)}>
                    <td style={{ fontFamily: 'var(--font-mono)', fontSize: '0.78rem' }}>
                      {r.url ? (
                        <a href={r.url} target="_blank" rel="noopener noreferrer">{r.recall_number || '—'}</a>
                      ) : (r.recall_number || '—')}
                    </td>
                    <td>{r.firm_name || '—'}</td>
                    <td style={{ maxWidth: 260, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                      {r.product_description || '—'}
                    </td>
                    <td style={{ maxWidth: 260, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                      {r.reason || '—'}
                    </td>
                    <td>
                      {r.classification && (
                        <span className={`tag tag-${classColor(r.classification)}`}>{r.classification}</span>
                      )}
                    </td>
                    <td><span className="tag tag-blue">{r.source}</span></td>
                    <td style={{ whiteSpace: 'nowrap', color: 'var(--text-tertiary)', fontSize: '0.8rem' }}>
                      {r.recall_date || '—'}
                    </td>
                    <td style={{ fontSize: '0.8rem' }}>
                      {expandedId === r.id ? '▲' : '▼'}
                    </td>
                  </tr>
                  {expandedId === r.id && (
                    <tr>
                      <td colSpan={8} style={{ background: 'var(--bg-elevated)', padding: '16px 20px' }}>
                        <div style={{ fontSize: '0.85rem', lineHeight: 1.7 }}>
                          <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                            <div>
                                <strong>產品詳細描述：</strong>
                                <p style={{ color: 'var(--text-secondary)', marginTop: 4, whiteSpace: 'pre-wrap' }}>{r.product_description || '無詳細描述'}</p>
                            </div>
                            <div>
                                <strong>召回原因：</strong>
                                <p style={{ color: 'var(--text-secondary)', marginTop: 4, whiteSpace: 'pre-wrap' }}>{r.reason || '無詳細描述'}</p>
                            </div>
                          </div>
                          <div style={{ marginTop: 16, display: 'flex', gap: '10px' }}>
                            {r.url && (
                            <a 
                              href={r.url} 
                              target="_blank" 
                              rel="noopener noreferrer"
                              className="btn btn-secondary btn-sm"
                            >
                              🔗 檢視原始來源
                            </a>
                            )}
                            <button 
                              className="btn btn-primary btn-sm ai-glow"
                              onClick={(e) => {
                                e.stopPropagation();
                                handleAnalyzeRecord('recall', r);
                              }}
                            >
                              ✨ AI 深度分析
                            </button>
                          </div>
                          {aiInsights[r.id] && (
                              <div className="mt-4 p-4 rounded bg-surface-300 ai-report-content text-sm" 
                                   style={{ border: '1px solid var(--border-color)' }}
                                   dangerouslySetInnerHTML={{ __html: aiInsights[r.id] }} />
                          )}
                        </div>
                      </td>
                    </tr>
                  )}
                  </React.Fragment>
                ))}
              </tbody>
            </table>
          </div>

          {/* Pagination */}
          <div className="pagination">
            <button disabled={page <= 1} onClick={() => setPage(page - 1)}>‹</button>
            {Array.from({ length: Math.min(pages, 7) }, (_, i) => {
              const p = pages <= 7 ? i + 1 : Math.max(1, Math.min(page - 3, pages - 6)) + i;
              return (
                <button key={p} className={p === page ? 'active' : ''} onClick={() => setPage(p)}>{p}</button>
              );
            })}
            <button disabled={page >= pages} onClick={() => setPage(page + 1)}>›</button>
            <span style={{ marginLeft: 12, fontSize: '0.78rem', color: 'var(--text-tertiary)' }}>
              共 {total} 筆
            </span>
          </div>
        </>
      )}
    </>
  );
}
