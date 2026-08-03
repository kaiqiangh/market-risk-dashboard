#!/usr/bin/env python3
"""离线校准脚本（架构 §1.8：2008/2018/2020 三段 → docs/calibration-report.md）。

数据全部免费可得：FRED VIXCLS/BAMLH0A0HYM2/DGS10 + yfinance SPX 历史。
随仓库发布（T05 取消 docs/ 忽略）；口径红线：校准完成前 UI 不得称"精确崩盘概率"。

用法：python scripts/calibration.py [--out docs/calibration-report.md]
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


def _fetch_fred_map(series_id: str, start: str, end: str) -> dict[str, float]:
    from pipeline.providers.fred import FredProvider
    from pipeline.settings import settings

    fred = FredProvider(settings)
    try:
        return {o["date"]: o["value"] for o in fred.get_series(series_id, start=start, end=end)}
    except Exception:  # noqa: BLE001
        return {}


def _fetch_spx_map(start: str, end: str) -> dict[str, float]:
    from pipeline.providers.yahoo import YahooProvider
    from pipeline.settings import settings

    yahoo = YahooProvider(settings)
    try:
        hist = yahoo.get_history_range("^GSPC", start=start, end=end)
    except Exception:  # noqa: BLE001
        return {}
    return {r["date"]: r["close"] for r in hist.rows if r.get("close") is not None}


def run_calibration(out_path: Path) -> int:
    from pipeline.risk.calibration import CALIBRATION_WINDOWS, evaluate_segment

    report_lines: list[str] = []
    report_lines.append("# Market Risk Dashboard — 离线校准报告")
    report_lines.append("")
    report_lines.append("**口径声明：** 本页风险分数为**模型化的市场压力估计**，并非精确的崩盘概率（架构 §1.8 口径红线）。")
    report_lines.append("")
    report_lines.append("## 方法")
    report_lines.append("")
    report_lines.append("对 2008/2018/2020 三段窗口运行简化风险模型（VIX + HY OAS + SPX 回撤的综合分），")
    report_lines.append("评估：提前预警时间、风险分数变化速度、最大回撤、未来 5/10/20/30 日波动率、风险等级稳定性。")
    report_lines.append("")
    report_lines.append("## 结果")
    report_lines.append("")

    ok = True
    for segment, meta in CALIBRATION_WINDOWS.items():
        start, end = meta["start"], meta["end"]
        vix_map = _fetch_fred_map("VIXCLS", start, end)
        hy_map = _fetch_fred_map("BAMLH0A0HYM2", start, end)
        spx_map = _fetch_spx_map(start, end)
        # 按共同交易日对齐（FRED 与 yfinance 交易日历不同步）
        common_dates = sorted(set(vix_map) & set(hy_map) & set(spx_map)) or sorted(set(spx_map))
        if not common_dates or not spx_map:
            report_lines.append(f"### {segment}（{meta['note']}）— ⚠️ 数据不可得（网络/限流），跳过")
            report_lines.append("")
            ok = False
            continue
        vix_values = [vix_map.get(d) for d in common_dates]
        hy_values = [hy_map.get(d) for d in common_dates]
        spx_values = [spx_map[d] for d in common_dates]
        result = evaluate_segment(common_dates, vix_values, hy_values, spx_values, segment)
        report_lines.append(f"### {segment}（{meta['note']}）")
        report_lines.append("")
        report_lines.append(f"- 交易日数：{result['n_days']}")
        report_lines.append(f"- 最大回撤：{result['max_drawdown_pct']}%")
        report_lines.append(f"- 提前预警（风险分≥60 相对峰值）：{result['early_warning_days_vs_peak']} 天（负数=峰值前预警）")
        report_lines.append(f"- 风险分 40→60 速度：{result['speed_40_to_60_days']} 天")
        report_lines.append(f"- 峰值后未来波动率：{result['future_vol']}")
        report_lines.append(f"- 风险等级切换次数：{result['level_switches']}")
        report_lines.append(f"- 分数范围：首 {result['score_first']} / 峰值 {result['score_max']} / 末 {result['score_last']}")
        report_lines.append("")

    report_lines.append("## 局限")
    report_lines.append("")
    report_lines.append("- 市场宽度历史（2008-2012）不可得 → 本报告未纳入宽度维度（评审 P0-3；T05 用近似重建）。")
    report_lines.append("- MVP 风险映射为启发式规则（pipeline/risk/scoring.py），非统计模型。")
    report_lines.append("- 免费数据源无 SLA，回测窗口可能因网络不可得而跳过。")
    report_lines.append("")

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text("\n".join(report_lines), encoding="utf-8")
    print(f"[calibration] 报告已写入 {out_path}")
    return 0 if ok else 1


def main() -> int:
    parser = argparse.ArgumentParser(description="离线校准：2008/2018/2020 → docs/calibration-report.md")
    parser.add_argument("--out", type=Path, default=Path("docs/calibration-report.md"))
    args = parser.parse_args()
    return run_calibration(args.out)


if __name__ == "__main__":
    raise SystemExit(main())
