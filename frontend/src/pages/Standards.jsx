import { useState, useMemo, useRef } from 'react';
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
  ChevronsRight,
  Search,
  Upload,
  BarChart2,
  List,
  HelpCircle,
  AlertTriangle,
  CheckSquare,
  Layers,
  SearchX,
  Clock
} from 'lucide-react';

const emptyForm = { standard_number: '', title: '', current_version: '', source_url: '', category: '', notes: '', latest_version: '', last_checked: '' };

const SCAN_POLL_INTERVAL_MS = 1500;
const SCAN_POLL_TIMEOUT_MS = 60000;

function sleep(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

// 後端 judge_categories 值 → 前端分類桶位／顯示樣式的對應表
// 查無結果一律用灰色系（不與任何暖色系狀態共用色相）：官網完全查不到此標準，
// 沒有任何版本資訊可比對，視覺上不應與「有更新」「缺少」等實際偵測到問題的狀態混淆。
const CATEGORY_META = {
  no_update:      { bucket: 'ok',       color: 'var(--accent-success)', bg: 'rgba(34,197,94,0.1)' },
  has_update:     { bucket: 'update',   color: 'var(--accent-warning)', bg: 'rgba(245,158,11,0.1)' },
  missing:        { bucket: 'missing',  color: 'var(--accent-danger)',  bg: 'rgba(239,68,68,0.1)' },
  not_found:      { bucket: 'notFound', color: 'var(--text-secondary)', bg: 'rgba(255,255,255,0.08)' },
  // 修訂中：官網已預告改版但新版尚未發布，與「有更新」區分（現行出版品並未改變）
  under_revision: { bucket: 'revision', color: 'var(--accent-info)',    bg: 'rgba(59,130,246,0.12)' },
  unknown:        { bucket: 'unknown',  color: 'var(--text-tertiary)',  bg: 'rgba(255,255,255,0.06)' },
};

/** 判斷單一法規標準命中的狀態分類（一筆可能同時命中多個，例如「有更新」+「缺少」） */
function classifyStandard(s) {
  if (!s.last_checked) return ['unknown'];
  if (s.judge_categories) {
    const cats = String(s.judge_categories).split(',').map(c => c.trim()).filter(Boolean);
    if (cats.length) return cats.map(c => CATEGORY_META[c]?.bucket || 'unknown');
  }
  // 相容舊資料／尚未提供 judge_categories 的來源（FDA、MDCG、TFDA、ASTM、EU 等）：沿用字串猜測
  if (s.judge_label && s.judge_label.includes('缺少')) return ['missing'];
  if (s.judge_label && (s.judge_label.includes('查無結果') || s.judge_label.includes('作廢'))) return ['notFound'];
  if (s.judge_label && s.judge_label.includes('無法判定')) return ['unknown'];
  if (s.judge_label && s.judge_label.includes('修訂中')) return ['revision'];
  if (s.has_update === 0) return ['ok'];          // 已是最新版
  if (s.has_update === 2) return ['revision'];    // 舊資料的「修訂中」枚舉值
  if (s.has_update === 1) return ['update'];      // 有更新 → 待更新
  if (s.judge_label) {
    const l = s.judge_label;
    if (l.includes('最新') && !l.includes('更新')) return ['ok'];
    return ['update'];
  }
  return ['unknown'];
}

/** 該筆是否為「查無結果」（官網完全找不到此標準，可能已作廢） */
function isNotFound(s) {
  return classifyStandard(s).includes('notFound');
}

/** 依 judge_categories／judge_label 組出狀態欄位要顯示的徽章（一筆可能同時顯示多個，例如「有更新」+「缺少」） */
function getStatusBadges(s) {
  const label = s.judge_label || (s.last_checked
    ? (s.has_update === 0 ? '🟢 已是最新版' : s.has_update === 2 ? '⚠️ 修訂中' : '📢 有更新')
    : null);
  if (!label) return null;

  if (s.judge_categories) {
    const cats = String(s.judge_categories).split(',').map(c => c.trim()).filter(Boolean);
    const parts = label.split('、');
    if (cats.length && cats.length === parts.length) {
      return cats.map((c, i) => ({
        text: parts[i],
        color: CATEGORY_META[c]?.color || 'var(--accent-warning)',
        bg: CATEGORY_META[c]?.bg || 'rgba(245,158,11,0.1)',
      }));
    }
  }
  // 相容舊資料／尚未提供 judge_categories 的來源：整段文字以字串猜測上色
  const isGood = label.includes('無更新') || label.includes('最新版');
  // 「查無結果」獨立判斷，一律灰色系，不落入「作廢／已改版」的紅色（danger）分支
  const isNotFoundLabel = label.includes('查無結果');
  const isDanger = !isNotFoundLabel && (label.includes('作廢') || label.includes('已改版'));
  if (isNotFoundLabel) {
    return [{ text: label, color: 'var(--text-secondary)', bg: 'rgba(255,255,255,0.08)' }];
  }
  const color = isGood ? 'var(--accent-success)' : isDanger ? 'var(--accent-danger)' : 'var(--accent-warning)';
  const bg = isGood ? 'rgba(34,197,94,0.1)' : isDanger ? 'rgba(239,68,68,0.1)' : 'rgba(245,158,11,0.1)';
  return [{ text: label, color, bg }];
}

// ─── Pagination ─────────────────────────────────────────────────────────────

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
      if (!isNaN(p) && p >= 1 && p <= totalPages) onPageChange(p);
      setJumpPage('');
    }
  };

  if (totalPages <= 1) return null;

  return (
    <div className="pagination" style={{ gap: '6px', flexWrap: 'wrap' }}>
      <button style={{ display: 'flex', alignItems: 'center', gap: '4px', padding: '0 12px' }} onClick={() => onPageChange(1)} disabled={currentPage === 1}>
        <ChevronsLeft size={16} /> 第一頁
      </button>
      <button style={{ display: 'flex', alignItems: 'center', gap: '4px', padding: '0 12px' }} onClick={() => onPageChange(currentPage - 1)} disabled={currentPage === 1}>
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

      <button style={{ display: 'flex', alignItems: 'center', gap: '4px', padding: '0 12px' }} onClick={() => onPageChange(currentPage + 1)} disabled={currentPage === totalPages}>
        下一頁 <ChevronRight size={16} />
      </button>
      <button style={{ display: 'flex', alignItems: 'center', gap: '4px', padding: '0 12px' }} onClick={() => onPageChange(totalPages)} disabled={currentPage === totalPages}>
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
            width: '60px', height: '36px', padding: '4px 8px',
            background: 'var(--bg-surface)', border: '1px solid var(--glass-border)',
            color: 'white', borderRadius: 'var(--radius-sm)', textAlign: 'center', outline: 'none'
          }}
        />
        頁
      </div>
    </div>
  );
}

