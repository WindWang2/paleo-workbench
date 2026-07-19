# WebEngine 富文本预览 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 为 HTML、HTM、MD 和 Markdown 提供不卡顿、仅本地内容的 WebEngine 内置预览。

**Architecture:** `PreviewProvider` 在工作线程决定 `web_document` 结果：HTML 只返回路径，Markdown 读取不超过 `MAX_TEXT_PREVIEW_BYTES` 并生成基础 HTML。`WebDocumentPreviewWidget` 使用隔离的 `QWebEngineProfile`、请求拦截器与页面导航限制来加载本地文件或受限 HTML；`DataReaderPanel` 只负责分派结果。

**Tech Stack:** Python 3、PySide6 QtWebEngine、pytest、pytest-qt。

## Global Constraints

- .html、.htm、.md 和 .markdown 仍可导入、分类、检索、查看路径及移出项目。
- HTML / HTM 不由 PreviewProvider 读取全文，直接交给本地 WebEngine URL。
- Markdown 只读取前 256 KiB，提供标题、段落、列表、代码块与 HTML 转义的基础渲染；超限结果显示“仅显示前 256 KiB”。
- WebEngine 只允许 file、data 和 about URL；阻止 http、https 及其他远程资源请求和导航。
- 不改变 PDF、文本、表格、图像、GeoTIFF、JSON 与专业数据预览行为。

---

### Task 1: 构造受限的 Web 文档预览结果

**Files:**
- Modify: `paleo_workbench/ui/pages/preview_provider.py`
- Modify: `tests/test_preview_provider.py`

**Interfaces:**
- Consumes: `MARKDOWN_FORMATS` and `MAX_TEXT_PREVIEW_BYTES`.
- Produces: `PreviewResult(mode="web_document", path: str, rich_html: str, warning: str)`; HTML has empty `rich_html`, Markdown has bounded generated HTML.

- [x] **Step 1: 写入失败的格式与读取边界测试**

在 `tests/test_preview_provider.py` 添加：

```python
@pytest.mark.parametrize("fmt", ["html", "htm"])
def test_html_web_preview_does_not_read_document(tmp_path, monkeypatch, fmt):
    path = tmp_path / f"large.{fmt}"
    path.write_text("<h1>large</h1>" * 100_000, encoding="utf-8")
    resource = ResourceItem(name=path.name, path=str(path), type="document", format=fmt)
    monkeypatch.setattr(Path, "read_text", lambda *_a, **_k: pytest.fail("must not read HTML"))

    result = PreviewProvider().preview(resource)

    assert result.mode == "web_document"
    assert result.path == str(path)
    assert result.rich_html == ""

def test_markdown_web_preview_is_bounded_and_escaped(tmp_path):
    path = tmp_path / "large.md"
    path.write_text("# Title\n\n- one\n\n<script>x</script>\n" * 50_000, encoding="utf-8")
    resource = ResourceItem(name=path.name, path=str(path), type="document", format="md")

    result = PreviewProvider().preview(resource)

    assert result.mode == "web_document"
    assert "<h1>Title</h1>" in result.rich_html
    assert "&lt;script&gt;x&lt;/script&gt;" in result.rich_html
    assert result.truncated is True
    assert result.warning == "仅显示前 256 KiB"
```

- [x] **Step 2: 运行测试，确认改动前失败**

Run: `pytest tests/test_preview_provider.py::test_html_web_preview_does_not_read_document tests/test_preview_provider.py::test_markdown_web_preview_is_bounded_and_escaped -q`

Expected: FAIL because `web_document` is not yet a preview mode.

- [x] **Step 3: 实施结果模式与基础 Markdown 渲染器**

在 `PreviewMode` 加入 `"web_document"`。为 HTML / HTM 返回 `PreviewResult(mode="web_document", ..., path=asset.path)`，不调用文件读取 API。

为 MD / Markdown 使用既有 `_read_preview_chunk(path)`，将字节以 UTF-8 replacement 解码后通过私有 `_markdown_to_html(markdown: str) -> str` 生成安全 HTML。实现必须先 `html.escape`，再识别 # 至 ###### 标题、- 或 * 无序列表、数字加点有序列表、三反引号围栏代码和普通段落；格式化后的 HTML 作为 `rich_html` 返回，并复用 `truncated` 与 `warning` 字段。

