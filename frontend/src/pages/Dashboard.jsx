import { Fragment } from 'react';
import { useQuery } from '@tanstack/react-query';
import { useNavigate } from 'react-router-dom';
import { api } from '../api';

export default function Dashboard() {
  const navigate = useNavigate();
  const { data: stats, isLoading: statsLoading } = useQuery({ queryKey: ['dashboard'], queryFn: () => api.getDashboard() });
  const { data: mrmSummary, isLoading: mrmLoading } = useQuery({ queryKey: ['mrmSummary'], queryFn: () => api.getMrmSummary() });
  const { data: trend, isLoading: trendLoading } = useQuery({ queryKey: ['trend'], queryFn: () => api.getTrend('all') });

  const loading = statsLoading || mrmLoading || trendLoading;

  if (loading) {
    return <div className="loading-overlay"><div className="spinner"></div><span>載入中…</span></div>;
  }

  // ---- 整理趨勢圖表資料 ----
  const trendMap = {};
  if (trend) {
    trend.recall_monthly_trend?.forEach(r => {
      if (!trendMap[r.month]) trendMap[r.month] = { month: r.month, recalls: 0, events: 0 };
      trendMap[r.month].recalls += r.count;
    });
    trend.event_monthly_trend?.forEach(r => {
      if (!trendMap[r.month]) trendMap[r.month] = { month: r.month, recalls: 0, events: 0 };
      trendMap[r.month].events += r.count;
    });
  }
  const mergedTrend = Object.values(trendMap).sort((a,b) => a.month.localeCompare(b.month));
  const maxTrendVal = Math.max(...mergedTrend.map(d => Math.max(d.recalls, d.events)), 1);

  // ---- 整理事件嚴重度分佈圖資料 (PIE) ----
  const severityMap = {};
  trend?.event_monthly_trend?.forEach(e => {
    const typeName = e.event_type || 'Other';
    severityMap[typeName] = (severityMap[typeName] || 0) + e.count;
  });
  const severityPieData = Object.entries(severityMap)
    .map(([name, value]) => ({ name, value }))
    .sort((a, b) => b.value - a.value);
  const totalSeverity = severityPieData.reduce((acc, curr) => acc + curr.value, 0) || 1;

  const colorMap = ['#ef4444', '#f59e0b', '#3b82f6', '#10b981', '#6b7280'];

  // ---- KPI 卡片資料 ----
  const kpi = mrmSummary?.kpi || {};
  
  const statCards = [
    { 
      label: '本季新增 Class I 召回', 
      value: kpi.class1_recalls_total ?? 0, 
      icon: '🚨', 
      color: (kpi.class1_recalls_total ?? 0) > 0 ? 'red' : 'green',
      sub: '極高風險立即處置'
    },
    { 
      label: '本月嚴重不良事件', 
      value: kpi.new_events_this_month ?? 0, 
      icon: '⚠️', 
      color: (kpi.new_events_this_month ?? 0) > 10 ? 'red' : 'amber',
      sub: '建議持續監察'
    },
    { 
      label: '未讀合規告警', 
      value: kpi.unread_alerts ?? 0, 
      icon: '📩', 
      color: (kpi.unread_alerts ?? 0) > 0 ? 'amber' : 'green',
      sub: '請速審閱'
    },
    { 
      label: '需評估之法規更新', 
      value: kpi.standards_needing_update ?? 0, 
      icon: '📋', 
      color: (kpi.standards_needing_update ?? 0) > 0 ? 'blue' : 'gray',
      sub: '對齊新版基準'
    },
  ];

  return (
    <div style={{ paddingBottom: '48px', animation: 'fadeIn 0.3s ease' }}>
      <div className="section-title">
        <div>
          <h1 className="page-title">品保監控戰情室 (QA Dashboard)</h1>
          <p className="page-subtitle">針對高風險異常、召回趨勢進行管理與跨域分析</p>
        </div>
        <div style={{ fontSize: '0.75rem', color: 'var(--text-tertiary)', background: 'var(--bg-surface)', padding: '4px 12px', borderRadius: '4px', border: '1px solid var(--glass-border)' }}>
          報表月份: {mrmSummary?.reporting_month || '未指定'}
        </div>
      </div>

      {/* KPI 卡片 (紅綠燈) */}
      <div className="stat-grid">
        {statCards.map((s) => (
          <div key={s.label} className="stat-card" data-color={s.color}>
            <div className="stat-icon" style={{ opacity: 1, fontSize: '1.2rem' }}>{s.icon}</div>
            <div className="stat-label">{s.label}</div>
            <div className="stat-value" style={{ 
              color: s.color === 'red' ? 'var(--accent-red)' : s.color === 'amber' ? 'var(--accent-amber)' : 'var(--text-primary)' 
            }}>
              {s.value}
            </div>
            {s.sub && <div className="stat-sub">{s.sub}</div>}
          </div>
        ))}
      </div>

      {/* 圖表區: 趨勢 + 佔比 */}
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(350px, 1fr))', gap: '24px', marginBottom: '24px' }}>
        
        {/* 近期不良事件與召回趨勢 (Line Chart) */}
        <div className="glass-card" style={{ gridColumn: '1 / -1' }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '24px' }}>
            <h2 style={{ fontSize: '1.1rem', fontWeight: 600 }}>📈 綜合趨勢 (事件 vs 召回)</h2>
            <div style={{ display: 'flex', gap: '16px', fontSize: '0.8rem' }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
                <span style={{ width: '12px', height: '3px', background: 'var(--accent-blue)', borderRadius: '2px' }}></span> 召回數
              </div>
              <div style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
                <span style={{ width: '12px', height: '3px', background: 'var(--accent-red)', borderRadius: '2px' }}></span> 不良事件
              </div>
            </div>
          </div>
          <div style={{ display: 'flex', alignItems: 'flex-end', height: '240px', gap: '8px', borderBottom: '1px solid var(--glass-border)', paddingBottom: '8px', position: 'relative', paddingLeft: '32px', paddingRight: '12px' }}>
            {/* Y軸簡易標記 */}
            <div style={{ position: 'absolute', left: 0, top: 0, bottom: '0', width: '28px', display: 'flex', flexDirection: 'column', justifyContent: 'space-between', fontSize: '10px', color: 'var(--text-tertiary)' }}>
              <span>{maxTrendVal}</span>
              <span>{Math.floor(maxTrendVal/2)}</span>
              <span>0</span>
            </div>
            
            {/* SVG 折線圖區域 */}
            <div style={{ position: 'relative', width: '100%', height: '100%' }}>
              
              {/* 背景輔助水平線 */}
              <div style={{ position: 'absolute', top: '50%', left: 0, right: 0, height: '1px', background: 'var(--glass-border)', opacity: 0.5, borderStyle: 'dashed', borderWidth: '1px 0 0 0' }} />
              
              <svg viewBox="0 0 100 100" preserveAspectRatio="none" style={{ position: 'absolute', top: 0, left: 0, width: '100%', height: '100%', overflow: 'visible' }}>
                {/* 召回數折線 */}
                <polyline 
                  points={(function() {
                    if (mergedTrend.length === 0) return "";
                    if (mergedTrend.length === 1) return `0,${100 - (mergedTrend[0].recalls / maxTrendVal) * 100} 100,${100 - (mergedTrend[0].recalls / maxTrendVal) * 100}`;
                    return mergedTrend.map((d, i) => `${(i / (mergedTrend.length - 1)) * 100},${100 - (Math.max(d.recalls, 0) / maxTrendVal) * 100}`).join(' ');
                  })()}
                  fill="none" 
                  stroke="var(--accent-blue)" 
                  strokeWidth="2" 
                  vectorEffect="non-scaling-stroke" 
                />
                {/* 不良事件折線 */}
                <polyline 
                  points={(function() {
                    if (mergedTrend.length === 0) return "";
                    if (mergedTrend.length === 1) return `0,${100 - (mergedTrend[0].events / maxTrendVal) * 100} 100,${100 - (mergedTrend[0].events / maxTrendVal) * 100}`;
                    return mergedTrend.map((d, i) => `${(i / (mergedTrend.length - 1)) * 100},${100 - (Math.max(d.events, 0) / maxTrendVal) * 100}`).join(' ');
                  })()}
                  fill="none" 
                  stroke="var(--accent-red)" 
                  strokeWidth="2" 
                  vectorEffect="non-scaling-stroke" 
                />
              </svg>

              {/* 資料節點與 Hover 感應區 */}
              {mergedTrend.map((d, i) => {
                const left = mergedTrend.length > 1 ? `${(i / (mergedTrend.length - 1)) * 100}%` : '50%';
                const bottomEvents = `${(Math.max(d.events, 0) / maxTrendVal) * 100}%`;
                const bottomRecalls = `${(Math.max(d.recalls, 0) / maxTrendVal) * 100}%`;
                const hoverWidth = mergedTrend.length > 1 ? `${100 / (mergedTrend.length - 1)}%` : '100%';
                
                return (
                  <Fragment key={`point-${d.month}`}>
                    {/* Recall 節點 */}
                    <div style={{ position: 'absolute', left, bottom: bottomRecalls, width: '8px', height: '8px', borderRadius: '50%', background: 'var(--bg-surface)', border: '2px solid var(--accent-blue)', transform: 'translate(-50%, 50%)', zIndex: 2, pointerEvents: 'none' }} />
                    {/* Event 節點 */}
                    <div style={{ position: 'absolute', left, bottom: bottomEvents, width: '8px', height: '8px', borderRadius: '50%', background: 'var(--bg-surface)', border: '2px solid var(--accent-red)', transform: 'translate(-50%, 50%)', zIndex: 2, pointerEvents: 'none' }} />
                    
                    {/* 隱形透明感應柱 */}
                    <div 
                      key={`hover-${d.month}`} 
                      style={{ position: 'absolute', left, bottom: 0, top: 0, width: hoverWidth, transform: 'translateX(-50%)', cursor: 'pointer', zIndex: 10 }}
                      onClick={() => navigate(`/events?month=${d.month}`)}
                      title={`${d.month}\n召回: ${d.recalls} | 事件: ${d.events}`}
                      onMouseEnter={(e) => { e.currentTarget.style.background = 'rgba(255,255,255,0.05)' }}
                      onMouseLeave={(e) => { e.currentTarget.style.background = 'transparent' }}
                    />
                  </Fragment>
                );
              })}
            </div>
          </div>
          <div style={{ display: 'flex', paddingLeft: '32px', paddingRight: '12px', marginTop: '8px', position: 'relative' }}>
            {mergedTrend.map((d, i) => {
              const left = mergedTrend.length > 1 ? `${(i / (mergedTrend.length - 1)) * 100}%` : '50%';
              const showLabel = mergedTrend.length <= 12 || (i % Math.ceil(mergedTrend.length / 10) === 0) || i === mergedTrend.length - 1;
              if (!showLabel) return null;
              return (
                <div key={`lbl-${d.month}`} style={{ position: 'absolute', left, transform: 'translateX(-50%)', fontSize: '10px', color: 'var(--text-secondary)' }}>
                  {d.month.substring(2)}
                </div>
              );
            })}
            {/* 撐開高度用 */}
            <div style={{ height: '14px' }}></div>
          </div>
        </div>

        {/* 嚴重度分佈 (Stacked Bar / Area) */}
        <div className="glass-card" style={{ display: 'flex', flexDirection: 'column' }}>
          <h2 style={{ fontSize: '1.1rem', fontWeight: 600, marginBottom: '24px' }}>📊 事件嚴重度佔比</h2>
          <div style={{ flex: 1, display: 'flex', flexDirection: 'column', justifyContent: 'center' }}>
            {severityPieData.length > 0 ? (
              <>
                <div style={{ width: '100%', display: 'flex', height: '32px', borderRadius: '16px', overflow: 'hidden', marginBottom: '24px', border: '1px solid var(--glass-border)' }}>
                  {severityPieData.map((d, idx) => (
                    <div 
                      key={d.name} 
                      style={{ width: `${(d.value/totalSeverity)*100}%`, backgroundColor: colorMap[idx % colorMap.length], height: '100%', borderRight: '1px solid var(--bg-surface)' }} 
                      title={`${d.name}: ${d.value}`}
                    />
                  ))}
                </div>
                <div style={{ display: 'grid', gridTemplateColumns: '1fr', gap: '12px' }}>
                  {severityPieData.map((d, idx) => (
                    <div key={d.name} style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', fontSize: '0.9rem', padding: '8px', borderRadius: '8px', background: 'var(--bg-surface)' }}>
                      <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                        <span style={{ width: '12px', height: '12px', borderRadius: '50%', backgroundColor: colorMap[idx % colorMap.length] }}></span>
                        <span style={{ color: 'var(--text-primary)', fontWeight: 500 }}>{d.name}</span>
                      </div>
                      <div style={{ display: 'flex', alignItems: 'center', gap: '12px' }}>
                        <span style={{ color: 'var(--text-secondary)', fontSize: '0.8rem' }}>{((d.value/totalSeverity)*100).toFixed(1)}%</span>
                        <span style={{ fontWeight: 700, width: '32px', textAlign: 'right' }}>{d.value}</span>
                      </div>
                    </div>
                  ))}
                </div>
              </>
            ) : (
              <div style={{ textAlign: 'center', color: 'var(--text-tertiary)', marginTop: '32px' }}>本期無不良事件資料</div>
            )}
          </div>
        </div>

        {/* 高風險失效產品型號 (Bar Chart) */}
        <div className="glass-card">
          <h2 style={{ fontSize: '1.1rem', fontWeight: 600, marginBottom: '24px' }}>🏆 高頻召回產品排名 (Top Risk)</h2>
          <div style={{ display: 'flex', flexDirection: 'column', gap: '16px' }}>
            {trend?.product_ranking?.length > 0 ? (
              trend.product_ranking.slice(0, 5).map(r => {
                const maxRecall = Math.max(...trend.product_ranking.map(x => x.recall_count), 1);
                return (
                  <div key={r.product_name}>
                    <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: '0.85rem', marginBottom: '6px', fontWeight: 500 }}>
                      <span style={{ color: 'var(--text-primary)', whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis', maxWidth: '70%' }}>{r.product_name}</span>
                      <span style={{ color: 'var(--text-secondary)' }}><strong style={{ color: 'var(--text-primary)' }}>{r.recall_count}</strong> 件</span>
                    </div>
                    <div style={{ width: '100%', background: 'var(--bg-surface)', height: '10px', borderRadius: '5px', overflow: 'hidden' }}>
                      <div style={{ height: '100%', borderRadius: '5px', background: 'var(--accent-purple)', width: `${(r.recall_count/maxRecall)*100}%` }} />
                    </div>
                  </div>
                );
              })
            ) : (
              <div style={{ display: 'flex', height: '100px', alignItems: 'center', justifyContent: 'center', color: 'var(--text-tertiary)' }}>尚無足夠召回數據進行排行</div>
            )}
          </div>
        </div>

        {/* 最新召回清單 */}
        <div className="glass-card" style={{ display: 'flex', flexDirection: 'column', height: '350px' }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '16px', borderBottom: '1px solid var(--glass-border)', paddingBottom: '12px' }}>
            <h2 style={{ fontSize: '1.1rem', fontWeight: 600 }}>🔔 最新召回動態</h2>
            <button 
              style={{ fontSize: '0.85rem', fontWeight: 500, color: 'var(--accent-blue)', background: 'none', border: 'none', cursor: 'pointer' }}
              onClick={() => navigate('/recalls')}
            >
              查看全部 &rarr;
            </button>
          </div>
          <div style={{ flex: 1, overflowY: 'auto', paddingRight: '4px' }}>
            {(stats?.latest_recalls?.length ?? 0) === 0 ? (
              <div style={{ height: '100%', display: 'flex', alignItems: 'center', justifyContent: 'center', color: 'var(--text-tertiary)' }}>尚無召回記錄</div>
            ) : (
              <div style={{ display: 'flex', flexDirection: 'column', gap: '12px' }}>
                {stats.latest_recalls.map((r) => (
                  <div 
                    key={r.id} 
                    style={{ padding: '12px', background: 'var(--bg-surface)', borderRadius: '8px', cursor: 'pointer', transition: 'background 0.2s', border: '1px solid transparent' }}
                    onClick={() => navigate(`/recalls`)}
                    onMouseEnter={(e) => { e.currentTarget.style.borderColor = 'var(--glass-border)'; e.currentTarget.style.background = 'var(--bg-primary)'; }}
                    onMouseLeave={(e) => { e.currentTarget.style.borderColor = 'transparent'; e.currentTarget.style.background = 'var(--bg-surface)'; }}
                  >
                    <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', marginBottom: '6px' }}>
                      <h4 style={{ fontWeight: 500, fontSize: '0.9rem', color: 'var(--text-primary)', whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis', flex: 1, marginRight: '8px' }} title={r.product_name || r.firm_name}>
                        {r.product_name || r.firm_name || '未知廠商'}
                      </h4>
                      <span style={{ 
                        fontSize: '10px', padding: '2px 8px', borderRadius: '4px', fontWeight: 600, letterSpacing: '0.5px', textTransform: 'uppercase', flexShrink: 0,
                        background: r.classification === 'Class I' ? 'rgba(239, 68, 68, 0.2)' : r.classification === 'Class II' ? 'rgba(245, 158, 11, 0.2)' : 'rgba(16, 185, 129, 0.2)',
                        color: r.classification === 'Class I' ? 'var(--accent-red)' : r.classification === 'Class II' ? 'var(--accent-amber)' : 'var(--text-primary)'
                      }}>
                        {r.classification || 'Unknown'}
                      </span>
                    </div>
                    <p style={{ fontSize: '0.8rem', color: 'var(--text-secondary)', display: '-webkit-box', WebkitLineClamp: 2, WebkitBoxOrient: 'vertical', overflow: 'hidden', lineHeight: 1.5 }} title={r.reason || r.product_description}>
                      {r.reason || r.product_description || '無詳細說明'}
                    </p>
                  </div>
                ))}
              </div>
            )}
          </div>
        </div>

      </div>
    </div>
  );
}
