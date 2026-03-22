import { useState } from 'react';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { api } from '../api';
import { toast } from 'react-hot-toast';
import { 
  Play, 
  RotateCw, 
  History, 
  Info, 
  Server, 
  Database, 
  Cpu, 
  Activity, 
  AlertCircle, 
  CheckCircle2, 
  ChevronRight, 
  Globe,
  ShieldAlert,
  Download,
  Terminal,
  Clock,
  ExternalLink
} from 'lucide-react';

export default function Settings() {
  const queryClient = useQueryClient();
  const [crawling, setCrawling] = useState({});

  const { data: crawlLogs = [], isFetching: loading } = useQuery({
    queryKey: ['crawlLogs'],
    queryFn: api.getCrawlLogs,
    refetchInterval: 5000,
  });

  // #16: 即時健康狀態
  const { data: healthData } = useQuery({
    queryKey: ['health'],
    queryFn: api.getHealth,
    refetchInterval: 30000,
  });

  const handleCrawl = async (name, historical = false) => {
    const key = historical ? `${name}_hist` : name;
    setCrawling((prev) => ({ ...prev, [key]: true }));
    try {
      await api.triggerCrawl(name, historical);
      toast.success(`已在背景啟動 ${name} ${historical ? '歷史完全同步' : '更新'} 任務`);
      setTimeout(() => queryClient.invalidateQueries({ queryKey: ['crawlLogs'] }), 1000);
      setTimeout(() => queryClient.invalidateQueries({ queryKey: ['crawlLogs'] }), 3000);
    } catch (e) { 
      toast.error(`啟動失敗: ${e.message}`);
    }
    finally { 
      setCrawling((prev) => ({ ...prev, [key]: false })); 
    }
  };

  const crawlers = [
    { 
      name: 'fda_recall', 
      label: 'FDA Recalls', 
      icon: <ShieldAlert className="text-accent-warning" size={24} />, 
      desc: '從 openFDA API 爬取全球醫療器材召回記錄', 
      schedule: '每日 04:00 (UTC)',
      tag: 'US'
    },
    { 
      name: 'fda_maude', 
      label: 'FDA MAUDE', 
      icon: <Activity className="text-accent-danger" size={24} />, 
      desc: '監控 openFDA 全球不良事件 (MAUDE) 報告', 
      schedule: '每日 04:00 (UTC)',
      tag: 'US'
    },
    { 
      name: 'tfda', 
      label: 'TFDA 警訊', 
      icon: <Globe className="text-accent-info" size={24} />, 
      desc: '從台灣食藥署 (TFDA) 官網同步最新安全警訊', 
      schedule: '每日 09:00 (CST)',
      tag: 'TW'
    },
    { 
      name: 'standards', 
      label: '法規標準更新', 
      icon: <Terminal className="text-accent-success" size={24} />, 
      desc: '追蹤 IEC/ISO 官方數據庫之版本異動狀態', 
      schedule: '每週一 02:00 (CST)',
      tag: 'Global'
    },
  ];

  return (
    <div className="space-y-8">
      <div className="section-title">
        <div>
          <h1 className="page-title">系統控制中心</h1>
          <p className="page-subtitle">管理數據採集引擎、查看自動化排程日誌與系統運行狀態</p>
        </div>
        <button
          className="btn btn-primary"
          onClick={() => handleCrawl('all')}
          disabled={crawling.all}
        >
          {crawling.all ? <RotateCw size={18} className="spinner" /> : <Play size={18} />}
          全部立即執行
        </button>
      </div>

      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(320px, 1fr))', gap: '20px' }}>
        {crawlers.map((c) => (
          <div key={c.name} className="glass-card" style={{ padding: '24px', display: 'flex', flexDirection: 'column' }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', marginBottom: '16px' }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: '12px' }}>
                <div style={{ 
                  width: '48px', height: '48px', borderRadius: '12px', 
                  background: 'var(--bg-elevated)', border: '1px solid var(--glass-border)',
                  display: 'flex', alignItems: 'center', justifyContent: 'center'
                }}>
                  {c.icon}
                </div>
                <div>
                  <h3 style={{ fontSize: '1.1rem', fontWeight: 700, color: 'var(--text-primary)' }}>{c.label}</h3>
                  <div style={{ display: 'flex', alignItems: 'center', gap: '6px', marginTop: '2px' }}>
                    <span className="tag" style={{ fontSize: '10px', padding: '1px 6px', opacity: 0.8 }}>{c.tag}</span>
                    <span style={{ fontSize: '11px', color: 'var(--text-tertiary)', display: 'flex', alignItems: 'center', gap: '4px' }}>
                      <Clock size={10} /> {c.schedule}
                    </span>
                  </div>
                </div>
              </div>
            </div>
            
            <p style={{ fontSize: '0.88rem', color: 'var(--text-secondary)', marginBottom: '24px', flex: 1, lineHeight: 1.5 }}>
              {c.desc}
            </p>
            
            <div style={{ display: 'flex', flexDirection: 'column', gap: '8px' }}>
              <button
                className="btn btn-secondary w-full justify-center"
                onClick={() => handleCrawl(c.name)}
                disabled={crawling[c.name]}
              >
                {crawling[c.name] ? (
                  <><RotateCw size={16} className="spinner" /> 執行中</>
                ) : <><Play size={16} /> 立即更新</>}
              </button>
              
              {(c.name === 'fda_maude' || c.name === 'fda_recall') && (
                <button
                  className="btn btn-ghost w-full justify-center"
                  onClick={() => handleCrawl(c.name, true)}
                  disabled={crawling[`${c.name}_hist`]}
                  style={{ fontSize: '0.8rem', border: '1px solid var(--glass-border)' }}
                >
                  {crawling[`${c.name}_hist`] ? (
                    <><RotateCw size={16} className="spinner" /> 同步中</>
                  ) : <><Download size={16} /> 歷史大規模數據補齊</>}
                </button>
              )}
            </div>
          </div>
        ))}
      </div>

      {/* Crawl Logs */}
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
            <p className="text-text-tertiary">系統啟動自動化排程或手動執行任務後，日誌將顯示於此</p>
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
                  <th>耗時</th>
                </tr>
              </thead>
              <tbody>
                {crawlLogs.map((log) => {
                  const duration = log.completed_at && log.started_at 
                    ? Math.round((new Date(log.completed_at) - new Date(log.started_at)) / 1000)
                    : null;
                  
                  return (
                    <tr key={log.id}>
                      <td style={{ fontWeight: 700, color: 'var(--text-primary)' }}>{log.crawler_name}</td>
                      <td>
                        {log.status === 'success' ? (
                          <span className="tag tag-green" style={{ display: 'flex', alignItems: 'center', gap: '4px', width: 'fit-content' }}>
                            <CheckCircle2 size={12} /> Success
                          </span>
                        ) : log.status === 'error' ? (
                          <span className="tag tag-red" style={{ display: 'flex', alignItems: 'center', gap: '4px', width: 'fit-content' }}>
                            <AlertCircle size={12} /> Error
                          </span>
                        ) : (
                          <span className="tag tag-amber" style={{ display: 'flex', alignItems: 'center', gap: '4px', width: 'fit-content' }}>
                            <RotateCw size={12} className="spinner" /> Running
                          </span>
                        )}
                      </td>
                      <td style={{ textAlign: 'right', fontFamily: 'var(--font-mono)' }}>{log.records_found?.toLocaleString() || 0}</td>
                      <td style={{ textAlign: 'right', fontFamily: 'var(--font-mono)' }}>
                        {log.new_records > 0 ? (
                          <span style={{ color: 'var(--accent-success)', fontWeight: 700 }}>+{log.new_records}</span>
                        ) : '0'}
                      </td>
                      <td style={{ maxWidth: '200px' }}>
                        <div style={{ overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', fontSize: '0.75rem', color: 'var(--accent-danger)' }} title={log.error_message}>
                          {log.error_message || <span style={{ color: 'var(--text-tertiary)' }}>—</span>}
                        </div>
                      </td>
                      <td style={{ fontSize: '0.8rem', color: 'var(--text-tertiary)' }}>
                        {log.started_at ? new Date(log.started_at).toLocaleString('zh-TW', { month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit', second: '2-digit' }) : '—'}
                      </td>
                      <td style={{ fontSize: '0.8rem', color: 'var(--text-tertiary)' }}>
                        {duration !== null ? `${duration}s` : log.status === 'running' ? '進行中' : '—'}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
      </div>

      {/* System Infrastructure */}
      <div className="glass-card" style={{ padding: '28px', background: 'var(--bg-secondary)', border: '1px solid var(--glass-border)' }}>
        <h3 className="text-lg font-bold mb-6 flex items-center gap-2">
          <Server size={20} className="text-accent-blue" />
          基礎設施架構資訊
        </h3>
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(200px, 1fr))', gap: '24px' }}>
          <div style={{ display: 'flex', gap: '12px' }}>
            <div style={{ color: 'var(--text-tertiary)' }}><Cpu size={24} /></div>
            <div>
              <div style={{ fontSize: '0.75rem', color: 'var(--text-tertiary)', textTransform: 'uppercase', letterSpacing: '0.05em', fontWeight: 700 }}>核心引擎</div>
              <div style={{ fontWeight: 600, color: 'var(--text-primary)' }}>FastAPI v0.109+</div>
              <div style={{ fontSize: '0.7rem', color: 'var(--text-tertiary)' }}>Python 3.12 (Asynchronous)</div>
            </div>
          </div>
          <div style={{ display: 'flex', gap: '12px' }}>
            <div style={{ color: 'var(--text-tertiary)' }}><Activity size={24} /></div>
            <div>
              <div style={{ fontSize: '0.75rem', color: 'var(--text-tertiary)', textTransform: 'uppercase', letterSpacing: '0.05em', fontWeight: 700 }}>任務處理</div>
              <div style={{ fontWeight: 600, color: 'var(--text-primary)' }}>Celery Workers</div>
              <div style={{ fontSize: '0.7rem', color: 'var(--text-tertiary)' }}>Redis Cluster (Message Broker)</div>
            </div>
          </div>
          <div style={{ display: 'flex', gap: '12px' }}>
            <div style={{ color: 'var(--text-tertiary)' }}><Database size={24} /></div>
            <div>
              <div style={{ fontSize: '0.75rem', color: 'var(--text-tertiary)', textTransform: 'uppercase', letterSpacing: '0.05em', fontWeight: 700 }}>持久化層</div>
              <div style={{ fontWeight: 600, color: 'var(--text-primary)' }}>PostgreSQL 16</div>
              <div style={{ fontSize: '0.7rem', color: 'var(--text-tertiary)' }}>Relational Data Storage</div>
            </div>
          </div>
          <div style={{ display: 'flex', gap: '12px' }}>
            <div style={{ color: 'var(--text-tertiary)' }}><ShieldAlert size={24} /></div>
            <div>
              <div style={{ fontSize: '0.75rem', color: 'var(--text-tertiary)', textTransform: 'uppercase', letterSpacing: '0.05em', fontWeight: 700 }}>前端版本</div>
              <div style={{ fontWeight: 600, color: 'var(--text-primary)' }}>v2.5.0 "Aria"</div>
              <div style={{ fontSize: '0.7rem', color: 'var(--text-tertiary)' }}>React 18 + Vite (OLED Theme)</div>
            </div>
          </div>
        </div>
        
        <div style={{ marginTop: '24px', paddingTop: '20px', borderTop: '1px solid var(--white-10)', display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
          <div style={{ fontSize: '0.75rem', color: 'var(--text-tertiary)', display: 'flex', alignItems: 'center', gap: '6px' }}>
             {healthData?.status === 'ok' ? (
               <><CheckCircle2 size={12} className="text-accent-success" /> 所有系統服務運行正常 (召回: {healthData.data_summary?.total_recalls ?? '...'}, 事件: {healthData.data_summary?.total_adverse_events ?? '...'})</>
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
    </div>
  );
}
