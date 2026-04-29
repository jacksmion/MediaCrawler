import React, { useState, useEffect, useRef } from 'react';
import {
  PlayIcon, StopIcon, PauseIcon, TrashIcon, PlusIcon,
  ArrowPathIcon, XMarkIcon, ChevronRightIcon,
} from '@heroicons/react/24/outline';

const PLATFORMS = [
  { id: 'dy', name: '抖音', color: 'text-emerald-500', bg: 'bg-emerald-500/10' },
  { id: 'xhs', name: '小红书', color: 'text-rose-500', bg: 'bg-rose-500/10' },
  { id: 'ks', name: '快手', color: 'text-orange-500', bg: 'bg-orange-500/10' },
  { id: 'bili', name: 'B站', color: 'text-pink-500', bg: 'bg-pink-500/10' },
  { id: 'wb', name: '微博', color: 'text-red-500', bg: 'bg-red-500/10' },
  { id: 'tieba', name: '贴吧', color: 'text-blue-500', bg: 'bg-blue-500/10' },
  { id: 'zhihu', name: '知乎', color: 'text-indigo-500', bg: 'bg-indigo-500/10' },
];

const CRAWLER_TYPES = [
  { id: 'search', name: '关键词搜索', key: 'keywords', placeholder: '例如: 露营, 户外装备' },
  { id: 'detail', name: '指定ID', key: 'specified_ids', placeholder: '视频ID, 多个用逗号分隔' },
  { id: 'creator', name: '博主主页', key: 'creator_ids', placeholder: '博主ID, 多个用逗号分隔' },
];

const API_BASE = `http://${window.location.hostname}:8080`;

