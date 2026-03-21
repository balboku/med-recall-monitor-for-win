import { useState, useEffect } from 'react';
import { useNavigate } from 'react-router-dom';
import { api } from '../api';

export default function Dashboard({ onUpdate }) {
  const navigate = useNavigate();
  const [stats, setStats] = useState(null);
  const [alerts, setAlerts] = useState([]);
  const [mrmSummary, setMrmSummary] = useState(null);
  const [trend, setTrend] = useState(null);
  const [loading, setLoading] = useState(true);

  const fetchData = async () => {
    try {
      const [dashData, alertData, mrmData, trendData] = await Promise.all([
        api.getDashboard(),
        api.getAlerts({ page_size: 10 }),
        api.getMrmSummary(),
        api.getTrend('6months')
      ]);
      setStats(dashData);
      setAlerts(alertData.items || []);
      setMrmSummary(mrmData);
      setTrend(trendData);
    } catch (e) {
      console.error(e);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => { fetchData(); }, []);

  const handleMarkRead = async (id) => {
    await api.markAlertRead(id);
    fetchData();
    onUpdate?.();
  };

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
    <div className="animate-fade-in space-y-6 pb-12">
      <div className="flex justify-between items-end mb-4">
        <div>
          <h1 className="text-2xl font-bold text-text-primary">品保監控戰情室 (QA Dashboard)</h1>
          <p className="text-sm text-text-secondary mt-1">針對高風險異常、召回趨勢進行管理與跨域分析</p>
        </div>
        <div className="text-xs text-text-muted bg-surface-200 px-3 py-1 rounded">
          報表月份: {mrmSummary?.reporting_month || '未指定'}
        </div>
      </div>

      {/* KPI 卡片 (紅綠燈) */}
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
        {statCards.map((s) => (
          <div key={s.label} className={`card p-4 border-l-4 ${s.color === 'red' ? 'border-status-danger bg-red-900/10' : s.color === 'amber' ? 'border-status-warning bg-yellow-900/10' : s.color === 'green' ? 'border-status-success' : 'border-primary-500'}`}>
            <div className="flex justify-between items-start">
              <div>
                <div className="text-sm text-text-secondary font-medium">{s.label}</div>
                <div className={`text-3xl font-bold mt-2 ${s.color === 'red' ? 'text-status-danger' : s.color === 'amber' ? 'text-status-warning' : 'text-text-primary'}`}>
                  {s.value}
                </div>
              </div>
              <div className="text-2xl opacity-80">{s.icon}</div>
            </div>
            {s.sub && <div className="text-xs mt-2 opacity-70 font-medium tracking-wide">{s.sub}</div>}
          </div>
        ))}
      </div>

      {/* 圖表區: 趨勢 + 佔比 */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        
        {/* 近期不良事件與召回趨勢 */}
        <div className="lg:col-span-2 card">
          <div className="flex justify-between items-center mb-6">
            <h2 className="text-lg font-semibold text-text-primary flex items-center">
              <span className="mr-2">📈</span>綜合趨勢 (事件 vs 召回)
            </h2>
            <div className="flex gap-4 text-xs font-medium">
              <div className="flex items-center gap-1"><span className="w-3 h-3 bg-blue-500 rounded-sm"></span> 召回數</div>
              <div className="flex items-center gap-1"><span className="w-3 h-3 bg-red-500 rounded-sm"></span> 不良事件</div>
            </div>
          </div>
          <div className="flex items-end h-[240px] gap-2 border-b border-border-color pb-2 relative pl-8">
            {/* Y軸簡易標記 */}
            <div className="absolute left-0 top-0 bottom-8 w-8 flex flex-col justify-between text-[10px] text-text-muted">
              <span>{maxTrendVal}</span>
              <span>{Math.floor(maxTrendVal/2)}</span>
              <span>0</span>
            </div>
            {mergedTrend.map(d => (
              <div 
                key={d.month} 
                className="flex flex-col items-center flex-1 h-full cursor-pointer hover:bg-surface-200/50 rounded transition-colors group relative"
                onClick={() => navigate(`/events?month=${d.month}`)}
              >
                {/* 預設隱藏的提示框 */}
                <div className="absolute -top-10 bg-surface-300 text-text-primary text-xs p-2 rounded opacity-0 group-hover:opacity-100 transition-opacity z-10 pointer-events-none whitespace-nowrap shadow-lg">
                  {d.month} <br/> 召回: {d.recalls} | 事件: {d.events}
                </div>
                
                <div className="flex items-end gap-1 h-full w-full justify-center pb-1">
                  <div className="bg-blue-500 w-[35%] rounded-t transition-all duration-500 hover:brightness-110" style={{ height: `${Math.max((d.recalls/maxTrendVal)*100, 2)}%`}} />
                  <div className="bg-red-500 w-[35%] rounded-t transition-all duration-500 hover:brightness-110" style={{ height: `${Math.max((d.events/maxTrendVal)*100, 2)}%`}} />
                </div>
              </div>
            ))}
          </div>
          <div className="flex gap-2 pl-8 mt-2">
            {mergedTrend.map(d => (
              <div key={`lbl-${d.month}`} className="flex-1 text-center text-[10px] text-text-secondary truncate">
                {d.month.substring(2)}
              </div>
            ))}
          </div>
        </div>

        {/* 嚴重度分佈 (Stacked Bar / Area) */}
        <div className="card flex flex-col">
          <h2 className="text-lg font-semibold text-text-primary mb-6 flex items-center">
            <span className="mr-2">📊</span>事件嚴重度佔比
          </h2>
          <div className="flex-1 flex flex-col justify-center">
            {severityPieData.length > 0 ? (
              <>
                <div className="w-full flex h-8 rounded-full overflow-hidden mb-6 shadow-inner ring-1 ring-border-color">
                  {severityPieData.map((d, idx) => (
                    <div 
                      key={d.name} 
                      style={{ width: `${(d.value/totalSeverity)*100}%`, backgroundColor: colorMap[idx % colorMap.length] }} 
                      title={`${d.name}: ${d.value}`}
                      className="h-full border-r border-surface-100 last:border-0 hover:brightness-110 transition-all cursor-help"
                    />
                  ))}
                </div>
                <div className="grid grid-cols-1 gap-3">
                  {severityPieData.map((d, idx) => (
                    <div key={d.name} className="flex items-center justify-between text-sm p-2 rounded hover:bg-surface-200 transition-colors">
                      <div className="flex items-center gap-2">
                        <span className="w-3 h-3 rounded-full" style={{ backgroundColor: colorMap[idx % colorMap.length] }}></span>
                        <span className="text-text-primary font-medium">{d.name}</span>
                      </div>
                      <div className="flex items-center gap-3">
                        <span className="text-text-secondary text-xs">{((d.value/totalSeverity)*100).toFixed(1)}%</span>
                        <span className="font-bold w-8 text-right">{d.value}</span>
                      </div>
                    </div>
                  ))}
                </div>
              </>
            ) : (
              <div className="text-center text-text-muted mt-8">本期無不良事件資料</div>
            )}
          </div>
        </div>

      </div>

      {/* 排行與動態列表 */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        
        {/* 高風險失效產品型號 (Bar Chart) */}
        <div className="card">
          <h2 className="text-lg font-semibold text-text-primary mb-6 flex items-center">
            <span className="mr-2">🏆</span>高頻召回產品排名 (Top Risk)
          </h2>
          <div className="flex flex-col gap-4">
            {trend?.product_ranking?.length > 0 ? (
              trend.product_ranking.slice(0, 5).map(r => {
                const maxRecall = Math.max(...trend.product_ranking.map(x => x.recall_count), 1);
                return (
                  <div key={r.product_name} className="group cursor-pointer">
                    <div className="flex justify-between text-sm mb-1.5 font-medium">
                      <span className="truncate w-3/4 text-text-primary group-hover:text-primary-400 transition-colors">{r.product_name}</span>
                      <span className="text-text-secondary"><span className="font-bold text-text-primary">{r.recall_count}</span> 件</span>
                    </div>
                    <div className="w-full bg-surface-300 h-2.5 rounded-full overflow-hidden shadow-inner">
                      <div className="h-full rounded-full transition-all duration-700 bg-purple-500" style={{ width: `${(r.recall_count/maxRecall)*100}%`}} />
                    </div>
                  </div>
                );
              })
            ) : (
              <div className="flex h-32 items-center justify-center text-text-muted">尚無足夠召回數據進行排行</div>
            )}
          </div>
        </div>

        {/* 最新召回清單 */}
        <div className="card flex flex-col h-[350px]">
          <div className="flex justify-between items-center mb-4 border-b border-border-color pb-3">
            <h2 className="text-lg font-semibold text-text-primary flex items-center">
              <span className="mr-2">🔔</span>最新召回動態
            </h2>
            <button className="text-sm font-medium text-primary-400 hover:text-primary-300 transition-colors" onClick={() => navigate('/recalls')}>查看全部 &rarr;</button>
          </div>
          <div className="flex-1 overflow-y-auto pr-1">
            {(stats?.latest_recalls?.length ?? 0) === 0 ? (
              <div className="h-full flex items-center justify-center text-text-muted">尚無召回記錄</div>
            ) : (
              <div className="space-y-3">
                {stats.latest_recalls.map((r) => (
                  <div key={r.id} className="p-3 bg-surface-200 rounded-lg hover:bg-surface-300 transition-colors cursor-pointer border border-transparent hover:border-surface-300" onClick={() => navigate(`/recalls`)}>
                    <div className="flex justify-between items-start mb-1.5">
                      <h4 className="font-medium text-text-primary text-sm truncate mr-2 flex-1" title={r.product_name || r.firm_name}>{r.product_name || r.firm_name || '未知廠商'}</h4>
                      <span className={`text-[10px] px-2 py-0.5 rounded flex-shrink-0 font-bold tracking-wide uppercase ${r.classification === 'Class I' ? 'bg-status-danger/20 text-status-danger' : r.classification === 'Class II' ? 'bg-status-warning/20 text-status-warning' : 'bg-status-success/20 text-status-success'}`}>
                        {r.classification || 'Unknown'}
                      </span>
                    </div>
                    <p className="text-xs text-text-secondary line-clamp-2 leading-relaxed" title={r.reason || r.product_description}>
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
