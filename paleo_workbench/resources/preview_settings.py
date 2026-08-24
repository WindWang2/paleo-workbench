from __future__ import annotations

from dataclasses import asdict, dataclass, fields
import hashlib
import json
from typing import Literal, Mapping

_INTEGER_RANGES = {
    "font_size": (8, 32),
    "text_limit_kib": (16, 4_096),
    "table_max_rows": (20, 2_000),
    "table_max_columns": (5, 200),
    "geotiff_thumbnail_px": (128, 2_048),
    "pdf_zoom_percent": (25, 400),
    "json_limit_mib": (1, 64),
    "json_array_collapse_threshold": (10, 10_000),
    "json_expand_depth": (0, 8),
    "media_volume": (0, 100),
    "geoviz_max_curves": (1, 64),
    "geoviz_max_depth_samples": (100, 50_000),
    "geoviz_max_slice_axis": (64, 4_096),
    "geoviz_max_points": (1_000, 1_000_000),
    "geoviz_surface_grid_size": (32, 1_024),
}

_BOOLEAN_FIELDS = {
    "show_metadata",
    "wrap_text",
    "auto_fit_columns",
    "smooth_images",
    "show_geo_metadata",
    "media_autoplay",
}


@dataclass(frozen=True)
class PreviewSettings:
    """Immutable user preferences shared by every data preview request."""

    font_size: int = 12
    show_metadata: bool = True
    text_limit_kib: int = 256
    wrap_text: bool = False
    table_max_rows: int = 200
    table_max_columns: int = 40
    auto_fit_columns: bool = True
    smooth_images: bool = True
    geotiff_thumbnail_px: int = 256
    show_geo_metadata: bool = True
    pdf_fit_mode: Literal["page", "width", "custom"] = "width"
    pdf_zoom_percent: int = 100
    json_limit_mib: int = 5
    json_array_collapse_threshold: int = 100
    json_expand_depth: int = 2
    media_autoplay: bool = False
    media_volume: int = 70
    geoviz_max_curves: int = 12
    geoviz_max_depth_samples: int = 2_000
    geoviz_max_slice_axis: int = 512
    geoviz_max_points: int = 50_000
    geoviz_surface_grid_size: int = 256
    density: Literal["comfortable", "compact"] = "comfortable"
    theme_mode: Literal["light", "system"] = "light"

    def __post_init__(self) -> None:
        if self.density not in ("comfortable", "compact"):
            raise ValueError("density must be 'comfortable' or 'compact'")
        if self.theme_mode not in ("light", "system"):
            raise ValueError("theme_mode must be 'light' or 'system'")
        for name in _BOOLEAN_FIELDS:
            if type(getattr(self, name)) is not bool:
                raise TypeError(f"{name} must be a boolean")
        for name, (minimum, maximum) in _INTEGER_RANGES.items():
            value = getattr(self, name)
            if not isinstance(value, int) or isinstance(value, bool):
                raise TypeError(f"{name} must be an integer")
            if not minimum <= value <= maximum:
                raise ValueError(f"{name} must be between {minimum} and {maximum}")
        if self.pdf_fit_mode not in {"page", "width", "custom"}:
            raise ValueError("pdf_fit_mode must be page, width, or custom")

    @classmethod
    def defaults(cls) -> "PreviewSettings":
        return cls()

    @classmethod
    def from_mapping(cls, values: Mapping[str, object]) -> "PreviewSettings":
        known = {field.name for field in fields(cls)}
        return cls(**{name: values[name] for name in known if name in values})

    def to_mapping(self) -> dict[str, object]:
        return asdict(self)

    def fingerprint(self) -> str:
        payload = json.dumps(
            self.to_mapping(),
            ensure_ascii=True,
            sort_keys=True,
            separators=(",", ":"),
        )
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]

    def to_geoviz_options(self):
        from geoviz import PreviewOptions

        return PreviewOptions(
            profile="local",
            max_curves=self.geoviz_max_curves,
            max_depth_samples=self.geoviz_max_depth_samples,
            max_slice_axis=self.geoviz_max_slice_axis,
            max_points=self.geoviz_max_points,
            surface_grid_size=self.geoviz_surface_grid_size,
        )
