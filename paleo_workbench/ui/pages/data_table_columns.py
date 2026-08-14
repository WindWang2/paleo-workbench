from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ColumnDefinition:
    key: str
    label: str
    required: bool = False


COLUMN_DEFINITIONS = (
    ColumnDefinition("name", "文件名", required=True),
    ColumnDefinition("type", "类型"),
    ColumnDefinition("stage", "生命周期"),
    ColumnDefinition("version", "版本"),
    ColumnDefinition("lineage", "血缘"),
    ColumnDefinition("tags", "标签"),
    ColumnDefinition("managed", "管理方式"),
    ColumnDefinition("integrity", "完整性"),
    ColumnDefinition("format", "格式"),
    ColumnDefinition("status", "状态"),
    ColumnDefinition("role", "角色"),
    ColumnDefinition("review_status", "审核状态"),
    ColumnDefinition("size", "大小"),
    ColumnDefinition("modified", "修改时间"),
    ColumnDefinition("source", "来源"),
    ColumnDefinition("path", "路径"),
)

COLUMN_BY_KEY = {column.key: column for column in COLUMN_DEFINITIONS}

COLUMN_TOOLTIPS = {
    "name": "资源或成果文件名",
    "type": "数据资源类型",
    "stage": "生命阶段 (RAW/DERIVED/OUTPUT)",
    "version": "当前版本标识",
    "lineage": "血缘状态：可溯源至 RAW 的层级 / 断链告警",
    "tags": "关联标签列表",
    "managed": "项目受管/外部链接",
    "integrity": "校验和与存在完整性",
    "format": "文件解析格式",
    "status": "当前处理状态",
    "role": "输入/成果角色",
    "review_status": "治理审核状态（草稿/待审核/已通过/已驳回）",
    "size": "文件大小",
    "modified": "修改或生成时间",
    "source": "数据来源说明",
    "path": "文件完整路径",
}

# Target default view (F5): the columns a data manager scans first — identity,
# lifecycle context, versioning, lineage, tagging, integrity, freshness.
DEFAULT_COLUMN_KEYS = [
    "name",
    "type",
    "stage",
    "version",
    "lineage",
    "tags",
    "integrity",
    "modified",
]
HEADERS = [column.label for column in COLUMN_DEFINITIONS]
