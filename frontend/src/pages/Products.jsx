import { useState, useEffect } from 'react';
import { api } from '../api';

const emptyForm = { name: '', keywords: '', fda_product_codes: '', description: '', is_active: true };

export default function Products() {
  const [products, setProducts] = useState([]);
  const [loading, setLoading] = useState(true);
  const [showModal, setShowModal] = useState(false);
  const [editing, setEditing] = useState(null);
  const [form, setForm] = useState(emptyForm);

  const fetchProducts = async () => {
    try {
      const data = await api.getProducts();
      setProducts(data);
    } catch (e) { console.error(e); }
    finally { setLoading(false); }
  };

  useEffect(() => { fetchProducts(); }, []);

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
      if (editing) {
        await api.updateProduct(editing.id, form);
      } else {
        await api.createProduct(form);
      }
      setShowModal(false);
      fetchProducts();
    } catch (e) { alert(e.message); }
  };

  const handleDelete = async (id) => {
    if (!confirm('確定要刪除此產品嗎？')) return;
    await api.deleteProduct(id);
    fetchProducts();
  };

  const handleToggle = async (p) => {
    await api.updateProduct(p.id, { is_active: !p.is_active });
    fetchProducts();
  };

  if (loading) {
    return <div className="loading-overlay"><div className="spinner"></div><span>載入中…</span></div>;
  }

  return (
    <>
      <div className="section-title">
        <div>
          <h1 className="page-title">產品監控管理</h1>
          <p className="page-subtitle">設定要監控的醫療器材產品及其關鍵字</p>
        </div>
        <button className="btn btn-primary" onClick={openNew}>＋ 新增產品</button>
      </div>

      {products.length === 0 ? (
        <div className="glass-card">
          <div className="empty-state">
            <div className="empty-state-icon">🔍</div>
            <h3>尚未設定監控產品</h3>
            <p>新增您要監控的醫療器材產品，系統將自動爬取相關召回記錄和不良事件</p>
            <button className="btn btn-primary" onClick={openNew}>＋ 新增第一個產品</button>
          </div>
        </div>
      ) : (
        <div style={{ display: 'grid', gap: 16 }}>
          {products.map((p) => (
            <div key={p.id} className="glass-card" style={{ display: 'flex', alignItems: 'center', gap: 20 }}>
              <div style={{ flex: 1 }}>
                <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: 6 }}>
                  <h3 style={{ fontSize: '1.1rem', fontWeight: 700 }}>{p.name}</h3>
                  <span className={`tag ${p.is_active ? 'tag-green' : 'tag-red'}`}>
                    {p.is_active ? '監控中' : '已停用'}
                  </span>
                </div>
                {p.description && (
                  <p style={{ fontSize: '0.85rem', color: 'var(--text-secondary)', marginBottom: 8 }}>
                    {p.description}
                  </p>
                )}
                <div style={{ display: 'flex', gap: 12, flexWrap: 'wrap' }}>
                  {p.keywords && (
                    <div style={{ fontSize: '0.78rem', color: 'var(--text-tertiary)' }}>
                      <strong>關鍵字：</strong>
                      {p.keywords.split(',').map((kw, i) => (
                        <span key={i} className="tag tag-blue" style={{ marginLeft: 4 }}>{kw.trim()}</span>
                      ))}
                    </div>
                  )}
                  {p.fda_product_codes && (
                    <div style={{ fontSize: '0.78rem', color: 'var(--text-tertiary)' }}>
                      <strong>FDA 代碼：</strong>
                      {p.fda_product_codes.split(',').map((c, i) => (
                        <span key={i} className="tag tag-purple" style={{ marginLeft: 4 }}>{c.trim()}</span>
                      ))}
                    </div>
                  )}
                </div>
              </div>

              <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                <label className="toggle" title={p.is_active ? '停用監控' : '啟用監控'}>
                  <input type="checkbox" checked={!!p.is_active} onChange={() => handleToggle(p)} />
                  <span className="toggle-slider"></span>
                </label>
                <button className="btn btn-ghost btn-sm" onClick={() => openEdit(p)}>✏️</button>
                <button className="btn btn-ghost btn-sm" onClick={() => handleDelete(p.id)} style={{ color: 'var(--accent-red)' }}>🗑️</button>
              </div>
            </div>
          ))}
        </div>
      )}

      {/* Modal */}
      {showModal && (
        <div className="modal-overlay" onClick={(e) => e.target === e.currentTarget && setShowModal(false)}>
          <div className="modal">
            <div className="modal-header">
              <h2>{editing ? '編輯產品' : '新增監控產品'}</h2>
              <button className="btn btn-ghost btn-sm" onClick={() => setShowModal(false)}>✕</button>
            </div>
            <div className="modal-body">
              <div className="form-group">
                <label className="form-label">產品名稱 *</label>
                <input
                  className="form-input"
                  value={form.name}
                  onChange={(e) => setForm({ ...form, name: e.target.value })}
                  placeholder="例：拋棄式無線超音波刀"
                />
              </div>
              <div className="form-group">
                <label className="form-label">監控關鍵字</label>
                <input
                  className="form-input"
                  value={form.keywords}
                  onChange={(e) => setForm({ ...form, keywords: e.target.value })}
                  placeholder="以英文逗號分隔，例：ultrasonic scalpel, harmonic"
                />
                <small style={{ color: 'var(--text-tertiary)', fontSize: '0.72rem' }}>
                  用於搜尋 FDA 召回和 MAUDE 不良事件資料庫
                </small>
              </div>
              <div className="form-group">
                <label className="form-label">FDA 產品代碼</label>
                <input
                  className="form-input"
                  value={form.fda_product_codes}
                  onChange={(e) => setForm({ ...form, fda_product_codes: e.target.value })}
                  placeholder="例：GEI, LYA"
                />
                <small style={{ color: 'var(--text-tertiary)', fontSize: '0.72rem' }}>
                  <a href="https://www.accessdata.fda.gov/scripts/cdrh/cfdocs/cfPCD/classification.cfm" target="_blank" rel="noopener noreferrer">
                    查詢 FDA 產品代碼
                  </a>
                </small>
              </div>
              <div className="form-group">
                <label className="form-label">描述</label>
                <textarea
                  className="form-textarea"
                  value={form.description}
                  onChange={(e) => setForm({ ...form, description: e.target.value })}
                  placeholder="產品描述或備註"
                />
              </div>
            </div>
            <div className="modal-footer">
              <button className="btn btn-secondary" onClick={() => setShowModal(false)}>取消</button>
              <button className="btn btn-primary" onClick={handleSave} disabled={!form.name.trim()}>
                {editing ? '儲存變更' : '新增產品'}
              </button>
            </div>
          </div>
        </div>
      )}
    </>
  );
}
