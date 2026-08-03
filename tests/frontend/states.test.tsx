/**
 * 状态组件测试：ErrorState（JSON 读取失败）/ StatusBadge（五态）/ EmptyState / AIBrief 降级。
 * 覆盖验收：JSON 读取失败、stale/missing/degraded、AI 分析降级而非瘫痪。
 */
import { describe, expect, it, vi, beforeEach, afterEach } from "vitest";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import "@/i18n";
import { ErrorState } from "@/components/ui/ErrorState";
import { EmptyState } from "@/components/ui/EmptyState";
import { StatusBadge } from "@/components/layout/StatusBadge";
import { AIBrief } from "@/components/ai/AIBrief";
import analysisFixture from "../fixtures/analysis.zh-CN.json";

describe("ErrorState（JSON 读取失败）", () => {
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

describe("EmptyState（缺失空态）", () => {
  it("renders default title", () => {
    render(<EmptyState />);
    expect(screen.getByText("暂无数据")).toBeInTheDocument();
  });
});

describe("StatusBadge（五态 → 徽标）", () => {
  beforeEach(() => {
    vi.spyOn(console, "warn").mockImplementation(() => undefined);
  });
  afterEach(() => {
    cleanup();
    vi.restoreAllMocks();
  });

  it("fresh → 正常", () => {
    render(<StatusBadge status="fresh" />);
    expect(screen.getByTestId("status-badge-fresh")).toHaveTextContent("正常");
  });

  it("delayed → 延迟（黄色提示）", () => {
    render(<StatusBadge status="delayed" />);
    expect(screen.getByTestId("status-badge-delayed")).toHaveTextContent("延迟");
  });

  it("stale → 已过期（明显警告）", () => {
    render(<StatusBadge status="stale" />);
    const badge = screen.getByTestId("status-badge-stale");
    expect(badge).toHaveTextContent("已过期");
    expect(badge.className).toContain("risk-high");
  });

  it("missing → 无数据", () => {
    render(<StatusBadge status="missing" />);
    expect(screen.getByTestId("status-badge-missing")).toHaveTextContent("无数据");
  });

  it("degraded → 部分降级", () => {
    render(<StatusBadge status="degraded" withDescription />);
    expect(screen.getByTestId("status-badge-degraded")).toHaveTextContent("部分降级");
    expect(screen.getByText(/数据源降级/)).toBeInTheDocument();
  });
});

describe("AIBrief（AI 分析区块）", () => {
  it("数据缺失 → 显示降级而非瘫痪", () => {
    render(<AIBrief analysis={undefined} loading={false} error />);
    expect(screen.getByTestId("ai-brief-degraded")).toBeInTheDocument();
    expect(screen.getByText(/AI 简报暂不可用/)).toBeInTheDocument();
  });

  it("加载中 → skeleton", () => {
    render(<AIBrief analysis={undefined} loading error={false} />);
    expect(screen.getByTestId("ai-brief-loading")).toBeInTheDocument();
  });

  it("数据就绪 → 渲染 summary / drivers / cases / evidence", () => {
    render(<AIBrief analysis={analysisFixture as never} loading={false} error={false} />);
    expect(screen.getByTestId("ai-brief")).toBeInTheDocument();
    expect(screen.getByText(/当前市场处于谨慎状态/)).toBeInTheDocument();
    expect(screen.getByText(/利率回落至 1.5% 下方/)).toBeInTheDocument();
    expect(screen.getByText(/维持谨慎/)).toBeInTheDocument();
    expect(screen.getByText(/风险分突破 70/)).toBeInTheDocument();
    // EvidenceLink 渲染证据徽标
    expect(screen.getAllByTestId("evidence-link").length).toBeGreaterThan(0);
  });
});
