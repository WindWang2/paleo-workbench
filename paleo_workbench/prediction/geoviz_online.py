"""Authenticated external single-well inference API client.

The well-log prediction page keeps the historic ``geoviz_online`` provider
name, but its wire protocol is the platform's authenticated inference API.
The client is deliberately Qt-free so every online invocation can use the
catalog-backed inference lifecycle and preserve a safe diagnostic trail.
"""

from __future__ import annotations

import json
import math
import os
import time
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urljoin, urlsplit
from urllib.request import Request, urlopen


INFERENCE_API_BASE_URL = "http://118.178.238.153:3100/api/v1"
DEFAULT_MODEL_VERSION_ID = "ef107a7e-e222-4326-81ee-65d1a3a23eff"
ONLINE_WAIT_TIMEOUT_SECONDS = 30
ONLINE_REQUEST_TIMEOUT_SECONDS = 120
ONLINE_POLL_TIMEOUT_SECONDS = 600

# Compatibility aliases for callers that used the old names.  They refer to
# the new API, never the retired GeoVizEngine test route.
GEOVIZ_ONLINE_ENDPOINT = INFERENCE_API_BASE_URL
GEOVIZ_MICROFACIES_MODEL_VERSION = DEFAULT_MODEL_VERSION_ID


class GeoVizOnlinePredictionError(RuntimeError):
    """The external inference API could not produce a usable result."""


def online_endpoint() -> str:
    """Return the configured API base URL without a trailing slash."""
    value = (
        os.environ.get("PALEO_GEOVIZ_ONLINE_BASE_URL")
        or os.environ.get("PALEO_GEOVIZ_ONLINE_ENDPOINT")
        or INFERENCE_API_BASE_URL
    )
    return str(value).strip().rstrip("/")


def online_api_key() -> str:
    """Return the session-only API key, never placing it in run metadata."""
    # Direct provider/test invocation does not pass through the Qt entry point.
    from paleo_workbench.env_bootstrap import load_local_env

    load_local_env()
    key = str(os.environ.get("PALEO_GEOVIZ_API_KEY") or "").strip()
    if not key:
        raise GeoVizOnlinePredictionError(
            "未配置推理 API 密钥。请在启动程序前设置 PALEO_GEOVIZ_API_KEY"
        )
    return key


def online_model_version_id() -> str:
    """Return a pinned model version unless the operator explicitly overrides it."""
    return str(
        os.environ.get("PALEO_GEOVIZ_MODEL_VERSION_ID")
        or DEFAULT_MODEL_VERSION_ID
    ).strip()


def online_wait_timeout_seconds() -> int:
    """Return the API's bounded synchronous wait period (1–120 seconds)."""
    return _bounded_env_int(
        "PALEO_GEOVIZ_ONLINE_WAIT_TIMEOUT_SECONDS",
        ONLINE_WAIT_TIMEOUT_SECONDS,
        minimum=1,
        maximum=120,
    )


def online_timeout_seconds() -> int:
    """Compatibility name for the request timeout used by older callers."""
    return _bounded_env_int(
        "PALEO_GEOVIZ_ONLINE_REQUEST_TIMEOUT_SECONDS",
        ONLINE_REQUEST_TIMEOUT_SECONDS,
        minimum=1,
        maximum=600,
    )


def online_poll_timeout_seconds() -> int:
    """Maximum wall-clock time spent polling an accepted prediction job."""
    return _bounded_env_int(
        "PALEO_GEOVIZ_ONLINE_POLL_TIMEOUT_SECONDS",
        ONLINE_POLL_TIMEOUT_SECONDS,
        minimum=1,
        maximum=3600,
    )