- [x] **Step 4: 运行预览提供器回归测试**

Run: `pytest tests/test_preview_provider.py -q`

Expected: PASS, including HTML no-read, Markdown bounded rendering, and unchanged other preview results.

- [x] **Step 5: 提交任务 1**

```bash
git add paleo_workbench/ui/pages/preview_provider.py tests/test_preview_provider.py
git commit -m "feat: build bounded web document previews"
```

### Task 2: 接入安全的 WebEngine 预览面板

**Files:**
- Modify: `paleo_workbench/ui/pages/preview_widgets.py`
- Modify: `paleo_workbench/ui/pages/data_reader_panel.py`
- Modify: `tests/test_preview_widgets.py`
- Modify: `tests/test_data_reader_panel.py`

**Interfaces:**
- Consumes: `PreviewResult(mode="web_document", path, rich_html, warning)` from Task 1.
- Produces: `WebDocumentPreviewWidget.load_document(path: str, html: str = "") -> None`; empty `html` loads a local file URL, nonempty `html` calls `setHtml` with the source directory as base URL.

- [x] **Step 1: 写入失败的 WebEngine 面板与阅读器分派测试**

```python
def test_web_document_widget_loads_local_file(qtbot, tmp_path):
    path = tmp_path / "page.html"
    path.write_text("<h1>Page</h1>", encoding="utf-8")
    widget = WebDocumentPreviewWidget()
    qtbot.addWidget(widget)

    widget.load_document(path.as_posix())

    assert widget.url().isLocalFile()
    assert widget.url().toLocalFile() == path.as_posix()

def test_reader_panel_dispatches_web_document(qtbot, tmp_path):
    panel = DataReaderPanel()
    qtbot.addWidget(panel)
    path = tmp_path / "page.html"

    panel.render(PreviewResult(mode="web_document", title="page.html", path=path.as_posix()))

    assert panel.stack.currentWidget() is panel.web_document_preview
```

- [x] **Step 2: 运行测试，确认改动前失败**

Run: `QT_QPA_PLATFORM=offscreen pytest tests/test_preview_widgets.py::test_web_document_widget_loads_local_file tests/test_data_reader_panel.py::test_reader_panel_dispatches_web_document -q`

Expected: FAIL because `WebDocumentPreviewWidget` and `web_document_preview` do not exist.

- [x] **Step 3: 实施本地安全 WebEngine 组件与阅读器分派**

在 `preview_widgets.py` 新增：

```python
class _LocalOnlyRequestInterceptor(QWebEngineUrlRequestInterceptor):
    def interceptRequest(self, info) -> None:
        if info.requestUrl().scheme() not in {"file", "data", "about"}:
            info.block(True)

class _LocalOnlyPage(QWebEnginePage):
    def acceptNavigationRequest(self, url, navigation_type, is_main_frame):
        return url.scheme() in {"file", "data", "about"}

class WebDocumentPreviewWidget(QWebEngineView):
    def load_document(self, path: str, html: str = "") -> None:
        base_url = QUrl.fromLocalFile(str(Path(path).parent) + "/")
        if html:
            self.setHtml(html, base_url)
        else:
            self.load(QUrl.fromLocalFile(path))
```

构造组件时创建其专属 `QWebEngineProfile`、安装拦截器和 `_LocalOnlyPage`，并将 `LocalContentCanAccessRemoteUrls` 设为 `False`。在 `DataReaderPanel` 中创建 `self.web_document_preview`，将 `web_document` 结果分派到 `load_document(result.path, result.rich_html)`。

- [x] **Step 4: 运行组件与阅读器回归测试**

Run: `QT_QPA_PLATFORM=offscreen pytest tests/test_preview_widgets.py tests/test_data_reader_panel.py -q`

Expected: Web 文档组件和阅读器分派测试通过。若当前无音频后端导致 DataReaderPanel 全文件测试阻塞，运行两条新增测试并记录环境限制。

- [x] **Step 5: 提交任务 2**

```bash
git add paleo_workbench/ui/pages/preview_widgets.py paleo_workbench/ui/pages/data_reader_panel.py tests/test_preview_widgets.py tests/test_data_reader_panel.py
git commit -m "feat: preview rich documents with webengine"
```
