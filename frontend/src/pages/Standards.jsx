import { useState, useMemo } from 'react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { api } from '../api';
import { toast } from 'react-hot-toast';
import {
  Plus,
  Edit2,
  Trash2,
  Globe,
  CheckCircle,
  RotateCcw,
  RefreshCw,
  X,
  Info,
  AlertCircle,
  ExternalLink,
  ChevronLeft,
  ChevronRight,
  ChevronsLeft,
  ChevronsRight
} from 'lucide-react';

const emptyForm = { standard_number: '', title: '', current_version: '', source_url: '', notes: '' };

function Pagination({ currentPage, totalPages, onPageChange }) {
  const [jumpPage, setJumpPage] = useState('');

  const getPageNumbers = () => {
    const pages = [];
    if (totalPages <= 10) {
      for (let i = 1; i <= totalPages; i++) pages.push(i);
    } else {
      if (currentPage <= 6) {
        for (let i = 1; i <= 8; i++) pages.push(i);
        pages.push('...', totalPages);
      } else if (currentPage >= totalPages - 5) {
        pages.push(1, '...');
        for (let i = totalPages - 7; i <= totalPages; i++) pages.push(i);
      } else {
        pages.push(1, '...');
        for (let i = currentPage - 2; i <= currentPage + 2; i++) pages.push(i);
        pages.push('...', totalPages);
      }
    }
    return pages;
  };

  const handleJump = (e) => {
    if (e.key === 'Enter') {
      const p = parseInt(jumpPage);
      if (!isNaN(p) && p >= 1 && p <= totalPages) {
        onPageChange(p);
      }
      setJumpPage('');
    }
  };

  if (totalPages <= 1) return null;

  return (
    <div className="pagination" style={{ gap: '6px', flexWrap: 'wrap' }}>
      <button
        style={{ display: 'flex', alignItems: 'center', gap: '4px', padding: '0 12px' }}
        onClick={() => onPageChange(1)}
        disabled={currentPage === 1}
      >
        <ChevronsLeft size={16} /> 第一頁
      </button>
      <button
        style={{ display: 'flex', alignItems: 'center', gap: '4px', padding: '0 12px' }}
        onClick={() => onPageChange(currentPage - 1)}
        disabled={currentPage === 1}
      >
        <ChevronLeft size={16} /> 上一頁
      </button>

      {getPageNumbers().map((p, i) => (
        <button
          key={i}
          className={p === currentPage ? 'active' : ''}
          onClick={() => p !== '...' && onPageChange(p)}
          disabled={p === '...'}
          style={p === '...' ? { border: 'none', background: 'transparent', color: 'var(--text-secondary)' } : { padding: '0 12px' }}
        >
          {p}
        </button>
      ))}

      <button
        style={{ display: 'flex', alignItems: 'center', gap: '4px', padding: '0 12px' }}
        onClick={() => onPageChange(currentPage + 1)}
        disabled={currentPage === totalPages}
      >
        下一頁 <ChevronRight size={16} />
      </button>
      <button
        style={{ display: 'flex', alignItems: 'center', gap: '4px', padding: '0 12px' }}
        onClick={() => onPageChange(totalPages)}
        disabled={currentPage === totalPages}
      >
        最尾頁 <ChevronsRight size={16} />
      </button>

      <div style={{ display: 'flex', alignItems: 'center', gap: '8px', marginLeft: '16px', color: 'var(--text-secondary)', fontSize: '0.9rem' }}>
        跳至
        <input
          type="text"
          value={jumpPage}
          onChange={(e) => setJumpPage(e.target.value)}
          onKeyDown={handleJump}
          placeholder="頁碼"
          style={{
            width: '60px',
            height: '36px',
            padding: '4px 8px',
            background: 'var(--bg-surface)',
            border: '1px solid var(--glass-border)',
            color: 'white',
            borderRadius: 'var(--radius-sm)',
            textAlign: 'center',
            outline: 'none'
          }}
        />
        頁
      </div>
    </div>
  );
}