def build_single_well_payload(
    well_name: str,
    well_log: Any,
    *,
    model_version_id: str,
    required_curves: list[str],
    minimum_rows: int,
    wait_timeout_seconds: int = ONLINE_WAIT_TIMEOUT_SECONDS,
) -> dict[str, Any]:
    """Build one API request from exactly the curves required by a model.

    A row is retained only if it contains a finite depth and finite values for
    every required curve.  This prevents unrelated LAS columns, NaNs, and
    partial rows from reaching the remote service.
    """
    resolved_name = str(well_name or getattr(well_log, "well_name", "") or "well-1")
    schema_curves = [str(name).strip() for name in required_curves if str(name).strip()]
    if not schema_curves:
        raise GeoVizOnlinePredictionError("模型未声明可用于预测的测井曲线列")
    if not str(model_version_id or "").strip():
        raise GeoVizOnlinePredictionError("未选择可调用的模型版本")

    curve_maps = _curve_maps(well_log)
    required_maps: dict[str, dict[float, float | None]] = {}
    for curve_name in schema_curves:
        mapping = curve_maps.get(curve_name.casefold())
        if mapping is None:
            raise GeoVizOnlinePredictionError(
                f"当前井缺少模型要求的曲线列: {curve_name}"
            )
        required_maps[curve_name] = mapping

    depths: set[float] = set()
    for mapping in required_maps.values():
        depths.update(mapping)
    rows: list[dict[str, float]] = []
    for depth in sorted(depths):
        row: dict[str, float] = {"深度": depth}
        for curve_name, mapping in required_maps.items():
            value = mapping.get(depth)
            if value is None:
                break
            row[curve_name] = value
        else:
            rows.append(row)

    required_count = max(1, int(minimum_rows or 1))
    if len(rows) < required_count:
        raise GeoVizOnlinePredictionError(
            "有效的连续递增深度点不足模型窗口："
            f"当前 {len(rows)} 行，模型要求至少 {required_count} 行（窗口）"
        )

    return {
        "modelVersionId": str(model_version_id).strip(),
        "waitTimeoutSeconds": max(1, min(120, int(wait_timeout_seconds))),
        "wells": [{"wellName": resolved_name, "rows": rows}],
    }


def run_single_well_prediction(
    well_name: str,
    well_log: Any,
    *,
    api_key: str,
    base_url: str | None = None,
    model_version_id: str | None = None,
    wait_timeout_seconds: int | None = None,
    request_timeout_seconds: int | None = None,
    poll_timeout_seconds: int | None = None,
) -> dict[str, Any]:
    """Discover the model contract, submit one well, and poll when needed."""
    key = str(api_key or "").strip()
    if not key:
        raise GeoVizOnlinePredictionError("未配置推理 API 密钥")
    endpoint = str(base_url or online_endpoint()).strip().rstrip("/")
    if not endpoint:
        raise GeoVizOnlinePredictionError("未配置线上推理服务地址")

    selected_model_id = str(model_version_id or online_model_version_id()).strip()
    request_timeout = (
        online_timeout_seconds()
        if request_timeout_seconds is None
        else max(1, int(request_timeout_seconds))
    )
    poll_timeout = (
        online_poll_timeout_seconds()
        if poll_timeout_seconds is None
        else max(1, int(poll_timeout_seconds))
    )
    wait_timeout = (
        online_wait_timeout_seconds()
        if wait_timeout_seconds is None
        else max(1, min(120, int(wait_timeout_seconds)))
    )

    _status, model_listing = _request_json(
        f"{endpoint}/models", api_key=key, timeout_seconds=request_timeout
    )
    model = _select_model(model_listing, selected_model_id)
    input_schema = model.get("inputSchema")
    if not isinstance(input_schema, dict):
        raise GeoVizOnlinePredictionError("模型未返回输入契约 inputSchema")
    required_curves = input_schema.get("curves")
    if not isinstance(required_curves, list):
        raise GeoVizOnlinePredictionError("模型输入契约缺少 curves")
    minimum_rows = _positive_int(input_schema.get("window"), fallback=1)

    payload = build_single_well_payload(
        well_name,
        well_log,
        model_version_id=str(model.get("id") or selected_model_id),
        required_curves=[str(name) for name in required_curves],
        minimum_rows=minimum_rows,
        wait_timeout_seconds=wait_timeout,
    )
    status_code, response = _request_json(
        f"{endpoint}/predict",
        api_key=key,
        payload=payload,
        timeout_seconds=request_timeout,
    )
    response = _wait_for_completion(
        endpoint,
        key,
        response,
        status_code=status_code,
        request_timeout_seconds=request_timeout,
        poll_timeout_seconds=poll_timeout,
    )
    regions = response_records(response)
    completed_model = response.get("model")
    completed_model = completed_model if isinstance(completed_model, dict) else model
    return {
        "endpoint": endpoint,
        "request_row_count": len(payload["wells"][0]["rows"]),
        "remote_model_version": str(completed_model.get("id") or model.get("id") or selected_model_id),
        "remote_model_name": str(completed_model.get("name") or model.get("name") or ""),
        "remote_model_display_version": str(
            completed_model.get("version") or model.get("version") or ""
        ),
        "job_id": str(response.get("jobId") or ""),
        "api_summary": response.get("summary") if isinstance(response.get("summary"), dict) else {},
        "predicted_regions": regions,
    }


