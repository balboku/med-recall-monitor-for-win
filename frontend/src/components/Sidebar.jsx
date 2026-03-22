import { NavLink } from 'react-router-dom';
import { 
  LayoutDashboard, 
  Bell, 
  Activity,
  AlertTriangle, 
  ClipboardList, 
  Sparkles, 
  Search, 
  Settings,
  ShieldAlert
} from 'lucide-react';

const navItems = [
  { section: '監控總覽' },
  { path: '/', icon: <LayoutDashboard size={18} />, label: 'Dashboard' },
  { path: '/alerts', icon: <ShieldAlert size={18} />, label: '告警中心' },
  { section: '資料查詢' },
  { path: '/recalls', icon: <Bell size={18} />, label: '召回記錄' },
  { path: '/events', icon: <AlertTriangle size={18} />, label: '不良事件' },
  { path: '/standards', icon: <ClipboardList size={18} />, label: '法規標準' },
  { path: '/reports', icon: <Sparkles size={18} />, label: 'AI 分析報告' },
  { section: '系統管理' },
  { path: '/products', icon: <Search size={18} />, label: '產品監控管理' },
  { path: '/settings', icon: <Settings size={18} />, label: '系統設定' },
];

export default function Sidebar({ alertCount }) {
  return (
    <aside className="sidebar">
      <div className="sidebar-brand">
        <div className="sidebar-brand-icon">
          <Activity size={24} color="white" />
        </div>
        <div>
          <h1>MedWatch</h1>
          <span>醫療器材監控系統</span>
        </div>
      </div>

      <nav className="sidebar-nav">
        {navItems.map((item, i) =>
          item.section ? (
            <div key={i} className="sidebar-section-title">{item.section}</div>
          ) : (
            <NavLink
              key={item.path}
              to={item.path}
              end={item.path === '/'}
              className={({ isActive }) => `nav-item${isActive ? ' active' : ''}`}
            >
              <span className="nav-icon">{item.icon}</span>
              <span>{item.label}</span>
              {item.path === '/alerts' && alertCount > 0 && (
                <span className="nav-badge">{alertCount}</span>
              )}
            </NavLink>
          )
        )}
      </nav>

      <div style={{
        padding: '20px 24px',
        borderTop: '1px solid var(--glass-border)',
        fontSize: '0.75rem',
        color: 'var(--text-tertiary)',
        display: 'flex',
        alignItems: 'center',
        gap: '8px'
      }}>
        <div style={{ width: 8, height: 8, borderRadius: '50%', background: 'var(--accent-success)' }}></div>
        MedWatch v1.1.0 — System Active
      </div>
    </aside>
  );
}
