# 富文本文件禁用内置预览 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让 HTML、HTM、Markdown 文件可导入和管理，但不再向 UI 传递富文本内容进行内置预览。

**Architecture:** 保留 `PreviewProvider._build_preview()` 的文件存在性检查与资源元数据构建。将富文本格式分支替换为轻量消息 `PreviewResult`，不调用 `_rich_text_preview()`；因此后台和 UI 线程都不会读取、转换或渲染全文。

**Tech Stack:** Python 3、pytest、PySide6 数据预览模型。

## Global Constraints

- .html、.htm、.md 和 .markdown 必须仍可正常导入、分类、检索、查看路径及移出项目。
- 这些格式不再构造或渲染内置富文本预览。
- 阅读器消息必须为“此类文档不提供内置预览，可使用打开目录定位文件”。
- 不改变 PDF、文本、表格、图像、地理栅格、JSON 与专业数据格式的预览行为。

---

### Task 1: 在预览提供器禁用富文本载荷

**Files:**
- Modify: `paleo_workbench/ui/pages/preview_provider.py:175-176`
- Modify: `tests/test_preview_provider.py:325-343`

**Interfaces:**
- Consumes: `MARKDOWN_FORMATS: set[str]` 与 `PreviewResult(mode="message", ...)`。
- Produces: 对富文本资源返回 `PreviewResult`，其中 `mode == "message"`、`rich_html == ""`，且 `message == "此类文档不提供内置预览，可使用打开目录定位文件"`。

- [x] **Step 1: 写入失败的 HTML 无预览回归测试**

在 `tests/test_preview_provider.py` 加入：

```python
def test_html_preview_returns_message_without_reading_full_document(tmp_path, monkeypatch):
    path = tmp_path / "large.html"
    path.write_text("<p>large</p>" * 100_000, encoding="utf-8")
    resource = ResourceItem(
        name="large.html", path=str(path), type="document", format="html"
    )

    def should_not_render(*_args, **_kwargs):
        raise AssertionError("HTML preview must not read or render the document")

    monkeypatch.setattr(PreviewProvider, "_rich_text_preview", should_not_render)

    result = PreviewProvider().preview(resource)

    assert result.mode == "message"
    assert result.message == "此类文档不提供内置预览，可使用打开目录定位文件"
    assert result.rich_html == ""
```

- [x] **Step 2: 运行测试，确认改动前失败**

Run: `pytest tests/test_preview_provider.py::test_html_preview_returns_message_without_reading_full_document -q`

Expected: FAIL，因为当前 HTML 分支会调用被替换的 `_rich_text_preview`。

- [x] **Step 3: 替换富文本预览分支**

在 `PreviewProvider._build_preview()` 中将：

```python
if fmt in MARKDOWN_FORMATS:
    return self._rich_text_preview(asset)
```

替换为：

```python
if fmt in MARKDOWN_FORMATS:
    return PreviewResult(
        mode="message",
        title=title,
        path=asset.path,
        revision=revision,
        format=asset.format,
        status=asset.status,
        type_label=asset.type,
        message="此类文档不提供内置预览，可使用打开目录定位文件",
    )
```

- [x] **Step 4: 更新既有富文本预览断言**

将既有 HTML 与 Markdown 测试改为断言消息模式和上述提示文本，确保所有富文本格式均遵循相同行为。

- [x] **Step 5: 运行定向回归测试**

Run: `pytest tests/test_preview_provider.py -q`

Expected: 所有预览提供器测试通过；若环境缺少可选 `markdown` 包，原 Markdown 渲染测试已经在本任务中改为不导入该包，不应再失败。

- [x] **Step 6: 提交实现**

```bash
git add paleo_workbench/ui/pages/preview_provider.py tests/test_preview_provider.py
git commit -m "fix: disable rich text previews"
```