def response_records(response_data: dict[str, Any]) -> list[dict[str, Any]]:
    """Normalize API predictions into catalog-backed facies intervals."""
    items = response_data.get("predictions")
    if not isinstance(items, list) or not items:
        raise GeoVizOnlinePredictionError("线上推理未返回任何沉积相预测结果")

    records: list[dict[str, Any]] = []
    for index, item in enumerate(items, start=1):
        if not isinstance(item, dict):
            continue
        depth = _finite_number(item.get("depth"))
        confidence = _finite_number(item.get("confidence"))
        facies = str(item.get("label") or "").strip()
        if depth is None or confidence is None or not facies:
            continue
        records.append(
            {
                "region_id": f"inference_api_{index}",
                "_sample_depth": depth,
                "facies": facies,
                "probability": confidence,
            }
        )
    if not records:
        raise GeoVizOnlinePredictionError("线上推理结果缺少深度、相名或置信度")
    from paleo_workbench.viz.prediction_helpers import normalize_sampled_prediction_regions

    records = normalize_sampled_prediction_regions(
        records, force=True, depth_key="_sample_depth"
    )
    for record in records:
        record.pop("_sample_depth", None)
    return records


def _curve_maps(well_log: Any) -> dict[str, dict[float, float | None]]:
    maps: dict[str, dict[float, float | None]] = {}
    for curve in list(getattr(well_log, "curves", None) or []):
        curve_name = str(getattr(curve, "name", "") or "").strip()
        if not curve_name:
            continue
        mapping: dict[float, float | None] = {}
        for depth, value in zip(
            list(getattr(curve, "depth", None) or []),
            list(getattr(curve, "values", None) or []),
        ):
            parsed_depth = _finite_number(depth)
            if parsed_depth is not None:
                mapping[parsed_depth] = _finite_number(value)
        # As with LAS viewers, the last duplicate mnemonic wins.
        maps[curve_name.casefold()] = mapping
    return maps


def _request_json(
    url: str,
    *,
    api_key: str,
    timeout_seconds: int,
    payload: dict[str, Any] | None = None,
) -> tuple[int, dict[str, Any]]:
    """Call an API endpoint and turn transport failures into safe diagnostics."""
    encoded: bytes | None = None
    headers = {"X-API-Key": api_key, "Accept": "application/json"}
    if payload is not None:
        try:
            encoded = json.dumps(payload, ensure_ascii=False, allow_nan=False).encode("utf-8")
        except (TypeError, ValueError) as exc:
            raise GeoVizOnlinePredictionError(f"无法组织线上预测请求数据: {exc}") from exc
        headers["Content-Type"] = "application/json"
    request = Request(url, data=encoded, headers=headers, method="POST" if encoded else "GET")
    try:
        with urlopen(request, timeout=timeout_seconds) as response:  # noqa: S310 -- explicit user action
            raw_response = response.read().decode("utf-8")
            status = int(getattr(response, "status", 200) or 200)
    except HTTPError as exc:
        raise GeoVizOnlinePredictionError(
            f"推理服务请求失败（HTTP {exc.code}）{_http_error_detail(exc)}"
        ) from exc
    except (URLError, TimeoutError, OSError) as exc:
        raise GeoVizOnlinePredictionError(f"无法连接线上推理服务: {exc}") from exc

    try:
        response_data = json.loads(raw_response)
    except json.JSONDecodeError as exc:
        raise GeoVizOnlinePredictionError("线上推理服务返回了无效 JSON") from exc
    if not isinstance(response_data, dict):
        raise GeoVizOnlinePredictionError("线上推理服务返回格式无效")
    return status, response_data


def _select_model(listing: dict[str, Any], requested_id: str) -> dict[str, Any]:
    models = listing.get("models")
    if not isinstance(models, list):
        raise GeoVizOnlinePredictionError("推理服务未返回可调用模型列表")
    if requested_id == "latest":
        for item in models:
            if isinstance(item, dict):
                return item
    for item in models:
        if isinstance(item, dict) and str(item.get("id") or "") == requested_id:
            return item
    raise GeoVizOnlinePredictionError(
        f"当前 API 密钥无权调用或找不到模型版本: {requested_id or 'latest'}"
    )


