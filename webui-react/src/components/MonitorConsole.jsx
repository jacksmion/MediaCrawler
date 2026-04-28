import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';

import CommentViewer from './CommentViewer';
import { formatDateTime } from './commentViewerData';

const API_BASE = `http://${window.location.hostname}:8080/api/monitors`;

export default function MonitorConsole() {
  const [items, setItems] = useState([]);
  const [selectedId, setSelectedId] = useState('');
  const [logs, setLogs] = useState([]);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState('');
  const [logsOpen, setLogsOpen] = useState(false);
  const [form, setForm] = useState({
    contentUrl: '',
    refreshIntervalSeconds: '60',
  });
  const selectedIdRef = useRef('');

  const selectedItem = useMemo(
    () => items.find((item) => item.monitor_item_id === selectedId) || null,
    [items, selectedId],
  );
  const forcedSourceId = useMemo(
    () => (selectedItem ? `dy:${selectedItem.content_id}:platform_runtime\\raw\\douyin\\comments.jsonl` : ''),
    [selectedItem],
  );
  const selectedWorkUrl = useMemo(() => {
    if (!selectedItem) return '';
    const rawUrl = String(selectedItem.content_url || '').trim();
    if (rawUrl.startsWith('http://') || rawUrl.startsWith('https://')) {
      return rawUrl;
    }
    if (selectedItem.content_id) {
      return `https://www.douyin.com/video/${selectedItem.content_id}`;
    }
    return '';
  }, [selectedItem]);

  const loadItems = useCallback(async (preserveSelection = true) => {
    setLoading((current) => current && items.length === 0);
    try {
      const response = await fetch(API_BASE);
      if (!response.ok) throw new Error('加载监控项失败');
      const body = await response.json();
      const nextItems = body.items || [];
      setItems(nextItems);
      if (!preserveSelection || !nextItems.some((item) => item.monitor_item_id === selectedIdRef.current)) {
        setSelectedId(nextItems[0]?.monitor_item_id || '');
      }
      setError('');
    } catch (err) {
      setError(err instanceof Error ? err.message : '加载监控项失败');
      setItems([]);
      setSelectedId('');
    } finally {
      setLoading(false);
    }
  }, [items.length]);

  const loadLogs = useCallback(async (monitorItemId) => {
    if (!monitorItemId) {
      setLogs([]);
      return;
    }
    try {
      const response = await fetch(`${API_BASE}/${encodeURIComponent(monitorItemId)}/logs`);
      if (!response.ok) throw new Error('加载监控日志失败');
      const body = await response.json();
      setLogs(body.items || []);
    } catch (err) {
      setLogs([]);
      setError(err instanceof Error ? err.message : '加载监控日志失败');
    }
  }, []);

  useEffect(() => {
    selectedIdRef.current = selectedId;
  }, [selectedId]);

  useEffect(() => {
    loadItems(false);
    const timer = window.setInterval(() => loadItems(true), 15000);
    return () => window.clearInterval(timer);
  }, [loadItems]);

  useEffect(() => {
    loadLogs(selectedId);
    if (!selectedId) return undefined;
    const timer = window.setInterval(() => loadLogs(selectedId), 10000);
    return () => window.clearInterval(timer);
  }, [selectedId, loadLogs]);

  const handleCreate = async (event) => {
    event.preventDefault();
    setSaving(true);
    try {
      const response = await fetch(API_BASE, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          content_url: form.contentUrl.trim(),
          refresh_interval_seconds: Number(form.refreshIntervalSeconds || 60),
        }),
      });
      if (!response.ok) {
        const body = await response.json().catch(() => ({}));
        throw new Error(body.detail || '创建监控项失败');
      }
      const created = await response.json();
      setForm({ contentUrl: '', refreshIntervalSeconds: '60' });
      await loadItems(false);
      setSelectedId(created.monitor_item_id);
      await loadLogs(created.monitor_item_id);
      setError('');
    } catch (err) {
      setError(err instanceof Error ? err.message : '创建监控项失败');
    } finally {
      setSaving(false);
    }
  };

  const handleControl = async (action) => {
    if (!selectedItem) return;
    try {
      const response = await fetch(`${API_BASE}/${encodeURIComponent(selectedItem.monitor_item_id)}/${action}`, {
        method: 'POST',
      });
      if (!response.ok) throw new Error(action === 'start' ? '启动监控失败' : '停止监控失败');
      await loadItems(true);
      await loadLogs(selectedItem.monitor_item_id);
      setError('');
    } catch (err) {
      setError(err instanceof Error ? err.message : '操作失败');
    }
  };

  const handleOpenWork = () => {
    if (!selectedWorkUrl) return;
    window.open(selectedWorkUrl, '_blank', 'noopener,noreferrer');
  };

  return (
    <div className="h-full p-8">
      {error ? (
        <div className="mb-4 rounded-2xl border border-rose-900/60 bg-rose-950/30 px-4 py-3 text-sm text-rose-300">{error}</div>
      ) : null}

      <div className="grid h-full grid-cols-[320px_minmax(0,1fr)] gap-6">
        <section className="flex min-h-0 flex-col overflow-hidden rounded-3xl border border-slate-800 bg-slate-900">
          <header className="border-b border-slate-800 px-5 py-4">
            <h3 className="text-lg font-bold text-white">监控项</h3>
            <p className="mt-1 text-xs text-slate-500">每个监控项对应一个抖音作品</p>
          </header>
          <form onSubmit={handleCreate} className="space-y-3 border-b border-slate-800 px-5 py-4">
            <input
              type="text"
              value={form.contentUrl}
              onChange={(event) => setForm((current) => ({ ...current, contentUrl: event.target.value }))}
              placeholder="粘贴抖音作品链接"
              className="w-full rounded-2xl border border-slate-800 bg-slate-950 px-3 py-2 text-sm text-slate-200 outline-none transition focus:border-blue-500"
            />
            <div className="grid grid-cols-[96px_minmax(0,1fr)] gap-3">
              <input
                type="number"
                min="10"
                value={form.refreshIntervalSeconds}
                onChange={(event) => setForm((current) => ({ ...current, refreshIntervalSeconds: event.target.value }))}
                className="rounded-2xl border border-slate-800 bg-slate-950 px-3 py-2 text-sm text-slate-200 outline-none transition focus:border-blue-500"
              />
              <button
                type="submit"
                disabled={saving || !form.contentUrl.trim()}
                className="flex-1 rounded-2xl bg-blue-600 px-4 py-2 text-sm font-bold text-white transition hover:bg-blue-500 disabled:cursor-not-allowed disabled:bg-slate-700"
              >
                {saving ? '添加中...' : '新增监控'}
              </button>
            </div>
          </form>
          <div className="flex-1 overflow-y-auto">
            {loading ? (
              <div className="p-5 text-sm text-slate-500">正在加载监控项...</div>
            ) : items.length === 0 ? (
              <div className="p-5 text-sm text-slate-500">还没有监控项，先添加一个抖音作品。</div>
            ) : (
              items.map((item) => {
                const active = item.monitor_item_id === selectedId;
                return (
                  <button
                    key={item.monitor_item_id}
                    onClick={() => setSelectedId(item.monitor_item_id)}
                    className={`w-full border-b border-slate-800/80 px-5 py-4 text-left transition ${active ? 'bg-blue-600/10' : 'hover:bg-slate-800/40'}`}
                  >
                    <div className="line-clamp-2 text-sm font-semibold leading-6 text-slate-100">{item.title || `作品 ${item.content_id}`}</div>
                    <div className="mt-3 flex items-center justify-between text-xs text-slate-500">
                      <span className={`rounded-full px-2 py-1 ${item.status === 'running' ? 'bg-emerald-500/10 text-emerald-300' : 'bg-slate-800 text-slate-400'}`}>{item.status}</span>
                      <span>{item.refresh_interval_seconds}s</span>
                    </div>
                    <div className="mt-2 truncate text-[11px] text-slate-600">{item.content_id}</div>
                  </button>
                );
              })
            )}
          </div>
        </section>

        <section className="grid min-h-0 grid-rows-[auto_minmax(0,1fr)] gap-6">
          <header className="rounded-3xl border border-slate-800 bg-slate-900 px-5 py-4">
            {selectedItem ? (
              <div className="grid grid-cols-[minmax(0,1fr)_auto] items-start gap-6">
                <div className="min-w-0">
                  <div className="truncate text-lg font-bold text-white">{selectedItem.title || `作品 ${selectedItem.content_id}`}</div>
                  <div className="mt-3 flex flex-wrap gap-x-4 gap-y-2 text-xs text-slate-500">
                    <span>作品 ID：{selectedItem.content_id}</span>
                    <span>抖音号：{selectedItem.author_short_id || '-'}</span>
                    <span>刷新频率：{selectedItem.refresh_interval_seconds}s</span>
                    <span>最新评论抓取：{selectedItem.last_run_comment_count || 0}</span>
                    <span>最近成功：{formatDateTime(selectedItem.last_success_at)}</span>
                  </div>
                </div>
                <div className="flex gap-3">
                  <button
                    onClick={handleOpenWork}
                    disabled={!selectedWorkUrl}
                    className="rounded-2xl border border-slate-700 px-4 py-2.5 text-sm font-bold text-slate-200 transition hover:border-slate-600 hover:bg-slate-800/60 disabled:cursor-not-allowed disabled:border-slate-800 disabled:text-slate-500"
                  >
                    打开作品
                  </button>
                  <button
                    onClick={() => setLogsOpen(true)}
                    className="rounded-2xl border border-slate-700 px-4 py-2.5 text-sm font-bold text-slate-200 transition hover:border-slate-600 hover:bg-slate-800/60"
                  >
                    查看日志
                  </button>
                  <button
                    onClick={() => handleControl('start')}
                    className="rounded-2xl bg-emerald-600 px-5 py-2.5 text-sm font-bold text-white transition hover:bg-emerald-500"
                  >
                    启动
                  </button>
                  <button
                    onClick={() => handleControl('stop')}
                    className="rounded-2xl bg-slate-700 px-5 py-2.5 text-sm font-bold text-slate-100 transition hover:bg-slate-600"
                  >
                    停止
                  </button>
                </div>
              </div>
            ) : (
              <div className="text-sm text-slate-500">选择一个监控项后，这里会显示作品状态和控制按钮。</div>
            )}
          </header>

          <div className="min-h-0">
            <CommentViewer
              embedded
              forcedContentId={selectedItem?.content_id || ''}
              forcedSourceId={forcedSourceId}
              hideSourceSummary
              autoRefreshIntervalMs={selectedItem?.status === 'running' ? 10000 : 0}
            />
          </div>
        </section>
      </div>

      {logsOpen ? (
        <div className="absolute inset-0 z-30 flex justify-end bg-slate-950/55 backdrop-blur-sm">
          <div className="flex h-full w-[440px] flex-col border-l border-slate-800 bg-slate-900 shadow-2xl shadow-slate-950/50">
            <header className="flex items-start justify-between border-b border-slate-800 px-5 py-4">
              <div>
                <h3 className="text-xl font-bold text-white">运行日志</h3>
                <p className="mt-1 text-xs text-slate-500">
                  {selectedItem ? `${selectedItem.title || selectedItem.content_id}` : '选择监控项后查看日志'}
                </p>
              </div>
              <button
                onClick={() => setLogsOpen(false)}
                className="rounded-2xl border border-slate-700 px-3 py-2 text-xs font-bold text-slate-300 transition hover:border-slate-600 hover:text-slate-100"
              >
                关闭
              </button>
            </header>
            <div className="flex-1 overflow-y-auto px-5 py-4">
              {selectedItem ? (
                logs.length > 0 ? (
                  <div className="space-y-3 text-sm">
                    {logs.map((log) => (
                      <div key={log.event_id} className="rounded-2xl border border-slate-800 bg-slate-950/70 px-4 py-3">
                        <div className="flex items-center justify-between gap-3 text-xs text-slate-500">
                          <span>{log.level}</span>
                          <span>{formatDateTime(log.created_at)}</span>
                        </div>
                        <div className="mt-2 text-slate-200">{log.message}</div>
                      </div>
                    ))}
                  </div>
                ) : (
                  <div className="rounded-2xl border border-dashed border-slate-700 bg-slate-950/60 px-4 py-8 text-center text-sm text-slate-500">
                    当前监控项还没有运行日志。
                  </div>
                )
              ) : (
                <div className="rounded-2xl border border-dashed border-slate-700 bg-slate-950/60 px-4 py-8 text-center text-sm text-slate-500">
                  选择监控项后，这里会显示对应日志。
                </div>
              )}
            </div>
          </div>
        </div>
      ) : null}
    </div>
  );
}
