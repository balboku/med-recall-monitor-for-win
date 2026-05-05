import { useState } from 'react';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { toast } from 'react-hot-toast';
import { api } from '../api';
import {
  Activity,
  AlertCircle,
  CheckCircle2,
  Clock,
  Cpu,
  Database,
  Download,
  Globe,
  History,
  Play,
  RotateCw,
  Server,
  ShieldAlert,
  Terminal,
  X,
} from 'lucide-react';

const crawlerMeta = {
  fda_recall: {
    label: 'FDA Recalls',
    icon: <ShieldAlert className="text-accent-warning" size={24} />,
    desc: '從 openFDA API 擷取醫療器材召回資料',
    tag: 'US',
  },
  fda_maude: {
    label: 'FDA MAUDE',
    icon: <Activity className="text-accent-danger" size={24} />,
    desc: '同步 openFDA 不良事件 (MAUDE) 報告',
    tag: 'US',
  },
  tfda: {
    label: 'TFDA 警訊',
    icon: <Globe className="text-accent-info" size={24} />,
    desc: '同步台灣食藥署公開安全警訊',
    tag: 'TW',
  },
  standards: {
    label: '法規標準更新',
    icon: <Terminal className="text-accent-success" size={24} />,
    desc: '追蹤 IEC / ISO 標準版本與修訂狀態',
    tag: 'Global',
  },
};

function statusMeta(status) {
  if (status === 'success') return { label: 'Success', className: 'tag-green', icon: <CheckCircle2 size={12} /> };
  if (status === 'error') return { label: 'Error', className: 'tag-red', icon: <AlertCircle size={12} /> };
  if (status === 'running') return { label: 'Running', className: 'tag-amber', icon: <RotateCw size={12} className="spinner" /> };
  return { label: 'Idle', className: 'tag-blue', icon: <Clock size={12} /> };
}

function formatTime(value) {
  if (!value) return '尚未執行';
  return new Date(value).toLocaleString('zh-TW');
}

