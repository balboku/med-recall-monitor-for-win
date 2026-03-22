import { useState, useEffect, useRef } from 'react';
import { useQuery } from '@tanstack/react-query';
import DOMPurify from 'dompurify';
import React from 'react';
import { api } from '../api';

export default function Events() {
  const [page, setPage] = useState(1);
  const [search, setSearch] = useState('');
  const [debouncedSearch, setDebouncedSearch] = useState('');
  const [eventType, setEventType] = useState('');
  const [startDate, setStartDate] = useState('');
  const [endDate, setEndDate] = useState('');

  // #4: debounce 即時搜尋
  const debounceTimer = useRef(null);
  useEffect(() => {
    debounceTimer.current = setTimeout(() => {
      setDebouncedSearch(search);
      setPage(1);
    }, 400);
    return () => clearTimeout(debounceTimer.current);
  }, [search]);
  const [expandedId, setExpandedId] = useState(null);
  const [aiInsights, setAiInsights] = useState({});
  const toggleExpand = (record) => {
    const isExpanding = expandedId !== record.id;
    setExpandedId(isExpanding ? record.id : null);
    
    // 如果正在展開，且該紀錄已有存儲的分析結果，但狀態中還沒有，則填入
    if (isExpanding && record.ai_analysis && !aiInsights[record.id]) {
      setAiInsights(prev => ({ ...prev, [record.id]: record.ai_analysis }));
    }
  };

  const handleAnalyzeRecord = async (type, record) => {
    if (aiInsights[record.id] && !aiInsights[record.id].includes('分析錯誤')) return;
    setAiInsights(prev => ({ ...prev, [record.id]: '<div class="spinner" style="display:inline-block;width:14px;height:14px;border-width:2px;border-color:var(--primary-color) transparent transparent transparent"></div> 分析中...' }));
    try {
      const res = await api.analyzeRecord({ 
        record_type: type, 
        record_id: record.id,
        raw_data: JSON.stringify(record)
      });
      setAiInsights(prev => ({ ...prev, [record.id]: res.html }));
    } catch {
      setAiInsights(prev => ({ ...prev, [record.id]: '<span class="text-status-error">分析錯誤，請重試</span>' }));
    }
  };

  const { data: pageData, isFetching: loading } = useQuery({
    queryKey: ['events', { page, debouncedSearch, eventType, startDate, endDate }],
    queryFn: () => {
      const params = { page, page_size: 15 };
      if (debouncedSearch) params.search = debouncedSearch;
      if (eventType) params.event_type = eventType;
      if (startDate) params.start_date = startDate;
      if (endDate) params.end_date = endDate;
      return api.getEvents(params);
    },
    placeholderData: (previousData) => previousData,
  });

  const { data: stats } = useQuery({
    queryKey: ['events_stats'],
    queryFn: () => api.getEventStats(),
  });

  const events = pageData?.items || [];
  const total = pageData?.total || 0;
  const pages = pageData?.pages || 1;

  const handleSearch = (e) => {
    e.preventDefault();
    setDebouncedSearch(search);
    setPage(1);
  };

  const typeColor = (t) => {
    if (!t) return 'blue';
    const tl = t.toLowerCase();
    if (tl.includes('death')) return 'red';
    if (tl.includes('injury')) return 'amber';
    if (tl.includes('malfunction')) return 'cyan';
    return 'purple';
  };

  return (
    <>
      <h1 className="page-title">不良事件</h1>
      <p className="page-subtitle">FDA MAUDE 醫療器材不良事件報告查詢</p>

      {stats && (
        <div className="stat-grid" style={{ marginBottom: 24 }}>
          <div className="stat-card" data-color="amber">
            <div className="stat-label">事件總數</div>
            <div className="stat-value">{stats.total}</div>
            <div className="stat-sub">近 30 天 +{stats.recent_30d}</div>
          </div>
          {Object.entries(stats.by_type || {}).map(([k, v]) => (
            <div key={k} className="stat-card" data-color={typeColor(k)}>
              <div className="stat-label">{k || '未分類'}</div>
              <div className="stat-value">{v}</div>
            </div>
          ))}
        </div>
      )}

      <form className="search-bar" onSubmit={handleSearch}>
        <div className="search-input-wrapper" style={{ flex: 2 }}>
          <span className="search-icon">🔍</span>
          <input
            className="form-input"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder="搜尋品牌、廠商、事件描述…"
          />
        </div>
        <div style={{ display: 'flex', gap: '8px', alignItems: 'center' }}>
          <input 
            type="date" 
            className="form-input" 
            style={{ width: 'auto' }}
            value={startDate}
            onChange={(e) => { setStartDate(e.target.value); setPage(1); }}
          />
          <span style={{ color: 'var(--text-tertiary)' }}>~</span>
          <input 
            type="date" 
            className="form-input" 
            style={{ width: 'auto' }}
            value={endDate}
            onChange={(e) => { setEndDate(e.target.value); setPage(1); }}
          />
        </div>
        <select className="form-select" style={{ width: 'auto', minWidth: 140 }}
          value={eventType} onChange={(e) => { setEventType(e.target.value); setPage(1); }}>
          <option value="">所有事件類型</option>
          <option value="Death">Death</option>
          <option value="Injury">Injury</option>
          <option value="Malfunction">Malfunction</option>
        </select>
        <button className="btn btn-secondary btn-sm" type="submit">搜尋</button>
      </form>

      {loading ? (
        <div className="loading-overlay"><div className="spinner"></div><span>載入中…</span></div>
      ) : events.length === 0 ? (
        <div className="glass-card">
          <div className="empty-state">
            <div className="empty-state-icon">📭</div>
            <h3>尚無不良事件記錄</h3>
            <p>系統會依據監控產品自動爬取 FDA MAUDE 不良事件報告</p>
          </div>
        </div>
      ) : (
        <>
          <div className="table-container">
            <table className="data-table">
              <thead>
                <tr>
                  <th>報告編號</th>
                  <th>品牌 / 廠商</th>
                  <th>事件類型</th>
                  <th>設備問題</th>
                  <th>患者結果</th>
                  <th>日期</th>
                  <th></th>
                </tr>
              </thead>
              <tbody>
                {events.map((ev) => (
                  <React.Fragment key={ev.id}>
                    <tr style={{ cursor: 'pointer' }} onClick={() => toggleExpand(ev)}>
                      <td style={{ fontFamily: 'var(--font-mono)', fontSize: '0.78rem' }}>
                        {ev.report_number || '—'}
                      </td>
                      <td>
                        <div style={{ fontWeight: 600 }}>{ev.brand_name || '—'}</div>
                        <div style={{ fontSize: '0.75rem', color: 'var(--text-tertiary)' }}>{ev.manufacturer || ''}</div>
                      </td>
                      <td>
                        {ev.event_type && (
                          <span className={`tag tag-${typeColor(ev.event_type)}`}>{ev.event_type}</span>
                        )}
                      </td>
                      <td style={{ maxWidth: 200, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                        {ev.device_problem || '—'}
                      </td>
                      <td style={{ maxWidth: 150, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                        {ev.patient_outcome || '—'}
                      </td>
                      <td style={{ whiteSpace: 'nowrap', color: 'var(--text-tertiary)', fontSize: '0.8rem' }}>
                        {ev.date_received || '—'}
                      </td>
                      <td style={{ fontSize: '0.8rem' }}>
                        {expandedId === ev.id ? '▲' : '▼'}
                      </td>
                    </tr>
                    {expandedId === ev.id && (
                      <tr key={`${ev.id}-detail`}>
                        <td colSpan={7} style={{ background: 'var(--bg-elevated)', padding: '16px 20px' }}>
                          <div style={{ fontSize: '0.85rem', lineHeight: 1.7 }}>
                            <strong>事件描述：</strong>
                            <p style={{ color: 'var(--text-secondary)', marginTop: 4, whiteSpace: 'pre-wrap' }}>
                              {ev.event_description || '無詳細描述'}
                            </p>
                            <div style={{ marginTop: 16, display: 'flex', gap: '10px' }}>
                              <a 
                                href={`https://www.accessdata.fda.gov/scripts/cdrh/cfdocs/cfmaude/detail.cfm?mdrfoi__id=${encodeURIComponent(ev.report_number || '')}`} 
                                target="_blank" 
                                rel="noopener noreferrer"
                                className="btn btn-secondary btn-sm"
                              >
                                🔗 檢視 MAUDE 原始來源
                              </a>
                              <button 
                                className="btn btn-primary btn-sm ai-glow"
                                onClick={(e) => {
                                  e.stopPropagation();
                                  handleAnalyzeRecord('event', ev);
                                }}
                              >
                                ✨ AI 深度分析
                              </button>
                            </div>
                            {aiInsights[ev.id] && (
                                <div className="mt-4 p-4 rounded bg-surface-300 ai-report-content text-sm" 
                                     style={{ border: '1px solid var(--border-color)' }}
                                     dangerouslySetInnerHTML={{ __html: DOMPurify.sanitize(aiInsights[ev.id]) }} />
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

          <div className="pagination">
            <button disabled={page <= 1} onClick={() => setPage(page - 1)}>‹</button>
            {(() => {
              const maxVisible = 7;
              let start = 1, end = pages;
              if (pages > maxVisible) {
                start = Math.max(1, page - Math.floor(maxVisible / 2));
                end = start + maxVisible - 1;
                if (end > pages) { end = pages; start = Math.max(1, end - maxVisible + 1); }
              }
              return Array.from({ length: end - start + 1 }, (_, i) => start + i).map(p => (
                <button key={p} className={p === page ? 'active' : ''} onClick={() => setPage(p)}>{p}</button>
              ));
            })()}
            <button disabled={page >= pages} onClick={() => setPage(page + 1)}>›</button>
            <span style={{ marginLeft: 12, fontSize: '0.78rem', color: 'var(--text-tertiary)' }}>共 {total} 筆</span>
          </div>
        </>
      )}
    </>
  );
}
