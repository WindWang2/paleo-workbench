# WebEngine 富文本预览设计

## 目标

为 HTML、HTM、MD 和 Markdown 恢复内置预览，同时避免大文档在 UI 线程解析造成卡顿。

## 格式策略

- HTML / HTM：WebEngine 通过本地文件 URL 直接加载，不由预览提供器读取全文。
- MD / Markdown：预览提供器在后台只读取前 256 KiB，转换为基础 HTML；超过上限时附加“仅显示前 256 KiB”提示。
- Markdown 基础渲染覆盖标题、段落、无序列表、有序列表、代码块和行内转义；不依赖可选 markdown 包。

## WebEngine 安全边界

- 仅允许本地文件及相对资源。
- 禁止本地内容访问远程 URL。
- 阻止 http、https 等外部导航与资源请求。
- 预览面板只读，不提供在应用内打开外部链接的行为。

## 数据流

PreviewProvider 根据格式返回 web_document 预览结果。HTML / HTM 仅传递文件路径；Markdown 在工作线程生成受限 HTML 载荷。DataReaderPanel 将结果交给 WebDocumentPreviewWidget：HTML 调用 load(QUrl.fromLocalFile(path))，Markdown 调用 setHtml(html, baseUrl)。

## 验证

- HTML / HTM 不触发 PreviewProvider 的全文读取。
- Markdown 预览读取上限为 256 KiB，并提供截断提示。
- WebEngine 禁止远程 URL 导航，同时保留本地 HTML 相对资源加载。
- PDF、文本、表格、图像、GeoTIFF、JSON 与专业数据预览不变。

