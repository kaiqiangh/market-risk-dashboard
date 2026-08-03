"""全局数据 Envelope（架构 §3.1）。

所有数据集文件必须包裹 BaseEnvelope；freshness_status 由管道统一判定
（不信任 Provider 自报，架构 §8.4）。本模块同时提供契约基类与共享原语：
- ContractModel：禁隐式字段 + 拒绝 NaN/Infinity（三件套硬约束，架构 §3.1）
- UTCDateTime：ISO 8601 UTC + Z 严格校验
- FreshnessStatus：五态枚举
"""

from __future__ import annotations

import math
import re
from typing import Annotated, Any, Literal

from pydantic import AfterValidator, BaseModel, ConfigDict, Field

FreshnessStatus = Literal["fresh", "delayed", "stale", "missing", "degraded"]

# 数据契约版本（单一事实源；analysis/contract.py 复用）
SCHEMA_VERSION = "1.0.0"


def is_schema_compatible(file_version: str, current_version: str = SCHEMA_VERSION) -> bool:
    """向后兼容检查。

    规则：major 必须一致（结构不兼容）；file minor ≤ current minor（新字段在旧版本
    中不允许出现，反之旧文件缺省字段由模型默认值补齐）。返回 False 表示拒绝发布。
    """

    def _parts(version: str) -> list[int]:
        try:
            return [int(part) for part in version.split(".")[:3]]
        except ValueError:
            return []

    fv, cv = _parts(file_version), _parts(current_version)
    if not fv or not cv:
        return False
    return fv[0] == cv[0] and fv[1] <= cv[1]

# ISO 8601 UTC + Z，如 2026-08-03T10:00:00Z（允许毫秒小数位）
_UTC_DATETIME_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?Z$")


def validate_utc_datetime(value: str) -> str:
    """严格校验 ISO 8601 UTC + Z 时间字符串。"""
    if not isinstance(value, str) or not _UTC_DATETIME_RE.match(value):
        raise ValueError(
            f"时间必须为 ISO 8601 UTC + Z 格式（如 2026-08-03T10:00:00Z），收到: {value!r}"
        )
    return value


UTCDateTime = Annotated[str, AfterValidator(validate_utc_datetime)]


class ContractModel(BaseModel):
    """数据契约基类。

    硬约束（架构 §3.1/§8.3）：
    - extra="forbid"：禁止隐式字段（JSON Schema additionalProperties=false 同构）
    - allow_inf_nan=False：拒绝 NaN/Infinity（所有 float 字段生效）
    """

    model_config = ConfigDict(extra="forbid", allow_inf_nan=False, validate_assignment=True)

    @classmethod
    def parse_finite(cls, value: Any) -> "ContractModel":
        """便捷入口：解析并确保拒绝 NaN/Infinity（供测试与管道复用）。"""
        return cls.model_validate(value)


class BaseEnvelope(ContractModel):
    """全局数据信封（架构 §3.1）。

    payload 为业务数据；各数据集模型通过子类覆写 payload 类型做强校验
    （如 MacroEnvelope(payload: MacroDataset)）。
    """

    generated_at: UTCDateTime
    schema_version: str = Field(min_length=1, description='语义化版本，如 "1.0.0"')
    source: str | list[str]
    source_updated_at: UTCDateTime | None = None
    freshness_status: FreshnessStatus
    data_quality: float = Field(ge=0.0, le=1.0, description="数据质量 0-1")
    payload: dict[str, Any]


def ensure_no_nan_inf(value: float) -> float:
    """防御性检查（供显式调用；正常路径由 allow_inf_nan=False 拦截）。"""
    if value is not None and isinstance(value, float) and (math.isnan(value) or math.isinf(value)):
        raise ValueError("数值禁止为 NaN/Infinity")
    return value