def _wait_for_completion(
    base_url: str,
    api_key: str,
    response: dict[str, Any],
    *,
    status_code: int,
    request_timeout_seconds: int,
    poll_timeout_seconds: int,
) -> dict[str, Any]:
    status = str(response.get("status") or "").lower()
    if status == "completed":
        return response
    if status in {"failed", "canceled"}:
        raise GeoVizOnlinePredictionError(_terminal_error(response))
    if status_code != 202 and status not in {"queued", "preprocessing", "predicting"}:
        raise GeoVizOnlinePredictionError(
            f"线上推理服务返回了未知任务状态: {status or '未提供'}"
        )

    poll_url = _trusted_poll_url(base_url, response.get("pollUrl"))
    deadline = time.monotonic() + poll_timeout_seconds
    while True:
        delay_seconds = _poll_delay_seconds(response.get("pollAfterMs"))
        if time.monotonic() + delay_seconds > deadline:
            raise GeoVizOnlinePredictionError("线上推理轮询超时，任务仍未完成")
        time.sleep(delay_seconds)
        status_code, response = _request_json(
            poll_url,
            api_key=api_key,
            timeout_seconds=request_timeout_seconds,
        )
        status = str(response.get("status") or "").lower()
        if status == "completed":
            return response
        if status in {"failed", "canceled"}:
            raise GeoVizOnlinePredictionError(_terminal_error(response))
        if status_code != 202 and status not in {"queued", "preprocessing", "predicting"}:
            raise GeoVizOnlinePredictionError(
                f"线上推理服务返回了未知任务状态: {status or '未提供'}"
            )
        new_poll_url = response.get("pollUrl")
        if new_poll_url:
            poll_url = _trusted_poll_url(base_url, new_poll_url)


def _trusted_poll_url(base_url: str, poll_url: Any) -> str:
    value = str(poll_url or "").strip()
    if not value:
        raise GeoVizOnlinePredictionError("线上推理任务未提供轮询地址")
    base = urlsplit(base_url)
    target = urlsplit(value)
    if target.scheme or target.netloc:
        if (target.scheme, target.netloc) != (base.scheme, base.netloc):
            raise GeoVizOnlinePredictionError("线上推理任务返回了不受信任的轮询地址")
        return value
    return urljoin(f"{base_url}/", value)


def _terminal_error(response: dict[str, Any]) -> str:
    detail = response.get("error") or response.get("latestMessage") or response.get("message")
    if isinstance(detail, dict):
        detail = detail.get("message") or detail.get("code") or str(detail)
    return f"线上推理任务失败: {str(detail or '服务未提供失败原因')[:1000]}"


def _poll_delay_seconds(value: Any) -> float:
    try:
        delay = float(value) / 1000.0
    except (TypeError, ValueError):
        delay = 2.0
    return max(0.05, min(delay, 10.0))


def _positive_int(value: Any, *, fallback: int) -> int:
    try:
        return max(1, int(value))
    except (TypeError, ValueError):
        return fallback


def _bounded_env_int(name: str, default: int, *, minimum: int, maximum: int) -> int:
    try:
        value = int(os.environ.get(name, default))
    except (TypeError, ValueError):
        return default
    return max(minimum, min(value, maximum))


def _finite_number(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _http_error_detail(error: HTTPError) -> str:
    try:
        body = error.read().decode("utf-8", errors="replace").strip()
    except Exception:
        return ""
    if not body:
        return ""
    try:
        decoded = json.loads(body)
        if isinstance(decoded, dict):
            nested = decoded.get("error")
            if isinstance(nested, dict):
                body = str(nested.get("message") or nested.get("code") or nested)
            else:
                body = str(decoded.get("message") or decoded.get("error") or body)
    except json.JSONDecodeError:
        pass
    return f": {body[:1000]}"


__all__ = [
    "DEFAULT_MODEL_VERSION_ID",
    "GEOVIZ_MICROFACIES_MODEL_VERSION",
    "GEOVIZ_ONLINE_ENDPOINT",
    "INFERENCE_API_BASE_URL",
    "GeoVizOnlinePredictionError",
    "build_single_well_payload",
    "online_api_key",
    "online_endpoint",
    "online_model_version_id",
    "online_poll_timeout_seconds",
    "online_timeout_seconds",
    "online_wait_timeout_seconds",
    "response_records",
    "run_single_well_prediction",
]
