# MediaCrawler

MediaCrawler 是一个社交媒体采集项目，当前支持通过统一 runtime 执行链抓取多个平台的数据，并提供 CLI、API、WebUI 三种使用入口。

## 项目状态

当前主执行链已经迁移到 `connectors + runtime + application/services`：

- CLI 入口: [cli.py](D:/workspace/MediaCrawler/cli.py:1)
- API 入口: [api/main.py](D:/workspace/MediaCrawler/api/main.py:1)
- WebUI 前端: [webui-react](D:/workspace/MediaCrawler/webui-react)

支持的平台包括：

- 小红书 `xhs`
- 抖音 `dy`
- 快手 `ks`
- Bilibili `bili`
- 微博 `wb`
- 百度贴吧 `tieba`
- 知乎 `zhihu`

## 功能概览

- 统一的平台任务模型：`search` / `detail` / `creator`
- 支持 CLI、FastAPI、React WebUI
- 支持二维码登录、Cookie 登录
- 支持文件输出和数据库输出
- 支持运行时事件、任务、结果、原始记录归档

## 环境要求

- Python `>= 3.11`
- Node.js `>= 18`，用于 `webui-react`
- 已安装 Chromium/Chrome，或允许 Playwright 自动管理浏览器

## 安装

推荐使用 `uv`：

```powershell
uv sync
uv run playwright install chromium
```

如果使用虚拟环境，也需要确保至少这些依赖可用：

- `playwright`
- `fastapi`
- `uvicorn`
- `sqlalchemy`
- `aiofiles`
- `motor`
- `openpyxl`

## 快速开始

### 1. 直接运行 CLI

项目当前推荐入口是 [cli.py](D:/workspace/MediaCrawler/cli.py:1)。

使用示例 JSON：

```powershell
uv run .\cli.py .\examples\cli\dy_search.json
```

也可以直接传参数：

```powershell
uv run .\cli.py `
  -p dy `
  -m search `
  -o jsonl `
  -k 张家界 `
  -s 1 `
  -n 1
```

### 2. 仅进行登录

```powershell
uv run .\cli.py .\examples\cli\xhs_login.json
```

### 3. 启动 API

```powershell
uv run python -m api.main
```

默认监听：

- `http://127.0.0.1:8080`
- Swagger 文档: `http://127.0.0.1:8080/docs`

### 4. 启动 WebUI

先启动 API，再启动前端：

```powershell
cd .\webui-react
npm install
npm run dev
```

前端默认开发地址：

- `http://127.0.0.1:5173`

## CLI 使用方式

`cli.py` 现在支持三种常用形式：

1. 直接把 JSON 文件路径作为位置参数传入
2. 用 `--request-json` 传 JSON 文件路径
3. 用 `--request-json` 传 JSON 字符串

例如：

```powershell
uv run .\cli.py .\examples\cli\dy_search.json
```

```powershell
$req = Get-Content .\examples\cli\dy_search.json -Raw
uv run .\cli.py --request-json $req
```

示例文件位于：

- [examples/cli](D:/workspace/MediaCrawler/examples/cli)

其中包括：

- `xhs_search.json`
- `dy_search.json`
- `bili_detail.json`
- `zhihu_creator.json`
- `xhs_login.json`

## 输出说明

输出分为终端 summary 和持久化结果两部分。

### 文件输出

当 `save_option` 为 `json` / `jsonl` / `excel` 时，主要会写入：

- `data/platform_runtime/normalized/`: 标准化内容
- `data/platform_runtime/raw/`: 原始响应记录
- `data/platform_runtime/tasks/`: 任务与作业快照
- `data/platform_runtime/events/`: 运行事件
- `data/<platform>/`: Excel 输出

### 数据库输出

当 `save_option` 为以下值时，runtime 会走数据库后端：

- `sqlite`
- `db`（MySQL）
- `postgres`
- `mongodb`

关系型数据库会写入 runtime 通用表；MongoDB 会写入 runtime 集合。

## API 说明

API 主要用于 WebUI 或外部控制器调用，当前核心能力包括：

- 启动任务
- 停止任务
- 查询任务状态
- 拉取运行日志
- 获取平台和配置选项

核心路由位于：

- [api/routers/crawler.py](D:/workspace/MediaCrawler/api/routers/crawler.py:1)
- [api/routers/config.py](D:/workspace/MediaCrawler/api/routers/config.py:1)
- [api/routers/data.py](D:/workspace/MediaCrawler/api/routers/data.py:1)

## 常见问题

### 1. `playwright` 缺失

报错通常类似：

```text
ModuleNotFoundError: No module named 'playwright'
```

处理方式：

```powershell
uv sync
uv run playwright install chromium
```

### 2. `--request-json` 传文件路径时报 JSON 解析错误

确保使用的是当前代码版本。当前入口已经支持把 JSON 文件路径直接传给 `--request-json`。

### 3. 报二维码登录或浏览器验证

这是正常行为。很多平台在没有可用 Cookie 时会要求扫码或滑块验证。

### 4. 数据库初始化失败

检查以下配置：

- [config/db_config.py](D:/workspace/MediaCrawler/config/db_config.py:1)
- 环境变量中的数据库地址、账号、密码

## 开发说明

当前建议按下面的边界理解代码结构：

- `api/`、`webui-react/`、CLI 入口：只负责交互和启动
- `application/services/`：只保留通用编排
  - `crawler_runtime.py`
  - `connector_crawlers.py`
  - `requirement_mapper.py`
  - `task_executor.py`
  - `state_store.py`
- `connectors/`：负责平台能力调用、平台结果归一化、平台错误标准化、平台登录适配
- `runtime/`：负责浏览器、HTTP、代理、缓存、会话、签名、存储、脚本资源等运行时基础设施
- `database/`：当前作为 `runtime/storage` 的数据库 backend 实现层使用

主执行链是：

`入口 -> application/services -> connectors -> runtime`

如果要增加桌面窗口，当前最省事的路径是复用 `webui-react + FastAPI`，外面再包一层桌面壳，而不是重写一套原生桌面 UI。

## 许可与使用限制

本项目当前声明为非商业学习用途。使用前请阅读项目根目录中的 `LICENSE`，并自行确保使用方式符合目标平台条款与当地法律法规。
