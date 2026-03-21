import { useState } from 'react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { api } from '../api';
import { toast } from 'react-hot-toast';

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
    return <div className="loading-overlay"><div className="spinner"></div><span>載入中…</span></div>;
  }

  const withUpdates = standards.filter((s) => s.has_update);
  const noUpdates = standards.filter((s) => !s.has_update);

  return (
    <>
      <div className="section-title">
        <div>
          <h1 className="page-title">法規標準追蹤</h1>
          <p className="page-subtitle">追蹤 IEC/ISO 等相關法規標準的最新版本</p>
        </div>
        <button className="btn btn-primary" onClick={openNew}>＋ 新增標準</button>
      </div>

      {standards.length === 0 ? (
        <div className="glass-card">
          <div className="empty-state">
            <div className="empty-state-icon">📋</div>
            <h3>尚未追蹤任何標準</h3>
            <p>新增您關注的法規標準（如 IEC 60601-1、ISO 13485），系統會自動檢查版本更新</p>
            <button className="btn btn-primary" onClick={openNew}>＋ 新增標準</button>
          </div>
        </div>
      ) : (
        <>
          {/* With updates section */}
          {withUpdates.length > 0 && (
            <div style={{ marginBottom: 24 }}>
              <h3 style={{ fontSize: '1rem', fontWeight: 700, marginBottom: 12, color: 'var(--accent-cyan)' }}>
                🔄 有版本更新 ({withUpdates.length})
              </h3>
              <div style={{ display: 'grid', gap: 12 }}>
                {withUpdates.map((s) => (
                  <StandardCard key={s.id} standard={s} onEdit={openEdit} onDelete={handleDelete} highlight />
                ))}
              </div>
            </div>
          )}

          {/* No updates section */}
          <div>
            {withUpdates.length > 0 && (
              <h3 style={{ fontSize: '1rem', fontWeight: 700, marginBottom: 12, color: 'var(--text-secondary)' }}>
                ✅ 版本最新 ({noUpdates.length})
              </h3>
            )}
            <div style={{ display: 'grid', gap: 12 }}>
              {noUpdates.map((s) => (
                <StandardCard key={s.id} standard={s} onEdit={openEdit} onDelete={handleDelete} />
              ))}
            </div>
          </div>
        </>
      )}

      {/* Modal */}
      {showModal && (
        <div className="modal-overlay" onClick={(e) => e.target === e.currentTarget && setShowModal(false)}>
          <div className="modal">
            <div className="modal-header">
              <h2>{editing ? '編輯標準' : '新增追蹤標準'}</h2>
              <button className="btn btn-ghost btn-sm" onClick={() => setShowModal(false)}>✕</button>
            </div>
            <div className="modal-body">
              <div className="form-group">
                <label className="form-label">標準編號 *</label>
                <input className="form-input" value={form.standard_number}
                  onChange={(e) => setForm({ ...form, standard_number: e.target.value })}
                  placeholder="例：IEC 60601-1" />
              </div>
              <div className="form-group">
                <label className="form-label">標準名稱 *</label>
                <input className="form-input" value={form.title}
                  onChange={(e) => setForm({ ...form, title: e.target.value })}
                  placeholder="例：Medical electrical equipment - General requirements" />
              </div>
              <div className="form-group">
                <label className="form-label">目前已知版本</label>
                <input className="form-input" value={form.current_version}
                  onChange={(e) => setForm({ ...form, current_version: e.target.value })}
                  placeholder="例：Edition 3.2 (2020)" />
              </div>
              <div className="form-group">
                <label className="form-label">來源網址</label>
                <input className="form-input" value={form.source_url}
                  onChange={(e) => setForm({ ...form, source_url: e.target.value })}
                  placeholder="IEC/ISO 標準頁面網址" />
              </div>
              <div className="form-group">
                <label className="form-label">備註</label>
                <textarea className="form-textarea" value={form.notes}
                  onChange={(e) => setForm({ ...form, notes: e.target.value })}
                  placeholder="相關備註" />
              </div>
            </div>
            <div className="modal-footer">
              <button className="btn btn-secondary" onClick={() => setShowModal(false)}>取消</button>
              <button className="btn btn-primary" onClick={handleSave}
                disabled={!form.standard_number.trim() || !form.title.trim()}>
                {editing ? '儲存變更' : '新增標準'}
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
      display: 'flex', alignItems: 'center', gap: 20,
      ...(highlight ? { borderColor: 'rgba(6,182,212,0.3)', boxShadow: '0 0 20px rgba(6,182,212,0.08)' } : {}),
    }}>
      <div style={{ flex: 1 }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: 4 }}>
          <span style={{
            fontFamily: 'var(--font-mono)', fontSize: '0.95rem', fontWeight: 700,
            color: highlight ? 'var(--accent-cyan)' : 'var(--text-primary)',
          }}>
            {s.standard_number}
          </span>
          {s.has_update ? (
            <span className="tag tag-cyan">有更新</span>
          ) : (
            <span className="tag tag-green">最新</span>
          )}
          <span className={`tag tag-${s.status === 'active' ? 'green' : 'amber'}`} style={{ opacity: 0.7 }}>
            {s.status || 'active'}
          </span>
        </div>
        <div style={{ fontSize: '0.88rem', color: 'var(--text-secondary)', marginBottom: 6 }}>
          {s.title}
        </div>
        <div style={{ display: 'flex', gap: 20, fontSize: '0.78rem', color: 'var(--text-tertiary)' }}>
          {s.current_version && <span>已知版本：{s.current_version}</span>}
          {s.latest_version && s.latest_version !== s.current_version && (
            <span style={{ color: 'var(--accent-cyan)', fontWeight: 600 }}>最新版本：{s.latest_version}</span>
          )}
          {s.last_checked && <span>上次檢查：{new Date(s.last_checked).toLocaleDateString('zh-TW')}</span>}
        </div>
        {s.notes && (
          <div style={{ fontSize: '0.78rem', color: 'var(--text-tertiary)', marginTop: 4, fontStyle: 'italic' }}>
            {s.notes}
          </div>
        )}
      </div>
      <div style={{ display: 'flex', gap: 8 }}>
        {s.source_url && (
          <a href={s.source_url} target="_blank" rel="noopener noreferrer" className="btn btn-ghost btn-sm">🔗</a>
        )}
        <button className="btn btn-ghost btn-sm" onClick={() => onEdit(s)}>✏️</button>
        <button className="btn btn-ghost btn-sm" onClick={() => onDelete(s.id)} style={{ color: 'var(--accent-red)' }}>🗑️</button>
      </div>
    </div>
  );
}
