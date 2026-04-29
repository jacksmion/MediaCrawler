# Task Logging Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add key-step-level logging to tasks with per-task filtering, and display logs in a new tab in the TaskCenter UI.

**Architecture:** Add `task_id` to `LogEntry` schema so the frontend can filter WebSocket logs by selected task. Add detailed log points in `task_manager.py`'s `_run_once` method. The frontend adds a "评论/日志" tab switcher, fetches history via REST API, and receives real-time logs via the existing WebSocket.

**Tech Stack:** Python/FastAPI (backend), React with hooks (frontend), WebSocket (real-time log stream)

---

### Task 1: Add task_id to LogEntry schema

**Files:**
- Modify: `api/schemas/crawler.py:102-108`

- [ ] **Step 1: Add task_id field to LogEntry**

```python
class LogEntry(BaseModel):
    """Log entry"""
    id: int
    task_id: str = ""
    timestamp: str
    level: Literal["info", "warning", "error", "success", "debug"]
    message: str
```

- [ ] **Step 2: Commit**

```bash
git add api/schemas/crawler.py
git commit -m "feat: add task_id field to LogEntry schema"
```

---

### Task 2: Pass task_id through CrawlerLogService

**Files:**
- Modify: `api/services/crawler_log_service.py:43-55`

- [ ] **Step 1: Update create_entry to accept and store task_id**

Replace the `create_entry` method:

```python
def create_entry(self, message: str, level: str = "info", task_id: str = "") -> LogEntry:
    """Create and persist a log entry in the in-memory buffer."""
    self._log_id += 1
    entry = LogEntry(
        id=self._log_id,
        task_id=task_id,
        timestamp=datetime.now().strftime("%H:%M:%S"),
        level=level,
        message=message,
    )
    self._logs.append(entry)
    if len(self._logs) > self.max_logs:
        self._logs = self._logs[-self.max_logs:]
    return entry
```

- [ ] **Step 2: Commit**

```bash
git add api/services/crawler_log_service.py
git commit -m "feat: pass task_id through CrawlerLogService.create_entry"
```

---

### Task 3: Add task_id to log calls in ApiLogHandler

**Files:**
- Modify: `api/services/task_manager.py:36-51`

- [ ] **Step 1: Update ApiLogHandler.emit to pass task_id**

The `ApiLogHandler` already stores `self.task_id`. Pass it to `create_entry`:

```python
class ApiLogHandler(logging.Handler):
    def __init__(self, log_service: CrawlerLogService, task_id: str) -> None:
        super().__init__(level=logging.INFO)
        self.log_service = log_service
        self.task_id = task_id
        self.setFormatter(logging.Formatter(f"[{task_id}] %(message)s"))

    def emit(self, record: logging.LogRecord) -> None:
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return
        message = self.format(record)
        level = self.log_service.parse_level(record.levelname)
        entry = self.log_service.create_entry(message, level, task_id=self.task_id)
        loop.call_soon_threadsafe(lambda: asyncio.ensure_future(self.log_service.push(entry), loop=loop))
```

- [ ] **Step 2: Commit**

```bash
git add api/services/task_manager.py
git commit -m "feat: pass task_id in ApiLogHandler.emit"
```

---

### Task 4: Add key-step log points in _run_once

**Files:**
- Modify: `api/services/task_manager.py:284-349`

- [ ] **Step 1: Add detailed log calls in _run_once**

The `_run_once` method currently logs only start and completion. Add intermediate key-step logs. Replace the entire `_run_once` method:

```python
async def _run_once(self, rt: TaskRuntime, item: dict) -> dict[str, Any]:
    task_id = rt.task_id
    log_service = self._log_services.get(task_id, CrawlerLogService())
    crawler = None
    api_log_handler = ApiLogHandler(log_service, task_id)
    logger = logging.getLogger("MediaCrawler")

    try:
        logger.addHandler(api_log_handler)
        await log_service.push(log_service.create_entry(
            f"开始采集: 平台={rt.platform}, 类型={rt.crawler_type}",
            "info", task_id=task_id,
        ))

        config = item.get("config", {})
        keywords = config.get("keywords", "")
        specified_ids = config.get("specified_ids", "")

        if rt.crawler_type == "search" and keywords:
            kw_list = [k.strip() for k in keywords.split(",") if k.strip()]
            await log_service.push(log_service.create_entry(
                f"开始搜索关键词: {', '.join(kw_list)}",
                "info", task_id=task_id,
            ))
        elif rt.crawler_type == "detail" and specified_ids:
            id_list = [i.strip() for i in specified_ids.split(",") if i.strip()]
            await log_service.push(log_service.create_entry(
                f"开始采集详情，共 {len(id_list)} 个内容",
                "info", task_id=task_id,
            ))
        elif rt.crawler_type == "creator":
            creator_ids = config.get("creator_ids", "")
            id_list = [i.strip() for i in creator_ids.split(",") if i.strip()]
            await log_service.push(log_service.create_entry(
                f"开始采集博主主页，共 {len(id_list)} 个博主",
                "info", task_id=task_id,
            ))

        crawler = CrawlerFactory.create_crawler(platform=rt.platform)
        if hasattr(crawler, "account_id"):
            crawler.account_id = rt.account_id

        payload = {
            "platform": rt.platform,
            "crawler_type": rt.crawler_type,
            "keywords": config.get("keywords", ""),
            "specified_ids": config.get("specified_ids", ""),
            "creator_ids": config.get("creator_ids", ""),
            "sort_type": config.get("sort_type", ""),
            "enable_comments": config.get("enable_comments", True),
            "enable_sub_comments": config.get("enable_sub_comments", False),
            "comment_time_filter_h": config.get("comment_time_filter_h", 0),
            "headless": config.get("headless", True),
            "save_option": "jsonl",
        }
        apply_runtime_request_overrides(payload)

        requirement = build_requirement_from_request_payload(payload, source="task_center")

        enable_comments = config.get("enable_comments", True)
        if enable_comments:
            await log_service.push(log_service.create_entry(
                "开始采集评论", "info", task_id=task_id,
            ))

        result = await crawler.start_with_requirement(requirement)

        comment_count = 0
        if isinstance(result, dict):
            for task_result in result.values():
                if isinstance(task_result, list):
                    comment_count += len(task_result)

        if rt.crawler_type == "search":
            await log_service.push(log_service.create_entry(
                "搜索完成", "success", task_id=task_id,
            ))
        elif rt.crawler_type == "detail":
            await log_service.push(log_service.create_entry(
                "详情采集完成", "success", task_id=task_id,
            ))

        if enable_comments and comment_count > 0:
            await log_service.push(log_service.create_entry(
                f"评论采集完成，共采集 {comment_count} 条评论",
                "success", task_id=task_id,
            ))

        task_store.update_task(task_id, {
            "comment_count": comment_count,
            "last_run_at": datetime.now().isoformat(),
            "last_run_status": "success",
        })
        await log_service.push(log_service.create_entry(
            "采集完成", "success", task_id=task_id,
        ))
        return result or {}

    except asyncio.CancelledError:
        await log_service.push(log_service.create_entry(
            "任务已取消", "warning", task_id=task_id,
        ))
        raise
    except Exception as exc:
        rt.status = "error"
        task_store.update_task(task_id, {
            "status": "error",
            "last_run_status": "error",
            "error_message": str(exc),
        })
        await log_service.push(log_service.create_entry(
            f"采集失败: {exc}", "error", task_id=task_id,
        ))
        raise
    finally:
        logger.removeHandler(api_log_handler)
        await cleanup_runtime(crawler)
```

- [ ] **Step 2: Also update the _run_loop error log calls to pass task_id**

In `_run_loop`, the two `create_entry` calls need `task_id=rt.task_id`:

Line with `"Loop cycle error"`:
```python
await log_service.push(log_service.create_entry(f"Loop cycle error ({consecutive_errors}/{MAX_CONSECUTIVE_ERRORS}): {exc}", "error", task_id=rt.task_id))
```

Line with `"Stopping loop"`:
```python
await log_service.push(log_service.create_entry(f"Stopping loop: {MAX_CONSECUTIVE_ERRORS} consecutive errors", "error", task_id=rt.task_id))
```

- [ ] **Step 3: Commit**

```bash
git add api/services/task_manager.py
git commit -m "feat: add key-step log points with task_id in task execution"
```

---

### Task 5: Add frontend tab switcher and log display

**Files:**
- Modify: `webui-react/src/components/TaskCenter.jsx`

- [ ] **Step 1: Add state variables for logs**

Add after the existing state declarations (after line 47):

```jsx
const [activeTab, setActiveTab] = useState('comments');
const [logs, setLogs] = useState([]);
const logListRef = useRef(null);
const wsLogsRef = useRef(null);
```

- [ ] **Step 2: Add loadTaskLogs function**

Add after the `loadComments` function (after line 155):

```jsx
const loadTaskLogs = async (taskId) => {
  try {
    const res = await fetch(`${API_BASE}/api/tasks/${taskId}/logs`);
    const data = await res.json();
    setLogs(data.logs || []);
  } catch (e) { console.error(e); setLogs([]); }
};
```

- [ ] **Step 3: Add WebSocket log connection useEffect**

Add after the existing WebSocket status useEffect (after line 114):

