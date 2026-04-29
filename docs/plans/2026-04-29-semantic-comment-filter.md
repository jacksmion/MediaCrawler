# 语义评论过滤 实现计划

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** 评论过滤支持关键词精确匹配 + Embedding 语义匹配混合模式，用户通过"灵敏度"控制阈值。

**Architecture:** 新增 `api/services/semantic_filter.py`（单例模型 + encode + cosine），集成进 `comment_reader.list_comments`；任务配置新增 `comment_filter_sensitivity` 字段；前端搜索栏和新建任务表单同步增加灵敏度选择器。

**Tech Stack:** Python `sentence-transformers`、`numpy`、`bge-small-zh-v1.5` 模型、React + Tailwind

---

## Task 1: 安装依赖

**Step 1: 安装 sentence-transformers**

```bash
cd d:\workspace\MediaCrawler
.venv\Scripts\pip install sentence-transformers
```

期望输出末尾：`Successfully installed sentence-transformers-...`

**Step 2: 验证**

```bash
.venv\Scripts\python -c "from sentence_transformers import SentenceTransformer; print('OK')"
```

期望：`OK`

**Step 3: Commit**

```bash
# 更新 requirements.txt
echo sentence-transformers>> requirements.txt
git add requirements.txt
git commit -m "deps: add sentence-transformers for semantic filter"
```

---

## Task 2: 创建 `semantic_filter.py`

**Files:**
- Create: `api/services/semantic_filter.py`
- Test: `tests/api/services/test_semantic_filter.py`

**背景：**
- 模型名：`BAAI/bge-small-zh-v1.5`（首次运行自动下载到 HuggingFace cache）
- 余弦相似度公式：`dot(a, b) / (||a|| * ||b||)`
- 锚点语句：每个查询 query 直接作为锚点，不需要预定义意图词库

**Step 1: 写失败测试**

新建 `tests/api/services/test_semantic_filter.py`：

```python
import pytest
from api.services.semantic_filter import SemanticFilter, SENSITIVITY_THRESHOLDS

def test_sensitivity_thresholds_defined():
    assert "precise" in SENSITIVITY_THRESHOLDS
    assert "balanced" in SENSITIVITY_THRESHOLDS
    assert "loose" in SENSITIVITY_THRESHOLDS
    assert SENSITIVITY_THRESHOLDS["precise"] > SENSITIVITY_THRESHOLDS["balanced"]

def test_semantic_filter_finds_similar(semantic_filter):
    texts = [
        "这个怎么入手啊",    # 语义近似 "购买意向"
        "哈哈哈好搞笑",      # 无关
        "求个购买链接",      # 语义近似
        "博主好漂亮",        # 无关
    ]
    results = semantic_filter.filter(texts, query="购买意向", threshold=0.5)
    assert "这个怎么入手啊" in results
    assert "求个购买链接" in results
    assert "哈哈哈好搞笑" not in results

def test_empty_query_returns_empty(semantic_filter):
    results = semantic_filter.filter(["随便一条评论"], query="", threshold=0.7)
    assert results == []

def test_empty_texts_returns_empty(semantic_filter):
    results = semantic_filter.filter([], query="购买意向", threshold=0.7)
    assert results == []

@pytest.fixture(scope="module")
def semantic_filter():
    from api.services.semantic_filter import SemanticFilter
    return SemanticFilter()
```

**Step 2: 运行测试验证失败**

```bash
.venv\Scripts\python -m pytest tests/api/services/test_semantic_filter.py -v
```

期望：`ModuleNotFoundError: No module named 'api.services.semantic_filter'`

**Step 3: 实现 `api/services/semantic_filter.py`**

```python
"""Semantic comment filtering using sentence embeddings."""
from __future__ import annotations

import logging
import numpy as np
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from sentence_transformers import SentenceTransformer

logger = logging.getLogger(__name__)

SENSITIVITY_THRESHOLDS: dict[str, float] = {
    "precise": 0.85,
    "balanced": 0.75,
    "loose": 0.60,
}

_MODEL_NAME = "BAAI/bge-small-zh-v1.5"


class SemanticFilter:
    """Singleton-friendly semantic filter using bge-small-zh-v1.5."""

    def __init__(self, model_name: str = _MODEL_NAME) -> None:
        self._model: SentenceTransformer | None = None
        self._model_name = model_name

    def _get_model(self) -> "SentenceTransformer":
        if self._model is None:
            try:
                from sentence_transformers import SentenceTransformer
                logger.info("Loading embedding model: %s", self._model_name)
                self._model = SentenceTransformer(self._model_name)
                logger.info("Embedding model loaded.")
            except ImportError as exc:
                raise RuntimeError(
                    "sentence-transformers not installed. Run: pip install sentence-transformers"
                ) from exc
        return self._model

    def filter(self, texts: list[str], *, query: str, threshold: float) -> list[str]:
        """Return texts whose semantic similarity to query >= threshold."""
        if not query or not texts:
            return []

        model = self._get_model()

        # Encode query and all texts in one batch
        all_inputs = [query] + texts
        embeddings = model.encode(all_inputs, normalize_embeddings=True, show_progress_bar=False)

        query_vec = embeddings[0]           # shape: (dim,)
        text_vecs = embeddings[1:]          # shape: (N, dim)

        # Cosine similarity (vectors are normalized, so dot product = cosine sim)
        scores: np.ndarray = text_vecs @ query_vec

        return [text for text, score in zip(texts, scores) if float(score) >= threshold]

    def filter_with_scores(
        self, texts: list[str], *, query: str
    ) -> list[tuple[str, float]]:
        """Return (text, score) pairs sorted by score descending."""
        if not query or not texts:
            return []

        model = self._get_model()
        all_inputs = [query] + texts
        embeddings = model.encode(all_inputs, normalize_embeddings=True, show_progress_bar=False)
        query_vec = embeddings[0]
        text_vecs = embeddings[1:]
        scores: np.ndarray = text_vecs @ query_vec

        pairs = list(zip(texts, (float(s) for s in scores)))
        pairs.sort(key=lambda x: x[1], reverse=True)
        return pairs


# Module-level singleton to reuse loaded model across requests
semantic_filter = SemanticFilter()
```

