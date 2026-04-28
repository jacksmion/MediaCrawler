import React, { useEffect, useState } from 'react';

import { COMMENT_LEVEL_OPTIONS, SORT_OPTIONS, formatDateTime, formatSourceTitle } from './commentViewerData';

const API_BASE = `http://${window.location.hostname}:8080/api/comments`;

export default function CommentViewer() {
  const [sources, setSources] = useState([]);
  const [selectedSourceId, setSelectedSourceId] = useState('');
  const [comments, setComments] = useState([]);
  const [selectedComment, setSelectedComment] = useState(null);
  const [keyword, setKeyword] = useState('');
  const [commentLevel, setCommentLevel] = useState('');
  const [location, setLocation] = useState('');
  const [sort, setSort] = useState('published_at_desc');
  const [sourceFilter, setSourceFilter] = useState('');
  const [loading, setLoading] = useState(true);
  const [commentsLoading, setCommentsLoading] = useState(false);
  const [detailLoading, setDetailLoading] = useState(false);
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
        setSelectedSourceId(items[0]?.source_id || '');
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
  }, []);

  useEffect(() => {
    if (!selectedSourceId) {
      setComments([]);
      setSelectedComment(null);
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

    const loadComments = async () => {
      setCommentsLoading(true);
      try {
        const response = await fetch(`${API_BASE}?${params.toString()}`);
        if (!response.ok) {
          throw new Error('加载评论列表失败');
        }
        const body = await response.json();
        setComments(body.items || []);
        setSelectedComment(null);
        setError('');
      } catch (err) {
        setComments([]);
        setSelectedComment(null);
        setError(err instanceof Error ? err.message : '加载评论失败');
      } finally {
        setCommentsLoading(false);
      }
    };

    loadComments();
  }, [selectedSourceId, keyword, commentLevel, location, sort]);

  const handleSelectComment = async (commentId) => {
    const params = new URLSearchParams({ source_id: selectedSourceId });
    setDetailLoading(true);
    try {
      const response = await fetch(`${API_BASE}/${encodeURIComponent(commentId)}?${params.toString()}`);
      if (!response.ok) {
        throw new Error('加载评论详情失败');
      }
      const body = await response.json();
      setSelectedComment(body);
      setError('');
    } catch (err) {
      setSelectedComment(null);
      setError(err instanceof Error ? err.message : '加载详情失败');
    } finally {
      setDetailLoading(false);
    }
  };

  const visibleSources = sources.filter((source) => {
    const needle = sourceFilter.trim().toLowerCase();
    if (!needle) return true;
    return (
      formatSourceTitle(source).toLowerCase().includes(needle) ||
      String(source.platform_content_id).toLowerCase().includes(needle)
    );
  });

  if (!loading && sources.length === 0) {
    return (
      <div className="p-8">
        <div className="rounded-3xl border border-dashed border-slate-700 bg-slate-900/60 p-12 text-center text-slate-400">
          <div className="text-lg font-semibold text-slate-200">暂未发现可查看的抖音评论数据</div>
          <div className="mt-2 text-sm text-slate-500">请先完成一次抖音评论抓取，再回到这里查看评论。</div>
          {error ? <div className="mt-4 text-sm text-rose-400">{error}</div> : null}
        </div>
      </div>
    );
  }

  return (
    <div className="h-full p-8">
      <div className="mb-6 flex items-end justify-between">
        <div>
          <h2 className="text-3xl font-black tracking-tight text-white">抖音评论查看</h2>
          <p className="mt-2 text-sm text-slate-500">先解决评论可视化查看，后续再平滑扩展成监控台与线索工作台。</p>
        </div>
        {error ? <div className="rounded-2xl border border-rose-900/60 bg-rose-950/30 px-4 py-3 text-sm text-rose-300">{error}</div> : null}
      </div>

      <div className="grid h-[calc(100%-88px)] grid-cols-[320px_minmax(0,1fr)_360px] gap-6">
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

        <section className="flex min-h-0 flex-col overflow-hidden rounded-3xl border border-slate-800 bg-slate-900">
          <header className="border-b border-slate-800 px-5 py-4">
            <div className="grid grid-cols-[minmax(0,1fr)_140px_140px_120px] gap-3">
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
            <table className="w-full min-w-[880px] border-collapse text-left text-sm">
              <thead className="sticky top-0 bg-slate-900 text-[11px] uppercase tracking-wider text-slate-500">
                <tr>
                  <th className="px-5 py-4">时间</th>
                  <th className="px-5 py-4">评论内容</th>
                  <th className="px-5 py-4">昵称</th>
                  <th className="px-5 py-4">用户 ID</th>
                  <th className="px-5 py-4">地区</th>
                  <th className="px-5 py-4">层级</th>
                  <th className="px-5 py-4">回复对象</th>
                  <th className="px-5 py-4 text-right">点赞</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-800/70">
                {commentsLoading ? (
                  <tr>
                    <td colSpan="8" className="px-5 py-8 text-center text-slate-500">
                      正在加载评论列表...
                    </td>
                  </tr>
                ) : comments.length === 0 ? (
                  <tr>
                    <td colSpan="8" className="px-5 py-8 text-center text-slate-500">
                      当前筛选条件下没有评论。
                    </td>
                  </tr>
                ) : (
                  comments.map((comment) => (
                    <tr
                      key={comment.comment_id}
                      onClick={() => handleSelectComment(comment.comment_id)}
                      className="cursor-pointer transition hover:bg-slate-800/40"
                    >
                      <td className="px-5 py-4 whitespace-nowrap text-slate-400">{formatDateTime(comment.published_at)}</td>
                      <td className="px-5 py-4">
                        <div className="max-w-[340px] truncate text-slate-100">{comment.comment_text || '-'}</div>
                      </td>
                      <td className="px-5 py-4 text-slate-200">{comment.author_nickname || '-'}</td>
                      <td className="px-5 py-4 font-mono text-xs text-slate-500">{comment.author_platform_id || '-'}</td>
                      <td className="px-5 py-4 text-slate-300">{comment.ip_location || '-'}</td>
                      <td className="px-5 py-4 text-slate-300">{comment.comment_level === 2 ? '二级回复' : '一级评论'}</td>
                      <td className="px-5 py-4 font-mono text-xs text-slate-500">{comment.parent_comment_id || '-'}</td>
                      <td className="px-5 py-4 text-right font-semibold text-emerald-400">{comment.like_count}</td>
                    </tr>
                  ))
                )}
              </tbody>
            </table>
          </div>
        </section>

        <section className="flex min-h-0 flex-col overflow-hidden rounded-3xl border border-slate-800 bg-slate-900">
          <header className="border-b border-slate-800 px-5 py-4">
            <h3 className="text-lg font-bold text-white">评论详情</h3>
            <p className="mt-1 text-xs text-slate-500">支持回看完整评论文本与原始 payload</p>
          </header>
          <div className="flex-1 overflow-y-auto px-5 py-4">
            {detailLoading ? (
              <div className="text-sm text-slate-500">正在加载评论详情...</div>
            ) : selectedComment ? (
              <div className="space-y-5">
                <DetailBlock label="评论正文" value={selectedComment.comment_text || '-'} />
                <DetailGrid
                  items={[
                    ['评论 ID', selectedComment.platform_comment_id || '-'],
                    ['作品 ID', selectedComment.platform_content_id || '-'],
                    ['用户昵称', selectedComment.author_nickname || '-'],
                    ['用户 ID', selectedComment.author_platform_id || '-'],
                    ['IP 属地', selectedComment.ip_location || '-'],
                    ['主页地区', selectedComment.author_home_location || '-'],
                    ['评论层级', selectedComment.comment_level === 2 ? '二级回复' : '一级评论'],
                    ['父评论', selectedComment.parent_comment_id || '-'],
                    ['根评论', selectedComment.root_comment_id || '-'],
                    ['发布时间', formatDateTime(selectedComment.published_at)],
                    ['点赞数', String(selectedComment.like_count ?? 0)],
                    ['回复数', String(selectedComment.reply_count ?? 0)],
                  ]}
                />
                <DetailBlock label="Metadata" value={JSON.stringify(selectedComment.metadata || {}, null, 2)} monospace />
                <DetailBlock label="Raw Payload" value={JSON.stringify(selectedComment.raw_payload || {}, null, 2)} monospace />
              </div>
            ) : (
              <div className="rounded-2xl border border-dashed border-slate-700 bg-slate-950/60 px-4 py-8 text-center text-sm text-slate-500">
                选择一条评论后，这里会展示完整详情。
              </div>
            )}
          </div>
        </section>
      </div>
    </div>
  );
}

function DetailBlock({ label, value, monospace = false }) {
  return (
    <div>
      <div className="mb-2 text-xs font-bold uppercase tracking-wider text-slate-500">{label}</div>
      <pre
        className={`overflow-x-auto rounded-2xl border border-slate-800 bg-slate-950/80 p-4 text-sm whitespace-pre-wrap break-words ${
          monospace ? 'font-mono text-slate-300' : 'text-slate-100'
        }`}
      >
        {value}
      </pre>
    </div>
  );
}

function DetailGrid({ items }) {
  return (
    <div className="grid grid-cols-2 gap-3">
      {items.map(([label, value]) => (
        <div key={label} className="rounded-2xl border border-slate-800 bg-slate-950/80 p-4">
          <div className="text-[11px] font-bold uppercase tracking-wider text-slate-500">{label}</div>
          <div className="mt-2 break-all text-sm text-slate-100">{value}</div>
        </div>
      ))}
    </div>
  );
}
