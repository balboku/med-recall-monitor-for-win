import { useEffect, useMemo, useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import DOMPurify from 'dompurify';
import { api } from '../api';
import {
  AlertTriangle,
  Calendar,
  CheckCircle2,
  ChevronUp,
  Clock,
  Download,
  FileText,
  RefreshCw,
  ShieldCheck,
  Sparkles,
  Trash2,
  Zap,
} from 'lucide-react';

function reportStatusMeta(status) {
  if (status === 'approved') return { label: '已核准', className: 'tag-green' };
  if (status === 'superseded') return { label: '已廢止', className: 'tag-red' };
  if (status === 'failed') return { label: '生成失敗', className: 'tag-red' };
  if (status === 'generating') return { label: '生成中', className: 'tag-amber' };
  return { label: '草稿', className: 'tag-blue' };
}

export default function Reports() {
  const queryClient = useQueryClient();
  const [selectedProduct, setSelectedProduct] = useState('');
  const [startDate, setStartDate] = useState('');
  const [endDate, setEndDate] = useState('');
  const [activeReportId, setActiveReportId] = useState(null);
  const [errorMsg, setErrorMsg] = useState('');
  const [showScrollTop, setShowScrollTop] = useState(false);
  const [filterProduct, setFilterProduct] = useState('');
  const [operatorName, setOperatorName] = useState('');
  const [replacementReportId, setReplacementReportId] = useState('');

  const { data: products = [] } = useQuery({
    queryKey: ['products'],
    queryFn: api.getProducts,
  });

  const { data: reportsData = [] } = useQuery({
    queryKey: ['reports'],
    queryFn: api.getReports,
    refetchInterval: (query) => {
      const data = query?.state?.data;
      if (!Array.isArray(data)) return false;
      return data.some((report) => report.report_status === 'generating') ? 5000 : false;
    },
  });

  const allReports = Array.isArray(reportsData) ? reportsData : [];
  const reports = useMemo(() => {
    if (!filterProduct) return allReports;
    return allReports.filter((report) => String(report.product_id) === String(filterProduct));
  }, [allReports, filterProduct]);

  const activeSummary = allReports.find((report) => report.id === activeReportId) || null;

  const { data: activeDetail } = useQuery({
    queryKey: ['report', activeReportId, activeSummary?.report_status],
    queryFn: () => api.getReport(activeReportId),
    enabled: Boolean(activeReportId && activeSummary?.report_status && activeSummary.report_status !== 'generating'),
  });

  const activeReport = activeDetail || activeSummary || null;
  const activeStatus = reportStatusMeta(activeReport?.report_status);
  const replacementOptions = allReports.filter((report) =>
    activeReport && report.product_id === activeReport.product_id && report.id !== activeReport.id && report.report_status !== 'generating'
  );

  useEffect(() => {
    if (products.length > 0 && !selectedProduct) {
      setSelectedProduct(String(products[0].id));
    }
  }, [products, selectedProduct]);

  useEffect(() => {
    if (activeReport && activeReport.generated_by && !operatorName) {
      setOperatorName(activeReport.generated_by);
    }
  }, [activeReport, operatorName]);

  useEffect(() => {
    const handleScroll = () => setShowScrollTop(window.scrollY > 400);
    window.addEventListener('scroll', handleScroll);
    return () => window.removeEventListener('scroll', handleScroll);
  }, []);

  useEffect(() => {
    if (activeReportId && !allReports.some((report) => report.id === activeReportId)) {
      setActiveReportId(null);
    }
  }, [activeReportId, allReports]);

  const generateMutation = useMutation({
    mutationFn: (payload) => api.generateReport(payload.productId, payload.data),
    onSuccess: (newReport) => {
      setActiveReportId(newReport.id);
      queryClient.invalidateQueries({ queryKey: ['reports'] });
    },
  });

  const approvalMutation = useMutation({
    mutationFn: ({ id, payload }) => api.approveReport(id, payload),
    onSuccess: async (_, variables) => {
      queryClient.invalidateQueries({ queryKey: ['reports'] });
      queryClient.invalidateQueries({ queryKey: ['report', variables.id] });
      setReplacementReportId('');
    },
  });

  const deleteMutation = useMutation({
    mutationFn: (id) => api.deleteReport(id),
    onSuccess: (_, id) => {
      if (activeReportId === id) setActiveReportId(null);
      queryClient.invalidateQueries({ queryKey: ['reports'] });
    },
  });

  const handleGenerate = async () => {
    if (!selectedProduct || !startDate || !endDate) {
      setErrorMsg('請完整填寫產品與日期區間');
      return;
    }
    if (startDate > endDate) {
      setErrorMsg('起始日期不可晚於結束日期');
      return;
    }
    const daysDiff = (new Date(endDate) - new Date(startDate)) / (1000 * 60 * 60 * 24);
    if (daysDiff > 1095) {
      setErrorMsg('分析期間不可超過 3 年（1095 天），請縮小範圍');
      return;
    }
    const today = new Date().toISOString().split('T')[0];
    if (endDate > today) {
      setErrorMsg('結束日期不可在未來');
      return;
    }
    setErrorMsg('');
    try {
      const operator = operatorName.trim() || 'system';
      await generateMutation.mutateAsync({
        productId: selectedProduct,
        data: { start_date: startDate, end_date: endDate, operator },
      });
    } catch (error) {
      setErrorMsg(error.message || '產出失敗');
    }
  };

  const handleApproval = async (action) => {
    if (!activeReport) return;
    if (!operatorName.trim()) {
      setErrorMsg('請先輸入操作者 / 簽核人姓名');
      return;
    }
    try {
      await approvalMutation.mutateAsync({
        id: activeReport.id,
        payload: {
          operator: operatorName.trim(),
          action,
          superseded_by: replacementReportId ? Number(replacementReportId) : null,
        },
      });
      setErrorMsg('');
    } catch (error) {
      setErrorMsg(error.message || '簽核流程失敗');
    }
  };

  const handleDownload = () => {
    if (!activeReport?.report_html) return;
    const blob = new Blob([activeReport.report_html], { type: 'text/html' });
    const url = URL.createObjectURL(blob);
    const anchor = document.createElement('a');
    anchor.href = url;
    anchor.download = `QA_Report_${activeReport.product_name || 'Report'}_${activeReport.start_date}.html`;
    document.body.appendChild(anchor);
    anchor.click();
    document.body.removeChild(anchor);
    URL.revokeObjectURL(url);
  };

  const handleDelete = async (event, id) => {
    event.stopPropagation();
    const targetReport = allReports.find((report) => report.id === id);
    if (targetReport?.report_status === 'approved') {
      setErrorMsg('已核准報告不可刪除，請使用廢止流程。');
      return;
    }
    const confirmMessage = targetReport?.report_status === 'draft'
      ? '確定要刪除這份草稿報告嗎？此操作無法復原。'
      : '確定要刪除這份報告嗎？';
    if (!window.confirm(confirmMessage)) return;

    try {
      await deleteMutation.mutateAsync(id);
    } catch (error) {
      setErrorMsg(error.message || '刪除失敗');
    }
  };

  return (
    <div className="space-y-6">
      <div className="section-title">
        <div>
          <h1 className="page-title">AI 分析報告</h1>
          <p className="page-subtitle">從資料補抓、AI 生成到人工簽核，都在同一頁完成</p>
        </div>
      </div>

      <div className="glass-card" style={{ padding: '28px' }}>
        <h2 className="text-xl font-bold text-text-primary mb-6 flex items-center gap-2">
          <Sparkles size={20} className="text-accent-blue" />
          生成深度合規分析報告
        </h2>
        <div className="grid grid-cols-1 md:grid-cols-5 gap-4">
          <div className="form-group mb-0">
            <label className="form-label">選擇監控對象</label>
            <select value={selectedProduct} onChange={(e) => setSelectedProduct(e.target.value)} className="form-select">
              <option value="" disabled>請選擇產品</option>
              {products.map((product) => (
                <option key={product.id} value={product.id}>{product.name}</option>
              ))}
            </select>
          </div>
          <div className="form-group mb-0">
            <label className="form-label">起始日期</label>
            <input type="date" value={startDate} onChange={(e) => setStartDate(e.target.value)} className="form-input" />
          </div>
          <div className="form-group mb-0">
            <label className="form-label">結束日期</label>
            <input type="date" value={endDate} onChange={(e) => setEndDate(e.target.value)} className="form-input" />
          </div>
          <div className="form-group mb-0">
            <label className="form-label">操作者 / 建立人</label>
            <input
              className="form-input"
              value={operatorName}
              onChange={(e) => setOperatorName(e.target.value)}
              placeholder="例：qa.lead"
            />
          </div>
          <div className="flex items-end">
            <button onClick={handleGenerate} disabled={generateMutation.isPending} className="btn btn-primary w-full h-[42px] justify-center">
              {generateMutation.isPending ? (
                <><RefreshCw size={18} className="spinner" /> 分析中...</>
              ) : (
                <><Sparkles size={18} /> 生成深度報告</>
              )}
            </button>
          </div>
        </div>
        {errorMsg && (
          <div style={{ marginTop: '16px', color: 'var(--accent-danger)', fontSize: '0.85rem', display: 'flex', alignItems: 'center', gap: '6px' }}>
            <AlertTriangle size={14} /> {errorMsg}
          </div>
        )}
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-4 gap-6">
        <div className="lg:col-span-1">
          <div className="glass-card" style={{ padding: '20px', height: 'fit-content' }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '12px' }}>
              <h3 className="text-lg font-bold flex items-center gap-2">
                <Clock size={18} className="text-text-tertiary" />
                歷史報告 ({reports.length})
              </h3>
            </div>
            <select
              className="form-select"
              style={{ width: '100%', marginBottom: '12px', fontSize: '0.8rem' }}
              value={filterProduct}
              onChange={(e) => setFilterProduct(e.target.value)}
            >
              <option value="">所有產品</option>
              {products.map((product) => (
                <option key={product.id} value={product.id}>{product.name}</option>
              ))}
            </select>
            <div className="space-y-2 overflow-y-auto pr-2" style={{ maxHeight: 'calc(100vh - 350px)' }}>
              {reports.map((report) => {
                const meta = reportStatusMeta(report.report_status);
                return (
                  <div
                    key={report.id}
                    onClick={() => setActiveReportId(report.id)}
                    className={`group p-3 rounded-lg cursor-pointer transition-all border ${
                      activeReportId === report.id
                        ? 'border-accent-blue bg-accent-blue-glow shadow-sm'
                        : 'border-white/5 hover:border-white/10 hover:bg-white/5'
                    }`}
                  >
                    <div className="flex justify-between items-start gap-2">
                      <div className={`text-sm font-bold truncate ${activeReportId === report.id ? 'text-accent-blue' : 'text-text-primary'}`}>
                        {report.product_name}
                      </div>
                      {report.report_status !== 'approved' && (
                        <button onClick={(event) => handleDelete(event, report.id)} className="text-accent-danger opacity-0 group-hover:opacity-100 transition-opacity">
                          <Trash2 size={14} />
                        </button>
                      )}
                    </div>
                    <div className="text-[11px] text-text-tertiary mt-1 flex items-center gap-1">
                      <Calendar size={10} />
                      {report.start_date?.split('T')[0]} ~ {report.end_date?.split('T')[0]}
                    </div>
                    <div style={{ marginTop: '8px' }}>
                      <span className={`tag ${meta.className}`}>{meta.label}</span>
                    </div>
                  </div>
                );
              })}
              {reports.length === 0 && (
                <div className="text-center py-8 text-text-tertiary text-sm italic">
                  暫無報告
                </div>
              )}
            </div>
          </div>
        </div>

        <div className="lg:col-span-3">
          {!activeReport ? (
            <div className="glass-card flex flex-col items-center justify-center min-h-[500px] text-text-tertiary text-center">
              <FileText size={64} style={{ opacity: 0.1, marginBottom: '16px' }} />
              <p>請從左側選擇一份報告或新增分析</p>
            </div>
          ) : activeReport.report_status === 'generating' ? (
            <div className="glass-card flex flex-col items-center justify-center min-h-[500px] space-y-4 text-center">
              <div className="w-16 h-16 border-4 border-accent-blue border-t-transparent rounded-full animate-spin"></div>
              <p className="text-lg font-bold">AI 專家正在進行深度數據挖掘...</p>
              <p className="text-text-tertiary text-sm">背景任務完成後，畫面會自動更新。</p>
            </div>
          ) : activeReport.report_status === 'failed' ? (
            <div className="glass-card flex flex-col items-center justify-center min-h-[300px] text-center">
              <AlertTriangle size={48} style={{ color: 'var(--accent-danger)', marginBottom: '16px' }} />
              <p className="text-lg font-bold">報告生成失敗</p>
              <p className="text-text-tertiary text-sm">請檢查日期區間、AI 金鑰或背景工作執行狀況後重新產生。</p>
            </div>
          ) : (
            <div className="space-y-6">
              <div className="sticky top-4 z-20 backdrop-blur-xl bg-bg-secondary/80 border border-white/10 rounded-2xl shadow-xl p-4 md:p-6 mb-6">
                <div className="flex flex-col md:flex-row justify-between items-start md:items-center gap-4">
                  <div>
                    <div className="flex items-center gap-2 mb-1 flex-wrap">
                      <span className="px-2 py-0.5 bg-accent-blue-glow text-accent-blue text-[10px] font-bold rounded uppercase tracking-wider flex items-center gap-1">
                        <ShieldCheck size={10} /> Deep Compliance Analysis
                      </span>
                      <span className={`tag ${activeStatus.className}`}>{activeStatus.label}</span>
                      <h3 className="text-xl font-extrabold text-text-primary">{activeReport.product_name}</h3>
                    </div>
                    <p className="text-xs text-text-tertiary flex items-center gap-2">
                      <Calendar size={14} />
                      {activeReport.start_date?.split('T')[0]} ➜ {activeReport.end_date?.split('T')[0]}
                    </p>
                    {(activeReport.approved_by || activeReport.approved_at) && (
                      <p className="text-xs text-text-tertiary" style={{ marginTop: '4px' }}>
                        簽核資訊: {activeReport.approved_by || '—'} {activeReport.approved_at ? `@ ${new Date(activeReport.approved_at).toLocaleString('zh-TW')}` : ''}
                      </p>
                    )}
                  </div>
                  <div className="flex gap-2 w-full md:w-auto flex-wrap">
                    <input
                      className="form-input"
                      style={{ minWidth: '180px', width: 'auto' }}
                      value={operatorName}
                      onChange={(e) => setOperatorName(e.target.value)}
                      placeholder="簽核人 / 操作者"
                    />
                    <button onClick={handleDownload} className="btn btn-primary px-6 shadow-lg shadow-accent-blue/20">
                      <Download size={18} /> 下載 HTML
                    </button>
                    {activeReport.report_status !== 'approved' && (
                      <button onClick={(event) => handleDelete(event, activeReport.id)} className="btn btn-secondary px-4 text-accent-danger hover:bg-accent-danger-glow border-accent-danger/20">
                        <Trash2 size={18} />
                      </button>
                    )}
                  </div>
                </div>

                <div className="mt-4 pt-4 border-t border-white/5 grid grid-cols-1 md:grid-cols-[1.2fr_1fr_auto_auto] gap-3 items-end">
                  <div>
                    <label className="form-label">替代報告（廢止時選填）</label>
                    <select className="form-select" value={replacementReportId} onChange={(e) => setReplacementReportId(e.target.value)}>
                      <option value="">不指定替代報告</option>
                      {replacementOptions.map((report) => (
                        <option key={report.id} value={report.id}>
                          #{report.id} {report.start_date?.split('T')[0]} ~ {report.end_date?.split('T')[0]} ({reportStatusMeta(report.report_status).label})
                        </option>
                      ))}
                    </select>
                  </div>
                  <div className="text-xs text-text-tertiary">
                    <div>建立人: {activeReport.generated_by || 'system'}</div>
                    <div>模型: {activeReport.model_used || '—'}</div>
                  </div>
                  {activeReport.report_status === 'draft' && (
                    <button className="btn btn-secondary justify-center" onClick={() => handleApproval('approve')} disabled={approvalMutation.isPending}>
                      {approvalMutation.isPending ? <RefreshCw size={16} className="spinner" /> : <CheckCircle2 size={16} />}
                      核准
                    </button>
                  )}
                  {activeReport.report_status !== 'superseded' && (
                    <button className="btn btn-ghost justify-center" onClick={() => handleApproval('supersede')} disabled={approvalMutation.isPending}>
                      {approvalMutation.isPending ? <RefreshCw size={16} className="spinner" /> : <AlertTriangle size={16} />}
                      廢止
                    </button>
                  )}
                </div>

                <div className="mt-4 pt-4 border-t border-white/5 flex flex-wrap gap-2 md:gap-3 overflow-x-auto no-scrollbar">
                  <NavItem href="#section-summary" label="執行摘要" />
                  <NavItem href="#section-stats" label="統計圖表" />
                  <NavItem href="#section-risk" label="風險矩陣" />
                  <NavItem href="#section-regulatory" label="法規影響" />
                  <NavItem href="#section-capa" label="改善建議" />
                </div>
              </div>

              {activeReport.stats_json && (
                <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
                  <ReportStat label="總召回數" value={activeReport.stats_json.total_recalls} color="var(--accent-warning)" icon={<AlertTriangle size={16} />} />
                  <ReportStat label="總不良事件" value={activeReport.stats_json.total_events} color="var(--accent-danger)" icon={<AlertTriangle size={16} />} />
                  <ReportStat label="嚴重警告" value={activeReport.stats_json.critical_warnings} color="var(--accent-danger)" icon={<ShieldCheck size={16} />} />
                  <div className="glass-card" style={{ padding: '16px', background: 'var(--bg-elevated)' }}>
                    <div className="text-[10px] uppercase font-bold text-text-tertiary mb-2 flex items-center gap-1">
                      <Zap size={12} className="text-accent-info" /> 主要失效模式
                    </div>
                    <div className="flex flex-wrap gap-1">
                      {activeReport.stats_json.top_issues?.slice(0, 3).map((issue, index) => (
                        <span key={index} className="text-[10px] px-1.5 py-0.5 bg-accent-info-glow rounded text-accent-info border border-accent-info/20">
                          {issue}
                        </span>
                      ))}
                    </div>
                  </div>
                </div>
              )}

              <div className="glass-card" style={{ background: 'var(--bg-surface)', border: '1px solid var(--glass-border)', padding: '40px' }}>
                <div
                  dangerouslySetInnerHTML={{ __html: DOMPurify.sanitize(activeReport.report_html || '') }}
                  className="prose prose-invert max-w-none text-sm rich-report-container"
                />
              </div>
            </div>
          )}
        </div>
      </div>

      {showScrollTop && (
        <button
          onClick={() => window.scrollTo({ top: 0, behavior: 'smooth' })}
          className="fixed bottom-8 right-8 w-12 h-12 bg-accent-blue text-white rounded-full flex items-center justify-center shadow-2xl hover:scale-110 active:scale-95 transition-all z-50"
        >
          <ChevronUp size={24} />
        </button>
      )}
    </div>
  );
}

function NavItem({ href, label }) {
  const handleClick = (event) => {
    event.preventDefault();
    const element = document.querySelector(href);
    if (!element) return;
    const offset = 200;
    const bodyTop = document.body.getBoundingClientRect().top;
    const elementTop = element.getBoundingClientRect().top;
    window.scrollTo({
      top: elementTop - bodyTop - offset,
      behavior: 'smooth',
    });
  };

  return (
    <a
      href={href}
      onClick={handleClick}
      className="text-[11px] font-bold text-text-tertiary hover:text-accent-blue px-3 py-1.5 rounded-lg bg-white/5 hover:bg-accent-blue-glow border border-white/5 hover:border-accent-blue/20 transition-all whitespace-nowrap"
    >
      {label}
    </a>
  );
}

function ReportStat({ label, value, color, icon }) {
  return (
    <div className="glass-card" style={{ padding: '16px', background: 'var(--bg-elevated)' }}>
      <div className="text-[10px] uppercase font-bold text-text-tertiary mb-1 flex items-center gap-1">
        {icon} {label}
      </div>
      <div style={{ color, fontSize: '1.5rem', fontWeight: 800 }}>{value || 0}</div>
    </div>
  );
}
