import { useState } from 'react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { api } from '../api';
import { toast } from 'react-hot-toast';
import {
  Plus,
  Edit2,
  Trash2,
  Search,
  ExternalLink,
  Package,
  X,
  AlertCircle,
  Tag
} from 'lucide-react';

const emptyForm = { name: '', keywords: '', fda_product_codes: '', description: '', is_active: true };

export default function Products() {
  const queryClient = useQueryClient();
  const [showModal, setShowModal] = useState(false);
  const [editing, setEditing] = useState(null);
  const [form, setForm] = useState(emptyForm);

  const { data: products = [], isLoading: loading } = useQuery({
    queryKey: ['products'],
    queryFn: api.getProducts,
  });

  const mutation = useMutation({
    mutationFn: async ({ action, id, payload }) => {
      if (action === 'create') return api.createProduct(payload);
      if (action === 'update') return api.updateProduct(id, payload);
      if (action === 'delete') return api.deleteProduct(id);
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['products'] });
    },
  });

  const openNew = () => { setEditing(null); setForm(emptyForm); setShowModal(true); };
  const openEdit = (p) => {
    setEditing(p);
    setForm({
      name: p.name,
      keywords: p.keywords,
      fda_product_codes: p.fda_product_codes,
      description: p.description || '',
      is_active: !!p.is_active,
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
    if (!confirm('確定要刪除此產品嗎？')) return;
    try {
      await mutation.mutateAsync({ action: 'delete', id });
    } catch (e) { toast.error(e.message); }
  };

  const handleToggle = async (p) => {
    try {
      await mutation.mutateAsync({ action: 'update', id: p.id, payload: { is_active: !p.is_active } });
    } catch (e) { toast.error(e.message); }
  };

  if (loading) {
    return (
      <div className="loading-overlay">
        <div className="spinner"></div>
        <span>載入數據中，請稍候...</span>
      </div>
    );
  }

  return (
    <>
      <div className="section-title">
        <div>
          <h1 className="page-title">產品監控管理</h1>
          <p className="page-subtitle">設定醫療器材監控項目，系統將依據關鍵字追蹤全球法規與召回動態</p>
        </div>
        <button className="btn btn-primary" onClick={openNew}>
          <Plus size={18} /> 新增監控產品
        </button>
      </div>

      {products.length === 0 ? (
        <div className="glass-card" style={{ padding: '80px 40px' }}>
          <div className="empty-state">
            <div className="empty-state-icon">
              <Search size={64} style={{ color: 'var(--accent-blue)', opacity: 0.6 }} />
            </div>
            <h3>尚未建立監控清單</h3>
            <p>新增您感興趣的醫療器材，系統將自動為您整合 FDA、 recalls.gov 等多個權威來源的最新資訊</p>
            <button className="btn btn-primary" onClick={openNew} style={{ marginTop: '12px' }}>
              <Plus size={18} /> 開始您的第一個監控
            </button>
          </div>
        </div>
      ) : (
        <div className="product-grid" style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(400px, 1fr))', gap: '20px' }}>
          {products.map((p) => (
            <div key={p.id} className="glass-card product-card" style={{ display: 'flex', flexDirection: 'column', padding: '24px' }}>
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', marginBottom: '16px' }}>
                <div style={{ display: 'flex', alignItems: 'center', gap: '12px' }}>
                  <div style={{
                    width: '44px',
                    height: '44px',
                    borderRadius: '12px',
                    background: p.is_active ? 'var(--accent-blue-glow)' : 'var(--bg-elevated)',
                    display: 'flex',
                    alignItems: 'center',
                    justifyContent: 'center',
                    color: p.is_active ? 'var(--accent-blue)' : 'var(--text-tertiary)'
                  }}>
                    <Package size={24} />
                  </div>
                  <div>
                    <h3 style={{ fontSize: '1.15rem', fontWeight: 700, color: 'var(--text-primary)', marginBottom: '4px' }}>{p.name}</h3>
                    <span className={`tag ${p.is_active ? 'tag-green' : 'tag-red'}`}>
                      {p.is_active ? '動態監控中' : '暫停監控'}
                    </span>
                  </div>
                </div>
                <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                  <label className="toggle" title={p.is_active ? '停用監控' : '啟用監控'}>
                    <input type="checkbox" checked={!!p.is_active} onChange={() => handleToggle(p)} />
                    <span className="toggle-slider"></span>
                  </label>
                </div>
              </div>

              {p.description && (
                <p style={{ fontSize: '0.9rem', color: 'var(--text-secondary)', marginBottom: '20px', lineHeight: '1.5', flexGrow: 1, whiteSpace: 'pre-wrap' }}>
                  {p.description}
                </p>
              )}

              <div style={{ display: 'flex', flexDirection: 'column', gap: '12px', padding: '16px', background: 'rgba(255,255,255,0.02)', borderRadius: '12px', border: '1px solid var(--glass-border)' }}>
                <div style={{ display: 'flex', alignItems: 'flex-start', gap: '8px' }}>
                  <Tag size={14} style={{ marginTop: '2px', color: 'var(--accent-blue)' }} />
                  <div style={{ flex: 1 }}>
                    <div style={{ fontSize: '0.75rem', fontWeight: 600, color: 'var(--text-tertiary)', marginBottom: '4px', textTransform: 'uppercase' }}>追蹤關鍵字</div>
                    <div style={{ display: 'flex', gap: '6px', flexWrap: 'wrap' }}>
                      {p.keywords ? p.keywords.split(',').map((kw, i) => (
                        <span key={i} className="tag tag-blue" style={{ fontSize: '0.7rem' }}>{kw.trim()}</span>
                      )) : <span style={{ fontSize: '0.75rem', color: 'var(--text-tertiary)', fontStyle: 'italic' }}>未設定</span>}
                    </div>
                  </div>
                </div>

                <div style={{ display: 'flex', alignItems: 'flex-start', gap: '8px' }}>
                  <AlertCircle size={14} style={{ marginTop: '2px', color: 'var(--accent-purple)' }} />
                  <div style={{ flex: 1 }}>
                    <div style={{ fontSize: '0.75rem', fontWeight: 600, color: 'var(--text-tertiary)', marginBottom: '4px', textTransform: 'uppercase' }}>FDA 產品代碼</div>
                    <div style={{ display: 'flex', gap: '6px', flexWrap: 'wrap' }}>
                      {p.fda_product_codes ? p.fda_product_codes.split(',').map((c, i) => (
                        <span key={i} className="tag tag-purple" style={{ fontSize: '0.7rem' }}>{c.trim()}</span>
                      )) : <span style={{ fontSize: '0.75rem', color: 'var(--text-tertiary)', fontStyle: 'italic' }}>未設定</span>}
                    </div>
                  </div>
                </div>
              </div>

              <div style={{ display: 'flex', justifyContent: 'flex-end', gap: '12px', marginTop: '20px', borderTop: '1px solid var(--glass-border)', paddingTop: '16px' }}>
                <button className="btn btn-ghost btn-sm" onClick={() => openEdit(p)} style={{ cursor: 'pointer' }}>
                  <Edit2 size={16} /> 編輯詳情
                </button>
                <button className="btn btn-ghost btn-sm" onClick={() => handleDelete(p.id)} style={{ color: 'var(--accent-danger)', cursor: 'pointer' }}>
                  <Trash2 size={16} /> 移除產品
                </button>
              </div>
            </div>
          ))}
        </div>
      )}

      {/* Modal */}
      {showModal && (
        <div className="modal-overlay">
          <div className="modal" style={{ maxWidth: '600px' }}>
            <div className="modal-header">
              <h2 style={{ display: 'flex', alignItems: 'center', gap: '12px' }}>
                {editing ? <Edit2 size={20} /> : <Plus size={20} />}
                {editing ? '編輯產品設定' : '新增監控產品'}
              </h2>
              <button className="btn btn-ghost btn-sm" onClick={() => setShowModal(false)}>
                <X size={20} />
              </button>
            </div>
            <div className="modal-body">
              <div className="form-group">
                <label className="form-label">產品名稱 <span style={{ color: 'var(--accent-danger)' }}>*</span></label>
                <input
                  className="form-input"
                  value={form.name}
                  onChange={(e) => setForm({ ...form, name: e.target.value })}
                  placeholder="例：拋棄式無線超音波刀"
                  autoFocus
                />
              </div>
              <div className="form-group">
                <label className="form-label">監控關鍵字</label>
                <div className="search-input-wrapper">
                  <Search size={16} className="search-icon" />
                  <input
                    className="form-input"
                    value={form.keywords}
                    onChange={(e) => setForm({ ...form, keywords: e.target.value })}
                    placeholder="以英文逗號分隔，例：ultrasonic scalpel, harmonic"
                  />
                </div>
                <small style={{ color: 'var(--text-tertiary)', fontSize: '0.75rem', marginTop: '6px', display: 'block' }}>
                  用於在全球醫療器材數據庫（如 FDA）中精確檢索相關召回記錄與不良事件。
                </small>
              </div>
              <div className="form-group">
                <label className="form-label">FDA 產品分類代碼 (Classification Code)</label>
                <div style={{ display: 'flex', gap: '8px' }}>
                  <input
                    className="form-input"
                    value={form.fda_product_codes}
                    onChange={(e) => setForm({ ...form, fda_product_codes: e.target.value })}
                    placeholder="例：GEI, LYA"
                    style={{ flex: 1 }}
                  />
                  <a
                    href="https://www.accessdata.fda.gov/scripts/cdrh/cfdocs/cfPCD/classification.cfm"
                    target="_blank"
                    rel="noopener noreferrer"
                    className="btn btn-secondary btn-sm"
                    title="前往 FDA 官網查詢代碼"
                    style={{ whiteSpace: 'nowrap' }}
                  >
                    <ExternalLink size={14} /> 查詢
                  </a>
                </div>
              </div>
              <div className="form-group">
                <label className="form-label">備註說明</label>
                <textarea
                  className="form-textarea"
                  value={form.description}
                  onChange={(e) => setForm({ ...form, description: e.target.value })}
                  placeholder="紀錄產品規格、內部代碼或特定監控需求..."
                  style={{ minHeight: '100px' }}
                />
              </div>
            </div>
            <div className="modal-footer">
              <button className="btn btn-secondary" onClick={() => setShowModal(false)}>取消</button>
              <button
                className="btn btn-primary"
                onClick={handleSave}
                disabled={!form.name.trim() || mutation.isPending}
              >
                {mutation.isPending ? '處理中...' : (editing ? '儲存變更' : '開始監控')}
              </button>
            </div>
          </div>
        </div>
      )}
    </>
  );
}
