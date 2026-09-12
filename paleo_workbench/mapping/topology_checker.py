"""拓扑检查器宿主面（拓扑编辑迁移 M4 §5）。

桥 ``run_geometry_checks`` / ``fix_geometry_error`` 的结果 + 双豁免
（忽略列表、缝隙白名单）+ 保存门禁过滤。工区余量由桥自制规则返回。
"""
from __future__ import annotations

import json
from collections.abc import Iterable, Mapping
from datetime import datetime, timezone

__all__ = ["TopologyChecker", "ignore_key"]


def ignore_key(error: Mapping[str, object]) -> tuple[str, str, str, str]:
    """忽略身份：规则 + 层 + 要素 + 对方要素（不依赖一次运行的临时 id）。"""
    return (
        str(error.get("rule") or ""),
        str(error.get("layer_id") or ""),
        str(error.get("feature_id") or ""),
        str(error.get("other_feature_id") or ""),
    )


class TopologyChecker:
    """上次检查结果 + 豁免 + 桥运行/修复。"""

    def __init__(self) -> None:
        self.last_errors: list[dict[str, object]] = []
        self.last_run_at: str | None = None
        self.workspace: dict | None = None
        self._ignored: dict[tuple[str, str, str, str], str] = {}
        self.allowed_gaps: list[dict] = []

    # -- 豁免 ----------------------------------------------------------------

    def ignore(self, error: Mapping[str, object], *, reason: str = "") -> None:
        self._ignored[ignore_key(error)] = str(reason or "")

    def restore(self, error: Mapping[str, object]) -> None:
        self._ignored.pop(ignore_key(error), None)

    def is_ignored(self, error: Mapping[str, object]) -> bool:
        return ignore_key(error) in self._ignored

    def ignored_keys(self) -> set[tuple[str, str, str, str]]:
        return set(self._ignored)

    def add_allowed_gap(self, geometry: Mapping[str, object]) -> None:
        self.allowed_gaps.append(dict(geometry))

    def blocking_errors(self, errors: Iterable[Mapping[str, object]] | None = None
                        ) -> list[dict[str, object]]:
        source = list(errors) if errors is not None else list(self.last_errors)
        return [dict(error) for error in source if not self.is_ignored(error)]

    def persist(self) -> dict[str, object]:
        return {
            "ignored": [
                {
                    "rule": key[0],
                    "layer_id": key[1],
                    "feature_id": key[2],
                    "other_feature_id": key[3],
                    "reason": reason,
                }
                for key, reason in self._ignored.items()
            ],
            "allowed_gaps": list(self.allowed_gaps),
            "workspace": dict(self.workspace) if self.workspace else None,
        }

    def restore_state(self, snapshot: Mapping[str, object] | None) -> None:
        self._ignored.clear()
        self.allowed_gaps = []
        self.workspace = None
        if not snapshot:
            return
        for entry in snapshot.get("ignored") or ():
            if not isinstance(entry, Mapping):
                continue
            self._ignored[ignore_key(entry)] = str(entry.get("reason") or "")
        for geom in snapshot.get("allowed_gaps") or ():
            if isinstance(geom, Mapping):
                self.allowed_gaps.append(dict(geom))
        workspace = snapshot.get("workspace")
        if isinstance(workspace, Mapping):
            self.workspace = dict(workspace)

    # -- 运行 ----------------------------------------------------------------

    def run_for_commit(self, stack, canvas, layer_ids) -> list[dict[str, object]]:
        """保存前自动全量检查；返回未忽略错误（门禁输入）。"""
        self.run(stack, canvas, layer_ids)
        return self.blocking_errors()

    def run(self, stack, canvas, layer_ids, *, extra_config=None) -> list[dict[str, object]]:
        config = {
            "layer_ids": [str(layer_id) for layer_id in layer_ids],
            "rules": ["overlap", "gap", "is_valid", "workspace_remainder"],
            "precision": 8,
        }
        if self.workspace:
            config["workspace"] = self.workspace
        if self.allowed_gaps:
            config["allowed_gaps"] = {
                "type": "FeatureCollection",
                "features": [
                    {"type": "Feature", "geometry": geom, "properties": {}}
                    for geom in self.allowed_gaps
                ],
            }
        if extra_config:
            config.update(extra_config)
        raw = stack.run_geometry_checks(canvas, json.dumps(config))
        payload = raw if isinstance(raw, dict) else json.loads(str(raw or "{}"))
        self.last_errors = [
            dict(error) for error in (payload.get("errors") or [])
            if isinstance(error, Mapping)
        ]
        harvested = payload.get("allowed_gaps")
        if isinstance(harvested, list) and harvested:
            self.allowed_gaps = [
                dict(geom) for geom in harvested if isinstance(geom, Mapping)
            ]
        self.last_run_at = datetime.now(timezone.utc).isoformat()
        return list(self.last_errors)

    def fix(self, stack, canvas, error_id, method: int = 0) -> dict[str, object]:
        raw = stack.fix_geometry_error(canvas, str(error_id), int(method))
        payload = raw if isinstance(raw, dict) else json.loads(str(raw or "{}"))
        if isinstance(payload.get("errors"), list):
            self.last_errors = [dict(e) for e in payload["errors"]
                                if isinstance(e, Mapping)]
        return payload

    def fix_all(self, stack, canvas, error_ids, method: int = 0) -> dict[str, object]:
        raw = stack.fix_geometry_errors(
            canvas, json.dumps([str(i) for i in error_ids]), int(method))
        payload = raw if isinstance(raw, dict) else json.loads(str(raw or "{}"))
        if isinstance(payload.get("errors"), list):
            self.last_errors = [dict(e) for e in payload["errors"]
                                if isinstance(e, Mapping)]
        return payload
