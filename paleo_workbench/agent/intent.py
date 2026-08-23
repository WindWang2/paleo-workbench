"""User Intent Understanding & Domain Request Parser for Paleo AI GIS Harness."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class TaskDomain(str, Enum):
    DATA_MANAGEMENT = "data"
    WELL_LOGGING = "well"
    SEISMIC_INTERPRETATION = "seismic"
    SPATIAL_GIS = "gis"
    SINGLE_FACTOR_MAPPING = "cartography"
    PALEOMAP_COMPILATION = "compilation"
    VISUALIZATION = "visualization"
    QUALITY_CONTROL = "qa"
    GENERAL = "general"


@dataclass(frozen=True)
class ParsedIntent:
    raw_query: str
    primary_domain: TaskDomain
    secondary_domains: tuple[TaskDomain, ...]
    action_goal: str
    parameters: dict[str, Any]
    target_horizon: str = ""
    factor_type: str = ""
    suggested_skills: tuple[str, ...] = ()
    requires_data: bool = True
    confidence: float = 1.0


class IntentParser:
    """Intelligent natural language & structured request parser."""

    _KEYWORDS = {
        TaskDomain.WELL_LOGGING: ["井", "测井", "曲线", "连井", "对比", "分层", "标志层", "GR", "DTW", "拉平"],
        TaskDomain.SEISMIC_INTERPRETATION: ["地震", "剖面", "切片", "相干", "Inline", "Crossline", "Time", "层位", "断层", "等值面"],
        TaskDomain.SPATIAL_GIS: ["空间", "缓冲区", "拓扑", "自相交", "投影", "坐标", "叠加", "相交", "多边形", "图层"],
        TaskDomain.SINGLE_FACTOR_MAPPING: ["单因素", "插值", "IDW", "砂地比", "孔隙度", "厚度", "各向异性", "廊道", "等值线", "网格"],
        TaskDomain.PALEOMAP_COMPILATION: ["古地理", "编图", "岩相", "相带", "沉积", "图例", "指北针", "比例尺", "排版", "出版"],
        TaskDomain.DATA_MANAGEMENT: ["导入", "资产", "版本", "血缘", "CAS", "RAW", "catalog", "存储", "清洗"],
        TaskDomain.QUALITY_CONTROL: ["质检", "QC", "合规", "残差", "检查", "修复", "自愈", "孤立点", "极值"],
        TaskDomain.VISUALIZATION: ["三维", "渲染", "视口", "导出", "SVG", "PDF", "PNG", "GeoTIFF", "截图", "高精"],
    }

    def parse(self, user_query: str, context: dict[str, Any] | None = None) -> ParsedIntent:
        """Parse natural language instruction into structured domain intent."""
        query = str(user_query).strip()
        matched_domains = []

        for domain, keywords in self._KEYWORDS.items():
            score = sum(1 for kw in keywords if kw.lower() in query.lower())
            if score > 0:
                matched_domains.append((score, domain))

        matched_domains.sort(key=lambda x: x[0], reverse=True)

        if matched_domains:
            primary_domain = matched_domains[0][1]
            secondary = tuple(d for s, d in matched_domains[1:])
        else:
            primary_domain = TaskDomain.GENERAL
            secondary = ()

        # Extract horizon / formation target
        horizon_match = re.search(r"([T|J|K|P|C|D|S|O|Є]\w+|\w+组|\w+段)", query)
        target_horizon = horizon_match.group(1) if horizon_match else ""

        # Extract factor type
        factor_type = ""
        if "砂地比" in query or "砂岩" in query:
            factor_type = "sand_ratio"
        elif "厚度" in query:
            factor_type = "thickness"
        elif "孔隙度" in query:
            factor_type = "porosity"
        elif "渗透率" in query:
            factor_type = "permeability"

        # Determine suggested skills
        suggested_skills = []
        if primary_domain == TaskDomain.SINGLE_FACTOR_MAPPING or "单因素" in query:
            suggested_skills.append("skill.single_factor_mapping_pipeline")
        if primary_domain == TaskDomain.WELL_LOGGING or "对比" in query or "对齐" in query:
            suggested_skills.append("skill.well_correlation_pipeline")
        if primary_domain == TaskDomain.PALEOMAP_COMPILATION or "编图" in query:
            suggested_skills.append("skill.comprehensive_paleomap_pipeline")

        parameters = dict(context or {})
        if target_horizon:
            parameters["target_horizon"] = target_horizon
        if factor_type:
            parameters["factor_type"] = factor_type

        return ParsedIntent(
            raw_query=query,
            primary_domain=primary_domain,
            secondary_domains=secondary,
            action_goal=query,
            parameters=parameters,
            target_horizon=target_horizon,
            factor_type=factor_type,
            suggested_skills=tuple(suggested_skills),
            requires_data=True,
            confidence=0.95 if matched_domains else 0.5,
        )


intent_parser = IntentParser()
