/**
 * State component tests: ErrorState (JSON read failure) / StatusBadge (five states) / EmptyState / AIBrief degraded.
 * Covers acceptance: JSON read failure, stale/missing/degraded, AI analysis degrades instead of crashing.
 */
import { describe, expect, it, vi, beforeEach, afterEach } from "vitest";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import "@/i18n";
import { ErrorState } from "@/components/ui/ErrorState";
import { EmptyState } from "@/components/ui/EmptyState";
import { StatusBadge } from "@/components/layout/StatusBadge";
import { AIBrief } from "@/components/ai/AIBrief";
import factsFixture from "../fixtures/facts.json";
import { analysisEnFixture, analysisZhFixture as analysisFixture } from "./helpers/analysisFixtures";
import { deriveAnalysisPresentation } from "@/lib/analysisState";

const validPresentation = deriveAnalysisPresentation({
  current: analysisFixture as never,
  alternate: analysisEnFixture as never,
  facts: factsFixture as never,
});

describe("ErrorState (JSON read failure)", () => {
  it("renders title/message/retry and fires onRetry", () => {
    const onRetry = vi.fn();
    render(<ErrorState onRetry={onRetry} detail={["payload.total_score: invalid"]} />);
    expect(screen.getByRole("alert")).toBeInTheDocument();
    expect(screen.getByText("数据加载失败")).toBeInTheDocument();
    expect(screen.getByText("payload.total_score: invalid")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "重试" }));
    expect(onRetry).toHaveBeenCalledTimes(1);
  });
});

describe("EmptyState (missing empty state)", () => {
  it("renders default title", () => {
    render(<EmptyState />);
    expect(screen.getByText("暂无数据")).toBeInTheDocument();
  });
});

describe("StatusBadge (five states → badge)", () => {
  beforeEach(() => {
    vi.spyOn(console, "warn").mockImplementation(() => undefined);
  });
  afterEach(() => {
    cleanup();
    vi.restoreAllMocks();
  });

  it("fresh → normal", () => {
    render(<StatusBadge status="fresh" />);
    expect(screen.getByTestId("status-badge-fresh")).toHaveTextContent("正常");
  });

  it("delayed → delayed (yellow hint)", () => {
    render(<StatusBadge status="delayed" />);
    expect(screen.getByTestId("status-badge-delayed")).toHaveTextContent("延迟");
  });

  it("stale → stale (prominent warning via fresh family, ADR-0002)", () => {
    render(<StatusBadge status="stale" />);
    const badge = screen.getByTestId("status-badge-stale");
    expect(badge).toHaveTextContent("已过期");
    expect(badge.className).toContain("fresh-warn");
  });

  it("missing → no data", () => {
    render(<StatusBadge status="missing" />);
    expect(screen.getByTestId("status-badge-missing")).toHaveTextContent("无数据");
  });

  it("cache replay badge is distinct from delayed (#66)", () => {
    render(<StatusBadge status="delayed" fromCache />);
    const badge = screen.getByTestId("status-badge-cache");
    expect(badge).toHaveTextContent("缓存回放");
    expect(badge).not.toHaveTextContent("延迟");
  });

  it("degraded → partially degraded", () => {
    render(<StatusBadge status="degraded" withDescription />);
    expect(screen.getByTestId("status-badge-degraded")).toHaveTextContent("部分降级");
    expect(screen.getByText(/数据源降级/)).toBeInTheDocument();
  });
});

describe("AIBrief (AI analysis block)", () => {
  it("missing data → shows degraded instead of crashing", () => {
    render(
      <AIBrief
        presentation={{ status: "missing", notice: "analysisMissing", validated: false }}
        loading={false}
      />,
    );
    expect(screen.getByTestId("ai-brief-state")).toHaveAttribute("data-state", "analysisMissing");
    expect(screen.getByText(/智能简报暂不可用/)).toBeInTheDocument();
  });

  it("loading → skeleton", () => {
    render(<AIBrief presentation={validPresentation} loading />);
    expect(screen.getByTestId("ai-brief-loading")).toBeInTheDocument();
  });

  it("data ready → renders summary / drivers / cases / evidence", () => {
    render(<AIBrief presentation={validPresentation} loading={false} />);
    expect(screen.getByTestId("ai-brief")).toBeInTheDocument();
    expect(screen.getByText(/当前市场处于谨慎状态/)).toBeInTheDocument();
    expect(screen.getByText(/利率回落至 1.5% 下方/)).toBeInTheDocument();
    expect(screen.getByText(/维持谨慎/)).toBeInTheDocument();
    expect(screen.getByText(/风险分突破 70/)).toBeInTheDocument();
    // EvidenceLink renders the evidence badge
    expect(screen.getAllByTestId("evidence-link").length).toBeGreaterThan(0);
  });

  it.each([
    ["analysisMalformed", "degraded", "智能简报未通过校验"],
    ["pairIncomplete", "degraded", "双语简报不完整"],
    ["pairMismatch", "degraded", "双语简报版本不一致"],
    ["factsMissing", "missing", "智能简报缺少事实基础"],
    ["factsUnidentified", "degraded", "智能简报缺少已确认的事实身份"],
    ["lineageMissing", "degraded", "智能简报缺少可确认的依据链"],
    ["lineageMismatch", "degraded", "智能简报依据不一致"],
    ["inputUnhealthy", "degraded", "智能简报缺乏新鲜数据基础"],
    ["delayed", "delayed", "智能简报已延迟"],
    ["stale", "stale", "智能简报已过期"],
    ["empty", "empty", "智能简报缺少可用输入"],
  ] as const)("%s → localized status and recovery copy", (notice, status, title) => {
    render(<AIBrief presentation={{ status, notice, validated: false }} />);
    expect(screen.getByTestId("ai-brief-state")).toHaveAttribute("data-state", notice);
    expect(screen.getByText(title)).toBeInTheDocument();
  });
});