export default function Settings() {
  const queryClient = useQueryClient();
  const [crawling, setCrawling] = useState({});
  const [modalState, setModalState] = useState({ open: false, crawler: null });
  const [selectedProductIds, setSelectedProductIds] = useState(new Set());

  const { data: products = [] } = useQuery({
    queryKey: ['products'],
    queryFn: api.getProducts,
  });

  const { data: crawlLogs = [], isFetching: loading } = useQuery({
    queryKey: ['crawlLogs'],
    queryFn: api.getCrawlLogs,
    refetchInterval: 5000,
  });

  const { data: healthData } = useQuery({
    queryKey: ['health'],
    queryFn: api.getHealth,
    refetchInterval: 15000,
  });

  const { data: systemInfo } = useQuery({
    queryKey: ['systemInfo'],
    queryFn: api.getSystemInfo,
    refetchInterval: 60000,
  });

  const handleCrawl = async (name, options = {}) => {
    const historical = options.historical || false;
    const key = historical ? `${name}_hist` : name;
    setCrawling((prev) => ({ ...prev, [key]: true }));
    try {
      await api.triggerCrawl(name, options);
      toast.success(`已在背景啟動 ${name} ${historical ? '歷史補抓' : '更新'} 任務`);
      queryClient.invalidateQueries({ queryKey: ['crawlLogs'] });
      queryClient.invalidateQueries({ queryKey: ['health'] });
      queryClient.invalidateQueries({ queryKey: ['dashboard'] });
    } catch (error) {
      toast.error(`啟動失敗: ${error.message}`);
    } finally {
      setCrawling((prev) => ({ ...prev, [key]: false }));
    }
  };

  const crawlers = Object.keys(crawlerMeta).map((name) => ({
    name,
    ...crawlerMeta[name],
    intervalHours: systemInfo?.scheduler?.crawlers?.[name]?.interval_hours,
    health: healthData?.crawlers?.[name],
  }));

  return (
    <div className="space-y-8">
      <div className="section-title">
        <div>
          <h1 className="page-title">系統控制中心</h1>
          <p className="page-subtitle">查看真實排程狀態、手動觸發同步，並追蹤背景任務是否正常完成</p>
        </div>
        <button className="btn btn-primary" onClick={() => handleCrawl('all')} disabled={crawling.all}>
          {crawling.all ? <RotateCw size={18} className="spinner" /> : <Play size={18} />}
          全部立即執行
        </button>
      </div>

      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(320px, 1fr))', gap: '20px' }}>
        {crawlers.map((crawler) => {
          const meta = statusMeta(crawler.health?.last_status);
          return (
            <div key={crawler.name} className="glass-card" style={{ padding: '24px', display: 'flex', flexDirection: 'column' }}>
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', marginBottom: '16px' }}>
                <div style={{ display: 'flex', alignItems: 'center', gap: '12px' }}>
                  <div style={{
                    width: '48px',
                    height: '48px',
                    borderRadius: '12px',
                    background: 'var(--bg-elevated)',
                    border: '1px solid var(--glass-border)',
                    display: 'flex',
                    alignItems: 'center',
                    justifyContent: 'center',
                  }}>
                    {crawler.icon}
                  </div>
                  <div>
                    <h3 style={{ fontSize: '1.1rem', fontWeight: 700, color: 'var(--text-primary)' }}>{crawler.label}</h3>
                    <div style={{ display: 'flex', alignItems: 'center', gap: '6px', marginTop: '2px', flexWrap: 'wrap' }}>
                      <span className="tag" style={{ fontSize: '10px', padding: '1px 6px', opacity: 0.8 }}>{crawler.tag}</span>
                      <span style={{ fontSize: '11px', color: 'var(--text-tertiary)', display: 'flex', alignItems: 'center', gap: '4px' }}>
                        <Clock size={10} /> 每 {crawler.intervalHours || '—'} 小時
                      </span>
                    </div>
                  </div>
                </div>
                <span className={`tag ${meta.className}`} style={{ display: 'flex', alignItems: 'center', gap: '4px' }}>
                  {meta.icon} {meta.label}
                </span>
              </div>

              <p style={{ fontSize: '0.88rem', color: 'var(--text-secondary)', marginBottom: '16px', lineHeight: 1.5 }}>
                {crawler.desc}
              </p>

              <div style={{
                marginBottom: '20px',
                padding: '12px',
                background: 'rgba(255,255,255,0.02)',
                borderRadius: '8px',
                border: '1px solid var(--glass-border)',
                fontSize: '0.8rem',
                display: 'grid',
                gap: '6px',
              }}>
                <div>最近執行: <span style={{ color: 'var(--text-secondary)' }}>{formatTime(crawler.health?.last_run)}</span></div>
                <div>本輪掃描: <span style={{ color: 'var(--text-secondary)' }}>{crawler.health?.records_found ?? 0}</span></div>
                <div>新增資料: <span style={{ color: 'var(--text-secondary)' }}>{crawler.health?.new_records ?? 0}</span></div>
                {crawler.health?.error && (
                  <div style={{ color: 'var(--accent-danger)' }}>最近錯誤: {crawler.health.error}</div>
                )}
              </div>

              <div style={{ display: 'flex', flexDirection: 'column', gap: '8px', marginTop: 'auto' }}>
                <button
                  className="btn btn-secondary w-full justify-center"
                  onClick={() => handleCrawl(crawler.name)}
                  disabled={crawling[crawler.name]}
                >
                  {crawling[crawler.name] ? (
                    <><RotateCw size={16} className="spinner" /> 執行中</>
                  ) : (
                    <><Play size={16} /> 立即更新</>
                  )}
                </button>

                {(crawler.name === 'fda_maude' || crawler.name === 'fda_recall') && (
                  <button
                    className="btn btn-ghost w-full justify-center"
                    onClick={() => {
                      setModalState({ open: true, crawler: crawler.name });
                      setSelectedProductIds(new Set(products.map(p => p.id)));
                    }}
                    disabled={crawling[`${crawler.name}_hist`]}
                    style={{ fontSize: '0.8rem', border: '1px solid var(--glass-border)' }}
                  >
                    {crawling[`${crawler.name}_hist`] ? (
                      <><RotateCw size={16} className="spinner" /> 補抓中</>
                    ) : (
                      <><Download size={16} /> 歷史大規模補抓</>
                    )}
                  </button>
                )}
              </div>
            </div>
          );
        })}
      </div>

      <div>
        <div className="section-title" style={{ marginBottom: '16px' }}>
          <h2 style={{ display: 'flex', alignItems: 'center', gap: '10px' }}>
            <History size={22} className="text-text-tertiary" />
            執行監控日誌
          </h2>
        </div>

        {loading && !crawlLogs.length ? (
          <div className="glass-card" style={{ padding: '60px', textAlign: 'center' }}>
            <RotateCw className="spinner" size={32} style={{ margin: '0 auto 16px', color: 'var(--accent-blue)' }} />
            <p className="text-text-tertiary">正在抓取運行日誌...</p>
          </div>
        ) : crawlLogs.length === 0 ? (
          <div className="glass-card" style={{ padding: '60px', textAlign: 'center' }}>
            <Terminal size={48} style={{ margin: '0 auto 16px', opacity: 0.1 }} />
            <h3 className="text-text-primary">尚無執行記錄</h3>
            <p className="text-text-tertiary">當排程或手動任務啟動後，日誌會顯示在這裡</p>
          </div>
        ) : (
          <div className="table-container">
            <table className="data-table">
              <thead>
                <tr>
                  <th>採集引擎</th>
                  <th>當前狀態</th>
                  <th style={{ textAlign: 'right' }}>掃描總數</th>
                  <th style={{ textAlign: 'right' }}>入庫數量</th>
                  <th>錯誤詳情</th>
                  <th>開始時間</th>
                  <th>完成時間</th>
                </tr>
              </thead>
              <tbody>
                {crawlLogs.map((log) => {
                  const meta = statusMeta(log.status);
                  return (
                    <tr key={log.id}>
                      <td style={{ fontWeight: 700, color: 'var(--text-primary)' }}>{log.crawler_name}</td>
                      <td>
                        <span className={`tag ${meta.className}`} style={{ display: 'flex', alignItems: 'center', gap: '4px', width: 'fit-content' }}>
                          {meta.icon} {meta.label}
                        </span>
                      </td>
                      <td style={{ textAlign: 'right', fontFamily: 'var(--font-mono)' }}>{log.records_found?.toLocaleString() || 0}</td>
                      <td style={{ textAlign: 'right', fontFamily: 'var(--font-mono)' }}>
                        {log.new_records > 0 ? (
                          <span style={{ color: 'var(--accent-success)', fontWeight: 700 }}>+{log.new_records}</span>
                        ) : '0'}
                      </td>
                      <td style={{ maxWidth: '220px' }}>
                        <div style={{ overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', fontSize: '0.75rem', color: 'var(--accent-danger)' }} title={log.error_message}>
                          {log.error_message || <span style={{ color: 'var(--text-tertiary)' }}>—</span>}
                        </div>
                      </td>
                      <td style={{ fontSize: '0.8rem', color: 'var(--text-tertiary)' }}>{formatTime(log.started_at)}</td>
                      <td style={{ fontSize: '0.8rem', color: 'var(--text-tertiary)' }}>
                        {log.status === 'running' ? '進行中' : formatTime(log.completed_at)}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
      </div>

      <div className="glass-card" style={{ padding: '28px', background: 'var(--bg-secondary)', border: '1px solid var(--glass-border)' }}>
        <h3 className="text-lg font-bold mb-6 flex items-center gap-2">
          <Server size={20} className="text-accent-blue" />
          系統實際資訊
        </h3>
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(220px, 1fr))', gap: '24px' }}>
          <InfoBlock icon={<Cpu size={24} />} label="Python" value={systemInfo?.stack?.python || '—'} />
          <InfoBlock icon={<Activity size={24} />} label="FastAPI" value={systemInfo?.stack?.fastapi || '—'} />
          <InfoBlock icon={<Terminal size={24} />} label="Celery" value={systemInfo?.stack?.celery || '—'} />
          <InfoBlock icon={<Database size={24} />} label="資料庫" value={systemInfo?.database_backend || '—'} />
        </div>

        <div style={{ marginTop: '24px', paddingTop: '20px', borderTop: '1px solid var(--white-10)', display: 'flex', justifyContent: 'space-between', alignItems: 'center', gap: '12px', flexWrap: 'wrap' }}>
          <div style={{ fontSize: '0.75rem', color: 'var(--text-tertiary)', display: 'flex', alignItems: 'center', gap: '6px' }}>
            {healthData?.status === 'ok' ? (
              <><CheckCircle2 size={12} className="text-accent-success" /> 系統健康狀態正常，召回 {healthData.data_summary?.total_recalls ?? 0} 筆，事件 {healthData.data_summary?.total_adverse_events ?? 0} 筆</>
            ) : (
              <><AlertCircle size={12} className="text-accent-warning" /> 系統狀態查詢中...</>
            )}
          </div>
          {healthData?.unread_failure_alerts > 0 && (
            <span style={{ fontSize: '0.75rem', color: 'var(--accent-danger)', fontWeight: 600 }}>
              ⚠️ {healthData.unread_failure_alerts} 則未讀爬蟲失敗告警
            </span>
          )}
        </div>
      </div>

      {/* Product Select Modal */}
      {modalState.open && (
        <div style={{
          position: 'fixed', top: 0, left: 0, right: 0, bottom: 0,
          background: 'rgba(0,0,0,0.6)', backdropFilter: 'blur(4px)',
          display: 'flex', alignItems: 'center', justifyContent: 'center', zIndex: 1000
        }}>
          <div className="glass-card" style={{ width: '400px', maxWidth: '90vw', padding: '24px', display: 'flex', flexDirection: 'column', gap: '16px' }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
              <h3 style={{ fontSize: '1.2rem', fontWeight: 600, color: 'var(--text-primary)' }}>選擇歷史補抓之產品</h3>
              <button
                onClick={() => setModalState({ open: false, crawler: null })}
                style={{ background: 'transparent', border: 'none', color: 'var(--text-secondary)', cursor: 'pointer' }}
              >
                <X size={20} />
              </button>
            </div>

            <p style={{ fontSize: '0.88rem', color: 'var(--text-secondary)' }}>
              請勾選要進行歷史大範圍資料抓取的產品。這將有助於專注特定產品並避免系統過載。
            </p>

            <div style={{ maxHeight: '300px', overflowY: 'auto', border: '1px solid var(--glass-border)', borderRadius: '8px', padding: '8px', display: 'flex', flexDirection: 'column', gap: '8px' }}>
              {products.length === 0 ? (
                <div style={{ padding: '16px', textAlign: 'center', color: 'var(--text-tertiary)' }}>尚無啟用中的產品</div>
              ) : (
                products.map(p => (
                  <label key={p.id} style={{ display: 'flex', alignItems: 'center', gap: '12px', padding: '8px', cursor: 'pointer', borderRadius: '4px', background: 'rgba(255,255,255,0.02)' }}>
                    <input
                      type="checkbox"
                      checked={selectedProductIds.has(p.id)}
                      onChange={(e) => {
                        const newSet = new Set(selectedProductIds);
                        if (e.target.checked) newSet.add(p.id);
                        else newSet.delete(p.id);
                        setSelectedProductIds(newSet);
                      }}
                      style={{ width: '16px', height: '16px', accentColor: 'var(--accent-blue)', cursor: 'pointer' }}
                    />
                    <span style={{ color: 'var(--text-primary)', fontSize: '0.9rem' }}>{p.name}</span>
                  </label>
                ))
              )}
            </div>

            <div style={{ display: 'flex', gap: '12px', marginTop: '8px' }}>
              <button
                className="btn btn-secondary flex-1 justify-center"
                onClick={() => setModalState({ open: false, crawler: null })}
              >
                取消
              </button>
              <button
                className="btn btn-primary flex-1 justify-center"
                onClick={() => {
                  handleCrawl(modalState.crawler, { historical: true, productIds: Array.from(selectedProductIds) });
                  setModalState({ open: false, crawler: null });
                }}
                disabled={selectedProductIds.size === 0}
              >
                確認開始
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

function InfoBlock({ icon, label, value }) {
  return (
    <div style={{ display: 'flex', gap: '12px' }}>
      <div style={{ color: 'var(--text-tertiary)' }}>{icon}</div>
      <div>
        <div style={{ fontSize: '0.75rem', color: 'var(--text-tertiary)', textTransform: 'uppercase', letterSpacing: '0.05em', fontWeight: 700 }}>
          {label}
        </div>
        <div style={{ fontWeight: 600, color: 'var(--text-primary)' }}>{value}</div>
      </div>
    </div>
  );
}
