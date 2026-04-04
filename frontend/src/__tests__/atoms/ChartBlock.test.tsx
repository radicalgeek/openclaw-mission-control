import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import type { ReactNode } from "react";

// ── Mock recharts ────────────────────────────────────────────────────────────
// jsdom has no SVG layout engine; mock recharts entirely so tests run fast.

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

// ── Import after mocking ─────────────────────────────────────────────────────

import { ChartBlock } from "@/components/atoms/ChartBlock";

// ── Helpers ──────────────────────────────────────────────────────────────────

const DATA = [
  { day: "Mon", value: 10 },
  { day: "Tue", value: 8 },
  { day: "Wed", value: 5 },
];

const BASE_SPEC = {
  type: "line" as const,
  title: "Test Chart",
  xKey: "day",
  yKeys: ["value"],
  data: DATA,
};

// ── Tests ────────────────────────────────────────────────────────────────────

describe("ChartBlock", () => {
  it("renders a title when spec.title is provided", () => {
    render(<ChartBlock spec={{ ...BASE_SPEC, title: "My Burndown" }} />);
    expect(screen.getByText("My Burndown")).toBeDefined();
  });

  it("renders a line chart for type=line", () => {
    render(<ChartBlock spec={BASE_SPEC} />);
    expect(screen.getByTestId("recharts-line-chart")).toBeDefined();
  });

  it("renders a bar chart for type=bar", () => {
    render(<ChartBlock spec={{ ...BASE_SPEC, type: "bar" }} />);
    expect(screen.getByTestId("recharts-bar-chart")).toBeDefined();
  });

  it("renders an area chart for type=area", () => {
    render(<ChartBlock spec={{ ...BASE_SPEC, type: "area" }} />);
    expect(screen.getByTestId("recharts-area-chart")).toBeDefined();
  });

  it("renders a pie chart for type=pie", () => {
    render(<ChartBlock spec={{ ...BASE_SPEC, type: "pie", yKeys: ["value"] }} />);
    expect(screen.getByTestId("recharts-pie-chart")).toBeDefined();
  });

  it("renders a donut chart for type=donut", () => {
    render(<ChartBlock spec={{ ...BASE_SPEC, type: "donut", yKeys: ["value"] }} />);
    expect(screen.getByTestId("recharts-pie-chart")).toBeDefined();
  });

  it("handles yKeys as a string (single series shorthand)", () => {
    render(<ChartBlock spec={{ ...BASE_SPEC, yKeys: "value" }} />);
    expect(screen.getByTestId("recharts-line-chart")).toBeDefined();
  });

  it("shows an error for missing type", () => {
    const { type: _type, ...noType } = BASE_SPEC;
    render(<ChartBlock spec={noType} />);
    expect(screen.getByText(/Invalid chart spec/i)).toBeDefined();
  });

  it("shows an error for invalid type value", () => {
    render(<ChartBlock spec={{ ...BASE_SPEC, type: "radar" as never }} />);
    expect(screen.getByText(/Invalid chart spec/i)).toBeDefined();
  });

  it("shows an error for empty data array", () => {
    render(<ChartBlock spec={{ ...BASE_SPEC, data: [] }} />);
    expect(screen.getByText(/Invalid chart spec/i)).toBeDefined();
  });

  it("shows an error for null input", () => {
    render(<ChartBlock spec={null} />);
    expect(screen.getByText(/Invalid chart spec/i)).toBeDefined();
  });

  it("shows an error for non-object input", () => {
    render(<ChartBlock spec="not-an-object" />);
    expect(screen.getByText(/Invalid chart spec/i)).toBeDefined();
  });

  it("renders without a title when spec.title is omitted", () => {
    const { title: _title, ...noTitle } = BASE_SPEC;
    render(<ChartBlock spec={noTitle} />);
    // BASE_SPEC.title is "Test Chart" — if title is omitted it should not appear
    expect(screen.queryByText("Test Chart")).toBeNull();
  });

  it("truncates data to 500 rows without crashing", () => {
    const bigData = Array.from({ length: 600 }, (_, i) => ({ day: `D${i}`, value: i }));
    // Should render without throwing
    render(<ChartBlock spec={{ ...BASE_SPEC, data: bigData }} />);
    expect(screen.getByTestId("recharts-line-chart")).toBeDefined();
  });
});