```jsx
// WebSocket logs
useEffect(() => {
  const ws = new WebSocket(`ws://${window.location.hostname}:8080/api/ws/logs`);
  ws.onmessage = (event) => {
    try {
      const entry = JSON.parse(event.data);
      if (entry.task_id === selectedTaskId) {
        setLogs(prev => [...prev, entry]);
      }
    } catch (e) { /* ignore */ }
  };
  wsLogsRef.current = ws;
  return () => ws.close();
}, [selectedTaskId]);
```

- [ ] **Step 4: Auto-scroll logs to bottom**

Add useEffect after the WebSocket logs useEffect:

```jsx
useEffect(() => {
  if (activeTab === 'logs' && logListRef.current) {
    logListRef.current.scrollTop = logListRef.current.scrollHeight;
  }
}, [logs, activeTab]);
```

- [ ] **Step 5: Update handleSelectTask to load logs**

Replace `handleSelectTask` (line 157-164):

```jsx
const handleSelectTask = (taskId) => {
  setSelectedTaskId(taskId);
  setActiveTab('comments');
  setActiveSource(null);
  setLogs([]);
  const task = tasks.find(t => t.task_id === taskId);
  const initKw = task?.config?.comment_keyword_filter || '';
  setCommentKeyword(initKw);
  loadComments(taskId, initKw);
  loadTaskLogs(taskId);
};
```

- [ ] **Step 6: Add LogRow helper**

Add before the `return` statement (before line 217):

```jsx
const LEVEL_COLORS = {
  info: 'text-slate-400',
  warning: 'text-amber-400',
  error: 'text-red-400',
  success: 'text-emerald-400',
  debug: 'text-slate-600',
};

