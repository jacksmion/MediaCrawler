import React, { useCallback, useEffect, useState } from 'react';

import { COMMENT_LEVEL_OPTIONS, SORT_OPTIONS, formatDateTime, formatSourceTitle } from './commentViewerData';

const API_BASE = `http://${window.location.hostname}:8080/api/comments`;

export default function CommentViewer(props) {
  const {
    embedded = false,
    forcedContentId = '',
    forcedSourceId = '',
    hideSourceSummary = false,
    autoRefreshIntervalMs = 0,
  } = props;
  const [sources, setSources] = useState([]);
  const [selectedSourceId, setSelectedSourceId] = useState('');
  const [comments, setComments] = useState([]);
  const [keyword, setKeyword] = useState('');
  const [commentLevel, setCommentLevel] = useState('');
  const [location, setLocation] = useState('');
  const [sort, setSort] = useState('published_at_desc');
  const [sourceFilter, setSourceFilter] = useState('');
  const [loading, setLoading] = useState(true);
  const [commentsLoading, setCommentsLoading] = useState(false);
  const [error, setError] = useState('');

  useEffect(() => {
    const loadSources = async () => {
      setLoading(true);
      try {
        const response = await fetch(`${API_BASE}/sources`);
        if (!response.ok) {
          throw new Error('加载评论来源失败');
        }
        const body = await response.json();
        const items = body.items || [];
        setSources(items);
        if (forcedSourceId) {
          setSelectedSourceId(forcedSourceId);
        } else if (!forcedContentId) {
          setSelectedSourceId(items[0]?.source_id || '');
        }
        setError('');
      } catch (err) {
        setError(err instanceof Error ? err.message : '加载失败');
        setSources([]);
        setSelectedSourceId('');
      } finally {
        setLoading(false);
      }
    };

    loadSources();
  }, [forcedContentId, forcedSourceId]);

  useEffect(() => {
    if (forcedSourceId) {
      setSelectedSourceId(forcedSourceId);
      return;
    }
    if (!forcedContentId) return;
    const matched = sources.find((source) => String(source.platform_content_id) === String(forcedContentId));
    setSelectedSourceId(matched?.source_id || '');
  }, [forcedContentId, forcedSourceId, sources]);

  const loadComments = useCallback(async (options = {}) => {
    const { silent = false } = options;
    if (!selectedSourceId) {
      setComments([]);
      return;
    }
    const params = new URLSearchParams({
      source_id: selectedSourceId,
      limit: '50',
      offset: '0',
      sort,
    });
    if (keyword.trim()) params.set('keyword', keyword.trim());
    if (commentLevel) params.set('comment_level', commentLevel);
    if (location.trim()) params.set('location', location.trim());
    if (!silent) {
      setCommentsLoading(true);
    }
    try {
      const response = await fetch(`${API_BASE}?${params.toString()}`);
      if (!response.ok) {
        throw new Error('加载评论列表失败');
      }
      const body = await response.json();
      setComments(body.items || []);
      setError('');
    } catch (err) {
      if (!silent) {
        setComments([]);
      }
      setError(err instanceof Error ? err.message : '加载评论失败');
    } finally {
      if (!silent) {
        setCommentsLoading(false);
      }
    }
  }, [selectedSourceId, sort, keyword, commentLevel, location]);

  useEffect(() => {
    loadComments({ silent: false });
  }, [loadComments]);

  useEffect(() => {
    if (!autoRefreshIntervalMs || autoRefreshIntervalMs < 1000 || !selectedSourceId) {
      return undefined;
    }
    const timer = window.setInterval(() => {
      loadComments({ silent: true });
    }, autoRefreshIntervalMs);
    return () => window.clearInterval(timer);
  }, [autoRefreshIntervalMs, selectedSourceId, loadComments]);

  const visibleSources = sources.filter((source) => {
    if (forcedContentId && String(source.platform_content_id) !== String(forcedContentId)) {
      return false;
    }
    const needle = sourceFilter.trim().toLowerCase();
    if (!needle) return true;
    return (
      formatSourceTitle(source).toLowerCase().includes(needle) ||
      String(source.platform_content_id).toLowerCase().includes(needle)
    );
  });
  const selectedSource = sources.find((source) => source.source_id === selectedSourceId) || null;

  const hasForcedSelection = Boolean(forcedContentId || forcedSourceId);
  if (!loading && visibleSources.length === 0) {
    return (
      <div className={embedded ? 'h-full' : 'p-8'}>
        <div className="rounded-3xl border border-dashed border-slate-700 bg-slate-900/60 p-12 text-center text-slate-400">
          <div className="text-lg font-semibold text-slate-200">
            {hasForcedSelection ? '当前监控项还没有可展示的评论数据' : '暂未发现可查看的抖音评论数据'}
          </div>
          <div className="mt-2 text-sm text-slate-500">
            {hasForcedSelection ? '请先启动这个监控项并等待一次评论刷新完成。' : '请先完成一次抖音评论抓取，再回到这里查看评论。'}
          </div>
          {error ? <div className="mt-4 text-sm text-rose-400">{error}</div> : null}
        </div>
      </div>
    );
  }

  return (
    <div className={`h-full ${embedded ? '' : 'p-8'}`}>
      {!embedded ? (
      <div className="mb-6 flex items-end justify-between">
        <div>
          <h2 className="text-3xl font-black tracking-tight text-white">抖音评论查看</h2>
          <p className="mt-2 text-sm text-slate-500">先解决评论可视化查看，后续再平滑扩展成监控台与线索工作台。</p>
        </div>
        {error ? <div className="rounded-2xl border border-rose-900/60 bg-rose-950/30 px-4 py-3 text-sm text-rose-300">{error}</div> : null}
      </div>
      ) : null}

      <div className={`grid ${embedded ? 'h-full grid-cols-[minmax(0,1fr)]' : 'h-[calc(100%-88px)] grid-cols-[320px_minmax(0,1fr)]'} gap-6`}>
        {!embedded ? (
        <section className="flex min-h-0 flex-col overflow-hidden rounded-3xl border border-slate-800 bg-slate-900">
          <header className="border-b border-slate-800 px-5 py-4">
            <h3 className="text-lg font-bold text-white">评论来源</h3>
            <p className="mt-1 text-xs text-slate-500">当前仅接入抖音评论文件</p>
            <input
              type="text"
              value={sourceFilter}
              onChange={(event) => setSourceFilter(event.target.value)}
              placeholder="搜索作品 ID 或标题"
              className="mt-4 w-full rounded-2xl border border-slate-800 bg-slate-950 px-3 py-2 text-sm text-slate-200 outline-none transition focus:border-blue-500"
            />
          </header>
          <div className="flex-1 overflow-y-auto">
            {loading ? (
              <div className="p-5 text-sm text-slate-500">正在加载评论来源...</div>
            ) : visibleSources.length === 0 ? (
              <div className="p-5 text-sm text-slate-500">没有符合条件的评论来源。</div>
            ) : (
              visibleSources.map((source) => {
                const active = source.source_id === selectedSourceId;
                return (
                  <button
                    key={source.source_id}
                    onClick={() => setSelectedSourceId(source.source_id)}
                    className={`w-full border-b border-slate-800/80 px-5 py-4 text-left transition ${active ? 'bg-blue-600/10' : 'hover:bg-slate-800/40'}`}
                  >
                    <div className="truncate text-sm font-semibold text-slate-100">{formatSourceTitle(source)}</div>
                    <div className="mt-2 flex items-center justify-between text-xs text-slate-500">
                      <span>{source.comment_count} 条评论</span>
                      <span>{formatDateTime(source.latest_comment_at || source.updated_at * 1000)}</span>
                    </div>
                    <div className="mt-2 truncate text-[11px] text-slate-600">{source.platform_content_id}</div>
                  </button>
                );
              })
            )}
          </div>
        </section>
        ) : null}

        <section className="flex min-h-0 flex-col overflow-hidden rounded-3xl border border-slate-800 bg-slate-900">
          <header className="border-b border-slate-800 px-5 py-4">
            {selectedSource && !hideSourceSummary ? (
              <div className="mb-4 rounded-2xl border border-slate-800 bg-slate-950/70 px-4 py-3">
                <div className="text-xs font-bold uppercase tracking-wider text-slate-500">当前作品</div>
                <div className="mt-2 line-clamp-2 text-sm font-semibold text-slate-100">{formatSourceTitle(selectedSource)}</div>
                <div className="mt-2 flex flex-wrap items-center gap-x-4 gap-y-1 text-xs text-slate-500">
                  <span>作品 ID：{selectedSource.platform_content_id}</span>
                  <span>抖音号：{selectedSource.author_short_id || '-'}</span>
                  <span>评论数：{selectedSource.comment_count}</span>
                  <span>最新评论：{formatDateTime(selectedSource.latest_comment_at || selectedSource.updated_at)}</span>
                </div>
              </div>
            ) : embedded ? (
              <div className="mb-4 rounded-2xl border border-dashed border-slate-800 bg-slate-950/50 px-4 py-3 text-sm text-slate-500">
                正在为当前监控项匹配评论来源...
              </div>
            ) : null}
            <div className="grid grid-cols-[minmax(0,1fr)_120px_120px_120px] gap-2.5">
              <input
                type="text"
                value={keyword}
                onChange={(event) => setKeyword(event.target.value)}
                placeholder="搜索评论关键词"
                className="rounded-2xl border border-slate-800 bg-slate-950 px-3 py-2 text-sm text-slate-200 outline-none transition focus:border-blue-500"
              />
              <select
                value={commentLevel}
                onChange={(event) => setCommentLevel(event.target.value)}
                className="rounded-2xl border border-slate-800 bg-slate-950 px-3 py-2 text-sm text-slate-200 outline-none transition focus:border-blue-500"
              >
                {COMMENT_LEVEL_OPTIONS.map((option) => (
                  <option key={option.value || 'all'} value={option.value}>
                    {option.label}
                  </option>
                ))}
              </select>
              <input
                type="text"
                value={location}
                onChange={(event) => setLocation(event.target.value)}
                placeholder="地区/IP 属地"
                className="rounded-2xl border border-slate-800 bg-slate-950 px-3 py-2 text-sm text-slate-200 outline-none transition focus:border-blue-500"
              />
              <select
                value={sort}
                onChange={(event) => setSort(event.target.value)}
                className="rounded-2xl border border-slate-800 bg-slate-950 px-3 py-2 text-sm text-slate-200 outline-none transition focus:border-blue-500"
              >
                {SORT_OPTIONS.map((option) => (
                  <option key={option.value} value={option.value}>
                    {option.label}
                  </option>
                ))}
              </select>
            </div>
          </header>

          <div className="flex-1 overflow-auto">
            <table className="w-full min-w-[640px] border-collapse text-left text-sm">
              <thead className="sticky top-0 bg-slate-900 text-[11px] uppercase tracking-[0.18em] text-slate-500">
                <tr>
                  <th className="px-4 py-3">时间</th>
                  <th className="px-4 py-3">评论内容</th>
                  <th className="px-4 py-3">用户</th>
                  <th className="px-4 py-3">地区</th>
                  <th className="px-4 py-3">类型</th>
                  <th className="px-4 py-3 text-right">赞</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-800/70">
                {commentsLoading ? (
                  <tr>
                    <td colSpan="6" className="px-4 py-8 text-center text-slate-500">
                      正在加载评论列表...
                    </td>
                  </tr>
                ) : comments.length === 0 ? (
                  <tr>
                    <td colSpan="6" className="px-4 py-8 text-center text-slate-500">
                      当前筛选条件下没有评论。
                    </td>
                  </tr>
                ) : (
                  comments.map((comment) => (
                    <tr
                      key={comment.comment_id}
                      className="transition hover:bg-slate-800/40"
                    >
                      <td className="px-4 py-3 align-top whitespace-nowrap text-[13px] text-slate-400">{formatDateTime(comment.published_at)}</td>
                      <td className="px-4 py-3 align-top">
                        <div className="max-w-[520px] truncate text-[15px] font-medium leading-6 text-slate-100">{comment.comment_text || '-'}</div>
                      </td>
                      <td className="px-4 py-3 align-top">
                        <div className="max-w-[160px] truncate text-[14px] font-semibold text-slate-100">{comment.author_nickname || '-'}</div>
                        {comment.author_platform_id ? (
                          <a
                            href={`https://www.douyin.com/user/${comment.author_platform_id}`}
                            target="_blank"
                            rel="noreferrer"
                            onClick={(e) => e.stopPropagation()}
                            className="mt-1 block truncate font-mono text-[11px] text-slate-500 hover:text-blue-400 hover:underline"
                            title="访问抖音主页"
                          >
                            {comment.author_short_id || comment.author_platform_id}
                          </a>
                        ) : (
                          <div className="mt-1 truncate font-mono text-[11px] text-slate-500">
                            {comment.author_short_id || '-'}
                          </div>
                        )}
                      </td>
                      <td className="px-4 py-3 align-top text-[13px] text-slate-300">{comment.ip_location || '-'}</td>
                      <td className="px-4 py-3 align-top text-[13px] text-slate-300">
                        {comment.comment_level === 2 ? '回复' : '评论'}
                      </td>
                      <td className="px-4 py-3 align-top text-right text-[13px] font-semibold text-emerald-400">{comment.like_count}</td>
                    </tr>
                  ))
                )}
              </tbody>
            </table>
          </div>
        </section>
      </div>

    </div>
  );
}
