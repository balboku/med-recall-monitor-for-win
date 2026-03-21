import React, { useState, useEffect } from 'react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { api } from '../api';

export default function Reports() {
  const [selectedProduct, setSelectedProduct] = useState('');
  const [startDate, setStartDate] = useState('');
  const [endDate, setEndDate] = useState('');
  const [activeReport, setActiveReport] = useState(null);
  const [errorMsg, setErrorMsg] = useState('');
  const queryClient = useQueryClient();

  const { data: products = [] } = useQuery({
    queryKey: ['products'],
    queryFn: api.getProducts,
  });

  const { data: reports = [] } = useQuery({
    queryKey: ['reports'],
    queryFn: api.getReports,
  });

  useEffect(() => {
    if (products.length > 0 && !selectedProduct) {
      setSelectedProduct(products[0].id);
    }
  }, [products, selectedProduct]);

  const generateMutation = useMutation({
    mutationFn: async (payload) => {
      return api.generateReport(payload.productId, payload.data);
    },
    onSuccess: (newReport) => {
      setActiveReport(newReport);
      queryClient.invalidateQueries({ queryKey: ['reports'] });
    },
  });

  const handleDownload = () => {
    if (!activeReport || !activeReport.report_html) return;
    
    // 建立完整的 HTML 檔案內容
    const blob = new Blob([activeReport.report_html], { type: 'text/html' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    // 檔名包含產品名稱與日期
    a.download = `QA_Report_${activeReport.product_name}_${activeReport.start_date}_${activeReport.end_date}.html`;
    document.body.appendChild(a);
    a.click();
    
    // 清理
    document.body.removeChild(a);
    URL.revokeObjectURL(url);
  };

  const handleGenerate = async () => {
    if (!selectedProduct || !startDate || !endDate) {
      setErrorMsg('請完整填寫產品與日期區間');
      return;
    }
    setErrorMsg('');
    try {
      await generateMutation.mutateAsync({
        productId: selectedProduct,
        data: { start_date: startDate, end_date: endDate }
      });
    } catch (err) {
      setErrorMsg(err.message || '產出失敗，請檢查後端或 API Key 設定。');
    }
  };

  const loadReport = async (id) => {
    try {
      const rep = await api.getReport(id);
      setActiveReport(rep);
    } catch {
      setErrorMsg('無法載入該報告');
    }
  };

  return (
    <div className="space-y-6 animate-fade-in">
      {/* 頂部設定區 */}
      <div className="card">
        <h2 className="text-xl font-semibold text-text-primary mb-4">產出深度分析報告</h2>
        <div className="flex flex-col md:flex-row gap-4">
          <div className="flex-1">
            <label className="block text-sm text-text-secondary mb-1">監控產品</label>
            <select 
              value={selectedProduct} 
              onChange={e => setSelectedProduct(e.target.value)}
              className="input-field"
            >
              <option value="" disabled>請選擇產品</option>
              {products.map(p => (
                <option key={p.id} value={p.id}>{p.name}</option>
              ))}
            </select>
          </div>
          <div className="flex-1">
            <label className="block text-sm text-text-secondary mb-1">起始日期</label>
            <input 
              type="date" 
              value={startDate} 
              onChange={e => setStartDate(e.target.value)} 
              className="input-field" 
            />
          </div>
          <div className="flex-1">
            <label className="block text-sm text-text-secondary mb-1">結束日期</label>
            <input 
              type="date" 
              value={endDate} 
              onChange={e => setEndDate(e.target.value)} 
              className="input-field" 
            />
          </div>
          <div className="flex items-end">
            <button 
              onClick={handleGenerate} 
              disabled={generateMutation.isPending}
              className="btn btn-primary h-11 px-8 whitespace-nowrap"
            >
              {generateMutation.isPending ? '正在進行大數據精確分析 (請稍候 1-2 分鐘)...' : '✨ 產出報告'}
            </button>
          </div>
        </div>
        {errorMsg && <p className="text-status-error text-sm mt-3">{errorMsg}</p>}
      </div>

      {/* 報告顯示區與歷史紀錄 */}
      <div className="grid grid-cols-1 lg:grid-cols-4 gap-6">
        <div className="lg:col-span-1 border-r border-border-color pr-6">
          <div className="flex justify-between items-center mb-4">
            <h3 className="text-lg font-medium text-text-primary">歷史報告</h3>
            <span className="text-xs text-text-muted">{reports.length} 份</span>
          </div>
          <div className="space-y-3 overflow-y-auto pr-2" style={{ maxHeight: 'calc(100vh - 350px)' }}>
            {reports.map(r => {
              const isActive = activeReport && activeReport.id === r.id;
              return (
                <div 
                  key={r.id} 
                  onClick={() => loadReport(r.id)}
                  className={`card p-4 cursor-pointer transition-all duration-200 relative group
                    ${isActive ? 'ring-2 ring-primary-500 bg-surface-200' : 'hover:bg-surface-200 hover:translate-x-1'}`}
                >
                  {isActive && (
                    <div className="absolute left-0 top-0 bottom-0 w-1 bg-primary-500 rounded-l"></div>
                  )}
                  <div className="flex justify-between items-start">
                    <div className="text-sm font-semibold text-text-primary truncate pr-2">{r.product_name}</div>
                    {isActive && <span className="text-[10px] bg-primary-500 text-white px-1 rounded">ACTIVE</span>}
                  </div>
                  <div className="text-xs text-text-secondary mt-2 flex items-center gap-1">
                    <span className="opacity-70">📅</span> {r.start_date} ~ {r.end_date}
                  </div>
                  <div className="text-[10px] text-text-muted mt-2 border-t border-border-color pt-2 flex justify-between">
                    <span>{new Date(r.created_at).toLocaleDateString()}</span>
                    <span className="group-hover:text-primary-400 transition-colors">檢視詳情 →</span>
                  </div>
                </div>
              );
            })}
            {reports.length === 0 && (
              <div className="text-center py-10 opacity-50">
                <div className="text-3xl mb-2">📁</div>
                <p className="text-sm">尚無歷史報告</p>
              </div>
            )}
          </div>
        </div>

        <div className="lg:col-span-3">
          {activeReport ? (
            <div className="space-y-6">
              {/* 報告標頭與下載按鈕 */}
              <div className="flex justify-between items-center bg-card p-4 rounded-xl shadow-sm border border-border">
                <div>
                  <h3 className="text-lg font-bold text-text-primary">{activeReport.product_name} - 執行摘要報告</h3>
                  <p className="text-sm text-text-secondary">{activeReport.start_date} ~ {activeReport.end_date}</p>
                </div>
                <button 
                  onClick={handleDownload}
                  className="btn btn-secondary flex items-center gap-2 hover:bg-bg-secondary transition-all"
                  title="匯出專業 HTML 報表"
                >
                  <span className="text-lg">📥</span> 下載此報告
                </button>
              </div>

              {/* 統計面板 */}
              {activeReport.stats_json && Object.keys(activeReport.stats_json).length > 0 && (
                <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
                  <div className="card p-4">
                    <div className="text-sm text-text-secondary">總召回數</div>
                    <div className="text-2xl font-bold text-status-warning mt-1">{activeReport.stats_json.total_recalls || 0}</div>
                  </div>
                  <div className="card p-4">
                    <div className="text-sm text-text-secondary">總不良事件數</div>
                    <div className="text-2xl font-bold text-status-error mt-1">{activeReport.stats_json.total_events || 0}</div>
                  </div>
                  <div className="card p-4">
                    <div className="text-sm text-text-secondary">嚴重警告 (死傷)</div>
                    <div className="text-2xl font-bold text-status-danger mt-1">{activeReport.stats_json.critical_warnings || 0}</div>
                  </div>
                  <div className="card p-4">
                    <div className="text-sm text-text-secondary">主要問題</div>
                    <div className="text-xs text-text-primary mt-1 line-clamp-2">
                      {activeReport.stats_json.top_issues ? activeReport.stats_json.top_issues.join(', ') : '無資料'}
                    </div>
                  </div>
                </div>
              )}
              
              {/* HTML 報告內容 */}
              <div className="card min-h-[500px]">
                <div className="flex justify-between items-center mb-4 border-b border-border-color pb-2">
                  <h3 className="text-lg font-medium text-text-primary">
                     專家分析報告
                  </h3>
                  <span className="text-xs font-medium px-2 py-1 bg-primary-500/20 text-primary-400 rounded uppercase tracking-wide">
                    ✨ AI Executive Summary
                  </span>
                </div>
                
                <style>{`
                  .ai-report-content h1:first-of-type,
                  .ai-report-content h2:first-of-type,
                  .ai-report-content h3:first-of-type {
                    color: var(--color-primary-400);
                    font-size: 1.25rem;
                    margin-bottom: 0.75rem;
                  }
                  .ai-report-content blockquote:first-of-type,
                  .ai-report-content p:first-of-type {
                    font-size: 1.05rem;
                    line-height: 1.6;
                    color: var(--color-text-primary);
                    padding: 1rem 1.25rem;
                    background-color: rgba(59, 130, 246, 0.1); 
                    border-left: 4px solid var(--color-primary-500);
                    border-radius: 0 0.5rem 0.5rem 0;
                    margin-bottom: 2rem;
                    font-weight: 500;
                  }
                  .ai-report-content ul {
                    margin-top: 0.5rem;
                    margin-bottom: 1rem;
                  }
                  .ai-report-content li {
                    margin-bottom: 0.25rem;
                  }
                `}</style>

                <div 
                  className="prose prose-invert prose-blue max-w-none ai-report-content text-sm leading-relaxed"
                  dangerouslySetInnerHTML={{ __html: activeReport.report_html }}
                />
              </div>
            </div>
          ) : (
            <div className="card h-full flex items-center justify-center min-h-[400px]">
              <div className="text-center text-text-muted">
                <span className="text-4xl mb-3 block">📄</span>
                <p>請從左側選擇一份歷史報告，或在上方產生新報告</p>
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
