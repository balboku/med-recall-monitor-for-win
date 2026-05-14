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
  Megaphone,
  Play,
  RotateCw,
  Save,
  Server,
  ShieldAlert,
  Terminal,
  X,
  Languages,
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
  const [activeTab, setActiveTab] = useState('system');
  const [crawling, setCrawling] = useState({});
  const [modalState, setModalState] = useState({ open: false, crawler: null });
  const [selectedProductIds, setSelectedProductIds] = useState(new Set());
  const [announcementText, setAnnouncementText] = useState('');
  const [savingAnnouncement, setSavingAnnouncement] = useState(false);
  const [logPage, setLogPage] = useState(1);

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

  const { data: translationProgress } = useQuery({
    queryKey: ['translationProgress'],
    queryFn: api.getTranslationProgress,
    refetchInterval: 5000,
  });

  const { data: announcementData } = useQuery({
    queryKey: ['announcement'],
    queryFn: api.getAnnouncement,
    onSuccess: (data) => setAnnouncementText(data?.content ?? ''),
  });


  const handleTranslationToggle = async () => {
    try {
      if (translationProgress?.is_running) {
        await api.stopTranslationTask();
        toast.success("已送出停止翻譯訊號，正在等待當前語句翻譯完成...");
      } else {
        await api.startTranslationTask();
        toast.success("背景翻譯任務已啟動！");
      }
      queryClient.invalidateQueries({ queryKey: ['translationProgress'] });
    } catch (e) {
      toast.error(`任務切換失敗: ${e.message}`);
    }
  };

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

  const handleSaveAnnouncement = async () => {
    setSavingAnnouncement(true);
    try {
      await api.saveAnnouncement(announcementText);
      toast.success('公告已儲存！');
      queryClient.invalidateQueries({ queryKey: ['announcement'] });
    } catch (e) {
      toast.error(`儲存失敗: ${e.message}`);
    } finally {
      setSavingAnnouncement(false);
    }
  };

  const crawlers = Object.keys(crawlerMeta).map((name) => ({
    name,
    ...crawlerMeta[name],
    intervalHours: systemInfo?.scheduler?.crawlers?.[name]?.interval_hours,
    health: healthData?.crawlers?.[name],
  }));

  // Sync announcement content when data loads
  if (announcementData?.content !== undefined && announcementText === '' && announcementData.content !== '') {
    setAnnouncementText(announcementData.content);
  }

  const totalLogs = crawlLogs.length;
  const logsPerPage = 20;
  const totalLogPages = Math.ceil(totalLogs / logsPerPage);
  const paginatedLogs = crawlLogs.slice((logPage - 1) * logsPerPage, logPage * logsPerPage);

  return (
    <div className="space-y-8">
      {/* Tab Bar */}
      <div style={{ display: 'flex', gap: '4px', borderBottom: '1px solid var(--glass-border)', paddingBottom: '0' }}>
        <button
          onClick={() => setActiveTab('system')}
          style={{
            padding: '10px 20px',
            background: 'transparent',
            border: 'none',
            borderBottom: activeTab === 'system' ? '2px solid var(--accent-blue)' : '2px solid transparent',
            color: activeTab === 'system' ? 'var(--accent-blue)' : 'var(--text-secondary)',
            fontWeight: activeTab === 'system' ? 700 : 400,
            cursor: 'pointer',
            fontSize: '0.95rem',
            display: 'flex',
            alignItems: 'center',
            gap: '8px',
            transition: 'all 0.15s ease',
            marginBottom: '-1px',
          }}
        >
          <Server size={16} /> 系統控制中心
        </button>
        <button
          onClick={() => setActiveTab('announcement')}
          style={{
            padding: '10px 20px',
            background: 'transparent',
            border: 'none',
            borderBottom: activeTab === 'announcement' ? '2px solid var(--accent-blue)' : '2px solid transparent',
            color: activeTab === 'announcement' ? 'var(--accent-blue)' : 'var(--text-secondary)',
            fontWeight: activeTab === 'announcement' ? 700 : 400,
            cursor: 'pointer',
            fontSize: '0.95rem',
            display: 'flex',
            alignItems: 'center',
            gap: '8px',
            transition: 'all 0.15s ease',
            marginBottom: '-1px',
          }}
        >
          <Megaphone size={16} /> 公告
        </button>
      </div>

      {/* Announcement Tab */}
      {activeTab === 'announcement' && (
        <div className="glass-card" style={{ padding: '32px' }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '20px' }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: '12px' }}>
              <Megaphone size={22} className="text-accent-blue" />
              <div>
                <h2 style={{ fontSize: '1.1rem', fontWeight: 700, color: 'var(--text-primary)' }}>系統公告</h2>
                <p style={{ fontSize: '0.83rem', color: 'var(--text-tertiary)', marginTop: '2px' }}>編輯後點擊儲存，公告內容將持久化至資料庫</p>
              </div>
            </div>
            <button
              className="btn btn-primary"
              onClick={handleSaveAnnouncement}
              disabled={savingAnnouncement}
              style={{ display: 'flex', alignItems: 'center', gap: '8px' }}
            >
              {savingAnnouncement ? <RotateCw size={16} className="spinner" /> : <Save size={16} />}
              {savingAnnouncement ? '儲存中...' : '儲存公告'}
            </button>
          </div>
          <textarea
            value={announcementText}
            onChange={(e) => setAnnouncementText(e.target.value)}
            placeholder="在此輸入公告內容...&#10;&#10;支援多行文字輸入。"
            style={{
              width: '100%',
              minHeight: '320px',
              background: 'var(--bg-elevated)',
              border: '1px solid var(--glass-border)',
              borderRadius: '10px',
              padding: '16px',
              color: 'var(--text-primary)',
              fontSize: '0.95rem',
              lineHeight: 1.7,
              resize: 'vertical',
              outline: 'none',
              fontFamily: 'inherit',
              boxSizing: 'border-box',
              transition: 'border-color 0.15s ease',
            }}
            onFocus={(e) => e.target.style.borderColor = 'var(--accent-blue)'}
            onBlur={(e) => e.target.style.borderColor = 'var(--glass-border)'}
          />
          <div style={{ marginTop: '10px', fontSize: '0.78rem', color: 'var(--text-tertiary)', textAlign: 'right' }}>
            {announcementText.length} 字元
          </div>
        </div>
      )}

      {/* System Control Tab */}
      {activeTab === 'system' && <>
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
            <>
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
                    {paginatedLogs.map((log) => {
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

              {totalLogs > 2 && (
                <div className="pagination" style={{ marginTop: '16px' }}>
                  <button disabled={logPage <= 1} onClick={() => setLogPage(1)} title="第一頁">«</button>
                  <button disabled={logPage <= 1} onClick={() => setLogPage(Math.max(1, logPage - 1))}>‹</button>
                  {(() => {
                    const maxVisible = 7;
                    let start = 1;
                    let end = totalLogPages;
                    if (totalLogPages > maxVisible) {
                      start = Math.max(1, logPage - Math.floor(maxVisible / 2));
                      end = start + maxVisible - 1;
                      if (end > totalLogPages) {
                        end = totalLogPages;
                        start = Math.max(1, end - maxVisible + 1);
                      }
                    }
                    return Array.from({ length: end - start + 1 }, (_, index) => start + index).map((value) => (
                      <button key={value} className={value === logPage ? 'active' : ''} onClick={() => setLogPage(value)}>
                        {value}
                      </button>
                    ));
                  })()}
                  <button disabled={logPage >= totalLogPages} onClick={() => setLogPage(Math.min(totalLogPages, logPage + 1))}>›</button>
                  <button disabled={logPage >= totalLogPages} onClick={() => setLogPage(totalLogPages)} title="最後一頁">»</button>
                  <span style={{ marginLeft: 12, fontSize: '0.78rem', color: 'var(--text-tertiary)' }}>
                    共 {totalLogs} 筆
                  </span>
                </div>
              )}
            </>
          )}
        </div>

        <div className="glass-card" style={{ padding: '28px', background: 'var(--bg-secondary)', border: '1px solid var(--glass-border)' }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', marginBottom: '24px' }}>
            <div>
              <h3 className="text-lg font-bold flex items-center gap-2 mb-2">
                <Languages size={20} className="text-accent-blue" />
                背景事件描述全庫翻譯 (離放式)
              </h3>
              <p style={{ fontSize: '0.88rem', color: 'var(--text-secondary)' }}>
                考量到大量逐字翻譯可能遭到來源封鎖，系統將以緩速的背景頻率（每數秒一筆）自動為資料庫進行繁體中文翻譯。如果中斷可以隨時接續。
              </p>
            </div>
            <button
              className={`btn ${translationProgress?.is_running ? 'btn-ghost' : 'btn-primary'}`}
              onClick={handleTranslationToggle}
            >
              {translationProgress?.is_running ? <><RotateCw size={16} className="spinner" /> 暫停翻譯</> : <><Play size={16} /> 開始背景翻譯</>}
            </button>
          </div>

          {translationProgress && (
            <div>
              <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: '8px', fontSize: '0.85rem' }}>
                <span>翻譯進度：{translationProgress.translated.toLocaleString()} / {translationProgress.total.toLocaleString()}</span>
                <span style={{ color: 'var(--text-tertiary)' }}>{(translationProgress.translated / Math.max(translationProgress.total, 1) * 100).toFixed(1)}%</span>
              </div>
              <div style={{ width: '100%', height: '8px', background: 'var(--bg-elevated)', borderRadius: '4px', overflow: 'hidden' }}>
                <div style={{
                  width: `${(translationProgress.translated / Math.max(translationProgress.total, 1) * 100)}%`,
                  height: '100%',
                  background: translationProgress.is_running ? 'var(--accent-blue)' : 'var(--text-tertiary)',
                  transition: 'width 0.5s ease'
                }} />
              </div>
              <div style={{ marginTop: '12px', fontSize: '0.8rem', color: 'var(--text-tertiary)', display: 'flex', gap: '16px' }}>
                <span>剩餘需翻譯：{translationProgress.pending.toLocaleString()} 筆</span>
                <span>狀態：{translationProgress.is_running ? <span style={{ color: 'var(--accent-blue)' }}>執行中</span> : '已暫停'}</span>
              </div>
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
      </> /* end system tab */}
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
