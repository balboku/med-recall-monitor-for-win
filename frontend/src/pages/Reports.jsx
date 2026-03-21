import React, { useState, useEffect } from 'react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { api } from '../api';
import { 
  FileText, 
  Calendar, 
  Download, 
  Trash2, 
  ArrowUp, 
  BarChart2, 
  AlertTriangle, 
  Info,
  Sparkles,
  RefreshCw,
  Clock,
  ChevronRight,
  ChevronUp,
  ExternalLink,
  ShieldCheck,
  Zap
} from 'lucide-react';

export default function Reports() {
  const [selectedProduct, setSelectedProduct] = useState('');
  const [startDate, setStartDate] = useState('');
  const [endDate, setEndDate] = useState('');
  const [activeReport, setActiveReport] = useState(null);
  const [errorMsg, setErrorMsg] = useState('');
  const [showScrollTop, setShowScrollTop] = useState(false);
  const queryClient = useQueryClient();

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
      const isGenerating = data.some(r => r.report_status === 'generating');
      return isGenerating ? 5000 : false;
    }
  });

  const reports = Array.isArray(reportsData) ? reportsData : [];

  useEffect(() => {
    if (products.length > 0 && !selectedProduct) {
      setSelectedProduct(products[0].id);
    }
  }, [products, selectedProduct]);

  useEffect(() => {
    const handleScroll = () => {
      setShowScrollTop(window.scrollY > 400);
    };
    window.addEventListener('scroll', handleScroll);
    return () => window.removeEventListener('scroll', handleScroll);
  }, []);

  const generateMutation = useMutation({
    mutationFn: (payload) => api.generateReport(payload.productId, payload.data),
    onSuccess: (newReport) => {
      setActiveReport(newReport);
      queryClient.invalidateQueries({ queryKey: ['reports'] });
    },
  });

  const deleteMutation = useMutation({
    mutationFn: (id) => api.deleteReport(id),
    onSuccess: (_, id) => {
      if (activeReport?.id === id) setActiveReport(null);
      queryClient.invalidateQueries({ queryKey: ['reports'] });
    },
  });

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
      setErrorMsg(err.message || '產出失敗');
    }
  };

  const handleDownload = () => {
    if (!activeReport?.report_html) return;
    const blob = new Blob([activeReport.report_html], { type: 'text/html' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `QA_Report_${activeReport.product_name || 'Report'}_${activeReport.start_date}.html`;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    URL.revokeObjectURL(url);
  };

  const loadReport = async (id) => {
    try {
      const rep = await api.getReport(id);
      setActiveReport(rep);
      window.scrollTo({ top: 0, behavior: 'smooth' });
    } catch {
      setErrorMsg('無法載入該報告');
    }
  };

  const handleDelete = async (e, id) => {
    e.stopPropagation();
    if (window.confirm('確定要刪除這份報告嗎？')) {
      try {
        await deleteMutation.mutateAsync(id);
      } catch {
        setErrorMsg('刪除失敗');
      }
    }
  };

  return (
    <div className="space-y-6">
      <div className="section-title">
        <div>
          <h1 className="page-title">AI 分析報告</h1>
          <p className="page-subtitle">利用大語言模型對選定期間的監控數據進行深度合規分析</p>
        </div>
      </div>

      <div className="glass-card" style={{ padding: '28px' }}>
        <h2 className="text-xl font-bold text-text-primary mb-6 flex items-center gap-2">
          <Sparkles size={20} className="text-accent-blue" />
          生成深度合規分析報告
        </h2>
        <div className="grid grid-cols-1 md:grid-cols-4 gap-4">
          <div className="form-group mb-0">
            <label className="form-label">選擇監控對象</label>
            <select 
              value={selectedProduct} 
              onChange={e => setSelectedProduct(e.target.value)}
              className="form-select"
            >
              <option value="" disabled>請選擇產品</option>
              {products.map(p => (
                <option key={p.id} value={p.id}>{p.name}</option>
              ))}
            </select>
          </div>
          <div className="form-group mb-0">
            <label className="form-label">起始日期</label>
            <div style={{ position: 'relative' }}>
              <input type="date" value={startDate} onChange={e => setStartDate(e.target.value)} className="form-input" />
            </div>
          </div>
          <div className="form-group mb-0">
            <label className="form-label">結束日期</label>
            <input type="date" value={endDate} onChange={e => setEndDate(e.target.value)} className="form-input" />
          </div>
          <div className="flex items-end">
            <button 
              onClick={handleGenerate} 
              disabled={generateMutation.isPending}
              className="btn btn-primary w-full h-[42px] justify-center"
            >
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
        {/* 左側清單 */}
        <div className="lg:col-span-1">
          <div className="glass-card" style={{ padding: '20px', height: 'fit-content' }}>
            <h3 className="text-lg font-bold mb-4 flex items-center gap-2">
              <Clock size={18} className="text-text-tertiary" />
              歷史報告 ({reports.length})
            </h3>
            <div className="space-y-2 overflow-y-auto pr-2" style={{ maxHeight: 'calc(100vh - 350px)' }}>
              {reports.map(r => (
                <div 
                  key={r.id} 
                  onClick={() => loadReport(r.id)}
                  className={`group p-3 rounded-lg cursor-pointer transition-all border
                    ${activeReport?.id === r.id 
                      ? 'border-accent-blue bg-accent-blue-glow shadow-sm' 
                      : 'border-white/5 hover:border-white/10 hover:bg-white/5'}`}
                >
                  <div className="flex justify-between items-start">
                    <div className={`text-sm font-bold truncate ${activeReport?.id === r.id ? 'text-accent-blue' : 'text-text-primary'}`}>
                      {r.product_name}
                    </div>
                    <button 
                      onClick={(e) => handleDelete(e, r.id)} 
                      className="text-accent-danger opacity-0 group-hover:opacity-100 transition-opacity"
                    >
                      <Trash2 size={14} />
                    </button>
                  </div>
                  <div className="text-[11px] text-text-tertiary mt-1 flex items-center gap-1">
                    <Calendar size={10} />
                    {r.start_date.split('T')[0]} ~ {r.end_date.split('T')[0]}
                  </div>
                  {r.report_status === 'generating' && (
                    <div className="flex items-center gap-2 mt-2">
                      <RefreshCw size={10} className="spinner text-accent-warning" />
                      <span className="text-[10px] text-accent-warning">AI 生成中...</span>
                    </div>
                  )}
                </div>
              ))}
              {reports.length === 0 && (
                <div className="text-center py-8 text-text-tertiary text-sm italic">
                  暫無報告
                </div>
              )}
            </div>
          </div>
        </div>

        {/* 右側內容 */}
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
              <p className="text-text-tertiary text-sm">這通常需要 10-20 秒，請勿關閉頁面。</p>
            </div>
          ) : (
            <div className="space-y-6">
              {/* Sticky Header with ToC */}
              <div className="sticky top-4 z-20 backdrop-blur-xl bg-bg-secondary/80 border border-white/10 rounded-2xl shadow-xl p-4 md:p-6 mb-6">
                <div className="flex flex-col md:flex-row justify-between items-start md:items-center gap-4">
                  <div>
                    <div className="flex items-center gap-2 mb-1">
                      <span className="px-2 py-0.5 bg-accent-blue-glow text-accent-blue text-[10px] font-bold rounded uppercase tracking-wider flex items-center gap-1">
                        <ShieldCheck size={10} /> Deep Compliance Analysis
                      </span>
                      <h3 className="text-xl font-extrabold text-text-primary">{activeReport.product_name}</h3>
                    </div>
                    <p className="text-xs text-text-tertiary flex items-center gap-2">
                      <Calendar size={14} />
                       {activeReport.start_date.split('T')[0]} ➜ {activeReport.end_date.split('T')[0]}
                    </p>
                  </div>
                  <div className="flex gap-2 w-full md:w-auto">
                    <button onClick={handleDownload} className="btn btn-primary px-6 shadow-lg shadow-accent-blue/20">
                      <Download size={18} /> 下載 HTML 報告
                    </button>
                    <button onClick={(e) => handleDelete(e, activeReport.id)} className="btn btn-secondary px-4 text-accent-danger hover:bg-accent-danger-glow border-accent-danger/20">
                      <Trash2 size={18} />
                    </button>
                  </div>
                </div>
                
                {/* Table of Contents */}
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
                      {activeReport.stats_json.top_issues?.slice(0, 3).map((issue, idx) => (
                        <span key={idx} className="text-[10px] px-1.5 py-0.5 bg-accent-info-glow rounded text-accent-info border border-accent-info/20">{issue}</span>
                      ))}
                    </div>
                  </div>
                </div>
              )}

              <div className="glass-card" style={{ background: 'var(--bg-surface)', border: '1px solid var(--glass-border)', padding: '40px' }}>
                <div 
                  dangerouslySetInnerHTML={{ __html: activeReport.report_html }} 
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
  const handleClick = (e) => {
    e.preventDefault();
    const element = document.querySelector(href);
    if (element) {
      const offset = 200; // Account for sticky header
      const bodyRect = document.body.getBoundingClientRect().top;
      const elementRect = element.getBoundingClientRect().top;
      const elementPosition = elementRect - bodyRect;
      const offsetPosition = elementPosition - offset;

      window.scrollTo({
        top: offsetPosition,
        behavior: 'smooth'
      });
    }
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
