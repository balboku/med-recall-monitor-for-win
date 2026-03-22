import { useState } from 'react';
import { useQueryClient } from '@tanstack/react-query';
import { toast } from 'react-hot-toast';
import { api } from '../api';
import { RefreshCw, Check } from 'lucide-react';

export default function Header({ title, alertCount, onAlertsCleared }) {
  const [crawling, setCrawling] = useState(false);
  const queryClient = useQueryClient();

  const handleCrawlAll = async () => {
    if (crawling) return;
    setCrawling(true);
    try {
      await api.triggerCrawl('all');
      toast.success('已在背景佇列啟動所有爬蟲');
      queryClient.invalidateQueries({ queryKey: ['crawlLogs'] });
      queryClient.invalidateQueries({ queryKey: ['health'] });
    } catch (e) {
      toast.error(`啟動失敗: ${e.message}`);
    } finally {
      setCrawling(false);
    }
  };

  const handleMarkAllRead = async () => {
    try {
      await api.markAllAlertsRead();
      toast.success('已將所有告警標記為已讀');
      queryClient.invalidateQueries({ queryKey: ['alerts'] });
      queryClient.invalidateQueries({ queryKey: ['dashboard'] });
      onAlertsCleared?.();
    } catch (e) {
      toast.error(e.message || '標記已讀失敗');
    }
  };

  return (
    <header className="header">
      <h2 className="header-title">{title}</h2>
      <div className="header-actions">
        <button
          className="btn btn-secondary btn-sm"
          onClick={handleCrawlAll}
          disabled={crawling}
          title="手動觸發所有爬蟲"
        >
          {crawling ? (
            <><RefreshCw size={14} className="spinner" /> 爬取中...</>
          ) : (
            <><RefreshCw size={14} /> 立即爬取</>
          )}
        </button>

        {alertCount > 0 && (
          <button className="btn btn-ghost btn-sm" onClick={handleMarkAllRead}>
            <Check size={14} /> 全部已讀 ({alertCount})
          </button>
        )}
      </div>
    </header>
  );
}
