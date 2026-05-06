import React, { useEffect, useRef, useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { useSearchParams } from 'react-router-dom';
import DOMPurify from 'dompurify';
import { api } from '../api';

function monthRange(month) {
  const [year, mon] = month.split('-').map(Number);
  const start = new Date(year, mon - 1, 1);
  const end = new Date(year, mon, 0);
  const format = (date) => date.toISOString().split('T')[0];
  return [format(start), format(end)];
}

export default function Events() {
  const [searchParams, setSearchParams] = useSearchParams();
  const [expandedId, setExpandedId] = useState(null);
  const [aiInsights, setAiInsights] = useState({});
  const [translations, setTranslations] = useState({});
  const [searchInput, setSearchInput] = useState(searchParams.get('search') || '');
  const debounceTimer = useRef(null);

  const page = Math.max(Number(searchParams.get('page') || '1') || 1, 1);
  const eventType = searchParams.get('event_type') || '';
  const startDate = searchParams.get('start_date') || '';
  const endDate = searchParams.get('end_date') || '';
  const productId = searchParams.get('product_id') || '';
  const searchValue = searchParams.get('search') || '';

  const updateParams = (updates, resetPage = true) => {
    const next = new URLSearchParams(searchParams);
    Object.entries(updates).forEach(([key, value]) => {
      if (value === '' || value === null || value === undefined) next.delete(key);
      else next.set(key, String(value));
    });
    if (resetPage) next.set('page', '1');
    setSearchParams(next);
  };

  useEffect(() => {
    setSearchInput(searchValue);
  }, [searchValue]);

  useEffect(() => {
    const month = searchParams.get('month');
    if (!month || startDate || endDate) return;
    const [monthStart, monthEnd] = monthRange(month);
    const next = new URLSearchParams(searchParams);
    next.set('start_date', monthStart);
    next.set('end_date', monthEnd);
    next.delete('month');
    next.set('page', '1');
    setSearchParams(next, { replace: true });
  }, [searchParams, setSearchParams, startDate, endDate]);

  useEffect(() => {
    debounceTimer.current = setTimeout(() => {
      if (searchInput !== searchValue) updateParams({ search: searchInput });
    }, 400);
    return () => clearTimeout(debounceTimer.current);
  }, [searchInput, searchValue]);

  const { data: products = [] } = useQuery({
    queryKey: ['products'],
    queryFn: api.getProducts,
  });

  const translateEventDescription = async (eventId, text) => {
    if (translations[eventId]) return;
    setTranslations((prev) => ({ ...prev, [eventId]: '翻譯中...' }));
    try {
      const res = await api.translateText({ text, target_lang: 'zh-TW' });
      setTranslations((prev) => ({ ...prev, [eventId]: res.translatedText }));
    } catch {
      setTranslations((prev) => ({ ...prev, [eventId]: '翻譯失敗' }));
    }
  };

  const toggleExpand = (record) => {
    const isExpanding = expandedId !== record.id;
    setExpandedId(isExpanding ? record.id : null);
    if (isExpanding && record.ai_analysis && !aiInsights[record.id]) {
      setAiInsights((prev) => ({ ...prev, [record.id]: record.ai_analysis }));
    }
    if (isExpanding && record.event_description && !translations[record.id]) {
      translateEventDescription(record.id, record.event_description);
    }
  };

  const handleAnalyzeRecord = async (record) => {
    if (aiInsights[record.id] && !aiInsights[record.id].includes('分析錯誤')) return;
    setAiInsights((prev) => ({
      ...prev,
      [record.id]: '<div class="spinner" style="display:inline-block;width:14px;height:14px;border-width:2px;border-color:var(--accent-blue) transparent transparent transparent"></div> 分析中...',
    }));
    try {
      const res = await api.analyzeRecord({
        record_type: 'event',
        record_id: record.id,
      });
      setAiInsights((prev) => ({ ...prev, [record.id]: res.html }));
    } catch {
      setAiInsights((prev) => ({ ...prev, [record.id]: '<span class="text-status-error">分析錯誤，請重試</span>' }));
    }
  };

  const { data: pageData, isFetching: loading } = useQuery({
    queryKey: ['events', { page, searchValue, eventType, startDate, endDate, productId }],
    queryFn: () => {
      const params = { page, page_size: 15 };
      if (searchValue) params.search = searchValue;
      if (eventType) params.event_type = eventType;
      if (startDate) params.start_date = startDate;
      if (endDate) params.end_date = endDate;
      if (productId) params.product_id = productId;
      return api.getEvents(params);
    },
    placeholderData: (previousData) => previousData,
  });

  const { data: stats } = useQuery({
    queryKey: ['events_stats'],
    queryFn: api.getEventStats,
  });

  const events = pageData?.items || [];
  const total = pageData?.total || 0;
  const pages = pageData?.pages || 1;

  const handleSearch = (e) => {
    e.preventDefault();
    updateParams({ search: searchInput });
  };

  const clearFilters = () => {
    setSearchInput('');
    setSearchParams({});
  };

  const typeColor = (type) => {
    if (!type) return 'blue';
    const normalized = type.toLowerCase();
    if (normalized.includes('death')) return 'red';
    if (normalized.includes('injury')) return 'amber';
    if (normalized.includes('malfunction')) return 'cyan';
    return 'purple';
  };

  return (
    <>
      <h1 className="page-title">不良事件</h1>
      <p className="page-subtitle">FDA MAUDE 事件資料查詢，支援 URL 篩選與 AI 單筆解析</p>

      {stats && (
        <div className="stat-grid" style={{ marginBottom: 24 }}>
          <div className="stat-card" data-color="amber">
            <div className="stat-label">事件總數</div>
            <div className="stat-value">{stats.total}</div>
            <div className="stat-sub">近 30 天 +{stats.recent_30d}</div>
          </div>
          {Object.entries(stats.by_type || {}).map(([key, value]) => (
            <div key={key} className="stat-card" data-color={typeColor(key)}>
              <div className="stat-label">{key || '未分類'}</div>
              <div className="stat-value">{value}</div>
            </div>
          ))}
        </div>
      )}

      <form className="search-bar" onSubmit={handleSearch}>
        <div className="search-input-wrapper" style={{ flex: 2 }}>
          <span className="search-icon">🔍</span>
          <input
            className="form-input"
            value={searchInput}
            onChange={(e) => setSearchInput(e.target.value)}
            placeholder="搜尋品牌、廠商、事件描述…"
          />
        </div>
        <select
          className="form-select"
          style={{ width: 'auto', minWidth: 170 }}
          value={productId}
          onChange={(e) => updateParams({ product_id: e.target.value })}
        >
          <option value="">所有產品</option>
          {products.map((product) => (
            <option key={product.id} value={product.id}>{product.name}</option>
          ))}
        </select>
        <div style={{ display: 'flex', gap: '8px', alignItems: 'center' }}>
          <input
            type="date"
            className="form-input"
            style={{ width: 'auto' }}
            value={startDate}
            onChange={(e) => updateParams({ start_date: e.target.value })}
          />
          <span style={{ color: 'var(--text-tertiary)' }}>~</span>
          <input
            type="date"
            className="form-input"
            style={{ width: 'auto' }}
            value={endDate}
            onChange={(e) => updateParams({ end_date: e.target.value })}
          />
        </div>
        <select
          className="form-select"
          style={{ width: 'auto', minWidth: 140 }}
          value={eventType}
          onChange={(e) => updateParams({ event_type: e.target.value })}
        >
          <option value="">所有事件類型</option>
          <option value="Death">Death</option>
          <option value="Injury">Injury</option>
          <option value="Malfunction">Malfunction</option>
        </select>
        <button className="btn btn-secondary btn-sm" type="submit">搜尋</button>
        <button className="btn btn-ghost btn-sm" type="button" onClick={clearFilters}>清除條件</button>
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
                  <th>監控產品</th>
                  <th>品牌 / 廠商</th>
                  <th>事件類型</th>
                  <th>設備問題</th>
                  <th>患者結果</th>
                  <th>日期</th>
                  <th></th>
                </tr>
              </thead>
              <tbody>
                {events.map((event) => (
                  <React.Fragment key={event.id}>
                    <tr style={{ cursor: 'pointer' }} onClick={() => toggleExpand(event)}>
                      <td style={{ fontFamily: 'var(--font-mono)', fontSize: '0.78rem' }}>
                        {event.report_number || '—'}
                      </td>
                      <td>{event.product_name || '—'}</td>
                      <td>
                        <div style={{ fontWeight: 600 }}>{event.brand_name || '—'}</div>
                        <div style={{ fontSize: '0.75rem', color: 'var(--text-tertiary)' }}>{event.manufacturer || ''}</div>
                      </td>
                      <td>
                        {event.event_type && (
                          <span className={`tag tag-${typeColor(event.event_type)}`}>{event.event_type}</span>
                        )}
                      </td>
                      <td style={{ maxWidth: 200, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                        {event.device_problem || '—'}
                      </td>
                      <td style={{ maxWidth: 150, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                        {event.patient_outcome || '—'}
                      </td>
                      <td style={{ whiteSpace: 'nowrap', color: 'var(--text-tertiary)', fontSize: '0.8rem' }}>
                        {event.date_received || '—'}
                      </td>
                      <td style={{ fontSize: '0.8rem' }}>{expandedId === event.id ? '▲' : '▼'}</td>
                    </tr>
                    {expandedId === event.id && (
                      <tr>
                        <td colSpan={8} style={{ background: 'var(--bg-elevated)', padding: '16px 20px' }}>
                          <div style={{ fontSize: '0.85rem', lineHeight: 1.7 }}>
                            <strong>事件描述：</strong>
                            <p style={{ color: 'var(--text-secondary)', marginTop: 4, whiteSpace: 'pre-wrap' }}>
                              {event.event_description_zh || translations[event.id] || '翻譯中...'}
                            </p>
                            <details style={{ marginTop: 8 }}>
                              <summary style={{ fontSize: '0.75rem', cursor: 'pointer', color: 'var(--text-tertiary)' }}>檢視原文 (English)</summary>
                              <p style={{ color: 'var(--text-tertiary)', marginTop: 4, whiteSpace: 'pre-wrap', fontSize: '0.75rem' }}>
                                {event.event_description || '無詳細描述'}
                              </p>
                            </details>
                            <div style={{ marginTop: 16, display: 'flex', gap: '10px' }}>
                              <a
                                href={event.mdr_report_key
                                  ? `https://www.accessdata.fda.gov/scripts/cdrh/cfdocs/cfmaude/detail.cfm?mdrfoi__id=${encodeURIComponent(event.mdr_report_key)}`
                                  : `https://www.accessdata.fda.gov/scripts/cdrh/cfdocs/cfMAUDE/search.CFM`}
                                target="_blank"
                                rel="noopener noreferrer"
                                className="btn btn-secondary btn-sm"
                                title={event.mdr_report_key ? "檢視原始報告" : "無原始 Key，前往 FDA 搜尋首頁"}
                              >
                                🔗 檢視 MAUDE 原始來源
                              </a>
                              <button
                                className="btn btn-primary btn-sm ai-glow"
                                onClick={(e) => {
                                  e.stopPropagation();
                                  handleAnalyzeRecord(event);
                                }}
                              >
                                ✨ AI 深度分析
                              </button>
                            </div>
                            {aiInsights[event.id] && (
                              <div
                                className="mt-4 p-4 rounded bg-surface-300 ai-report-content text-sm"
                                style={{ border: '1px solid var(--border-color)' }}
                                dangerouslySetInnerHTML={{ __html: DOMPurify.sanitize(aiInsights[event.id]) }}
                              />
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
            <button disabled={page <= 1} onClick={() => updateParams({ page: 1 }, false)} title="第一頁">«</button>
            <button disabled={page <= 1} onClick={() => updateParams({ page: page - 1 }, false)}>‹</button>
            {(() => {
              const maxVisible = 7;
              let start = 1;
              let end = pages;
              if (pages > maxVisible) {
                start = Math.max(1, page - Math.floor(maxVisible / 2));
                end = start + maxVisible - 1;
                if (end > pages) {
                  end = pages;
                  start = Math.max(1, end - maxVisible + 1);
                }
              }
              return Array.from({ length: end - start + 1 }, (_, index) => start + index).map((value) => (
                <button key={value} className={value === page ? 'active' : ''} onClick={() => updateParams({ page: value }, false)}>
                  {value}
                </button>
              ));
            })()}
            <button disabled={page >= pages} onClick={() => updateParams({ page: page + 1 }, false)}>›</button>
            <button disabled={page >= pages} onClick={() => updateParams({ page: pages }, false)} title="最後一頁">»</button>
            <span style={{ marginLeft: 12, fontSize: '0.78rem', color: 'var(--text-tertiary)' }}>
              共 {total} 筆
            </span>
          </div>
        </>
      )}
    </>
  );
}
