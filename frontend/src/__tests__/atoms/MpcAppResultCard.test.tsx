import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import type { ReactNode } from "react";

// ── Mock recharts so tests run without SVG layout engine ────────────────────
vi.mock("recharts", () => ({
  ResponsiveContainer: ({ children }: { children: ReactNode }) => (
    <div data-testid="recharts-responsive">{children}</div>
  ),
  LineChart: ({ children }: { children: ReactNode }) => (
    <div data-testid="recharts-line-chart">{children}</div>
  ),
  AreaChart: ({ children }: { children: ReactNode }) => (
    <div data-testid="recharts-area-chart">{children}</div>
  ),
  BarChart: ({ children }: { children: ReactNode }) => (
    <div data-testid="recharts-bar-chart">{children}</div>
  ),
  PieChart: ({ children }: { children: ReactNode }) => (
    <div data-testid="recharts-pie-chart">{children}</div>
  ),
  Line: () => null,
  Area: () => null,
  Bar: () => null,
  Pie: ({ children }: { children?: ReactNode }) => (
    <div data-testid="recharts-pie">{children}</div>
  ),
  Cell: () => null,
  CartesianGrid: () => null,
  XAxis: () => null,
  YAxis: () => null,
  Tooltip: () => null,
  Legend: () => null,
}));

import { MpcAppResultCard } from "@/components/atoms/MpcAppResultCard";

const VALID_CHART_META = {
  app: "chart",
  spec: {
    type: "line",
    title: "Burndown",
    xKey: "day",
    yKeys: ["remaining"],
    data: [{ day: "Mon", remaining: 10 }],
  },
};

describe("MpcAppResultCard", () => {
  it("renders chart when app=chart with valid spec", () => {
    render(
      <MpcAppResultCard metadata={VALID_CHART_META} fallbackContent="fallback" />,
    );
    // ChartBlock renders recharts inside it
    expect(screen.getByTestId("recharts-responsive")).toBeTruthy();
  });

  it("renders fallback Markdown when metadata is null", () => {
    render(
      <MpcAppResultCard metadata={null} fallbackContent="plain text fallback" />,
    );
    expect(screen.getByText("plain text fallback")).toBeTruthy();
  });

  it("renders fallback Markdown when metadata is undefined", () => {
    render(
      <MpcAppResultCard metadata={undefined} fallbackContent="undefined fallback" />,
    );
    expect(screen.getByText("undefined fallback")).toBeTruthy();
  });

  it("renders generic card for unknown app type", () => {
    render(
      <MpcAppResultCard
        metadata={{ app: "future-app", payload: {} }}
        fallbackContent="future app content"
      />,
    );
    expect(screen.getByText(/mcp-app: future-app/)).toBeTruthy();
  });

  it("renders fallback when metadata has no 'app' key", () => {
    render(
      <MpcAppResultCard
        metadata={{ spec: {} }}
        fallbackContent="no app fallback"
      />,
    );
    expect(screen.getByText("no app fallback")).toBeTruthy();
  });

  it("shows chart title from spec", () => {
    render(
      <MpcAppResultCard metadata={VALID_CHART_META} fallbackContent="" />,
    );
    expect(screen.getByText("Burndown")).toBeTruthy();
  });

  it("applies 'comment' variant in fallback when specified", () => {
    const { container } = render(
      <MpcAppResultCard
        metadata={null}
        fallbackContent="comment variant"
        variant="comment"
      />,
    );
    // No crash — variant is passed through
    expect(container).toBeTruthy();
  });
});
