"""全量校验入口（架构 §1.1/§3.5：管道内 + CI 复用）。

对 latest/*.json 做：schema 校验（Pydantic）+ schema_version 兼容 + freshness 标注。
任何校验失败不得发布（三件套契约）。
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from pipeline.schemas import (
    AnalysisDataset,
    CalendarEnvelope,
    CryptoEnvelope,
    EquitiesEnvelope,
    FactLayer,
    MacroEnvelope,
    NewsEnvelope,
    RiskEnvelope,
    SectorsEnvelope,
)
from pipeline.schemas.envelope import is_schema_compatible
from pipeline.validation.freshness import expected_interval_minutes_for, evaluate_freshness

# latest 文件名 → (模型, 期望间隔 dataset key)
DATASET_MODELS: dict[str, tuple[Any, str]] = {
    "macro.json": (MacroEnvelope, "macro"),
    "equities.json": (EquitiesEnvelope, "market"),
    "sectors.json": (SectorsEnvelope, "market"),
    "crypto.json": (CryptoEnvelope, "market"),
    "news.json": (NewsEnvelope, "news"),
    "calendar.json": (CalendarEnvelope, "calendar"),
    "risk.json": (RiskEnvelope, "analysis"),
}

# 自描述契约文件
STANDALONE_MODELS: dict[str, Any] = {
    "facts.json": FactLayer,
    "analysis.zh-CN.json": AnalysisDataset,
    "analysis.en.json": AnalysisDataset,
}


@dataclass
class ValidationReport:
    ok: bool = True
    files_checked: int = 0
    issues: list[str] = field(default_factory=list)

    def add_issue(self, issue: str) -> None:
        self.ok = False
        self.issues.append(issue)


def validate_file(path: Path) -> list[str]:
    """校验单个数据文件，返回问题列表（空 = 通过）。"""
    issues: list[str] = []
    name = path.name
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        return [f"{name}: 无法读取 JSON: {exc}"]

    if name in DATASET_MODELS:
        model, dataset_key = DATASET_MODELS[name]
        try:
            env = model.model_validate(data)
        except Exception as exc:  # noqa: BLE001
            return [f"{name}: schema 校验失败: {exc}"]
        if not is_schema_compatible(str(env.schema_version)):
            issues.append(f"{name}: schema_version {env.schema_version} 不兼容")
        # freshness 标注（时间维度 + 枚举有效性）
        status = evaluate_freshness(env.generated_at, expected_interval_minutes_for(dataset_key, 480))
        if status == "stale":
            issues.append(f"{name}: 数据已过期（freshness=stale）")
    elif name in STANDALONE_MODELS:
        model = STANDALONE_MODELS[name]
        try:
            obj = model.model_validate(data)
        except Exception as exc:  # noqa: BLE001
            return [f"{name}: schema 校验失败: {exc}"]
        if not is_schema_compatible(str(getattr(obj, "schema_version", "1.0.0"))):
            issues.append(f"{name}: schema_version 不兼容")
    else:
        issues.append(f"{name}: 未知数据集文件（未注册 schema）")

    return issues


def validate_all(latest_dir: Path, strict: bool = True) -> ValidationReport:
    """校验 latest/ 下全部已知文件。strict=False 时缺失文件不视为失败。"""
    report = ValidationReport()
    known = {**DATASET_MODELS, **STANDALONE_MODELS}
    for name, _model in known.items():
        path = latest_dir / name
        if not path.exists():
            if strict:
                report.add_issue(f"{name}: 文件缺失")
            continue
        report.files_checked += 1
        for issue in validate_file(path):
            report.add_issue(issue)
    return report


def main(latest_dir: str | None = None) -> int:
    from pipeline.settings import settings

    target = Path(latest_dir) if latest_dir else settings.data_dir / "latest"
    report = validate_all(target, strict=False)
    print(f"[validate_all] 检查 {report.files_checked} 个文件，问题 {len(report.issues)} 个")
    for issue in report.issues:
        print(f"  - {issue}")
    return 0 if report.ok else 1