**Step 4: 运行测试**

```bash
.venv\Scripts\python -m pytest tests/api/services/test_semantic_filter.py -v
```

> 注：首次运行会下载模型（~95MB），需要网络。之后缓存在 HuggingFace 本地目录。

期望：全部 PASS

**Step 5: Commit**

```bash
git add api/services/semantic_filter.py tests/api/services/test_semantic_filter.py
git commit -m "feat: add SemanticFilter with bge-small-zh-v1.5"
```

---

## Task 3: 集成到 `comment_reader.list_comments`

**Files:**
- Modify: `api/services/comment_reader.py`

**改动逻辑：** 当有 `keyword` 时，先做关键词精确匹配，再做语义匹配，合并去重，按原排序规则排列。

**Step 1: 在 `comment_reader.py` 顶部追加 import**

在现有 import 区域（第 1-8 行附近）末尾加：

```python
from api.services.semantic_filter import semantic_filter, SENSITIVITY_THRESHOLDS
```

**Step 2: 修改 `list_comments` 方法签名**

原签名（约第 103 行）：
```python
def list_comments(
    self,
    *,
    source_id: str,
    keyword: str | None,
    comment_level: int | None,
    location: str | None,
    limit: int,
    offset: int,
    sort: str,
) -> dict[str, Any]:
```

新签名（加 `sensitivity` 参数）：
```python
def list_comments(
    self,
    *,
    source_id: str,
    keyword: str | None,
    comment_level: int | None,
    location: str | None,
    sensitivity: str = "balanced",   # precise / balanced / loose
    limit: int,
    offset: int,
    sort: str,
) -> dict[str, Any]:
```

**Step 3: 替换关键词过滤逻辑**

原代码（约第 130-132 行）：
```python
if keyword:
    lowered_keyword = keyword.lower()
    rows = [row for row in rows if lowered_keyword in row.comment_text.lower()]
```

替换为：
```python
if keyword:
    lowered_keyword = keyword.lower()
    # Layer 1: exact keyword match
    exact_ids = {
        row.platform_comment_id
        for row in rows
        if lowered_keyword in row.comment_text.lower()
    }
    # Layer 2: semantic match (catches paraphrases)
    threshold = SENSITIVITY_THRESHOLDS.get(sensitivity, SENSITIVITY_THRESHOLDS["balanced"])
    texts = [row.comment_text for row in rows]
    try:
        semantic_matches = set(semantic_filter.filter(texts, query=keyword, threshold=threshold))
    except Exception as exc:
        logger.warning("Semantic filter failed, falling back to keyword only: %s", exc)
        semantic_matches = set()
    # Merge: keep row if either layer matched
    rows = [
        row for row in rows
        if row.platform_comment_id in exact_ids or row.comment_text in semantic_matches
    ]
```

**Step 4: 运行测试**

```bash
.venv\Scripts\python -m pytest tests/api/ -v
```

**Step 5: Commit**

```bash
git add api/services/comment_reader.py
git commit -m "feat: hybrid keyword+semantic filter in comment_reader"
```

---

## Task 4: API 新增 `sensitivity` 参数

**Files:**
- Modify: `api/routers/comments.py`

**Step 1: 在 `list_comments` 路由加参数**

```python
@router.get("", response_model=CommentListResponse)
async def list_comments(
    source_id: str,
    keyword: str | None = None,
    comment_level: int | None = Query(default=None, ge=1, le=2),
    location: str | None = None,
    sensitivity: str = Query(default="balanced", pattern="^(precise|balanced|loose)$"),  # 新增
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    sort: str = Query(default="published_at_desc"),
):
    try:
        return comment_reader.list_comments(
            source_id=source_id,
            keyword=keyword,
            comment_level=comment_level,
            location=location,
            sensitivity=sensitivity,    # 新增
            limit=limit,
            offset=offset,
            sort=sort,
        )
    ...
```

**Step 2: Commit**

```bash
git add api/routers/comments.py
git commit -m "feat: expose sensitivity param in GET /api/comments"
```

