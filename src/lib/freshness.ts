import type { FreshnessStatus } from "@/schemas/envelope";

/**
 * Freshness 五态语义与 UI（架构 §8.5）。
 * 判定（相对期望更新频率）：
 *   fresh   ≤ 1.5× 期望间隔 → 正常展示
 *   delayed 1.5× ~ 3×       → 黄色提示
 *   stale   > 3×            → 明显警告 + 数据角标"已过期"
 *   missing 从未有数据       → 空状态（EmptyState）
 *   degraded 部分 Provider 降级/回退（与时间无关）→ 降低置信度 + "部分降级"角标
 */

/** 期望更新间隔（ms）——与 config/sources.yaml expectations 保持同步（冻结 G4）。 */
export const EXPECTED_INTERVALS_MS: Record<string, number> = {
  market: 8 * 60 * 60 * 1000, // 行情/新闻 2-3 次/日
  news: 8 * 60 * 60 * 1000,
  macro: 4 * 60 * 60 * 1000, // 宏观 2-4h
  calendar: 24 * 60 * 60 * 1000, // 财报日历 1 次/日
  analysis: 12 * 60 * 60 * 1000, // AI 简报 2 次/日
};

/** 时间维度五态判定（不含 degraded；degraded 由 envelope.freshness_status 直接携带）。 */
export function evaluateFreshness(
  updatedAt: string | null,
  expectedIntervalMs: number,
  now: number = Date.now(),
): FreshnessStatus {
  if (!updatedAt) return "missing";
  const t = Date.parse(updatedAt);
  if (Number.isNaN(t)) return "missing";
  const age = now - t;
  if (age <= 1.5 * expectedIntervalMs) return "fresh";
  if (age <= 3.0 * expectedIntervalMs) return "delayed";
  return "stale";
}

export type BadgeTone = "success" | "warning" | "danger" | "neutral";

export interface FreshnessBadge {
  status: FreshnessStatus;
  /** i18n key（common 命名空间，如 common:status.fresh） */
  labelKey: string;
  tone: BadgeTone;
  /** 是否需要显著警示 */
  prominent: boolean;
  /** UI 语义说明（架构 §8.5 表格） */
  descriptionKey: string;
}

const BADGE_MAP: Record<FreshnessStatus, FreshnessBadge> = {
  fresh: {
    status: "fresh",
    labelKey: "status.fresh",
    tone: "success",
    prominent: false,
    descriptionKey: "status.freshDesc",
  },
  delayed: {
    status: "delayed",
    labelKey: "status.delayed",
    tone: "warning",
    prominent: false,
    descriptionKey: "status.delayedDesc",
  },
  stale: {
    status: "stale",
    labelKey: "status.stale",
    tone: "danger",
    prominent: true,
    descriptionKey: "status.staleDesc",
  },
  missing: {
    status: "missing",
    labelKey: "status.missing",
    tone: "neutral",
    prominent: false,
    descriptionKey: "status.missingDesc",
  },
  degraded: {
    status: "degraded",
    labelKey: "status.degraded",
    tone: "warning",
    prominent: true,
    descriptionKey: "status.degradedDesc",
  },
};

/** 五态 → UI 徽标/提示。 */
export function badgeFor(status: FreshnessStatus): FreshnessBadge {
  return BADGE_MAP[status];
}

/** envelope.freshness_status + 时间维度判定合并（stale 优先于 degraded？否：degraded 为降级语义，保留 envelope 值）。 */
export function effectiveStatus(envelopeStatus: FreshnessStatus, updatedAt: string | null): FreshnessStatus {
  if (envelopeStatus === "degraded" || envelopeStatus === "missing") return envelopeStatus;
  const computed = evaluateFreshness(updatedAt, EXPECTED_INTERVALS_MS.market);
  if (computed === "stale") return "stale";
  return envelopeStatus;
}
