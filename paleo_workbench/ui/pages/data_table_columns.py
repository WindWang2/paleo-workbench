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
    ColumnDefinition("format", "格式"),
    ColumnDefinition("status", "状态"),
    ColumnDefinition("role", "角色"),
    ColumnDefinition("size", "大小"),
    ColumnDefinition("source", "来源"),
    ColumnDefinition("path", "路径"),
)
COLUMN_BY_KEY = {column.key: column for column in COLUMN_DEFINITIONS}
DEFAULT_COLUMN_KEYS = [column.key for column in COLUMN_DEFINITIONS]
HEADERS = [column.label for column in COLUMN_DEFINITIONS]
