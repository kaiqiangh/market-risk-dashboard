"""管道 CLI 入口（架构 §1.3 冻结命令集 + T03 全量实现 + Fix 轮次）。

命令：
  --full          全量（默认）：采集+指标+风险+事实层+存储
  --market-only   仅行情/加密/A股
  --macro-only    仅宏观（FRED + FedWatch）
  --news-only     仅新闻
  --analysis-only 仅 AI 分析文件校验/中译合并（不采集）
  --fact-layer    只重建事实层（不采集）
  --backfill      预热回填 30-90 天历史（FedWatch 除外）
  --dry-run       试跑不写盘
  --locale        分析语言

Fix 轮次新增/修订：
- P0-4：AI 分析缺失时 metadata/freshness.json 的 analysis 域 = degraded（架构 §1.5）
- P1-5：--full 产出 latest/dashboard.json（首页聚合）
- P1-6：中译合并写入 metadata/translations.json 记录
- P1-7：写盘后统一 freshness 判定（validation/freshness.finalize_freshness）再落盘
- P2-9：writer.read_history 公开方法替代私有 _read_json
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path
from typing import Any

from pipeline import __version__
from pipeline.collectors import CalendarCollector, MacroCollector, MarketCollector, NewsCollector
from pipeline.factlayer import FactLayerBuilder
from pipeline.providers import ProviderRegistry, build_registry
from pipeline.report import write_run_report
from pipeline.risk.model import RiskModel
from pipeline.schemas import (
    DashboardAsset,
    DashboardEnvelope,
    DashboardPayload,
    RiskEnvelope,
)
from pipeline.settings import settings
from pipeline.storage import StorageWriter
from pipeline.universe import AssetUniverse
from pipeline.utils import now_utc
from pipeline.validation.freshness import finalize_freshness
from pipeline.validation.validate_all import validate_all

COMMANDS = (
    "full",
    "market-only",
    "macro-only",
    "news-only",
    "analysis-only",
    "fact-layer",
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="pipeline.run", description="Market Risk Dashboard 数据管道 CLI")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--full", action="store_true", help="全量（默认）：采集+指标+风险+事实层+存储")
    mode.add_argument("--market-only", action="store_true", help="仅行情/加密/A股")
    mode.add_argument("--macro-only", action="store_true", help="仅宏观（FRED + FedWatch）")
    mode.add_argument("--news-only", action="store_true", help="仅新闻采集")
    mode.add_argument("--analysis-only", action="store_true", help="仅 AI 分析文件校验/合并（不采集）")
    mode.add_argument("--fact-layer", action="store_true", help="只重建事实层（不采集）")
    parser.add_argument("--locale", choices=["zh-CN", "en"], default=None, help="分析语言（默认双语）")
    parser.add_argument("--dry-run", action="store_true", help="试跑：校验配置与参数，不写盘")
    parser.add_argument("--backfill", action="store_true", help="预热回填 30-90 天历史（FedWatch 除外）")
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    return parser


def _resolve_command(args: argparse.Namespace) -> str:
    for flag in COMMANDS:
        if getattr(args, flag.replace("-", "_")):
            return flag
    return "full"


# ============================================================
# 风险上下文组装
# ============================================================

def _build_risk_context(
    macro: Any,
    equities: Any,
    crypto: Any,
    histories: dict[str, list[dict[str, Any]]],
    qualities: list[float],
    prev_total_score: float | None,
    prev_dim_scores: dict[str, float] | None,
    risk_history: list[dict[str, Any]],
    series_history: dict[str, list[dict[str, Any]]],
) -> dict[str, Any]:
    """把采集结果组装成 RiskModel.score 所需上下文。"""
    from pipeline.indicators.breadth import breadth_snapshot
    from pipeline.indicators.trend import trend_snapshot

    breadth = breadth_snapshot(histories)
    trend = trend_snapshot(histories)

    # 跨资产确认信号（MVP 简化 7 项）
    vix = _macro_value(macro, "rates", "vixcls")
    hy = _macro_value(macro, "credit", "bamlh0a0hym2")
    dxy = _macro_value(macro, "fx", "dtwexbgs")
    real_rate = _macro_value(macro, "rates", "dfii10")
    spy_change = _latest_change(histories.get("SPY"))
    iwm_relative = breadth.get("small_cap_relative")
    btc_change = crypto.payload.assets[0].change_1d if crypto.payload.assets else None

    signals = [
        spy_change is not None and spy_change < 0,
        hy is not None and hy > 4.0,
        dxy is not None and dxy > 105,
        real_rate is not None and real_rate > 1.5,
        btc_change is not None and btc_change < 0,
        iwm_relative is not None and iwm_relative < 0,
    ]
    confirmation = round(sum(1 for s in signals if s) / len(signals), 4) if signals else None

    data_quality = sum(qualities) / len(qualities) if qualities else 1.0
    return {
        "macro": macro.payload,
        "equities": equities.payload,
        "crypto": crypto.payload,
        "histories": histories,
        "breadth": breadth,
        "trend": trend,
        "cross_asset": {"confirmation": confirmation},
        "data_quality": round(data_quality, 4),
        "series_history": series_history,
        "_prev_total_score": prev_total_score,
        "_prev_dim_scores": prev_dim_scores,
        "_risk_history": risk_history,
    }


def _macro_value(macro: Any, group: str, key: str) -> float | None:
    for ind in getattr(macro.payload, group, []):
        if ind.key == key:
            return ind.value
    return None


def _latest_change(rows: list[dict[str, Any]]) -> float | None:
    if not rows or len(rows) < 2:
        return None
    prev, last = rows[-2].get("close"), rows[-1].get("close")
    if not all(isinstance(v, (int, float)) for v in (prev, last)) or prev == 0:
        return None
    return round((last - prev) / prev * 100.0, 4)


def _read_prev_risk(writer: StorageWriter) -> tuple[float | None, dict[str, float] | None, list[dict[str, Any]]]:
    """读取 risk 历史：上一日总分 / 上一日各维分数 / 全量既往行（P2-9 公开 read_history）。"""
    rows = writer.read_history("risk", "daily")
    if not rows:
        return None, None, []
    last = rows[-1]
    prev_total = last.get("total_score")
    prev_dims = last.get("dim_scores") if isinstance(last.get("dim_scores"), dict) else None
    if isinstance(prev_dims, dict):
        prev_dims = {str(k): float(v) for k, v in prev_dims.items() if isinstance(v, (int, float))}
    return prev_total, prev_dims, rows


# ============================================================
# 统一 freshness 落盘（P1-7）
# ============================================================

def _finalize_and_write(
    writer: StorageWriter,
    name: str,
    env: Any,
    degraded: bool,
    extra_reason: str = "",
) -> Any:
    """统一 freshness 判定 + 写盘 + 更新 metadata/freshness.json（P1-7）。

    Collector 不再自填 freshness_status；写盘后按 sources.yaml 期望频率统一重算
    （fresh/delayed/stale/missing/degraded 五态），再落盘到 envelope 与 freshness.json。
    """
    generated_at = str(getattr(env, "generated_at", "") or "")
    status = finalize_freshness(name, generated_at or None, degraded)
    updated = env.model_copy(update={"freshness_status": status})
    writer.write_dataset(name, updated)
    reason = {"degraded": "degraded", "missing": "missing"}.get(status, "ok")
    if extra_reason:
        reason = f"{reason} ({extra_reason})"
    writer.update_freshness(name, status, reason)
    return updated


def _write_analysis_freshness(writer: StorageWriter) -> None:
    """AI 分析 freshness（P0-4，架构 §1.5）：缺失/失败 → analysis=degraded。"""
    zh = writer.latest_dir / "analysis.zh-CN.json"
    en = writer.latest_dir / "analysis.en.json"
    if not (zh.exists() and en.exists()):
        writer.update_freshness(
            "analysis", "degraded", "AI 分析文件缺失（无额度/失败重试耗尽）→ 降级"
        )
        return
    import json as _json

    generated_at = ""
    try:
        for path in (zh, en):
            data = _json.loads(path.read_text(encoding="utf-8"))
            generated_at = max(generated_at, str(data.get("generated_at", "")))
    except (_json.JSONDecodeError, OSError):
        generated_at = ""
    status = finalize_freshness("analysis", generated_at or None, False)
    reason = "ok" if status == "fresh" else status
    writer.update_freshness("analysis", status, reason)


# ============================================================
# 首页聚合（P1-5）
# ============================================================

def _build_dashboard(
    risk_env: RiskEnvelope,
    equities: Any,
    crypto: Any,
    sectors: Any,
    calendar: Any,
    data_quality: float,
    degraded: bool,
) -> DashboardEnvelope:
    """聚合 risk/crypto/equities/sectors/calendar 关键字段（架构 §2 L299 + §3.6）。"""
    r = risk_env.payload

    cross_asset: list[DashboardAsset] = []
    for a in equities.payload.assets[:6]:
        cross_asset.append(DashboardAsset(asset=a.symbol, category="equity", change_1d=a.change_1d))
    for a in crypto.payload.assets[:3]:
        cross_asset.append(DashboardAsset(asset=a.symbol, category="crypto", change_1d=a.change_1d))

    catalysts = [e.model_dump() for e in calendar.payload.events[:5]]

    sector_performance: list[dict[str, Any]] = []
    if sectors is not None:
        for s in sectors.payload.sectors:
            sector_performance.append({"key": s.key, "label": s.label, "label_zh": s.label_zh, "change_1d": s.change_1d})
        for t in sectors.payload.themes:
            sector_performance.append({"key": t.key, "label": t.label, "label_zh": t.label_zh, "change_1d": t.change_1d})

    payload = DashboardPayload(
        risk=r,
        regime=r.regime,
        top_drivers=r.top_drivers,
        cross_asset=cross_asset,
        catalysts=catalysts,
        sector_performance=sector_performance,
    )
    return DashboardEnvelope(
        generated_at=now_utc(),
        schema_version="1.0.0",
        source=["risk_model", "yfinance", "coingecko", "fmp", "rss_news"],
        source_updated_at=now_utc(),
        freshness_status="degraded" if degraded else "fresh",
        data_quality=round(data_quality, 3),
        payload=payload,
    )


# ============================================================
# 各命令
# ============================================================

def _run_collection(command: str) -> dict[str, Any]:
    """按命令执行采集，返回收集结果与耗时。"""
    started = time.monotonic()
    registry = build_registry(settings)
    universe = AssetUniverse.load(settings)
    writer = StorageWriter(settings.data_dir)

    results: dict[str, Any] = {
        "durations": {},
        "degraded": [],
        "provider_status": {},
        "histories": {},
        "qualities": [],
        "prev_total_score": None,
        "prev_dim_scores": None,
        "risk_history": [],
        "series_history": {},
        "macro_meta": {},
    }

    need_market = command in ("full", "market-only")
    need_macro = command in ("full", "macro-only")
    need_news = command in ("full", "news-only")
    need_calendar = command in ("full",)

    if need_market:
        t0 = time.monotonic()
        mc = MarketCollector(registry, universe, settings)
        market = mc.collect()
        results.update(
            equities=market["equities"],
            crypto=market["crypto"],
            sectors=market["sectors"],
            histories=market["histories"],
        )
        results["degraded"].extend(market["degraded"])
        results["provider_status"].update(market["provider_status"])
        results["qualities"].extend([market["equities"].data_quality, market["crypto"].data_quality, market["sectors"].data_quality])
        results["durations"]["market"] = time.monotonic() - t0

    if need_macro:
        t0 = time.monotonic()
        macc = MacroCollector(registry, settings)
        macro, macro_meta = macc.collect()
        results["macro"] = macro
        results["macro_meta"] = macro_meta
        results["degraded"].extend(macro_meta["degraded"])
        results["provider_status"].update(macro_meta["provider_status"])
        results["series_history"] = macro_meta.get("series_history", {})
        results["qualities"].append(macro.data_quality)
        results["durations"]["macro"] = time.monotonic() - t0

    if need_calendar:
        t0 = time.monotonic()
        ccc = CalendarCollector(registry, settings)
        calendar, cal_meta = ccc.collect()
        results["calendar"] = calendar
        results["calendar_degraded"] = bool(cal_meta["degraded"])
        results["degraded"].extend(cal_meta["degraded"])
        results["provider_status"].update(cal_meta["provider_status"])
        results["qualities"].append(calendar.data_quality)
        results["durations"]["calendar"] = time.monotonic() - t0

    if need_news:
        t0 = time.monotonic()
        ncc = NewsCollector(registry, settings)
        news, news_meta = ncc.collect()
        # 合并 AI 中译（若存在）+ 记录合并状态（P1-6）
        translations_path = settings.data_dir / "latest" / "news.zh-translations.json"
        if translations_path.exists():
            from pipeline.schemas import NewsTranslationsDataset

            import json as _json

            translations = NewsTranslationsDataset.model_validate(
                _json.loads(translations_path.read_text(encoding="utf-8"))
            )
            news = ncc.merge_translations(news, translations)
            merged_count = sum(1 for it in news.payload.items if it.title_zh)
            writer.record_translations("merged", merged_count, "news.zh-translations.json 已合并进 news.json")
        else:
            writer.record_translations("missing", 0, "news.zh-translations.json 不存在（AI 未产出中译）")
        results["news"] = news
        results["news_degraded"] = bool(news_meta["degraded"])
        results["degraded"].extend(news_meta["degraded"])
        results["provider_status"]["news"] = {
            "provider": news_meta.get("provider", "rss_news"),
            "sources": news_meta.get("source_status", {}),
        }
        results["qualities"].append(news.data_quality)
        results["durations"]["news"] = time.monotonic() - t0

    results["durations"]["collection"] = time.monotonic() - started
    return results


def _run_risk_and_write(results: dict[str, Any], writer: StorageWriter, command: str) -> tuple[bool, str | None]:
    """计算风险 + 事实层 + dashboard + 写盘 + 统一 freshness + 校验。返回 (ok, error)。"""
    try:
        risk_model = RiskModel(settings)
        prev_score, prev_dims, risk_history = _read_prev_risk(writer)
        ctx = _build_risk_context(
            macro=results["macro"],
            equities=results["equities"],
            crypto=results["crypto"],
            histories=results.get("histories", {}),
            qualities=results["qualities"],
            prev_total_score=prev_score,
            prev_dim_scores=prev_dims,
            risk_history=risk_history,
            series_history=results.get("series_history", {}),
        )
        risk_result = risk_model.score(ctx)
        risk_env = RiskEnvelope(
            generated_at=now_utc(),
            schema_version="1.0.0",
            source=["risk_model", "fred", "yfinance"],
            source_updated_at=now_utc(),
            freshness_status="degraded" if results["degraded"] else "fresh",
            data_quality=ctx["data_quality"],
            payload=risk_result,
        )

        builder = FactLayerBuilder()
        facts = builder.build(
            risk=risk_env,
            macro=results["macro"],
            equities=results["equities"],
            crypto=results["crypto"],
            news=results["news"],
            calendar=results["calendar"],
            sectors=results.get("sectors"),
        )
    except Exception as exc:  # noqa: BLE001
        return False, f"风险/事实层计算失败: {exc}"

    # ---- 写盘（统一 freshness 判定后落盘，P1-7）----
    try:
        degraded = bool(results["degraded"])
        macro = _finalize_and_write(writer, "macro", results["macro"], bool(results["macro_meta"].get("degraded")))
        equities = _finalize_and_write(writer, "equities", results["equities"], degraded)
        sectors = _finalize_and_write(writer, "sectors", results["sectors"], degraded)
        crypto = _finalize_and_write(writer, "crypto", results["crypto"], degraded)
        news = _finalize_and_write(writer, "news", results["news"], bool(results.get("news_degraded", False)))
        calendar = _finalize_and_write(writer, "calendar", results["calendar"], bool(results.get("calendar_degraded", False)))
        risk_env = _finalize_and_write(writer, "risk", risk_env, degraded)
        writer.write_standalone("facts", facts.model_dump(mode="json"))
        facts_status = "degraded" if degraded else finalize_freshness("facts", str(risk_env.generated_at), False)
        writer.update_freshness("facts", facts_status, "degraded" if facts_status == "degraded" else "ok")

        # dashboard（P1-5）
        dashboard_env = _build_dashboard(
            risk_env=risk_env,
            equities=equities,
            crypto=crypto,
            sectors=sectors,
            calendar=calendar,
            data_quality=ctx["data_quality"],
            degraded=degraded,
        )
        dashboard_env = _finalize_and_write(writer, "dashboard", dashboard_env, degraded)

        # AI 分析 freshness（P0-4）
        _write_analysis_freshness(writer)

        # 历史切片
        today = now_utc()[:10]
        risk_row = {
            "date": today,
            "total_score": risk_result.total_score,
            "risk_level": risk_result.risk_level,
            "regime": risk_result.regime,
            "confidence": risk_result.confidence,
            "dim_scores": {d.key: d.score for d in risk_result.dimensions},
        }
        writer.write_slices("risk", [risk_row])
        spy_rows = results.get("histories", {}).get("SPY", [])
        if spy_rows:
            market_row = {"date": spy_rows[-1]["date"], "symbol": "SPY", "close": spy_rows[-1]["close"]}
            writer.write_slices("market", [market_row])

        # 元数据
        writer.write_sources_metadata(results["provider_status"])
        writer.write_schema_version("1.0.0")
    except Exception as exc:  # noqa: BLE001
        return False, f"写盘失败: {exc}"

    # ---- 校验 ----
    report = validate_all(writer.latest_dir, strict=False)
    if not report.ok:
        return False, "校验失败: " + "; ".join(report.issues)

    results["risk"] = risk_env
    results["dashboard"] = dashboard_env
    return True, None


# ============================================================
# main
# ============================================================

def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    command = _resolve_command(args)

    # 配置自检
    try:
        settings.load_universe()
        settings.load_risk_model()
        settings.load_sources()
        settings.load_news_sources()
    except (FileNotFoundError, ValueError) as exc:
        print(f"[pipeline] 配置加载失败: {exc}", file=sys.stderr)
        return 1

    if args.dry_run:
        _print_plan(command, args)
        print("[pipeline] dry-run 完成，未写任何文件（no-op 正常退出）")
        return 0

    if command == "analysis-only":
        return _run_analysis_only()

    if args.backfill:
        return _run_backfill()

    started = time.monotonic()
    results = _run_collection(command)

    # 单域命令只写对应数据集（统一 freshness 判定，P1-7）
    if command == "market-only":
        writer = StorageWriter(settings.data_dir)
        _finalize_and_write(writer, "equities", results["equities"], bool(results["degraded"]))
        _finalize_and_write(writer, "crypto", results["crypto"], bool(results["degraded"]))
        _finalize_and_write(writer, "sectors", results["sectors"], bool(results["degraded"]))
        writer.write_sources_metadata(results["provider_status"])
        _print_summary(command, results, time.monotonic() - started)
        return 0

    if command == "macro-only":
        writer = StorageWriter(settings.data_dir)
        _finalize_and_write(writer, "macro", results["macro"], bool(results["macro_meta"].get("degraded")))
        _write_analysis_freshness(writer)
        writer.write_sources_metadata(results["provider_status"])
        _print_summary(command, results, time.monotonic() - started)
        return 0

    if command == "news-only":
        writer = StorageWriter(settings.data_dir)
        _finalize_and_write(writer, "news", results["news"], bool(results.get("news_degraded", False)))
        writer.write_sources_metadata(results["provider_status"])
        _print_summary(command, results, time.monotonic() - started)
        return 0

    # full / fact-layer
    if command == "fact-layer":
        ok, error = _run_fact_layer_only()
    else:
        writer = StorageWriter(settings.data_dir)
        ok, error = _run_risk_and_write(results, writer, command)
        results["durations"]["total"] = time.monotonic() - started

    if ok:
        write_run_report(
            settings.artifacts_dir,
            command=command,
            ok=True,
            durations=results.get("durations", {}),
            provider_status=results.get("provider_status", {}),
            degraded=results.get("degraded", []),
            dataset_counts={"latest": len(list((settings.data_dir / "latest").glob("*.json")))},
        )
        _print_summary(command, results, results.get("durations", {}).get("total", 0.0))
        return 0

    print(f"[pipeline] 失败: {error}", file=sys.stderr)
    write_run_report(
        settings.artifacts_dir,
        command=command, ok=False,
        durations=results.get("durations", {}),
        provider_status=results.get("provider_status", {}),
        degraded=results.get("degraded", []),
        dataset_counts={}, error=error,
    )
    return 1


def _run_fact_layer_only() -> tuple[bool, str | None]:
    """只重建事实层：读取 latest/*.json，重新组装 facts.json。"""
    writer = StorageWriter(settings.data_dir)

    def load(name: str, model: Any):
        data = writer.read_latest(name)
        return model.model_validate(data) if data else None

    from pipeline.schemas import CalendarEnvelope, CryptoEnvelope, EquitiesEnvelope, MacroEnvelope, NewsEnvelope, RiskEnvelope

    macro = load("macro", MacroEnvelope)
    equities = load("equities", EquitiesEnvelope)
    crypto = load("crypto", CryptoEnvelope)
    news = load("news", NewsEnvelope)
    calendar = load("calendar", CalendarEnvelope)
    risk = load("risk", RiskEnvelope)
    sectors_data = writer.read_latest("sectors")
    sectors = SectorsEnvelope.model_validate(sectors_data) if sectors_data else None

    if not all([macro, equities, crypto, news, calendar, risk]):
        return False, "事实层重建需要 latest/*.json 已存在（先运行 --full）"

    builder = FactLayerBuilder()
    facts = builder.build(risk=risk, macro=macro, equities=equities, crypto=crypto, news=news, calendar=calendar, sectors=sectors)
    writer.write_standalone("facts", facts.model_dump(mode="json"))
    writer.update_freshness("facts", "fresh", "rebuilt")
    _write_analysis_freshness(writer)
    return True, None


def _run_analysis_only() -> int:
    """AI 分析文件校验 + 中译合并（架构 §1.5 步骤 3/4）。"""
    import json as _json

    from pipeline.analysis.validate import validate_analysis_pair
    from pipeline.analysis.contract import analysis_path, input_path
    from pipeline.schemas import NewsTranslationsDataset

    zh_path = analysis_path("zh-CN")
    en_path = analysis_path("en")
    facts_path = input_path("facts")

    if not zh_path.exists() or not en_path.exists():
        print("[pipeline] analysis-only：分析文件缺失（AI 自动化产出后校验），跳过", file=sys.stderr)
        writer = StorageWriter(settings.data_dir)
        writer.update_freshness("analysis", "degraded", "AI 分析文件缺失（无额度/失败重试耗尽）→ 降级")
        return 0

    try:
        issues, _, _ = validate_analysis_pair(zh_path, en_path, facts_path if facts_path.exists() else None)
    except Exception as exc:  # noqa: BLE001
        print(f"[pipeline] analysis-only：校验失败: {exc}", file=sys.stderr)
        return 1

    if issues:
        print("[pipeline] analysis-only：双语一致性未通过：")
        for issue in issues:
            print(f"  - {issue}")
        return 1

    # 中译合并进 news.json（P1-6：记录合并状态）
    writer = StorageWriter(settings.data_dir)
    news_data = writer.read_latest("news")
    translations_path = settings.data_dir / "latest" / "news.zh-translations.json"
    if news_data and translations_path.exists():
        from pipeline.schemas import NewsEnvelope

        news = NewsEnvelope.model_validate(news_data)
        translations = NewsTranslationsDataset.model_validate(_json.loads(translations_path.read_text(encoding="utf-8")))
        collector = NewsCollector(build_registry(settings), settings)
        merged = collector.merge_translations(news, translations)
        merged_count = sum(1 for it in merged.payload.items if it.title_zh)
        writer.write_dataset("news", merged)
        writer.record_translations("merged", merged_count, "analysis-only 合并 news.zh-translations.json 进 news.json")
        print("[pipeline] analysis-only：中译已合并进 news.json")
    elif news_data:
        writer.record_translations("missing", 0, "news.zh-translations.json 不存在（AI 未产出中译）")

    writer.update_freshness("analysis", "fresh", "AI 分析文件校验通过")
    print("[pipeline] analysis-only：校验通过 ✓")
    return 0


def _run_backfill() -> int:
    """预热回填 30-90 天（FedWatch 除外，架构 §1.7/评审 P1-5）。

    拉取基准 + 全部美股历史；history/market 只写 SPY 基准序列（避免按日期
    合并时不同符号互相覆盖），其余符号仅预热 last-good 缓存供 quote 使用。
    """
    print("[pipeline] backfill：回填 30-90 天历史…")
    registry = build_registry(settings)
    writer = StorageWriter(settings.data_dir)
    universe = AssetUniverse.load(settings)

    for symbol in ["SPY", "IWM", "SOXX", *[a.symbol for a in universe.us_equities]]:
        try:
            out = registry.call("quotes", "get_history", f"backfill_{symbol}", args=(symbol, "1y"))
            rows = out["result"].rows
            if symbol == "SPY":
                writer.write_slices("market", [{"date": r["date"], "symbol": symbol, "close": r["close"]} for r in rows if r.get("close") is not None])
            print(f"  {symbol}: {len(rows)} 行回填")
        except Exception as exc:  # noqa: BLE001
            print(f"  {symbol}: 回填失败（降级不中断）: {exc}")
    print("[pipeline] backfill：完成")
    return 0


def _print_plan(command: str, args: argparse.Namespace) -> None:
    print("Market Risk Dashboard 管道运行计划")
    print(f"  命令        : {command}")
    print(f"  语言        : {args.locale or '双语'}")
    print(f"  dry-run     : {args.dry_run}")
    print(f"  backfill    : {args.backfill}")
    print(f"  配置目录    : {settings.config_dir}")
    print(f"  数据目录    : {settings.data_dir}")
    print("  ⚠ T03：真实采集已实现；dry-run 不触网不写盘。")


def _print_summary(command: str, results: dict[str, Any], elapsed: float) -> None:
    counts: dict[str, int] = {}
    for key, env in results.items():
        payload = getattr(env, "payload", None)
        if payload is None:
            continue
        for attr in ("assets", "items", "events", "sectors"):
            if hasattr(payload, attr):
                counts[key] = len(getattr(payload, attr))
                break
    print(f"[pipeline] {command} 完成（{elapsed:.1f}s）")
    print(f"  数据集项数  : {counts}")
    print(f"  降级        : {len(results.get('degraded', []))} 处")
    if results.get("degraded"):
        for d in results["degraded"][:10]:
            print(f"    - {d}")
    risk = results.get("risk")
    print(f"  风险分      : {risk.payload.total_score if risk else None}")


if __name__ == "__main__":
    raise SystemExit(main())