const LEVEL_LABELS = {
  info: 'INFO',
  warning: 'WARN',
  error: 'ERR',
  success: 'OK',
  debug: 'DBG',
};
```

- [ ] **Step 7: Update right panel header to include tabs and conditionally render content**

Replace the entire right panel section (lines 286-398), the section starting with `{/* Right Panel - Comments */}` up to but not including the create task modal:

```jsx
{/* Right Panel */}
<div className="flex-1 flex flex-col min-w-0">
  {!selectedTask ? (
    <div className="flex-1 flex items-center justify-center text-slate-600 text-sm">选择左侧任务查看详情</div>
  ) : (
    <>
      <div className="p-4 border-b border-slate-800 flex items-center justify-between">
        <div className="min-w-0 flex-1">
          <h3 className="font-bold">{selectedTask.name}</h3>
          {activeSource?.content_title && (
            <a
              href={getContentUrl(activeSource.platform_code, activeSource.platform_content_id)}
              target="_blank"
              rel="noreferrer"
              className="text-xs text-slate-400 hover:text-blue-400 hover:underline transition-colors mt-0.5 truncate block"
              title="在原文平台打开作品"
            >
              {activeSource.content_title}
            </a>
          )}
        </div>
        <div className="flex items-center space-x-1 ml-4 shrink-0">
          <button
            onClick={() => setActiveTab('comments')}
            className={`px-3 py-1 rounded-lg text-xs font-bold transition-colors ${activeTab === 'comments' ? 'bg-slate-700 text-white' : 'text-slate-500 hover:text-slate-300'}`}
          >
            评论 {comments.total > 0 ? comments.total : ''}
          </button>
          <button
            onClick={() => setActiveTab('logs')}
            className={`px-3 py-1 rounded-lg text-xs font-bold transition-colors ${activeTab === 'logs' ? 'bg-slate-700 text-white' : 'text-slate-500 hover:text-slate-300'}`}
          >
            日志
          </button>
          <button onClick={() => activeTab === 'comments' ? loadComments(selectedTaskId, commentKeyword) : loadTaskLogs(selectedTaskId)} disabled={commentLoading}
            className="p-2 rounded-lg hover:bg-slate-800 text-slate-400 ml-1">
            <ArrowPathIcon className={`w-4 h-4 ${commentLoading ? 'animate-spin' : ''}`} />
          </button>
        </div>
      </div>

      {/* Comments Tab */}
      {activeTab === 'comments' && (
        <>
          <div className="px-4 py-2 border-b border-slate-800/50 flex items-center gap-2 shrink-0">
            <input
              type="text"
              value={commentKeyword}
              onChange={e => {
                const val = e.target.value;
                setCommentKeyword(val);
                if (debounceRef.current) clearTimeout(debounceRef.current);
                debounceRef.current = setTimeout(() => loadComments(selectedTaskId, val), 400);
              }}
              placeholder="搜索评论内容关键词..."
              className="flex-1 bg-slate-800/60 border border-slate-700/50 rounded-lg px-3 py-1.5 text-xs text-slate-300 placeholder-slate-600 focus:outline-none focus:border-slate-500 transition-colors"
            />
            {commentKeyword && (
              <button
                onClick={() => { setCommentKeyword(''); loadComments(selectedTaskId, ''); }}
                className="text-slate-500 hover:text-slate-300 text-xs whitespace-nowrap">
                清除
              </button>
            )}
          </div>
          <div className="flex-1 overflow-auto">
            {comments.items.length === 0 ? (
              <div className="p-6 text-center text-sm text-slate-600">暂无评论数据</div>
            ) : (
              <table className="w-full text-sm border-collapse">
                <thead>
                  <tr className="border-b border-slate-700 bg-slate-800/60 sticky top-0 z-10">
                    <th className="px-4 py-2.5 text-left text-xs font-semibold text-slate-400 whitespace-nowrap w-36">时间</th>
                    <th className="px-4 py-2.5 text-left text-xs font-semibold text-slate-400 whitespace-nowrap w-28">用户名</th>
                    <th className="px-4 py-2.5 text-left text-xs font-semibold text-slate-400 whitespace-nowrap w-28">抖音号</th>
                    <th className="px-4 py-2.5 text-left text-xs font-semibold text-slate-400 whitespace-nowrap w-20">IP归属地</th>
                    <th className="px-4 py-2.5 text-left text-xs font-semibold text-slate-400">评论内容</th>
                  </tr>
                </thead>
                <tbody>
                  {comments.items.map((c, i) => (
                    <tr key={i} className="border-b border-slate-800/30">
                      <td className="px-4 py-2.5 text-[11px] text-slate-500 whitespace-nowrap">
                        {c.published_at ? new Date(c.published_at).toLocaleString('zh-CN', { month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit', second: '2-digit' }) : '-'}
                      </td>
                      <td className="px-4 py-2.5">
                        <span className="text-sm font-medium text-slate-200 truncate block max-w-[100px]" title={c.author_nickname}>
                          {c.author_nickname || '匿名'}
                        </span>
                      </td>
                      <td className="px-4 py-2.5 text-[11px] text-slate-500 truncate max-w-[100px]">
                        {c.author_platform_id ? (
                          <a
                            href={`https://www.douyin.com/user/${c.author_platform_id}`}
                            target="_blank"
                            rel="noreferrer"
                            onClick={(e) => e.stopPropagation()}
                            className="hover:text-blue-400 hover:underline inline-block truncate w-full"
                            title="访问抖音主页"
                          >
                            {c.author_short_id || c.author_platform_id}
                          </a>
                        ) : (
                          <span title={c.author_short_id || '-'} className="truncate block w-full">
                            {c.author_short_id || '-'}
                          </span>
                        )}
                      </td>
                      <td className="px-4 py-2.5 text-[11px] text-slate-500 whitespace-nowrap">
                        {c.ip_location || '-'}
                      </td>
                      <td className="px-4 py-2.5 text-sm text-slate-300">
                        <div className="flex items-center justify-between gap-2 max-w-[150px] sm:max-w-[250px] lg:max-w-[400px]">
                          <span className="truncate" title={c.comment_text}>{c.comment_text}</span>
                        </div>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </div>
        </>
      )}

      {/* Logs Tab */}
      {activeTab === 'logs' && (
        <div ref={logListRef} className="flex-1 overflow-auto font-mono text-xs">
          {logs.length === 0 ? (
            <div className="p-6 text-center text-sm text-slate-600">暂无日志</div>
          ) : (
            logs.map((log, i) => (
              <div key={i} className="px-4 py-1.5 border-b border-slate-800/30 flex items-start gap-3">
                <span className="text-slate-600 shrink-0">{log.timestamp}</span>
                <span className={`shrink-0 font-bold w-10 text-right ${LEVEL_COLORS[log.level] || 'text-slate-400'}`}>
                  {LEVEL_LABELS[log.level] || 'INFO'}
                </span>
                <span className="text-slate-300 break-all">{log.message}</span>
              </div>
            ))
          )}
        </div>
      )}
    </>
  )}
</div>
```

- [ ] **Step 8: Commit**

```bash
git add webui-react/src/components/TaskCenter.jsx
git commit -m "feat: add logs tab with task-level filtering in TaskCenter"
```

---

### Task 6: Smoke test

- [ ] **Step 1: Start the backend**

```bash
cd D:\workspace\MediaCrawler && python -m api.main
```

- [ ] **Step 2: Verify the logs API returns task_id**

```bash
curl http://localhost:8080/api/tasks/<task_id>/logs
```

Expected: each log entry contains `"task_id": "task_..."`

- [ ] **Step 3: Start the frontend dev server**

```bash
cd D:\workspace\MediaCrawler\webui-react && npm run dev
```

- [ ] **Step 4: Verify in browser**

1. Open the TaskCenter page
2. Create and run a task
3. Click on the running task
4. Switch to "日志" tab — should see real-time log entries appearing
5. Switch to "评论" tab — should still work as before
6. Click a different task, switch to "日志" — should show only that task's logs