export default function Standards() {
  const queryClient = useQueryClient();
  const [showModal, setShowModal] = useState(false);
  const [editing, setEditing] = useState(null);
  const [form, setForm] = useState(emptyForm);
  const [currentPage, setCurrentPage] = useState(1);
  const [filterCategory, setFilterCategory] = useState('all');
  const itemsPerPage = 50;

  const { data: standards = [], isLoading: loading } = useQuery({
    queryKey: ['standards'],
    queryFn: api.getStandards,
  });

  const mutation = useMutation({
    mutationFn: async ({ action, id, payload }) => {
      if (action === 'create') return api.createStandard(payload);
      if (action === 'update') return api.updateStandard(id, payload);
      if (action === 'delete') return api.deleteStandard(id);
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['standards'] });
    },
  });

  // Derive unique categories from 'notes' field (hook must be before early return)
  const categories = useMemo(() => {
    const cats = new Set(standards.map(s => s.notes).filter(n => n && typeof n === 'string'));
    return Array.from(cats).sort();
  }, [standards]);

  const filteredStandards = useMemo(() => {
    if (filterCategory === 'all') return standards;
    return standards.filter(s => s.notes === filterCategory);
  }, [standards, filterCategory]);

  const openNew = () => { setEditing(null); setForm(emptyForm); setShowModal(true); };
  const openEdit = (s) => {
    setEditing(s);
    setForm({
      standard_number: s.standard_number,
      title: s.title,
      current_version: s.current_version || '',
      source_url: s.source_url || '',
      notes: s.notes || '',
    });
    setShowModal(true);
  };

  const handleSave = async () => {
    try {
      await mutation.mutateAsync({
        action: editing ? 'update' : 'create',
        id: editing?.id,
        payload: form,
      });
      setShowModal(false);
      toast.success('儲存成功');
    } catch (e) { toast.error(e.message); }
  };

  const handleDelete = async (id) => {
    if (!confirm('確定要移除此標準？')) return;
    try {
      await mutation.mutateAsync({ action: 'delete', id });
      setShowModal(false);
    } catch (e) { toast.error(e.message); }
  };

  const handleRefresh = async (s) => {
    try {
      toast.success(`正在為 ${s.title} 啟動更新掃描...`);
      await api.triggerCrawl('standards', { standardId: s.id });
    } catch (e) { toast.error(e.message); }
  };

  if (loading) {
    return (
      <div className="loading-overlay">
        <div className="spinner"></div>
        <span>正在同步全球標準數據庫...</span>
      </div>
    );
  }

  // Sorting: Prioritize updates, then natural order (Windows folder style) by title
  const sortedStandards = [...filteredStandards].sort((a, b) => {
    if (a.has_update && !b.has_update) return -1;
    if (!a.has_update && b.has_update) return 1;
    return (a.title || '').localeCompare(b.title || '', undefined, { numeric: true, sensitivity: 'base' });
  });

  const totalPages = Math.ceil(sortedStandards.length / itemsPerPage) || 1;
  // Ensure current page is valid when reducing data size (e.g. searching/deleting)
  const safeCurrentPage = Math.min(currentPage, totalPages);

  const startIndex = (safeCurrentPage - 1) * itemsPerPage;
  const currentData = sortedStandards.slice(startIndex, startIndex + itemsPerPage);

  return (
    <>
      <div className="section-title">
        <div>
          <h1 className="page-title">法規標準追蹤</h1>
          <p className="page-subtitle">實時監控 IEC、ISO 及各國醫療器材技術標準的修訂進度</p>
        </div>
        <div style={{ display: 'flex', gap: '12px' }}>
          <select
            className="form-select"
            value={filterCategory}
            onChange={(e) => {
              setFilterCategory(e.target.value);
              setCurrentPage(1);
            }}
            style={{ width: '200px', cursor: 'pointer' }}
          >
            <option value="all">所有類別</option>
            {categories.map(c => (
              <option key={c} value={c}>{c}</option>
            ))}
          </select>
          <button className="btn btn-primary" onClick={openNew}>
            <Plus size={18} /> 新增追蹤標準
          </button>
        </div>
      </div>

      {standards.length === 0 ? (
        <div className="glass-card" style={{ padding: '80px 40px' }}>
          <div className="empty-state">
            <div className="empty-state-icon">
              <Globe size={64} style={{ color: 'var(--accent-info)', opacity: 0.6 }} />
            </div>
            <h3>目前無追蹤項目</h3>
            <p>添加如 IEC 60601、ISO 13485 等關鍵標準，系統將自動偵測官方發布的新版本</p>
            <button className="btn btn-primary" onClick={openNew} style={{ marginTop: '12px' }}>
              <Plus size={18} /> 開始追蹤標準
            </button>
          </div>
        </div>
      ) : (
        <div style={{ display: 'flex', flexDirection: 'column', gap: '24px' }}>

          <div className="table-container">
            <table className="data-table">
              <thead>
                <tr>
                  <th>文件編號 / 法規名稱</th>
                  <th style={{ width: '160px' }}>當前版本</th>
                  <th style={{ width: '160px' }}>最新同步版本</th>
                  <th style={{ width: '180px' }}>上次檢查時間</th>
                  <th style={{ width: '120px', textAlign: 'right' }}>操作</th>
                </tr>
              </thead>
              <tbody>
                {currentData.map((s) => (
                  <tr key={s.id} style={{
                    background: s.has_update ? 'rgba(245, 158, 11, 0.05)' : 'transparent',
                    borderLeft: s.has_update ? '3px solid var(--accent-warning)' : '3px solid transparent'
                  }}>
                    <td>
                      <div style={{ display: 'flex', alignItems: 'center', gap: '10px' }}>
                        <div style={{ display: 'flex', flexDirection: 'column' }}>
                          {s.standard_number && (
                            <span style={{ fontSize: '0.85rem', color: 'var(--text-secondary)', fontFamily: 'var(--font-mono)', marginBottom: '2px' }}>
                              {s.standard_number}
                            </span>
                          )}
                          <span style={{ fontWeight: 700, fontSize: '1rem', color: 'var(--text-primary)' }}>
                            {s.title}
                          </span>
                        </div>
                        {s.has_update && (
                          <span className="tag tag-amber" style={{ display: 'flex', alignItems: 'center', gap: '4px' }}>
                            <RotateCcw size={12} /> 有新版本
                          </span>
                        )}
                      </div>
                      {s.notes && (
                        <div style={{ display: 'flex', alignItems: 'center', gap: '4px', fontSize: '0.75rem', color: 'var(--text-tertiary)', marginTop: '6px' }}>
                          <AlertCircle size={12} /> {s.notes}
                        </div>
                      )}
                    </td>
                    <td style={{ verticalAlign: 'middle' }}>
                      {s.current_version ? (
                        <span style={{ color: 'var(--text-secondary)', fontFamily: 'var(--font-mono)', fontSize: '0.9rem' }}>{s.current_version}</span>
                      ) : (
                        <span style={{ color: 'var(--text-tertiary)', fontStyle: 'italic', fontSize: '0.85rem' }}>未註記</span>
                      )}
                    </td>
                    <td style={{ verticalAlign: 'middle' }}>
                      <span style={{
                        color: s.has_update ? 'var(--accent-warning)' : 'var(--text-secondary)',
                        fontWeight: s.has_update ? 700 : 400,
                        fontFamily: 'var(--font-mono)', fontSize: '0.9rem'
                      }}>
                        {s.latest_version || (s.has_update ? '檢測到更新' : (s.current_version || '同步中'))}
                      </span>
                    </td>
                    <td style={{ verticalAlign: 'middle' }}>
                      <div style={{ display: 'flex', alignItems: 'center', gap: '6px', color: 'var(--text-tertiary)', fontSize: '0.85rem' }}>
                        <Info size={14} />
                        {s.last_checked
                          ? new Date(s.last_checked).toLocaleDateString('zh-TW', { year: 'numeric', month: '2-digit', day: '2-digit' })
                          : '尚未檢查'}
                      </div>
                    </td>
                    <td style={{ verticalAlign: 'middle', textAlign: 'right' }}>
                      <div style={{ display: 'flex', justifyContent: 'flex-end', gap: '4px' }}>
                        {s.source_url && (
                          <a href={s.source_url} target="_blank" rel="noopener noreferrer" className="btn btn-ghost btn-sm" title="查看官方文件">
                            <ExternalLink size={16} />
                          </a>
                        )}
                        <button className="btn btn-ghost btn-sm" onClick={() => handleRefresh(s)} title="執行更新掃描" style={{ color: 'var(--accent-info)' }}>
                          <RefreshCw size={16} />
                        </button>
                        <button className="btn btn-ghost btn-sm" onClick={() => openEdit(s)} title="編輯">
                          <Edit2 size={16} />
                        </button>
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          <Pagination
            currentPage={safeCurrentPage}
            totalPages={totalPages}
            onPageChange={(p) => setCurrentPage(p)}
          />
        </div>
      )}

      {/* Modal */}
      {showModal && (
        <div className="modal-overlay">
          <div className="modal" style={{ maxWidth: '600px' }}>
            <div className="modal-header">
              <h2 style={{ display: 'flex', alignItems: 'center', gap: '12px' }}>
                {editing ? <Edit2 size={20} /> : <Plus size={20} />}
                {editing ? '編輯標準資訊' : '新增追蹤標準'}
              </h2>
              <button className="btn btn-ghost btn-sm" onClick={() => setShowModal(false)}>
                <X size={20} />
              </button>
            </div>
            <div className="modal-body">
              <div className="form-group">
                <label className="form-label">公司文件編號 <span style={{ color: 'var(--accent-danger)' }}>*</span></label>
                <input className="form-input" value={form.standard_number}
                  onChange={(e) => setForm({ ...form, standard_number: e.target.value })}
                  placeholder="例：R101-0001-01" autoFocus />
              </div>
              <div className="form-group">
                <label className="form-label">法規名稱 <span style={{ color: 'var(--accent-danger)' }}>*</span></label>
                <input className="form-input" value={form.title}
                  onChange={(e) => setForm({ ...form, title: e.target.value })}
                  placeholder="例：Medical electrical equipment - General requirements" />
              </div>
              <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '16px' }}>
                <div className="form-group">
                  <label className="form-label">目前使用版本</label>
                  <input className="form-input" value={form.current_version}
                    onChange={(e) => setForm({ ...form, current_version: e.target.value })}
                    placeholder="例：Edition 3.2" />
                </div>
                <div className="form-group">
                  <label className="form-label">官方來源網址</label>
                  <input className="form-input" value={form.source_url}
                    onChange={(e) => setForm({ ...form, source_url: e.target.value })}
                    placeholder="IEC/ISO 官網頁面" />
                </div>
              </div>
              <div className="form-group">
                <label className="form-label">內部備註 / 應用範圍</label>
                <textarea className="form-textarea" value={form.notes}
                  onChange={(e) => setForm({ ...form, notes: e.target.value })}
                  placeholder="紀錄此標準與產品開發的關聯性..." style={{ minHeight: '100px' }} />
              </div>
            </div>
            <div className="modal-footer" style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
              <div>
                {editing && (
                  <button className="btn btn-ghost" onClick={() => handleDelete(editing.id)} style={{ color: 'var(--accent-danger)' }} title="刪除">
                    <Trash2 size={18} style={{ marginRight: '6px' }} />
                    刪除標準
                  </button>
                )}
              </div>
              <div style={{ display: 'flex', gap: '8px' }}>
                <button className="btn btn-secondary" onClick={() => setShowModal(false)}>取消</button>
                <button className="btn btn-primary" onClick={handleSave}
                  disabled={!form.standard_number.trim() || !form.title.trim() || mutation.isPending}>
                  {mutation.isPending ? '提交中...' : (editing ? '儲存變更' : '加入追蹤清單')}
                </button>
              </div>
            </div>
          </div>
        </div>
      )}
    </>
  );
}
