import { useState } from 'react';
import { api } from '../api';

export default function Header({ title, alertCount, onAlertsCleared }) {
  const [crawling, setCrawling] = useState(false);

  const handleCrawlAll = async () => {
    if (crawling) return;
    setCrawling(true);
    try {
      await api.triggerCrawl('all');
    } catch (e) {
      console.error('Crawl failed:', e);
    } finally {
      setCrawling(false);
    }
  };

  const handleMarkAllRead = async () => {
    try {
      await api.markAllAlertsRead();
      onAlertsCleared?.();
    } catch (e) {
      console.error(e);
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
            <><span className="spinner" style={{ width: 14, height: 14 }}></span> 爬取中...</>
          ) : (
            <>🔄 立即爬取</>
          )}
        </button>

        {alertCount > 0 && (
          <button className="btn btn-ghost btn-sm" onClick={handleMarkAllRead}>
            ✓ 全部已讀 ({alertCount})
          </button>
        )}
      </div>
    </header>
  );
}
