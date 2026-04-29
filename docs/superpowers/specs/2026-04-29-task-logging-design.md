# 任务日志功能设计

## 概述

为任务中心增加关键步骤级别的日志功能，支持按任务过滤查看，通过 Tab 切换评论和日志视图。

## 后端改动

### 1. LogEntry 增加 task_id

`api/schemas/crawler.py`:

```python
class LogEntry(BaseModel):
    id: int
    task_id: str = ""      # 新增
    timestamp: str
    level: Literal["info", "warning", "error", "success", "debug"]
    message: str
```

### 2. CrawlerLogService 传入 task_id

`api/services/crawler_log_service.py`:

- `create_entry(message, level, task_id="")` 增加 task_id 参数，写入 LogEntry

### 3. 关键步骤日志点

在 `api/services/task_manager.py` 的任务执行流程中添加：

| 步骤 | 日志消息 | 级别 |
|------|---------|------|
| 搜索开始 | `开始搜索关键词: {keywords}` | info |
| 搜索完成 | `搜索完成，找到 {count} 条结果` | success |
| 详情采集开始 | `开始采集详情，共 {count} 个内容` | info |
| 详情采集完成 | `详情采集完成` | success |
| 评论采集开始 | `开始采集评论` | info |
| 评论采集完成 | `评论采集完成，共采集 {count} 条评论` | success |
| 数据保存 | `已保存 {count} 条数据` | info |

### 4. REST API

`GET /api/tasks/{task_id}/logs` — 返回该任务的历史日志列表。

## 前端改动

### 1. Tab 切换

右侧面板标题栏添加"评论"/"日志" Tab，用 `activeTab` 状态控制。

### 2. 日志展示

- 切换到日志 Tab 或选中任务时，调 REST API 拉取历史日志
- WebSocket `/ws/logs` 接收实时日志，前端按 `task_id` 过滤
- 日志行格式：`[timestamp] [level badge] message`
- level 颜色：success 绿、warning 黄、error 红、info 默认灰
- 自动滚动到底部

### 3. 任务切换

- 清空日志列表，重新拉取新任务历史日志
- WebSocket 连接保持不变，前端过滤

## 不涉及

- 不改动 WebSocket 协议本身（保持全量推送，前端过滤）
- 不添加调试级别日志
- 不改动左侧任务列表布局