// ─── Overview Tab ────────────────────────────────────────────────────────────

function OverviewTab({ standards }) {
  const stats = useMemo(() => {
    const total = standards.length;
    // 一筆標準可能同時命中多個分類（例如「有更新」+「缺少」），故每個命中的桶位都各自累加，
    // 卡片加總可能大於總數。
    let ok = 0, update = 0, missing = 0, notFound = 0, revision = 0, unknown = 0;
    const byCategory = {};

    standards.forEach((s) => {
      const classes = classifyStandard(s);
      const cat = s.category || '（未分類）';
      if (!byCategory[cat]) byCategory[cat] = { total: 0, ok: 0, update: 0, missing: 0, notFound: 0, revision: 0, unknown: 0 };
      byCategory[cat].total++;

      classes.forEach((cls) => {
        if (cls === 'ok') ok++;
        else if (cls === 'update') update++;
        else if (cls === 'missing') missing++;
        else if (cls === 'notFound') notFound++;
        else if (cls === 'revision') revision++;
        else unknown++;
        byCategory[cat][cls] = (byCategory[cat][cls] || 0) + 1;
      });
    });

    const categories = Object.entries(byCategory).sort(([a], [b]) => a.localeCompare(b, 'zh-TW'));
    return { total, ok, update, missing, notFound, revision, unknown, categories };
  }, [standards]);

  const cardStyle = (color, bg) => ({
    flex: '1 1 180px',
    background: bg,
    border: `1px solid ${color}`,
    borderRadius: '12px',
    padding: '20px 24px',
    display: 'flex',
    flexDirection: 'column',
    gap: '8px',
  });

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: '28px' }}>

      {/* 整體統計卡片 */}
      <div className="glass-card" style={{ padding: '24px' }}>
        <h2 style={{ fontSize: '1rem', fontWeight: 700, color: 'var(--text-secondary)', marginBottom: '16px', display: 'flex', alignItems: 'center', gap: '8px' }}>
          <Layers size={16} /> 全部法規標準
        </h2>
        <div style={{ display: 'flex', gap: '16px', flexWrap: 'wrap' }}>
          {/* 總數 */}
          <div style={cardStyle('var(--glass-border)', 'var(--bg-glass)')}>
            <div style={{ fontSize: '0.8rem', color: 'var(--text-secondary)', display: 'flex', alignItems: 'center', gap: '6px' }}>
              <List size={14} /> 總數
            </div>
            <div style={{ fontSize: '2rem', fontWeight: 800, color: 'var(--text-primary)' }}>{stats.total}</div>
          </div>
          {/* 已是最新版 */}
          <div style={cardStyle('var(--accent-success)', 'rgba(34,197,94,0.08)')}>
            <div style={{ fontSize: '0.8rem', color: 'var(--accent-success)', display: 'flex', alignItems: 'center', gap: '6px' }}>
              <CheckSquare size={14} /> 已是最新版
            </div>
            <div style={{ fontSize: '2rem', fontWeight: 800, color: 'var(--accent-success)' }}>{stats.ok}</div>
          </div>
          {/* 待更新 */}
          <div style={cardStyle('var(--accent-warning)', 'rgba(245,158,11,0.08)')}>
            <div style={{ fontSize: '0.8rem', color: 'var(--accent-warning)', display: 'flex', alignItems: 'center', gap: '6px' }}>
              <AlertTriangle size={14} /> 待更新
            </div>
            <div style={{ fontSize: '2rem', fontWeight: 800, color: 'var(--accent-warning)' }}>{stats.update}</div>
          </div>
          {/* 缺少 */}
          <div style={cardStyle('var(--accent-danger)', 'rgba(239,68,68,0.08)')}>
            <div style={{ fontSize: '0.8rem', color: 'var(--accent-danger)', display: 'flex', alignItems: 'center', gap: '6px' }}>
              <AlertCircle size={14} /> 缺少法規標準
            </div>
            <div style={{ fontSize: '2rem', fontWeight: 800, color: 'var(--accent-danger)' }}>{stats.missing}</div>
          </div>
          {/* 查無結果：灰色系（官網完全查不到，沒有版本資訊可比對，不與有更新/缺少共用暖色） */}
          <div style={cardStyle('var(--text-secondary)', 'rgba(255,255,255,0.05)')}>
            <div style={{ fontSize: '0.8rem', color: 'var(--text-secondary)', display: 'flex', alignItems: 'center', gap: '6px' }}>
              <SearchX size={14} /> 查無結果
            </div>
            <div style={{ fontSize: '2rem', fontWeight: 800, color: 'var(--text-secondary)' }}>{stats.notFound}</div>
            <div style={{ fontSize: '0.72rem', color: 'var(--text-tertiary)', marginTop: '-4px' }}>（可能已作廢）</div>
          </div>
          {/* 修訂中 */}
          <div style={cardStyle('var(--accent-info)', 'rgba(59,130,246,0.08)')}>
            <div style={{ fontSize: '0.8rem', color: 'var(--accent-info)', display: 'flex', alignItems: 'center', gap: '6px' }}>
              <Clock size={14} /> 修訂中
            </div>
            <div style={{ fontSize: '2rem', fontWeight: 800, color: 'var(--accent-info)' }}>{stats.revision}</div>
            <div style={{ fontSize: '0.72rem', color: 'var(--text-tertiary)', marginTop: '-4px' }}>（新版尚未發布）</div>
          </div>
          {/* 無法判定 */}
          <div style={cardStyle('var(--text-tertiary)', 'rgba(255,255,255,0.04)')}>
            <div style={{ fontSize: '0.8rem', color: 'var(--text-tertiary)', display: 'flex', alignItems: 'center', gap: '6px' }}>
              <HelpCircle size={14} /> 無法判定
            </div>
            <div style={{ fontSize: '2rem', fontWeight: 800, color: 'var(--text-tertiary)' }}>{stats.unknown}</div>
            <div style={{ fontSize: '0.72rem', color: 'var(--text-tertiary)', marginTop: '-4px' }}>（尚未掃描或查找失敗）</div>
          </div>
        </div>
      </div>

      {/* 依類別摘要 */}
      {stats.categories.length > 0 && (
        <div className="glass-card" style={{ padding: '24px' }}>
          <h2 style={{ fontSize: '1rem', fontWeight: 700, color: 'var(--text-secondary)', marginBottom: '16px', display: 'flex', alignItems: 'center', gap: '8px' }}>
            <BarChart2 size={16} /> 依類別統計
          </h2>
          <div className="table-container">
            <table className="data-table">
              <thead>
                <tr>
                  <th>類別</th>
                  <th style={{ width: '80px', textAlign: 'center' }}>總數</th>
                  <th style={{ width: '100px', textAlign: 'center' }}>已是最新版</th>
                  <th style={{ width: '80px', textAlign: 'center' }}>待更新</th>
                  <th style={{ width: '100px', textAlign: 'center' }}>缺少法規</th>
                  <th style={{ width: '90px', textAlign: 'center' }}>查無結果</th>
                  <th style={{ width: '80px', textAlign: 'center' }}>修訂中</th>
                  <th style={{ width: '80px', textAlign: 'center' }}>無法判定</th>
                </tr>
              </thead>
              <tbody>
                {stats.categories.map(([cat, c]) => (
                  <tr key={cat}>
                    <td>
                      <span style={{
                        fontSize: '0.85rem', padding: '3px 8px', borderRadius: '6px',
                        background: 'var(--bg-glass)', border: '1px solid var(--glass-border)', color: 'var(--text-primary)', fontWeight: 600
                      }}>
                        {cat}
                      </span>
                    </td>
                    <td style={{ textAlign: 'center', color: 'var(--text-secondary)', fontWeight: 600 }}>{c.total}</td>
                    <td style={{ textAlign: 'center' }}>
                      {c.ok > 0
                        ? <span style={{ color: 'var(--accent-success)', fontWeight: 700 }}>{c.ok}</span>
                        : <span style={{ color: 'var(--text-tertiary)' }}>—</span>}
                    </td>
                    <td style={{ textAlign: 'center' }}>
                      {c.update > 0
                        ? <span style={{ color: 'var(--accent-warning)', fontWeight: 700 }}>{c.update}</span>
                        : <span style={{ color: 'var(--text-tertiary)' }}>—</span>}
                    </td>
                    <td style={{ textAlign: 'center' }}>
                      {c.missing > 0
                        ? <span style={{ color: 'var(--accent-danger)', fontWeight: 700 }}>{c.missing}</span>
                        : <span style={{ color: 'var(--text-tertiary)' }}>—</span>}
                    </td>
                    <td style={{ textAlign: 'center' }}>
                      {c.notFound > 0
                        ? <span style={{ color: 'var(--text-secondary)', fontWeight: 700 }}>{c.notFound}</span>
                        : <span style={{ color: 'var(--text-tertiary)' }}>—</span>}
                    </td>
                    <td style={{ textAlign: 'center' }}>
                      {c.revision > 0
                        ? <span style={{ color: 'var(--accent-info)', fontWeight: 700 }}>{c.revision}</span>
                        : <span style={{ color: 'var(--text-tertiary)' }}>—</span>}
                    </td>
                    <td style={{ textAlign: 'center' }}>
                      {c.unknown > 0
                        ? <span style={{ color: 'var(--text-tertiary)', fontWeight: 600 }}>{c.unknown}</span>
                        : <span style={{ color: 'var(--text-tertiary)' }}>—</span>}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </div>
  );
}

// ─── Main Component ──────────────────────────────────────────────────────────

export default function Standards() {
  const queryClient = useQueryClient();
  const [activeTab, setActiveTab] = useState('overview');
  const [showModal, setShowModal] = useState(false);
  const [editing, setEditing] = useState(null);
  const [form, setForm] = useState(emptyForm);
  const fileInputRef = useRef(null);
  const [currentPage, setCurrentPage] = useState(1);
  const [filterCategory, setFilterCategory] = useState('all');
  const [scanModal, setScanModal] = useState(null);
  const [resolving, setResolving] = useState(false);
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

  const categories = useMemo(() => {
    const cats = new Set(standards.map(s => s.category).filter(n => n && typeof n === 'string'));
    return Array.from(cats).sort();
  }, [standards]);

  // 可自動查找的來源：ISO（虛擬瀏覽器）、IEC（webstore 搜尋 API）、EN（歐盟協調標準公報清單）。
  // 以「類別」為主，未填類別時退而由「法規名稱」前綴推斷，與後端 _resolve_source_kind 一致。
  // EN 須優先判斷：'EN ISO 13485' 同時含 EN 與 ISO，但應走協調標準清單。
  const resolveSource = useMemo(() => {
    const cat = (form.category || '').trim().toUpperCase();
    if (cat.startsWith('TAIWAN TFDA')) return 'TW';
    if (cat.startsWith('FDA')) return 'FDA';
    if (cat.includes('ASTM') || cat.includes('AAMI')) return 'ASTM';
    if (cat === 'MDCG GUIDANCE') return 'MDCG';
    if (cat === 'EU REGULATION') return 'EU';
    if (cat === 'EN ISO / EN' || cat === 'BS EN' || cat === 'EN') return 'EN';
    if (cat === 'ISO' || cat === 'IEC') return cat;
    if (cat) return null;
    const title = (form.title || '').trim().toUpperCase();
    if (title.startsWith('ASTM') || title.startsWith('AAMI') || title.startsWith('ANSI/AAMI')) return 'ASTM';
    if (title.startsWith('EN ') || title.startsWith('BS EN ')) return 'EN';
    if (title.startsWith('ISO')) return 'ISO';
    if (title.startsWith('IEC')) return 'IEC';
    return null;
  }, [form.category, form.title]);

  const filteredStandards = useMemo(() => {
    if (filterCategory === 'all') return standards;
    return standards.filter(s => s.category === filterCategory);
  }, [standards, filterCategory]);

  const openNew = () => { setEditing(null); setForm(emptyForm); setShowModal(true); };
  const openEdit = (s) => {
    setEditing(s);
    setForm({
      standard_number: s.standard_number,
      title: s.title,
      current_version: s.current_version || '',
      source_url: s.source_url || '',
      category: s.category || '',
      notes: s.notes || '',
      latest_version: s.latest_version || '',
      last_checked: s.last_checked || '',
    });
    setShowModal(true);
  };

  const handleImport = async (e) => {
    const file = e.target.files?.[0];
    if (!file) return;
    e.target.value = null;
    try {
      const text = await file.text();
      const lines = text.split('\n');
      const importedData = [];
      let inTable = false;
      let headers = [];

      for (let line of lines) {
        line = line.trim();
        if (!line.includes('|')) continue;
        const cols = line.split('|').map(c => c.trim()).filter((c, i, arr) => i > 0 && i < arr.length - 1);
        if (cols.length === 0) continue;
        if (!inTable && cols.some(c => c.includes('---'))) continue;
        if (cols.includes('公司文件編號') || cols.includes('法規名稱')) {
          inTable = true; headers = cols; continue;
        }
        if (inTable && !cols.some(c => c.includes('---'))) {
          const standard_number = cols[headers.indexOf('公司文件編號')] || '';
          const title = cols[headers.indexOf('法規名稱')] || '';
          let versionIndex = headers.indexOf('目前使用版本');
          if (versionIndex === -1) versionIndex = headers.indexOf('版本');
          const current_version = versionIndex !== -1 ? (cols[versionIndex] || '') : '';
          const category = headers.includes('類別') ? (cols[headers.indexOf('類別')] || '') : '';
          if (standard_number && title) {
            importedData.push({ standard_number, title, current_version, category, source_url: '', notes: '' });
          }
        }
      }

      if (importedData.length === 0) { toast.error('未在檔案中找到有效的法規標準表格'); return; }
      const tId = toast.loading(`正在匯入 ${importedData.length} 筆資料...`);
      const res = await api.importStandards(importedData);
      toast.success(res.message || '匯入完成', { id: tId });
      queryClient.invalidateQueries({ queryKey: ['standards'] });
    } catch (err) {
      console.error(err);
      toast.error('匯入發生錯誤：' + err.message);
    }
  };

  const handleSave = async () => {
    try {
      await mutation.mutateAsync({ action: editing ? 'update' : 'create', id: editing?.id, payload: form });
      setShowModal(false);
      toast.success('儲存成功');
    } catch (e) { toast.error(e.message); }
  };

  const handleResolveUrl = async () => {
    if (!form.title.trim()) { toast.error('請先填寫「法規名稱」（例如 ISO 10993-1）'); return; }
    setResolving(true);
    // IEC / EN 為純 HTTP（數秒內完成）；ISO 官網受 Cloudflare 防護，需虛擬瀏覽器。
    const tId = toast.loading(
      resolveSource === 'IEC' ? '正在到 IEC 官網搜尋...'
        : resolveSource === 'EN' ? '正在比對歐盟協調標準公報清單...'
          : resolveSource === 'EU' ? '正在查詢 EUR-Lex 與執委會指引清單...'
            : resolveSource === 'MDCG' ? '正在比對執委會 MDCG 指引清單...'
              : resolveSource === 'TW' ? '正在查詢全國法規資料庫...'
                : resolveSource === 'FDA' ? '正在比對 FDA 指引清單...'
                  : resolveSource === 'ASTM' ? '正在查詢 ASTM 官網現行版...'
            : '正在以虛擬瀏覽器到 ISO 官網搜尋（約需數十秒）...');
    try {
      const res = await api.resolveStandardUrl({ standard_name: form.title, current_version: form.current_version, standard_id: editing?.id || null });
      setForm((f) => ({ ...f, source_url: res.source_url, latest_version: res.now_year || res.now_title || f.latest_version, last_checked: res.last_checked || new Date().toISOString() }));
      queryClient.invalidateQueries({ queryKey: ['standards'] });
      const verdict = res.judge_label || (res.has_update ? '⚠️ 偵測到新版本' : '現行版即為最新');
      toast.success(`${verdict}｜${res.found_title}（網址已填入）\n${res.judge_message || ''}`, { id: tId, duration: 7000 });
    } catch (e) {
      toast.error(`查找失敗：${e.message}`, { id: tId });
    } finally {
      setResolving(false);
    }
  };

  const handleDelete = async (id) => {
    if (!confirm('確定要移除此標準？')) return;
    try {
      await mutation.mutateAsync({ action: 'delete', id });
      setShowModal(false);
    } catch (e) { toast.error(e.message); }
  };

  const handleRefresh = async (s) => {
    const sinceTime = Date.now() - 2000;
    setScanModal({ standard: s, status: 'loading', result: null, error: null });
    try {
      await api.triggerCrawl('standards', { standardId: s.id });
    } catch (e) {
      setScanModal({ standard: s, status: 'error', result: null, error: e.message });
      return;
    }
    const deadline = Date.now() + SCAN_POLL_TIMEOUT_MS;
    let finalLog = null;
    while (Date.now() < deadline) {
      await sleep(SCAN_POLL_INTERVAL_MS);
      try {
        const logs = await api.getCrawlLogs();
        finalLog = logs.find((l) => l.crawler_name === 'standards' && l.completed_at && new Date(l.completed_at).getTime() >= sinceTime) || null;
      } catch { /* 暫時忽略 */ }
      if (finalLog) break;
    }
    queryClient.invalidateQueries({ queryKey: ['standards'] });
    if (!finalLog) { setScanModal({ standard: s, status: 'timeout', result: null, error: null }); return; }
    let refreshedStandard = s;
    try {
      const freshStandards = await api.getStandards();
      refreshedStandard = freshStandards.find((x) => x.id === s.id) || s;
    } catch { /* 沿用掃描前資料 */ }
    setScanModal({ standard: refreshedStandard, status: finalLog.status === 'success' ? 'done' : 'failed', result: finalLog, error: null });
  };

  if (loading) {
    return (
      <div className="loading-overlay">
        <div className="spinner"></div>
        <span>正在同步全球標準數據庫...</span>
      </div>
    );
  }

  // ── List tab logic ──────────────────────────────────────────────────────────
  const sortedStandards = [...filteredStandards].sort((a, b) => {
    if (a.has_update && !b.has_update) return -1;
    if (!a.has_update && b.has_update) return 1;
    return (a.title || '').localeCompare(b.title || '', undefined, { numeric: true, sensitivity: 'base' });
  });
  const totalPages = Math.ceil(sortedStandards.length / itemsPerPage) || 1;
  const safeCurrentPage = Math.min(currentPage, totalPages);
  const startIndex = (safeCurrentPage - 1) * itemsPerPage;
  const currentData = sortedStandards.slice(startIndex, startIndex + itemsPerPage);

  // ── Tab styles ──────────────────────────────────────────────────────────────
  const tabBtn = (id) => ({
    padding: '8px 20px',
    borderRadius: '8px',
    border: 'none',
    cursor: 'pointer',
    fontWeight: 600,
    fontSize: '0.9rem',
    display: 'flex',
    alignItems: 'center',
    gap: '8px',
    transition: 'all 0.15s',
    background: activeTab === id ? 'var(--accent-primary)' : 'var(--bg-glass)',
    color: activeTab === id ? 'white' : 'var(--text-secondary)',
    border: activeTab === id ? '1px solid var(--accent-primary)' : '1px solid var(--glass-border)',
  });

  return (
    <>
      {/* Page header */}
      <div className="section-title">
        <div style={{ display: 'flex', flexDirection: 'column', gap: '12px' }}>
          <h1 className="page-title" style={{ margin: 0 }}>法規標準追蹤</h1>
          {/* Tab switcher */}
          <div style={{ display: 'flex', gap: '8px' }}>
            <button style={tabBtn('overview')} onClick={() => setActiveTab('overview')}>
              <BarChart2 size={16} /> 更新狀態總覽
            </button>
            <button style={tabBtn('list')} onClick={() => setActiveTab('list')}>
              <List size={16} /> 法規標準清單
            </button>
          </div>
        </div>
      </div>

      {/* ── Tab: Overview ── */}
      {activeTab === 'overview' && (
        <OverviewTab standards={standards} />
      )}

      {/* ── Tab: List ── */}
      {activeTab === 'list' && (
        <>
          {/* List toolbar */}
          <div style={{ display: 'flex', gap: '12px', marginBottom: '0', justifyContent: 'flex-end', flexWrap: 'wrap' }}>
            <select
              className="form-select"
              value={filterCategory}
              onChange={(e) => { setFilterCategory(e.target.value); setCurrentPage(1); }}
              style={{ width: '200px', cursor: 'pointer' }}
            >
              <option value="all">所有類別</option>
              {categories.map(c => <option key={c} value={c}>{c}</option>)}
            </select>
            <input type="file" accept=".md" style={{ display: 'none' }} ref={fileInputRef} onChange={handleImport} />
            <button className="btn btn-secondary" onClick={() => fileInputRef.current?.click()} title="匯入法規清單 MD 檔案">
              <Upload size={18} /> 從 MD 檔匯入
            </button>
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
            <div style={{ display: 'flex', flexDirection: 'column', gap: '24px' }}>
              <div className="table-container">
                <table className="data-table">
                  <thead>
                    <tr>
                      <th>文件編號 / 法規名稱</th>
                      <th style={{ width: '160px' }}>狀態</th>
                      <th style={{ width: '120px' }}>當前版本</th>
                      {/* IEC 的版本字串較長（例：2005+AMD1:2012+AMD2:2020 CSV），需較寬欄位 */}
                      <th style={{ width: '230px' }}>最新同步版本</th>
                      <th style={{ width: '180px' }}>上次檢查時間</th>
                      <th style={{ width: '120px', textAlign: 'right' }}>操作</th>
                    </tr>
                  </thead>
                  <tbody>
                    {currentData.map((s) => (
                      <tr key={s.id} style={{
                        // 查無結果一律用灰色標示（需人工確認是否已作廢），不與任何暖色系狀態共用色相，
                        // 否則整列的視覺訊號可能誤讀為「查到新版本了」。
                        background: isNotFound(s) ? 'rgba(255,255,255,0.05)'
                          : (s.has_update ? 'rgba(245, 158, 11, 0.05)' : 'transparent'),
                        borderLeft: isNotFound(s) ? '3px solid var(--text-secondary)'
                          : (s.has_update ? '3px solid var(--accent-warning)' : '3px solid transparent')
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
                            {s.has_update && !s.judge_label && (
                              <span className="tag tag-amber" style={{ display: 'flex', alignItems: 'center', gap: '4px' }}>
                                <RotateCcw size={12} /> 有新版本
                              </span>
                            )}
                          </div>
                          {(s.category || s.notes) && (
                            <div style={{ display: 'flex', flexDirection: 'column', gap: '4px', marginTop: '6px' }}>
                              {s.category && (
                                <div style={{ display: 'flex', alignItems: 'center' }}>
                                  <span style={{ fontSize: '0.7rem', padding: '2px 6px', borderRadius: '4px', background: 'var(--bg-glass)', border: '1px solid var(--glass-border)', color: 'var(--text-secondary)' }}>
                                    {s.category}
                                  </span>
                                </div>
                              )}
                              {s.notes && (
                                <div style={{ display: 'flex', alignItems: 'center', gap: '4px', fontSize: '0.75rem', color: 'var(--text-tertiary)' }}>
                                  <AlertCircle size={12} /> {s.notes}
                                </div>
                              )}
                            </div>
                          )}
                        </td>
                        <td style={{ verticalAlign: 'middle' }}>
                          {(() => {
                            const badges = getStatusBadges(s);
                            if (!badges) return <span style={{ color: 'var(--text-tertiary)', fontStyle: 'italic', fontSize: '0.85rem' }}>尚未掃描</span>;
                            return (
                              <div style={{ display: 'flex', flexDirection: 'column', gap: '4px' }}>
                                {badges.map((b, i) => (
                                  <span key={i} style={{ fontSize: '0.8rem', padding: '3px 8px', borderRadius: '6px', background: b.bg, color: b.color, border: `1px solid ${b.color}`, fontWeight: 600, whiteSpace: 'pre-wrap', lineHeight: '1.4', display: 'inline-block', maxWidth: '140px' }}>
                                    {b.text}
                                  </span>
                                ))}
                              </div>
                            );
                          })()}
                        </td>
                        <td style={{ verticalAlign: 'middle' }}>
                          {s.current_version
                            ? <span style={{ color: 'var(--text-secondary)', fontFamily: 'var(--font-mono)', fontSize: '0.9rem' }}>{s.current_version}</span>
                            : <span style={{ color: 'var(--text-tertiary)', fontStyle: 'italic', fontSize: '0.85rem' }}>未註記</span>}
                        </td>
                        <td style={{ verticalAlign: 'middle' }}>
                          {isNotFound(s)
                            // 查無結果：官網根本沒查到這個標準，沒有任何版本資訊可比對。
                            // 不可沿用 has_update 的「檢測到更新」文案，否則等於謊報查到了新版本。
                            ? <span style={{ color: 'var(--text-tertiary)', fontStyle: 'italic', fontSize: '0.85rem' }}>查無資料</span>
                            : <span style={{ color: s.has_update ? 'var(--accent-warning)' : 'var(--text-secondary)', fontWeight: s.has_update ? 700 : 400, fontFamily: 'var(--font-mono)', fontSize: '0.85rem', lineHeight: 1.4, wordBreak: 'break-word' }}>
                                {s.latest_version || (s.has_update ? '檢測到更新' : (s.current_version || '同步中'))}
                              </span>}
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
              <Pagination currentPage={safeCurrentPage} totalPages={totalPages} onPageChange={(p) => setCurrentPage(p)} />
            </div>
          )}
        </>
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
              <button className="btn btn-ghost btn-sm" onClick={() => setShowModal(false)}><X size={20} /></button>
            </div>
            <div className="modal-body">
              <div className="form-group">
                <label className="form-label">公司文件編號 <span style={{ color: 'var(--accent-danger)' }}>*</span></label>
                <input className="form-input" value={form.standard_number} onChange={(e) => setForm({ ...form, standard_number: e.target.value })} placeholder="例：R101-0001-01" autoFocus />
              </div>
              <div className="form-group">
                <label className="form-label">法規名稱 <span style={{ color: 'var(--accent-danger)' }}>*</span></label>
                <input className="form-input" value={form.title} onChange={(e) => setForm({ ...form, title: e.target.value })} placeholder="例：Medical electrical equipment - General requirements" />
              </div>
              <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '16px' }}>
                <div className="form-group">
                  <label className="form-label">類別</label>
                  <input className="form-input" value={form.category} onChange={(e) => setForm({ ...form, category: e.target.value })} placeholder="例：ISO 或 IEC" />
                </div>
                <div className="form-group">
                  <label className="form-label">目前使用版本</label>
                  <input className="form-input" value={form.current_version} onChange={(e) => setForm({ ...form, current_version: e.target.value })} placeholder="例：Edition 3.2" />
                </div>
              </div>
              <div className="form-group">
                <label className="form-label">官方來源網址</label>
                <div style={{ display: 'flex', gap: '8px' }}>
                  <input className="form-input" value={form.source_url} onChange={(e) => setForm({ ...form, source_url: e.target.value })} placeholder="IEC/ISO 官網頁面" style={{ flex: 1, minWidth: 0 }} />
                  {resolveSource && (
                    <button type="button" className="btn btn-secondary" onClick={handleResolveUrl} disabled={resolving || !form.title.trim()} title={`到 ${resolveSource} 官網搜尋此法規並自動填入官方網址`} style={{ flexShrink: 0, display: 'flex', alignItems: 'center', gap: '6px', whiteSpace: 'nowrap' }}>
                      {resolving ? <><div className="spinner" style={{ width: '14px', height: '14px' }}></div> 搜尋中</> : <><Search size={16} /> {resolveSource} 查找</>}
                    </button>
                  )}
                </div>
                {resolveSource && (
                  <span style={{ fontSize: '0.75rem', color: 'var(--text-tertiary)', marginTop: '4px', display: 'block' }}>
                    {resolveSource === 'IEC'
                      ? '依「法規名稱」到 IEC 官網查找官方頁面（僅針對此筆，數秒內完成）'
                      : resolveSource === 'EN'
                        ? '依「法規名稱」比對歐盟 MDR 協調標準官方公報清單（僅針對此筆，數秒內完成）'
                        : resolveSource === 'EU'
                          ? '查詢 EUR-Lex 現行合併版或執委會指引清單版本（僅針對此筆，數秒內完成）'
                          : resolveSource === 'MDCG'
                            ? '比對執委會 MDCG 指引清單的修訂版次（僅針對此筆，數秒內完成）'
                            : resolveSource === 'TW'
                              ? '依法規名稱查詢全國法規資料庫的最後修正日期（僅針對此筆）'
                              : resolveSource === 'FDA'
                                ? '比對 FDA 官方指引清單的發布日期，或查 eCFR 條文修訂日期（僅針對此筆）'
                                : resolveSource === 'ASTM'
                                  ? '由 ASTM 官網短代號轉址取得現行版（AAMI 受防護無法自動查詢）'
                                  : '依「法規名稱」到 ISO 官網查找官方頁面（僅針對此筆，需本機 Chrome）'}
                  </span>
                )}
              </div>
              {editing && (
                <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '16px' }}>
                  <div className="form-group">
                    <label className="form-label">最新查找版本</label>
                    <input className="form-input" value={form.latest_version || ''} readOnly placeholder="尚未查找" style={{ background: 'var(--bg-surface)', color: 'var(--text-secondary)', cursor: 'default' }} />
                  </div>
                  <div className="form-group">
                    <label className="form-label">最新查找日期</label>
                    <input className="form-input" value={form.last_checked ? new Date(form.last_checked).toLocaleString('zh-TW') : ''} readOnly placeholder="尚未查找" style={{ background: 'var(--bg-surface)', color: 'var(--text-secondary)', cursor: 'default' }} />
                  </div>
                </div>
              )}
              <div className="form-group">
                <label className="form-label">內部備註 / 應用範圍</label>
                <textarea className="form-textarea" value={form.notes} onChange={(e) => setForm({ ...form, notes: e.target.value })} placeholder="紀錄此標準與產品開發的關聯性..." style={{ minHeight: '100px' }} />
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
                <button className="btn btn-primary" onClick={handleSave} disabled={!form.standard_number.trim() || !form.title.trim() || mutation.isPending}>
                  {mutation.isPending ? '提交中...' : (editing ? '儲存變更' : '加入追蹤清單')}
                </button>
              </div>
            </div>
          </div>
        </div>
      )}

      {/* 單一標準掃描結果視窗 */}
      {scanModal && (
        <div className="modal-overlay">
          <div className="modal" style={{ maxWidth: '480px' }}>
            <div className="modal-header">
              <h2 style={{ display: 'flex', alignItems: 'center', gap: '12px' }}>
                <RefreshCw size={20} /> 掃描執行結果
              </h2>
              {scanModal.status !== 'loading' && (
                <button className="btn btn-ghost btn-sm" onClick={() => setScanModal(null)}><X size={20} /></button>
              )}
            </div>
            <div className="modal-body">
              <p style={{ marginBottom: '16px', color: 'var(--text-secondary)' }}>
                法規名稱：<strong style={{ color: 'var(--text-primary)' }}>{scanModal.standard.title}</strong>
              </p>

              {scanModal.status === 'loading' && (
                <div style={{ display: 'flex', alignItems: 'center', gap: '12px', padding: '12px 0' }}>
                  <div className="spinner"></div>
                  <span>正在執行掃描，請稍候...</span>
                </div>
              )}

              {scanModal.status === 'error' && (
                <div style={{ display: 'flex', alignItems: 'center', gap: '8px', color: 'var(--accent-danger)' }}>
                  <AlertCircle size={18} />
                  <span>啟動掃描失敗：{scanModal.error}</span>
                </div>
              )}

              {scanModal.status === 'timeout' && (
                <div style={{ display: 'flex', alignItems: 'flex-start', gap: '8px', color: 'var(--accent-warning)' }}>
                  <AlertCircle size={18} style={{ marginTop: '2px', flexShrink: 0 }} />
                  <span>掃描已在背景送出，但尚未在預期時間內完成，可能仍在執行中。請稍後重新整理頁面，查看「上次檢查時間」是否已更新。</span>
                </div>
              )}

              {(scanModal.status === 'done' || scanModal.status === 'failed') && (
                <div style={{ display: 'flex', flexDirection: 'column', gap: '10px' }}>
                  <div style={{ display: 'flex', alignItems: 'center', gap: '8px', color: scanModal.status === 'done' ? 'var(--accent-success)' : 'var(--accent-danger)' }}>
                    {scanModal.status === 'done' ? <CheckCircle size={18} /> : <AlertCircle size={18} />}
                    <strong>{scanModal.status === 'done' ? '掃描完成' : '掃描執行失敗'}</strong>
                  </div>
                  <div style={{ fontSize: '0.9rem', color: 'var(--text-secondary)', display: 'flex', flexDirection: 'column', gap: '4px' }}>
                    <span>目前使用版本：{scanModal.standard.current_version || '未註記'}</span>
                    <span>抓取最新版本：{scanModal.standard.latest_version || '未取得'}</span>
                    {scanModal.result?.completed_at && (
                      <span>完成時間：{new Date(scanModal.result.completed_at).toLocaleString('zh-TW')}</span>
                    )}
                  </div>
                  {scanModal.result?.error_message && (
                    <div style={{ fontSize: '0.9rem', color: 'var(--accent-danger)' }}>
                      錯誤訊息：{scanModal.result.error_message}
                    </div>
                  )}
                  {scanModal.status === 'done' && scanModal.standard.has_update > 0 && (
                    <div style={{ fontSize: '0.9rem', color: 'var(--accent-warning)' }}>
                      ⚠️ 偵測到新版本，請查看清單中的「最新同步版本」欄位。
                    </div>
                  )}
                </div>
              )}
            </div>
            <div className="modal-footer" style={{ display: 'flex', justifyContent: 'flex-end' }}>
              <button className="btn btn-primary" onClick={() => setScanModal(null)} disabled={scanModal.status === 'loading'}>確認</button>
            </div>
          </div>
        </div>
      )}
    </>
  );
}
