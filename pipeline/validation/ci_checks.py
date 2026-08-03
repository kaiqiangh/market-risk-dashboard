"""T05 数据静态校验（CI + 本地脚本共用，架构 §5#1 / PRD §20.2）。

覆盖检查项（与 validate-data.yml / scripts/validate_data.sh 等价）：
1. Schema 校验：全部 JSON 过 Pydantic 同构校验（禁隐式字段/NaN/枚举/时间）。
2. 必填字段：latest/* 已知数据集 + facts.json 必须存在；dashboard.json 存在时也必须通过。
3. 时间戳：envelope 时间 ISO 8601 UTC + Z（Pydantic UTCDateTime 强制）。
4. 数据质量：data_quality ∈ [0,1]（Pydantic 强制 + 显式复查）。
5. 风险分数范围：total_score / dimension.score / indicator.risk_score ∈ [0,100]。
6. NaN/Infinity：JSON 文本中的非法常量（Python json.loads 默认接受，这里拒绝）。
7. 重复新闻：news.json 中 id 重复 / (title+source+published_at) 重复。
8. 数据过期：按 freshness 五态检查 generated_at 相对期望频率（过期记为 WARNING，
   不阻塞发布——数据是静态快照，代码 PR 不应因数据时间而失败）。
9. 未知语言 key：analysis.*.json 的 language 必须属于受支持语言（zh-CN/en）。
10. 中英文缺失：analysis.zh-CN.json 与 analysis.en.json 成对存在（缺一则报错）；
    两者均缺失视为 AI 降级模式（WARNING）。
11. AI 双语结论不一致：复用 pipeline/analysis/validate.compare_bilingual。

退出码：0 = 通过（可含 WARNING）；1 = 存在 ERROR。
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from pipeline.analysis.contract import SUPPORTED_LANGUAGES
from pipeline.analysis.validate import compare_bilingual
from pipeline.schemas import (
    AnalysisDataset,
    CalendarEnvelope,
    CryptoEnvelope,
    DashboardEnvelope,
    EquitiesEnvelope,
    FactLayer,
    MacroEnvelope,
    NewsEnvelope,
    RiskEnvelope,
    SectorsEnvelope,
)
from pipeline.schemas.envelope import is_schema_compatible
from pipeline.validation.freshness import evaluate_freshness

# latest 文件名 → (模型, 期望频率 dataset key)；与 validate_all 保持一致
ENVELOPE_MODELS: dict[str, tuple[Any, str]] = {
    "macro.json": (MacroEnvelope, "macro"),
    "equities.json": (EquitiesEnvelope, "market"),
    "sectors.json": (SectorsEnvelope, "market"),
    "crypto.json": (CryptoEnvelope, "market"),
    "news.json": (NewsEnvelope, "news"),
    "calendar.json": (CalendarEnvelope, "calendar"),
    "risk.json": (RiskEnvelope, "analysis"),
    "dashboard.json": (DashboardEnvelope, "dashboard"),
}

# 自描述契约文件（不带 envelope）：存在时必须通过校验，不强制要求存在。
# facts.json 由管道每次运行产出；analysis.*.json 由 AI 自动化产出（缺失=降级模式）。
STANDALONE_MODELS: dict[str, Any] = {
    "facts.json": FactLayer,
    "analysis.zh-CN.json": AnalysisDataset,
    "analysis.en.json": AnalysisDataset,
}

# 可选的 envelope 文件（若出现则必须通过校验，不强制要求存在）
OPTIONAL_ENVELOPE_MODELS: dict[str, tuple[Any, str]] = {}

# 时间正则：ISO 8601 UTC（YYYY-MM-DDTHH:MM:SSZ 或带小数秒）
_ISO_UTC_RE = re.compile(
    r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?Z$"
)
_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_FRESHNESS_ENUM = {"fresh", "delayed", "stale", "missing", "degraded"}


def _reject_constant(name: str) -> Any:
    """JSON parse_constant：拒绝 NaN/Infinity/-Infinity（JSON 规范非法）。"""
    raise ValueError(f"JSON 含非法常量: {name}")


@dataclass
class CheckReport:
    """校验结果：errors 导致失败，warnings 仅提示。"""

    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    files_checked: int = 0

    def error(self, msg: str) -> None:
        self.errors.append(msg)

    def warn(self, msg: str) -> None:
        self.warnings.append(msg)

    @property
    def ok(self) -> bool:
        return not self.errors


def load_json_strict(path: Path) -> dict[str, Any]:
    """读取 JSON 并拒绝 NaN/Infinity 常量（Python 默认接受，这里显式拒绝）。"""
    text = path.read_text(encoding="utf-8")
    return json.loads(text, parse_constant=_reject_constant)


def check_latest(latest_dir: Path, report: CheckReport, now: datetime) -> None:
    """校验 latest/ 全部已知文件。"""
    if not latest_dir.exists():
        report.error(f"latest 目录缺失: {latest_dir}")
        return

    known = {**ENVELOPE_MODELS, **OPTIONAL_ENVELOPE_MODELS}
    for name, model_spec in known.items():
        path = latest_dir / name
        if not path.exists():
            if name in OPTIONAL_ENVELOPE_MODELS:
                continue
            report.error(f"{name}: 文件缺失（必填数据集）")
            continue
        report.files_checked += 1
        _check_one(path, name, model_spec, report, now)

    # 自描述契约文件（存在则校验；缺失按各自语义处理）
    for name, model in STANDALONE_MODELS.items():
        path = latest_dir / name
        if not path.exists():
            if name == "facts.json":
                report.error(f"{name}: 文件缺失（管道每次运行必须产出）")
            continue
        report.files_checked += 1
        _check_one(path, name, model, report, now)

    # 未知 analysis.*.json 语言（例如 analysis.fr.json）
    for path in sorted(latest_dir.glob("analysis.*.json")):
        lang = path.name[len("analysis.") : -len(".json")]
        if lang not in SUPPORTED_LANGUAGES:
            report.error(f"{path.name}: 未知语言 key {lang!r}（支持: {SUPPORTED_LANGUAGES}）")

    # 中英文成对：存在其一则必须两者都在；均缺失 → AI 降级模式（WARNING）
    zh = latest_dir / "analysis.zh-CN.json"
    en = latest_dir / "analysis.en.json"
    if zh.exists() != en.exists():
        missing = "analysis.en.json" if not en.exists() else "analysis.zh-CN.json"
        report.error(f"中英文分析文件缺失: {missing}（必须成对发布）")
    elif not zh.exists() and not en.exists():
        report.warn("analysis.*.json 均缺失：AI 简报未生成（降级模式，站点 AI 区块显示 degraded）")

    # 双语一致性（均存在时）
    if zh.exists() and en.exists():
        try:
            zh_obj = AnalysisDataset.model_validate(load_json_strict(zh))
            en_obj = AnalysisDataset.model_validate(load_json_strict(en))
            issues = compare_bilingual(zh_obj, en_obj)
            for issue in issues:
                report.error(f"AI 双语结论不一致: {issue}")
        except Exception as exc:  # noqa: BLE001
            report.error(f"AI 双语校验失败: {exc}")


def _check_one(path: Path, name: str, model_spec: tuple[Any, str] | Any, report: CheckReport, now: datetime) -> None:
    """校验单个文件：schema + 必填 + 时间戳 + 数据质量 + 风险范围 + 过期。"""
    try:
        data = load_json_strict(path)
    except (json.JSONDecodeError, OSError, ValueError) as exc:
        report.error(f"{name}: 无法读取/解析 JSON（含 NaN/Infinity?）: {exc}")
        return

    if name in ENVELOPE_MODELS or name in OPTIONAL_ENVELOPE_MODELS:
        model, dataset_key = model_spec  # type: ignore[misc]
        try:
            env = model.model_validate(data)
        except Exception as exc:  # noqa: BLE001
            report.error(f"{name}: schema 校验失败: {exc}")
            return
        # schema_version 兼容
        if not is_schema_compatible(str(env.schema_version)):
            report.error(f"{name}: schema_version {env.schema_version} 不兼容")
        # 时间戳格式（显式复查）
        for ts_field in ("generated_at", "source_updated_at"):
            value = getattr(env, ts_field, None)
            if value and not _ISO_UTC_RE.match(str(value)):
                report.error(f"{name}: {ts_field} 非 ISO 8601 UTC: {value!r}")
        # 数据质量
        if not (0.0 <= float(env.data_quality) <= 1.0):
            report.error(f"{name}: data_quality 超出 [0,1]: {env.data_quality}")
        # freshness 枚举
        if env.freshness_status not in _FRESHNESS_ENUM:
            report.error(f"{name}: freshness_status 非法: {env.freshness_status}")
        # 数据过期（时间维度；WARNING 不阻塞）
        status = evaluate_freshness(str(env.generated_at), _expected_minutes(dataset_key), now)
        if status == "stale":
            report.warn(f"{name}: 数据已过期（freshness=stale, generated_at={env.generated_at}）")
        elif status == "delayed":
            report.warn(f"{name}: 数据延迟（freshness=delayed, generated_at={env.generated_at}）")
        # 风险分数范围（risk.json 显式复查；payload 可能是 Pydantic 模型）
        if name == "risk.json":
            payload = env.payload
            if hasattr(payload, "model_dump"):
                payload = payload.model_dump()
            _check_risk_ranges(payload, report, name)
    elif name in STANDALONE_MODELS:
        model = STANDALONE_MODELS[name]
        try:
            obj = model.model_validate(data)
        except Exception as exc:  # noqa: BLE001
            report.error(f"{name}: schema 校验失败: {exc}")
            return
        if not is_schema_compatible(str(getattr(obj, "schema_version", "1.0.0"))):
            report.error(f"{name}: schema_version 不兼容")
        if name.startswith("analysis."):
            if getattr(obj, "language", None) not in SUPPORTED_LANGUAGES:
                report.error(f"{name}: language 非法: {getattr(obj, 'language', None)!r}")


def _expected_minutes(dataset_key: str) -> int:
    """期望更新间隔（分钟），读取 config/sources.yaml，失败回退 480。"""
    try:
        from pipeline.settings import settings

        expectations = settings.load_sources().get("expectations", {})
        minutes = int(expectations.get(dataset_key, {}).get("interval_minutes", 480))
        return minutes if minutes > 0 else 480
    except Exception:  # noqa: BLE001
        return 480


def _check_risk_ranges(payload: dict[str, Any], report: CheckReport, name: str) -> None:
    """风险分数范围显式复查（Pydantic Field 已约束，这里双保险）。"""
    try:
        total = float(payload["total_score"])
        if not (0.0 <= total <= 100.0):
            report.error(f"{name}: total_score 超出 [0,100]: {total}")
        for dim in payload.get("dimensions", []):
            score = float(dim.get("score", -1))
            if not (0.0 <= score <= 100.0):
                report.error(f"{name}: dimension {dim.get('key')} score 超出 [0,100]: {score}")
            for ind in dim.get("indicators", []):
                rs = ind.get("risk_score")
                if rs is not None:
                    rs = float(rs)
                    if not (0.0 <= rs <= 100.0):
                        report.error(
                            f"{name}: indicator {ind.get('key')} risk_score 超出 [0,100]: {rs}"
                        )
        confidence = payload.get("confidence")
        if confidence is not None and not (0.0 <= float(confidence) <= 1.0):
            report.error(f"{name}: confidence 超出 [0,1]: {confidence}")
    except (KeyError, TypeError, ValueError) as exc:
        report.error(f"{name}: 风险结构无法复查范围: {exc}")


def check_news_duplicates(latest_dir: Path, report: CheckReport) -> None:
    """重复新闻检查：id 重复 / (title+source+published_at) 重复。"""
    path = latest_dir / "news.json"
    if not path.exists():
        return
    try:
        data = load_json_strict(path)
        items = data.get("payload", {}).get("items", [])
    except Exception as exc:  # noqa: BLE001
        report.error(f"news.json: 重复新闻检查无法读取: {exc}")
        return
    ids: dict[str, int] = {}
    sigs: dict[str, int] = {}
    for i, item in enumerate(items):
        nid = item.get("id")
        if nid:
            ids[nid] = ids.get(nid, 0) + 1
        sig = (
            str(item.get("title", "")).strip().lower(),
            str(item.get("source", "")).strip().lower(),
            str(item.get("published_at", "")).strip(),
        )
        sigs[sig] = sigs.get(sig, 0) + 1
    for nid, count in ids.items():
        if count > 1:
            report.error(f"news.json: 重复新闻 id {nid!r}（出现 {count} 次）")
    for sig, count in sigs.items():
        if count > 1:
            report.error(f"news.json: 重复新闻 (title+source+published_at) {sig[0]!r}（出现 {count} 次）")


def check_history(data_dir: Path, report: CheckReport) -> None:
    """历史切片：文件可解析 + 行结构（date + total_score 范围）。"""
    for series in ("risk", "market"):
        for slice_name in ("30d", "90d", "daily"):
            path = data_dir / "history" / series / f"{slice_name}.json"
            if not path.exists():
                report.warn(f"history/{series}/{slice_name}.json 缺失（预热回填后应存在）")
                continue
            report.files_checked += 1
            try:
                rows = load_json_strict(path)
            except Exception as exc:  # noqa: BLE001
                report.error(f"history/{series}/{slice_name}.json: 解析失败: {exc}")
                continue
            if not isinstance(rows, list):
                report.error(f"history/{series}/{slice_name}.json: 顶层应为数组")
                continue
            for row in rows:
                if not isinstance(row, dict):
                    report.error(f"history/{series}/{slice_name}.json: 行非对象")
                    continue
                date = row.get("date")
                if not _DATE_RE.match(str(date or "")):
                    report.error(f"history/{series}/{slice_name}.json: 行 date 非法: {date!r}")
                score = row.get("total_score")
                if score is not None:
                    try:
                        score = float(score)
                    except (TypeError, ValueError):
                        report.error(f"history/{series}/{slice_name}.json: total_score 非法: {score!r}")
                    else:
                        if not (0.0 <= score <= 100.0):
                            report.error(f"history/{series}/{slice_name}.json: total_score 超出 [0,100]: {score}")
        index_path = data_dir / "history" / series / "index.json"
        if index_path.exists():
            report.files_checked += 1
            try:
                load_json_strict(index_path)
            except Exception as exc:  # noqa: BLE001
                report.error(f"history/{series}/index.json: 解析失败: {exc}")


def check_metadata_and_feeds(data_dir: Path, report: CheckReport) -> None:
    """metadata/* 与 feeds/* 可解析 + 基本结构。"""
    meta_checks = {
        "metadata/freshness.json": ("datasets", "schema_version"),
        "metadata/sources.json": ("domains", "schema_version"),
        "metadata/schema-version.json": ("schema_version",),
        "feeds/fedwatch-history.json": (),
    }
    for rel, keys in meta_checks.items():
        path = data_dir / rel
        if not path.exists():
            report.warn(f"{rel} 缺失（系统状态页数据源）")
            continue
        report.files_checked += 1
        try:
            data = load_json_strict(path)
        except Exception as exc:  # noqa: BLE001
            report.error(f"{rel}: 解析失败: {exc}")
            continue
        for key in keys:
            if key not in data:
                report.warn(f"{rel}: 缺少字段 {key!r}")


def run_all(data_dir: Path, now: datetime | None = None) -> CheckReport:
    """全量校验入口。data_dir 指向 public/data。"""
    now = now or datetime.now(timezone.utc)
    report = CheckReport()
    latest = data_dir / "latest"
    check_latest(latest, report, now)
    check_news_duplicates(latest, report)
    check_history(data_dir, report)
    check_metadata_and_feeds(data_dir, report)
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="T05 数据静态校验（Schema/必填/时间戳/质量/风险范围/NaN/重复/过期/语言/双语）"
    )
    parser.add_argument("--data-dir", type=Path, default=None, help="public/data 目录（默认 settings.data_dir）")
    args = parser.parse_args(argv)

    if args.data_dir is not None:
        data_dir = args.data_dir
    else:
        from pipeline.settings import settings

        data_dir = settings.data_dir

    report = run_all(data_dir)
    print(f"[validate_data] 检查 {report.files_checked} 个文件，ERROR {len(report.errors)} 个，WARNING {len(report.warnings)} 个")
    for issue in report.errors:
        print(f"  [ERROR] {issue}")
    for issue in report.warnings:
        print(f"  [WARN ] {issue}")

    if not report.ok:
        print("[validate_data] 结果：未通过（存在 ERROR）")
        return 1
    if report.warnings:
        print("[validate_data] 结果：通过（含 WARNING，请留意）")
    else:
        print("[validate_data] 结果：全部通过")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