---

## Task 5: 任务 Schema 新增 `comment_filter_sensitivity`

**Files:**
- Modify: `api/schemas/task.py`
- Modify: `api/services/task_manager.py`

**Step 1: `task.py` 新增字段**

在 `comment_keyword_filter` 行之后：
```python
comment_filter_sensitivity: str = "balanced"  # precise / balanced / loose
```

**Step 2: `task_manager.py` 新增字段存入 config**

在 `"comment_keyword_filter": req.comment_keyword_filter,` 之后：
```python
"comment_filter_sensitivity": req.comment_filter_sensitivity,
```

**Step 3: Commit**

```bash
git add api/schemas/task.py api/services/task_manager.py
git commit -m "feat: store comment_filter_sensitivity in task config"
```

---

## Task 6: 前端 — 搜索栏加灵敏度选择器

**Files:**
- Modify: `webui-react/src/components/TaskCenter.jsx`

**改动1：** 新增 `sensitivity` state（在 `commentKeyword` state 附近）：

```jsx
const [filterSensitivity, setFilterSensitivity] = useState('balanced');
```

**改动2：** `loadComments` 函数 URL 加 `sensitivity` 参数：

```jsx
const sensParam = keyword ? `&sensitivity=${filterSensitivity}` : '';
const res = await fetch(`...${kwParam}${sensParam}`);
```

**改动3：** 搜索栏右侧加灵敏度切换（仅有关键词时显示）：

在搜索 input 和清除按钮之间插入：

```jsx
{commentKeyword && (
  <div className="flex rounded-lg border border-slate-700 overflow-hidden shrink-0">
    {[
      { id: 'precise', label: '精准' },
      { id: 'balanced', label: '平衡' },
      { id: 'loose', label: '宽松' },
    ].map(opt => (
      <button
        key={opt.id}
        onClick={() => {
          setFilterSensitivity(opt.id);
          loadComments(selectedTaskId, commentKeyword);
        }}
        className={`px-2.5 py-1 text-[10px] font-medium transition-colors ${
          filterSensitivity === opt.id
            ? 'bg-blue-600 text-white'
            : 'bg-slate-800 text-slate-400 hover:text-slate-300'
        }`}
      >
        {opt.label}
      </button>
    ))}
  </div>
)}
```

**改动4：** `handleSelectTask` 读取任务的 sensitivity：

```jsx
const initSensitivity = task?.config?.comment_filter_sensitivity || 'balanced';
setFilterSensitivity(initSensitivity);
```

**Step: Commit**

```bash
git add webui-react/src/components/TaskCenter.jsx
git commit -m "feat: add sensitivity selector to comment search bar"
```

---

## Task 7: 前端 — 新建任务表单加灵敏度选择

**Files:**
- Modify: `webui-react/src/components/TaskCenter.jsx`

在新建任务的 `comment_keyword_filter` 输入框之后加灵敏度选择器：

```jsx
{form.crawler_type !== 'search' && form.comment_keyword_filter && (
  <div>
    <label className="block text-xs text-slate-400 mb-1">匹配灵敏度</label>
    <div className="flex space-x-2">
      {[
        { id: 'precise', label: '精准', desc: '只匹配高度相关' },
        { id: 'balanced', label: '平衡', desc: '推荐' },
        { id: 'loose', label: '宽松', desc: '覆盖更多近义表达' },
      ].map(opt => (
        <button
          key={opt.id}
          onClick={() => setForm(f => ({ ...f, comment_filter_sensitivity: opt.id }))}
          className={`flex-1 py-2 rounded-lg text-xs font-bold transition-all border ${
            form.comment_filter_sensitivity === opt.id
              ? 'bg-blue-600/20 border-blue-500/50 text-blue-400'
              : 'bg-slate-800 border-slate-700 text-slate-400 hover:border-slate-600'
          }`}
        >
          <div>{opt.label}</div>
          <div className="text-[9px] font-normal opacity-60 mt-0.5">{opt.desc}</div>
        </button>
      ))}
    </div>
  </div>
)}
```

同时在 form 初始 state 加 `comment_filter_sensitivity: 'balanced'`。

**Step: Commit**

```bash
git add webui-react/src/components/TaskCenter.jsx
git commit -m "feat: add sensitivity selector in create task modal"
```

---

## 验证清单

```bash
# 后端单测
.venv\Scripts\python -m pytest tests/ -v

# 启动后端
.venv\Scripts\uvicorn api.main:app --reload --port 8080

# 手动 API 测试（有任务数据时）
curl "http://localhost:8080/api/comments?source_id=<id>&keyword=购买意向&sensitivity=loose"

# 启动前端
cd webui-react && npm run dev

# 手动验证
# 1. 搜索框输入"购买意向" → 出现灵敏度切换 [精准|平衡|宽松]
# 2. 切换宽松 → 返回更多结果（包含"怎么入手""求链接"）
# 3. 切换精准 → 结果减少（只留高度相似的）
# 4. 新建任务(指定ID模式) → 输入过滤词后显示灵敏度选择
```
