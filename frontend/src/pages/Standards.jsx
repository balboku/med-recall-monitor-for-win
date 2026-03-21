import { useState } from 'react';
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
  X,
  Info,
  AlertCircle,
  ExternalLink
} from 'lucide-react';

const emptyForm = { standard_number: '', title: '', current_version: '', source_url: '', notes: '' };

export default function Standards() {
  const queryClient = useQueryClient();
  const [showModal, setShowModal] = useState(false);
  const [editing, setEditing] = useState(null);
  const [form, setForm] = useState(emptyForm);

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

  const withUpdates = standards.filter((s) => s.has_update);
  const noUpdates = standards.filter((s) => !s.has_update);

  return (
    <>
      <div className="section-title">
        <div>
          <h1 className="page-title">法規標準追蹤</h1>
          <p className="page-subtitle">實時監控 IEC、ISO 及各國醫療器材技術標準的修訂進度</p>
        </div>
        <button className="btn btn-primary" onClick={openNew}>
          <Plus size={18} /> 新增追蹤標準
        </button>
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
        <div style={{ display: 'flex', flexDirection: 'column', gap: '32px' }}>
          {/* With updates section */}
          {withUpdates.length > 0 && (
            <section>
              <div style={{ display: 'flex', alignItems: 'center', gap: '8px', marginBottom: '16px' }}>
                <RotateCcw size={20} style={{ color: 'var(--accent-warning)' }} />
                <h3 style={{ fontSize: '1.1rem', fontWeight: 700, color: 'var(--accent-warning)' }}>
                  發現版本更新 ({withUpdates.length})
                </h3>
              </div>
              <div style={{ display: 'grid', gap: '16px' }}>
                {withUpdates.map((s) => (
                  <StandardCard key={s.id} standard={s} onEdit={openEdit} onDelete={handleDelete} highlight />
                ))}
              </div>
            </section>
          )}

          {/* No updates section */}
          <section>
            <div style={{ display: 'flex', alignItems: 'center', gap: '8px', marginBottom: '16px' }}>
              <CheckCircle size={20} style={{ color: 'var(--accent-success)' }} />
              <h3 style={{ fontSize: '1.1rem', fontWeight: 700, color: 'var(--text-secondary)' }}>
                版本已是最新 ({noUpdates.length})
              </h3>
            </div>
            <div style={{ display: 'grid', gap: '16px', gridTemplateColumns: 'repeat(auto-fill, minmax(450px, 1fr))' }}>
              {noUpdates.map((s) => (
                <StandardCard key={s.id} standard={s} onEdit={openEdit} onDelete={handleDelete} />
              ))}
            </div>
          </section>
        </div>
      )}

      {/* Modal */}
      {showModal && (
        <div className="modal-overlay" onClick={(e) => e.target === e.currentTarget && setShowModal(false)}>
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
                <label className="form-label">標準編號 <span style={{ color: 'var(--accent-danger)' }}>*</span></label>
                <input className="form-input" value={form.standard_number}
                  onChange={(e) => setForm({ ...form, standard_number: e.target.value })}
                  placeholder="例：IEC 60601-1" autoFocus />
              </div>
              <div className="form-group">
                <label className="form-label">完整標題 <span style={{ color: 'var(--accent-danger)' }}>*</span></label>
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
            <div className="modal-footer">
              <button className="btn btn-secondary" onClick={() => setShowModal(false)}>取消</button>
              <button className="btn btn-primary" onClick={handleSave}
                disabled={!form.standard_number.trim() || !form.title.trim() || mutation.isPending}>
                {mutation.isPending ? '提交中...' : (editing ? '儲存變更' : '加入追蹤清單')}
              </button>
            </div>
          </div>
        </div>
      )}
    </>
  );
}

function StandardCard({ standard: s, onEdit, onDelete, highlight }) {
  return (
    <div className="glass-card" style={{
      display: 'flex', 
      flexDirection: 'column',
      padding: '20px',
      borderLeft: highlight ? '4px solid var(--accent-warning)' : '1px solid var(--glass-border)',
      background: highlight ? 'rgba(245, 158, 11, 0.03)' : 'var(--glass-bg)',
      transition: 'all var(--transition-normal)'
    }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', marginBottom: '12px' }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: '10px' }}>
          <span style={{
            fontFamily: 'var(--font-mono)', fontSize: '1rem', fontWeight: 700,
            color: 'var(--text-primary)',
          }}>
            {s.standard_number}
          </span>
          {s.has_update ? (
            <span className="tag tag-amber" style={{ display: 'flex', alignItems: 'center', gap: '4px' }}>
              <RotateCcw size={12} /> 有新版本
            </span>
          ) : (
            <span className="tag tag-green" style={{ display: 'flex', alignItems: 'center', gap: '4px' }}>
              <CheckCircle size={12} /> 最新
            </span>
          )}
        </div>
        <div style={{ display: 'flex', gap: '4px' }}>
          {s.source_url && (
            <a href={s.source_url} target="_blank" rel="noopener noreferrer" className="btn btn-ghost btn-sm" title="查看官方文件">
              <ExternalLink size={16} />
            </a>
          )}
          <button className="btn btn-ghost btn-sm" onClick={() => onEdit(s)} title="編輯">
            <Edit2 size={16} />
          </button>
          <button className="btn btn-ghost btn-sm" onClick={() => onDelete(s.id)} style={{ color: 'var(--accent-danger)' }} title="刪除">
            <Trash2 size={16} />
          </button>
        </div>
      </div>

      <div style={{ fontSize: '0.9rem', color: 'var(--text-secondary)', marginBottom: '16px', fontWeight: 500 }}>
        {s.title}
      </div>

      <div style={{ 
        marginTop: 'auto',
        display: 'grid', 
        gridTemplateColumns: '1fr 1fr', 
        gap: '12px', 
        fontSize: '0.8rem', 
        padding: '12px',
        background: 'rgba(255,255,255,0.02)',
        borderRadius: '8px',
        border: '1px solid var(--glass-border)'
      }}>
        <div style={{ display: 'flex', flexDirection: 'column', gap: '4px' }}>
          <span style={{ color: 'var(--text-tertiary)', fontWeight: 600 }}>當前版本</span>
          <span style={{ color: 'var(--text-primary)' }}>{s.current_version || '未註記'}</span>
        </div>
        <div style={{ display: 'flex', flexDirection: 'column', gap: '4px' }}>
          <span style={{ color: 'var(--text-tertiary)', fontWeight: 600 }}>最新同步版本</span>
          <span style={{ color: s.has_update ? 'var(--accent-warning)' : 'var(--text-primary)', fontWeight: s.has_update ? 700 : 400 }}>
            {s.latest_version || (s.has_update ? '檢測到更新' : (s.current_version || '同步中'))}
          </span>
        </div>
      </div>

      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginTop: '12px', fontSize: '0.72rem', color: 'var(--text-tertiary)' }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: '4px' }}>
          <Info size={12} />
          <span>上次檢查：{s.last_checked ? new Date(s.last_checked).toLocaleDateString('zh-TW', { year: 'numeric', month: 'long', day: 'numeric' }) : '尚未檢查'}</span>
        </div>
        {s.notes && (
          <div style={{ display: 'flex', alignItems: 'center', gap: '4px', maxWidth: '50%', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
            <AlertCircle size={12} />
            <span>{s.notes}</span>
          </div>
        )}
      </div>
    </div>
  );
}
