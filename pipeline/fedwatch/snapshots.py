"""FedWatch 本地每日快照累积（架构 §1.6/评审 P0-1）。

免费结算历史仅约 5 个交易日 → "较一周前变化"从上线日起累积；
积累满 7 天前快照 status=accumulating、change_1d=None（前端显示 insufficient data）。
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from pipeline.schemas import FedWatchSnapshot
from pipeline.utils import now_utc


def load_history(path: Path) -> list[dict]:
    """读取累积历史（不存在返回空列表）。"""
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, list) else []
    except (json.JSONDecodeError, OSError):
        return []


def save_history(path: Path, history: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(history, ensure_ascii=False, indent=2), encoding="utf-8")


def enrich_with_history(
    snapshot: FedWatchSnapshot,
    history: list[dict],
    history_path: Path,
    today: str | None = None,
) -> FedWatchSnapshot:
    """将新快照与历史合并，回填 change_1d 与 status。

    规则：
    - 同日已有快照 → 更新当日（去重）。
    - 历史 < 2 天 → accumulating（数据积累中）。
    - 历史 ≥ 2 天 → 计算各区间较昨日变化，status=ready。
    """
    today = today or now_utc()[:10]

    # 同日去重（就地修改传入列表，保证调用方 save_history 拿到更新后历史）
    history[:] = [h for h in history if str(h.get("date", ""))[:10] != today]
    yesterday = max((h for h in history if str(h.get("date", ""))[:10] < today), key=lambda h: h["date"], default=None)

    history.append(
        {
            # 逻辑日期（today）+ 当前时刻：保证按日累积可测可复现
            "date": f"{today}{now_utc()[10:]}",
            "meeting_date": snapshot.meeting_date,
            "effective_rate": snapshot.effective_rate,
            "implied_rate": snapshot.implied_rate,
            "inferred_action": snapshot.inferred_action,
            "probabilities": [p.model_dump() for p in snapshot.probabilities],
        }
    )
    history.sort(key=lambda h: h["date"])

    if yesterday is None or not yesterday.get("probabilities"):
        return snapshot

    prev_map = {p["target_rate"]: p["probability"] for p in yesterday["probabilities"]}
    change_1d: dict[str, float] = {}
    for prob in snapshot.probabilities:
        prev = prev_map.get(prob.target_rate)
        if prev is not None:
            change_1d[str(prob.target_rate)] = round(prob.probability - prev, 4)

    enriched = snapshot.model_copy(update={"change_1d": change_1d or None, "status": "ready"})
    return enriched
