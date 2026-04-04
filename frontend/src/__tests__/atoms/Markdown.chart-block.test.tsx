import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

// ── Mock ChartBlock so tests are isolated from recharts ──────────────────────
// We only care that <Markdown> *calls* <ChartBlock> with the right spec, not
// that recharts renders an SVG correctly.

vi.mock("@/components/atoms/ChartBlock", () => ({
  ChartBlock: ({ spec }: { spec: unknown }) => (
    <div
      data-testid="chart-block"
      data-spec={JSON.stringify(spec)}
    >
      chart
    </div>
  ),
}));

// ── Import after mocking ─────────────────────────────────────────────────────

import { Markdown } from "@/components/atoms/Markdown";

// ── Helpers ──────────────────────────────────────────────────────────────────

const makeChartBlock = (spec: object) =>
  "```json:chart\n" + JSON.stringify(spec) + "\n```";

const VALID_SPEC = {
  type: "line",
  xKey: "day",
  yKeys: ["remaining"],
  data: [{ day: "Mon", remaining: 10 }],
};

// ── Tests ────────────────────────────────────────────────────────────────────

describe("Markdown — json:chart interception", () => {
  it("renders a ChartBlock for a valid json:chart fenced block", () => {
    render(<Markdown content={makeChartBlock(VALID_SPEC)} variant="basic" />);
    expect(screen.getByTestId("chart-block")).toBeDefined();
  });

  it("passes the parsed spec to ChartBlock", () => {
    render(<Markdown content={makeChartBlock(VALID_SPEC)} variant="basic" />);
    const el = screen.getByTestId("chart-block");
    const parsed = JSON.parse(el.getAttribute("data-spec") ?? "null");
    expect(parsed).toMatchObject(VALID_SPEC);
  });

  it("falls back to a code block when the JSON is malformed", () => {
    const malformed = "```json:chart\n{ not valid json }\n```";
    render(<Markdown content={malformed} variant="basic" />);
    // No ChartBlock — malformed JSON falls through to <pre>/<code>
    expect(screen.queryByTestId("chart-block")).toBeNull();
    expect(screen.getByText(/not valid json/i)).toBeDefined();
  });

  it("renders a ChartBlock within the comment variant (channel threads)", () => {
    render(<Markdown content={makeChartBlock(VALID_SPEC)} variant="comment" />);
    expect(screen.getByTestId("chart-block")).toBeDefined();
  });

  it("renders a ChartBlock within the description variant", () => {
    render(<Markdown content={makeChartBlock(VALID_SPEC)} variant="description" />);
    expect(screen.getByTestId("chart-block")).toBeDefined();
  });

  it("renders surrounding Markdown text alongside the chart block", () => {
    const content =
      "Here is the sprint progress:\n\n" +
      makeChartBlock(VALID_SPEC) +
      "\n\nWork continues.";
    render(<Markdown content={content} variant="basic" />);
    expect(screen.getByText(/Here is the sprint progress/i)).toBeDefined();
    expect(screen.getByTestId("chart-block")).toBeDefined();
    expect(screen.getByText(/Work continues/i)).toBeDefined();
  });

  it("does not intercept a regular json fenced block", () => {
    const regular = "```json\n{\"key\": \"value\"}\n```";
    render(<Markdown content={regular} variant="basic" />);
    expect(screen.queryByTestId("chart-block")).toBeNull();
  });

  it("does not intercept plain text code blocks", () => {
    const plain = "```\ncurl -X GET https://example.com\n```";
    render(<Markdown content={plain} variant="basic" />);
    expect(screen.queryByTestId("chart-block")).toBeNull();
  });
});