export default function TaskCenter() {
  const [tasks, setTasks] = useState([]);
  const [selectedTaskId, setSelectedTaskId] = useState('');
  const [comments, setComments] = useState({ items: [], total: 0 });
  const [selectedComment, setSelectedComment] = useState(null);
  const [replies, setReplies] = useState([]);
  const [accounts, setAccounts] = useState([]);
  const [showCreate, setShowCreate] = useState(false);
  const [commentLoading, setCommentLoading] = useState(false);
  const [replyLoading, setReplyLoading] = useState(false);
  const [sourcesCache, setSourcesCache] = useState([]);
  const [form, setForm] = useState({
    name: '', platform: 'dy', account_id: '', crawler_type: 'search',
    mode: 'once', loop_interval_seconds: 60,
    keywords: '', specified_ids: '', creator_ids: '',
    enable_comments: true, comment_time_filter_h: 0, headless: true,
  });

  const pollRef = useRef(null);

  const fetchSources = async () => {
    if (sourcesCache.length > 0) return sourcesCache;
    try {
      const res = await fetch(`${API_BASE}/api/comments/sources`);
      const data = await res.json();
      const srcs = data.items || [];
      setSourcesCache(srcs);
      return srcs;
    } catch (e) { console.error(e); return []; }
  };

  const findSourceForTask = (task, sources) => {
    const cfg = task.config || {};
    // Detail mode: match by content_id
    if (cfg.specified_ids) {
      const firstId = cfg.specified_ids.split(',')[0].trim();
      return sources.find(s => s.platform_code === task.platform && s.platform_content_id === firstId);
    }
    // Search/creator mode: match by platform + title containing keywords
    if (cfg.keywords) {
      const kw = cfg.keywords.split(',')[0].trim().toLowerCase();
      return sources.find(s => s.platform_code === task.platform && (s.content_title || '').toLowerCase().includes(kw));
    }
    // Fallback: first source for this platform
    return sources.find(s => s.platform_code === task.platform);
  };

  // Fetch tasks
  const fetchTasks = async () => {
    try {
      const res = await fetch(`${API_BASE}/api/tasks`);
      const data = await res.json();
      setTasks(data.tasks || []);
    } catch (e) { console.error(e); }
  };

  // Fetch accounts for platform
  const fetchAccounts = async (platform) => {
    try {
      const res = await fetch(`${API_BASE}/api/account/list?platform=${platform}`);
      const data = await res.json();
      setAccounts(data.accounts || []);
      if (data.accounts?.length > 0) {
        setForm(f => ({ ...f, account_id: data.accounts[0].account_id }));
      }
    } catch (e) { console.error(e); }
  };

  useEffect(() => { fetchTasks(); }, []);

  // WebSocket status
  useEffect(() => {
    const ws = new WebSocket(`ws://${window.location.hostname}:8080/api/ws/status`);
    ws.onmessage = () => { fetchTasks(); };
    return () => ws.close();
  }, []);

  // Auto-poll comments for selected running loop task
  const selectedTaskStatus = tasks.find(t => t.task_id === selectedTaskId)?.status;
  const selectedTaskMode = tasks.find(t => t.task_id === selectedTaskId)?.mode;
  const selectedTaskInterval = tasks.find(t => t.task_id === selectedTaskId)?.loop_interval_seconds;

  useEffect(() => {
    if (pollRef.current) clearInterval(pollRef.current);
    if (selectedTaskMode === 'loop' && selectedTaskStatus === 'running') {
      pollRef.current = setInterval(() => loadComments(selectedTaskId), (selectedTaskInterval || 60) * 1000);
    }
    return () => { if (pollRef.current) clearInterval(pollRef.current); };
  }, [selectedTaskId, selectedTaskStatus, selectedTaskMode, selectedTaskInterval]);

  const loadComments = async (taskId) => {
    setCommentLoading(true);
    try {
      const task = tasks.find(t => t.task_id === taskId);
      if (!task) return;
      const sources = await fetchSources();
      const source = findSourceForTask(task, sources);
      if (!source) { setComments({ items: [], total: 0 }); setCommentLoading(false); return; }
      const res = await fetch(`${API_BASE}/api/comments?source_id=${encodeURIComponent(source.source_id)}&limit=50&sort=published_at_desc`);
      const data = await res.json();
      setComments(data);
    } catch (e) { console.error(e); }
    setCommentLoading(false);
  };

  const handleSelectTask = (taskId) => {
    setSelectedTaskId(taskId);
    setSelectedComment(null);
    loadComments(taskId);
  };

  const handleCreate = async () => {
    try {
      const res = await fetch(`${API_BASE}/api/tasks`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(form),
      });
      if (res.ok) {
        setShowCreate(false);
        fetchTasks();
      } else {
        const d = await res.json();
        alert('错误: ' + d.detail);
      }
    } catch (e) { console.error(e); alert('创建失败'); }
  };

  const handleAction = async (taskId, action) => {
    try {
      const res = await fetch(`${API_BASE}/api/tasks/${taskId}/${action}`, { method: 'POST' });
      if (!res.ok) { const d = await res.json(); alert(d.detail); }
      fetchTasks();
    } catch (e) { console.error(e); }
  };

  const handleDelete = async (taskId, name) => {
    if (!confirm(`确定删除任务「${name}」？`)) return;
    try {
      await fetch(`${API_BASE}/api/tasks/${taskId}`, { method: 'DELETE' });
      if (selectedTaskId === taskId) { setSelectedTaskId(''); setComments({ items: [], total: 0 }); }
      fetchTasks();
    } catch (e) { console.error(e); }
  };

  const loadReplies = async (comment) => {
    setReplyLoading(true);
    setSelectedComment(comment);
    try {
      const task = tasks.find(t => t.task_id === selectedTaskId);
      const sources = await fetchSources();
      const source = task ? findSourceForTask(task, sources) : null;
      if (source) {
        const res = await fetch(`${API_BASE}/api/comments?source_id=${encodeURIComponent(source.source_id)}&keyword=&comment_level=2&limit=50`);
        const data = await res.json();
        const commentId = comment.platform_comment_id || comment.comment_id;
        setReplies((data.items || []).filter(r => r.root_comment_id === commentId || r.parent_comment_id === commentId));
      }
    } catch (e) { console.error(e); setReplies([]); }
    setReplyLoading(false);
  };

  const getStatusBadge = (status) => {
    const map = {
      running: { color: 'bg-emerald-500', text: '运行中' },
      paused: { color: 'bg-amber-500', text: '已暂停' },
      completed: { color: 'bg-slate-600', text: '已完成' },
      error: { color: 'bg-red-500', text: '错误' },
      idle: { color: 'bg-slate-700', text: '待启动' },
    };
    const s = map[status] || map.idle;
    return <span className={`inline-flex items-center px-2 py-0.5 rounded-full text-[10px] font-bold text-white ${s.color}`}>{s.text}</span>;
  };

  const selectedTask = tasks.find(t => t.task_id === selectedTaskId);
  const crawlerType = CRAWLER_TYPES.find(c => c.id === form.crawler_type);

  return (
    <div className="flex h-full">
      {/* Left Panel - Task List */}
      <div className="w-80 shrink-0 border-r border-slate-800 flex flex-col">
        <div className="p-4 border-b border-slate-800 flex items-center justify-between">
          <h2 className="text-lg font-bold">任务中心</h2>
          <button onClick={() => { setShowCreate(true); fetchAccounts(form.platform); }}
            className="flex items-center space-x-1 px-3 py-1.5 bg-blue-600 hover:bg-blue-500 rounded-lg text-xs font-bold">
            <PlusIcon className="w-3.5 h-3.5" /><span>新建</span>
          </button>
        </div>
        <div className="flex-1 overflow-auto">
          {tasks.length === 0 && (
            <div className="p-6 text-center text-sm text-slate-600">暂无任务，点击「新建」创建第一个任务</div>
          )}
          {tasks.map(task => {
            const plat = PLATFORMS.find(p => p.id === task.platform) || PLATFORMS[0];
            return (
              <div key={task.task_id}
                onClick={() => handleSelectTask(task.task_id)}
                className={`p-4 border-b border-slate-800/50 cursor-pointer transition-colors ${selectedTaskId === task.task_id ? 'bg-slate-800/60' : 'hover:bg-slate-800/30'}`}>
                <div className="flex items-start justify-between">
                  <div className="flex-1 min-w-0">
                    <div className="flex items-center space-x-2">
                      <span className={`text-xs font-bold ${plat.color}`}>{plat.name}</span>
                      <span className="text-xs text-slate-500">{task.crawler_type === 'search' ? '搜索' : task.crawler_type === 'detail' ? '详情' : '博主'}</span>
                      {task.mode === 'loop' && <span className="text-[10px] text-slate-500">循环{task.loop_interval_seconds}s</span>}
                    </div>
                    <p className="text-sm font-medium mt-1 truncate">{task.name}</p>
                  </div>
                  {getStatusBadge(task.status)}
                </div>
                <div className="flex items-center justify-between mt-2">
                  <span className="text-[10px] text-slate-500">评论 {task.comment_count}</span>
                  <div className="flex items-center space-x-1">
                    {task.status === 'idle' || task.status === 'completed' || task.status === 'error' ? (
                      <button onClick={e => { e.stopPropagation(); handleAction(task.task_id, 'start'); }}
                        className="p-1 rounded hover:bg-emerald-900/30 text-emerald-400" title="启动">
                        <PlayIcon className="w-3.5 h-3.5" />
                      </button>
                    ) : task.status === 'running' && task.mode === 'loop' ? (
                      <button onClick={e => { e.stopPropagation(); handleAction(task.task_id, 'pause'); }}
                        className="p-1 rounded hover:bg-amber-900/30 text-amber-400" title="暂停">
                        <PauseIcon className="w-3.5 h-3.5" />
                      </button>
                    ) : null}
                    {task.status === 'running' && (
                      <button onClick={e => { e.stopPropagation(); handleAction(task.task_id, 'stop'); }}
                        className="p-1 rounded hover:bg-rose-900/30 text-rose-400" title="停止">
                        <StopIcon className="w-3.5 h-3.5" />
                      </button>
                    )}
                    {task.status === 'paused' && (
                      <button onClick={e => { e.stopPropagation(); handleAction(task.task_id, 'start'); }}
                        className="p-1 rounded hover:bg-emerald-900/30 text-emerald-400" title="恢复">
                        <PlayIcon className="w-3.5 h-3.5" />
                      </button>
                    )}
                    <button onClick={e => { e.stopPropagation(); handleDelete(task.task_id, task.name); }}
                      className="p-1 rounded hover:bg-rose-900/30 text-slate-500 hover:text-rose-400" title="删除">
                      <TrashIcon className="w-3.5 h-3.5" />
                    </button>
                  </div>
                </div>
              </div>
            );
          })}
        </div>
      </div>

      {/* Right Panel - Comments */}
      <div className="flex-1 flex flex-col min-w-0">
        {!selectedTask ? (
          <div className="flex-1 flex items-center justify-center text-slate-600 text-sm">选择左侧任务查看评论</div>
        ) : (
          <>
            <div className="p-4 border-b border-slate-800 flex items-center justify-between">
              <div>
                <h3 className="font-bold">{selectedTask.name}</h3>
                <p className="text-xs text-slate-500 mt-0.5">
                  共 {comments.total} 条评论
                  {selectedTask.mode === 'loop' && selectedTask.status === 'running' && ' · 自动刷新中'}
                </p>
              </div>
              <button onClick={() => loadComments(selectedTaskId)} disabled={commentLoading}
                className="p-2 rounded-lg hover:bg-slate-800 text-slate-400">
                <ArrowPathIcon className={`w-4 h-4 ${commentLoading ? 'animate-spin' : ''}`} />
              </button>
            </div>
            <div className="flex-1 overflow-auto">
              {comments.items.length === 0 ? (
                <div className="p-6 text-center text-sm text-slate-600">暂无评论数据</div>
              ) : (
                comments.items.map((c, i) => (
                  <div key={i}
                    onClick={() => loadReplies(c)}
                    className="px-6 py-3 border-b border-slate-800/30 hover:bg-slate-800/30 cursor-pointer transition-colors">
                    <div className="flex items-center space-x-2">
                      <span className="text-sm font-medium">{c.author_nickname || '匿名'}</span>
                      {c.ip_location && <span className="text-[10px] text-slate-600">IP: {c.ip_location}</span>}
                      <span className="text-[10px] text-slate-600 ml-auto">
                        {c.published_at ? new Date(c.published_at).toLocaleString() : ''}
                      </span>
                    </div>
                    <p className="text-sm text-slate-300 mt-1 line-clamp-2">{c.comment_text}</p>
                    <div className="flex items-center space-x-3 mt-1 text-[10px] text-slate-600">
                      <span>❤ {c.like_count || 0}</span>
                      <span>💬 {c.reply_count || 0}</span>
                      <ChevronRightIcon className="w-3 h-3 ml-auto text-slate-700" />
                    </div>
                  </div>
                ))
              )}
            </div>
          </>
        )}
      </div>

      {/* Comment Detail Drawer */}
      {selectedComment && (
        <div className="fixed inset-0 z-50 flex justify-end">
          <div className="absolute inset-0 bg-black/40" onClick={() => { setSelectedComment(null); setReplies([]); }} />
          <div className="relative w-full max-w-md bg-slate-900 border-l border-slate-700 flex flex-col">
            <div className="p-4 border-b border-slate-800 flex items-center justify-between">
              <h3 className="font-bold text-sm">评论详情</h3>
              <button onClick={() => { setSelectedComment(null); setReplies([]); }}
                className="p-1 rounded hover:bg-slate-800 text-slate-400">
                <XMarkIcon className="w-5 h-5" />
              </button>
            </div>
            <div className="flex-1 overflow-auto p-4 space-y-4">
              {/* Author info */}
              <div className="flex items-center space-x-3">
                <div className="w-10 h-10 rounded-full bg-slate-800 flex items-center justify-center text-lg">
                  {(selectedComment.author_nickname || '?')[0]}
                </div>
                <div>
                  <p className="font-bold text-sm">{selectedComment.author_nickname || '匿名'}</p>
                  <p className="text-xs text-slate-500">ID: {selectedComment.author_short_id || selectedComment.author_platform_id || '-'}</p>
                  {selectedComment.ip_location && <p className="text-xs text-slate-500">IP: {selectedComment.ip_location}</p>}
                </div>
              </div>
              {/* Comment text */}
              <p className="text-sm leading-relaxed">{selectedComment.comment_text}</p>
              <div className="flex items-center space-x-4 text-xs text-slate-500">
                <span>❤ {selectedComment.like_count || 0}</span>
                <span>💬 {selectedComment.reply_count || 0}</span>
                <span>{selectedComment.published_at ? new Date(selectedComment.published_at).toLocaleString() : ''}</span>
              </div>
              {/* Replies */}
              <div className="border-t border-slate-800 pt-3">
                <h4 className="text-xs font-bold text-slate-500 mb-3">回复 ({replies.length})</h4>
                {replyLoading ? (
                  <p className="text-xs text-slate-600">加载中...</p>
                ) : replies.length === 0 ? (
                  <p className="text-xs text-slate-600">暂无回复</p>
                ) : (
                  <div className="space-y-3">
                    {replies.map((r, i) => (
                      <div key={i} className="pl-3 border-l-2 border-slate-800">
                        <div className="flex items-center space-x-2">
                          <span className="text-xs font-medium">{r.author_nickname || '匿名'}</span>
                          <span className="text-[10px] text-slate-600">{r.published_at ? new Date(r.published_at).toLocaleString() : ''}</span>
                        </div>
                        <p className="text-xs text-slate-300 mt-0.5">{r.comment_text}</p>
                      </div>
                    ))}
                  </div>
                )}
              </div>
            </div>
          </div>
        </div>
      )}

      {/* Create Task Modal */}
      {showCreate && (
        <div className="fixed inset-0 z-50 flex items-center justify-center">
          <div className="absolute inset-0 bg-black/60" onClick={() => setShowCreate(false)} />
          <div className="relative bg-slate-900 border border-slate-700 rounded-2xl p-6 w-full max-w-lg space-y-4 max-h-[90vh] overflow-auto">
            <h3 className="text-lg font-bold">新建采集任务</h3>

            <div className="grid grid-cols-2 gap-4">
              <div>
                <label className="block text-xs text-slate-400 mb-1">平台</label>
                <select value={form.platform} onChange={e => { setForm(f => ({ ...f, platform: e.target.value, account_id: '' })); fetchAccounts(e.target.value); }}
                  className="w-full bg-slate-800 border border-slate-700 rounded-lg px-3 py-2 text-sm">
                  {PLATFORMS.map(p => <option key={p.id} value={p.id}>{p.name}</option>)}
                </select>
              </div>
              <div>
                <label className="block text-xs text-slate-400 mb-1">账号</label>
                <select value={form.account_id} onChange={e => setForm(f => ({ ...f, account_id: e.target.value }))}
                  className="w-full bg-slate-800 border border-slate-700 rounded-lg px-3 py-2 text-sm">
                  {accounts.length === 0 ? <option value="">暂无账号</option> : accounts.map(a => (
                    <option key={a.account_id} value={a.account_id}>{a.name} {a.status === 'active' ? '✓' : ''}</option>
                  ))}
                </select>
              </div>
            </div>

            <div>
              <label className="block text-xs text-slate-400 mb-1">任务名称</label>
              <input type="text" value={form.name} onChange={e => setForm(f => ({ ...f, name: e.target.value }))}
                placeholder="给任务起个名字" className="w-full bg-slate-800 border border-slate-700 rounded-lg px-3 py-2 text-sm placeholder-slate-600" />
            </div>

            <div>
              <label className="block text-xs text-slate-400 mb-1">采集类型</label>
              <div className="flex space-x-2">
                {CRAWLER_TYPES.map(ct => (
                  <button key={ct.id} onClick={() => setForm(f => ({ ...f, crawler_type: ct.id }))}
                    className={`flex-1 py-2 rounded-lg text-xs font-bold transition-all ${form.crawler_type === ct.id ? 'bg-blue-600/20 border-blue-500/50 text-blue-400 border' : 'bg-slate-800 border-slate-700 text-slate-400 border hover:border-slate-600'}`}>
                    {ct.name}
                  </button>
                ))}
              </div>
            </div>

            <div>
              <label className="block text-xs text-slate-400 mb-1">{crawlerType?.name || '关键词'}</label>
              <input type="text" value={form[crawlerType?.key || 'keywords']}
                onChange={e => setForm(f => ({ ...f, [crawlerType?.key || 'keywords']: e.target.value }))}
                placeholder={crawlerType?.placeholder} className="w-full bg-slate-800 border border-slate-700 rounded-lg px-3 py-2 text-sm placeholder-slate-600" />
            </div>

            <div>
              <label className="block text-xs text-slate-400 mb-2">执行模式</label>
              <div className="flex space-x-4">
                <label className="flex items-center space-x-2 cursor-pointer">
                  <input type="radio" name="mode" checked={form.mode === 'once'} onChange={() => setForm(f => ({ ...f, mode: 'once' }))} className="accent-blue-500" />
                  <span className="text-sm">单次执行</span>
                </label>
                <label className="flex items-center space-x-2 cursor-pointer">
                  <input type="radio" name="mode" checked={form.mode === 'loop'} onChange={() => setForm(f => ({ ...f, mode: 'loop' }))} className="accent-blue-500" />
                  <span className="text-sm">定时循环</span>
                </label>
                {form.mode === 'loop' && (
                  <div className="flex items-center space-x-1">
                    <input type="number" min="5" value={form.loop_interval_seconds}
                      onChange={e => setForm(f => ({ ...f, loop_interval_seconds: parseInt(e.target.value) || 60 }))}
                      className="w-16 bg-slate-800 border border-slate-700 rounded px-2 py-1 text-xs text-center" />
                    <span className="text-xs text-slate-500">秒</span>
                  </div>
                )}
              </div>
            </div>

            <div className="flex space-x-3 pt-2">
              <button onClick={() => setShowCreate(false)}
                className="flex-1 py-2.5 bg-slate-800 hover:bg-slate-700 rounded-lg text-sm font-medium">取消</button>
              <button onClick={handleCreate}
                className="flex-1 py-2.5 bg-blue-600 hover:bg-blue-500 rounded-lg text-sm font-bold">创建任务</button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
