import { BrowserRouter, Routes, Route, useLocation } from 'react-router-dom';
import { Toaster } from 'react-hot-toast';
import Sidebar from './components/Sidebar';
import Header from './components/Header';
import Dashboard from './pages/Dashboard';
import Products from './pages/Products';
import Recalls from './pages/Recalls';
import Events from './pages/Events';
import Standards from './pages/Standards';
import Settings from './pages/Settings';
import Reports from './pages/Reports';
import { api } from './api';
import './index.css';
import { useQuery } from '@tanstack/react-query';

const pageTitles = {
  '/': 'Dashboard 總覽',
  '/products': '產品監控管理',
  '/recalls': '召回記錄',
  '/events': '不良事件',
  '/standards': '法規標準',
  '/reports': 'AI 分析報告',
  '/settings': '系統設定',
};

function AppContent() {
  const location = useLocation();

  const { data: dashboardData, refetch: fetchAlertCount } = useQuery({
    queryKey: ['dashboard'],
    queryFn: () => api.getDashboard(),
    refetchInterval: 60000,
    refetchOnWindowFocus: true,
  });

  const alertCount = dashboardData?.unread_alerts || 0;

  const title = pageTitles[location.pathname] || 'MedWatch';

  return (
    <div className="app-layout">
      <Toaster position="top-center" />
      <Sidebar alertCount={alertCount} />
      <Header
        title={title}
        alertCount={alertCount}
        onAlertsCleared={fetchAlertCount}
      />
      <main className="main-content">
        <Routes>
          <Route path="/" element={<Dashboard />} />
          <Route path="/products" element={<Products />} />
          <Route path="/recalls" element={<Recalls />} />
          <Route path="/events" element={<Events />} />
          <Route path="/standards" element={<Standards />} />
          <Route path="/reports" element={<Reports />} />
          <Route path="/settings" element={<Settings />} />
        </Routes>
      </main>
    </div>
  );
}

export default function App() {
  return (
    <BrowserRouter>
      <AppContent />
    </BrowserRouter>
  );
}
