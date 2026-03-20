import { NavLink } from 'react-router-dom';

const navItems = [
  { section: '監控總覽' },
  { path: '/', icon: '📊', label: 'Dashboard' },
  { section: '資料查詢' },
  { path: '/recalls', icon: '🔔', label: '召回記錄' },
  { path: '/events', icon: '⚠️', label: '不良事件' },
  { path: '/standards', icon: '📋', label: '法規標準' },
  { path: '/reports', icon: '✨', label: 'AI 分析報告' },
  { section: '系統管理' },
  { path: '/products', icon: '🔍', label: '產品監控管理' },
  { path: '/settings', icon: '⚙️', label: '系統設定' },
];

export default function Sidebar({ alertCount }) {
  return (
    <aside className="sidebar">
      <div className="sidebar-brand">
        <div className="sidebar-brand-icon">🏥</div>
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
              {item.path === '/' && alertCount > 0 && (
                <span className="nav-badge">{alertCount}</span>
              )}
            </NavLink>
          )
        )}
      </nav>

      <div style={{
        padding: '16px 20px',
        borderTop: '1px solid var(--glass-border)',
        fontSize: '0.7rem',
        color: 'var(--text-tertiary)',
      }}>
        MedWatch v1.0.0
      </div>
    </aside>
  );
}
