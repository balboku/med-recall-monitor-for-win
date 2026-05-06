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

export default function Recalls() {
  const [searchParams, setSearchParams] = useSearchParams();
  const [expandedId, setExpandedId] = useState(null);
  const [aiInsights, setAiInsights] = useState({});
  const [searchInput, setSearchInput] = useState(searchParams.get('search') || '');
  const debounceTimer = useRef(null);

  const page = Math.max(Number(searchParams.get('page') || '1') || 1, 1);
  const source = searchParams.get('source') || '';
  const classification = searchParams.get('classification') || '';
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

  const toggleExpand = (record) => {
    const isExpanding = expandedId !== record.id;
    setExpandedId(isExpanding ? record.id : null);
    if (isExpanding && record.ai_analysis && !aiInsights[record.id]) {
      setAiInsights((prev) => ({ ...prev, [record.id]: record.ai_analysis }));
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
        record_type: 'recall',
        record_id: record.id,
      });
      setAiInsights((prev) => ({ ...prev, [record.id]: res.html }));
    } catch {
      setAiInsights((prev) => ({ ...prev, [record.id]: '<span class="text-status-error">分析錯誤，請重試</span>' }));
    }
  };

  const { data: pageData, isFetching: loading } = useQuery({
    queryKey: ['recalls', { page, searchValue, source, classification, startDate, endDate, productId }],
    queryFn: () => {
      const params = { page, page_size: 15 };
      if (searchValue) params.search = searchValue;
      if (source) params.source = source;
      if (classification) params.classification = classification;
      if (startDate) params.start_date = startDate;
      if (endDate) params.end_date = endDate;
      if (productId) params.product_id = productId;
      return api.getRecalls(params);
    },
    placeholderData: (previousData) => previousData,
  });

  const { data: stats } = useQuery({
    queryKey: ['recalls_stats'],
    queryFn: api.getRecallStats,
  });

  const recalls = pageData?.items || [];
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

  const classColor = (classificationValue) => {
    if (classificationValue === 'Class I') return 'red';
    if (classificationValue === 'Class II') return 'amber';
    if (classificationValue === 'Class III') return 'green';
    return 'blue';
  };

  return (
    <>
      <h1 className="page-title">召回記錄</h1>
      <p className="page-subtitle">FDA 與 TFDA 召回資料查詢，支援 URL 篩選與 AI 單筆解析</p>

      {stats && (
        <div className="stat-grid" style={{ marginBottom: 24 }}>
          <div className="stat-card" data-color="red">
            <div className="stat-label">召回總數</div>
            <div className="stat-value">{stats.total}</div>
            <div className="stat-sub">近 30 天 +{stats.recent_30d}</div>
          </div>
          {Object.entries(stats.by_classification || {}).map(([key, value]) => (
            <div key={key} className="stat-card" data-color={classColor(key)}>
              <div className="stat-label">{key}</div>
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
            placeholder="搜尋產品描述、原因、廠商…"
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
          style={{ width: 'auto', minWidth: 120 }}
          value={source}
          onChange={(e) => updateParams({ source: e.target.value })}
        >
          <option value="">所有來源</option>
          <option value="FDA">FDA</option>
          <option value="TFDA">TFDA</option>
        </select>
        <select
          className="form-select"
          style={{ width: 'auto', minWidth: 120 }}
          value={classification}
          onChange={(e) => updateParams({ classification: e.target.value })}
        >
          <option value="">所有等級</option>
          <option value="Class I">Class I</option>
          <option value="Class II">Class II</option>
          <option value="Class III">Class III</option>
        </select>
        <button className="btn btn-secondary btn-sm" type="submit">搜尋</button>
        <button className="btn btn-ghost btn-sm" type="button" onClick={clearFilters}>清除條件</button>
      </form>

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
                  <th>監控產品</th>
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
                {recalls.map((recall) => (
                  <React.Fragment key={recall.id}>
                    <tr style={{ cursor: 'pointer' }} onClick={() => toggleExpand(recall)}>
                      <td style={{ fontFamily: 'var(--font-mono)', fontSize: '0.78rem' }}>
                        {recall.url ? (
                          <a href={recall.url} target="_blank" rel="noopener noreferrer">
                            {recall.recall_number || '—'}
                          </a>
                        ) : (recall.recall_number || '—')}
                      </td>
                      <td>{recall.product_name || '—'}</td>
                      <td>{recall.firm_name || '—'}</td>
                      <td style={{ maxWidth: 220, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                        {recall.product_description || '—'}
                      </td>
                      <td style={{ maxWidth: 220, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                        {recall.reason || '—'}
                      </td>
                      <td>
                        {recall.classification && (
                          <span className={`tag tag-${classColor(recall.classification)}`}>{recall.classification}</span>
                        )}
                      </td>
                      <td><span className="tag tag-blue">{recall.source}</span></td>
                      <td style={{ whiteSpace: 'nowrap', color: 'var(--text-tertiary)', fontSize: '0.8rem' }}>
                        {recall.recall_date || '—'}
                      </td>
                      <td style={{ fontSize: '0.8rem' }}>{expandedId === recall.id ? '▲' : '▼'}</td>
                    </tr>
                    {expandedId === recall.id && (
                      <tr>
                        <td colSpan={9} style={{ background: 'var(--bg-elevated)', padding: '16px 20px' }}>
                          <div style={{ fontSize: '0.85rem', lineHeight: 1.7 }}>
                            <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                              <div>
                                <strong>產品詳細描述：</strong>
                                <p style={{ color: 'var(--text-secondary)', marginTop: 4, whiteSpace: 'pre-wrap' }}>
                                  {recall.product_description || '無詳細描述'}
                                </p>
                              </div>
                              <div>
                                <strong>召回原因：</strong>
                                <p style={{ color: 'var(--text-secondary)', marginTop: 4, whiteSpace: 'pre-wrap' }}>
                                  {recall.reason || '無詳細描述'}
                                </p>
                              </div>
                            </div>
                            <div style={{ marginTop: 16, display: 'flex', gap: '10px' }}>
                              {recall.url && (
                                <a href={recall.url} target="_blank" rel="noopener noreferrer" className="btn btn-secondary btn-sm">
                                  🔗 檢視原始來源
                                </a>
                              )}
                              <button
                                className="btn btn-primary btn-sm ai-glow"
                                onClick={(e) => {
                                  e.stopPropagation();
                                  handleAnalyzeRecord(recall);
                                }}
                              >
                                ✨ AI 深度分析
                              </button>
                            </div>
                            {aiInsights[recall.id] && (
                              <div
                                className="mt-4 p-4 rounded bg-surface-300 ai-report-content text-sm"
                                style={{ border: '1px solid var(--border-color)' }}
                                dangerouslySetInnerHTML={{ __html: DOMPurify.sanitize(aiInsights[recall.id]) }}
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
