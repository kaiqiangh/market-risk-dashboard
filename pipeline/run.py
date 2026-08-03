"""管道 CLI 入口（架构 §1.3 冻结命令集）。

T01 骨架：完整参数解析 + --dry-run no-op 正常退出。
T03 将填充各命令的实际采集/指标/风险/存储流程；届时本文件只做编排，不写业务逻辑。
"""

from __future__ import annotations

import argparse
import sys
from typing import Sequence

from pipeline import __version__
from pipeline.settings import settings

COMMANDS = (
    "full",
    "market-only",
    "macro-only",
    "news-only",
    "analysis-only",
    "fact-layer",
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="pipeline.run",
        description="Market Risk Dashboard 数据管道 CLI",
    )
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


def _print_plan(command: str, args: argparse.Namespace) -> None:
    """打印本次运行计划（--dry-run 时可见）。"""
    lines = [
        "Market Risk Dashboard 管道运行计划",
        f"  命令        : {command}",
        f"  语言        : {args.locale or '双语'}",
        f"  dry-run     : {args.dry_run}",
        f"  backfill    : {args.backfill}",
        f"  配置目录    : {settings.config_dir}",
        f"  数据目录    : {settings.data_dir}",
        "  ⚠ 本批次为 T01 工程骨架：采集/指标/风险/事实层实现将在 T03 落地。",
    ]
    print("\n".join(lines))


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    command = _resolve_command(args)

    # 配置自检：确保 config/*.yaml 可加载（骨架期就暴露配置错误）
    try:
        settings.load_universe()
        settings.load_risk_model()
        settings.load_sources()
        settings.load_news_sources()
    except (FileNotFoundError, ValueError) as exc:
        print(f"[pipeline] 配置加载失败: {exc}", file=sys.stderr)
        return 1

    _print_plan(command, args)

    if args.dry_run:
        print("[pipeline] dry-run 完成，未写任何文件（no-op 正常退出）")
        return 0

    # T01/T02 骨架期：非 dry-run 命令尚未实现，明确提示（T03 填充）。
    print(
        f"[pipeline] 命令 '{command}' 尚未实现：本批次仅工程骨架 + 数据契约。"
        " 实际采集/计算将在 T03 落地。",
        file=sys.stderr,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
