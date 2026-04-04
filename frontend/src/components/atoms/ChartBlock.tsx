"use client";

/**
 * ChartBlock — renders a validated `json:chart` spec as an interactive
 * Recharts chart.  Consumed by the `<Markdown>` component when it encounters
 * a fenced code block with the `json:chart` language tag.
 */

import { Component, type ReactNode } from "react";
import {
  AreaChart,
  Area,
  BarChart,
  Bar,
  LineChart,
  Line,
  PieChart,
  Pie,
  Cell,
  CartesianGrid,
  XAxis,
  YAxis,
  Tooltip,
  Legend,
  ResponsiveContainer,
} from "recharts";

// ─── Types ────────────────────────────────────────────────────────────────────

export type ChartType = "line" | "area" | "bar" | "pie" | "donut";

export interface ChartSpec {
  /** Discriminates which chart variant to render. */
  type: ChartType;
  /** Optional title rendered above the chart. */
  title?: string;
  /** Key in each data row used as the X-axis category or pie label. */
  xKey?: string;
  /** One or more field keys to plot as Y-axis series. Pie uses the first key as value. */
  yKeys?: string | string[];
  /** Optional X-axis label. */
  xLabel?: string;
  /** Optional Y-axis label. */
  yLabel?: string;
  /** Row data.  Values for `yKeys` must be numbers. */
  data: Record<string, string | number>[];
  /** Optional hex/CSS colour overrides (one per series). */
  colors?: string[];
  /** Chart height in px (default 260). */
  height?: number;
}

// ─── Constants ────────────────────────────────────────────────────────────────

const VALID_TYPES: ReadonlySet<string> = new Set([
  "line",
  "area",
  "bar",
  "pie",
  "donut",
]);

const DEFAULT_COLORS = [
  "#6366f1",
  "#10b981",
  "#f59e0b",
  "#ef4444",
  "#3b82f6",
  "#8b5cf6",
  "#06b6d4",
  "#f97316",
];

const MAX_DATA_ROWS = 500;

// ─── Validation ───────────────────────────────────────────────────────────────

function isValidSpec(spec: unknown): spec is ChartSpec {
  if (!spec || typeof spec !== "object" || Array.isArray(spec)) return false;
  const s = spec as Record<string, unknown>;
  if (typeof s.type !== "string" || !VALID_TYPES.has(s.type)) return false;
  if (!Array.isArray(s.data) || s.data.length === 0) return false;
  return true;
}

function resolveYKeys(spec: ChartSpec): string[] {
  if (!spec.yKeys) return [];
  return Array.isArray(spec.yKeys) ? spec.yKeys : [spec.yKeys];
}

// ─── Error boundary ───────────────────────────────────────────────────────────

interface BoundaryProps {
  children: ReactNode;
  fallback: ReactNode;
}
interface BoundaryState {
  hasError: boolean;
}

class ChartErrorBoundary extends Component<BoundaryProps, BoundaryState> {
  constructor(props: BoundaryProps) {
    super(props);
    this.state = { hasError: false };
  }

  static getDerivedStateFromError(): BoundaryState {
    return { hasError: true };
  }

  render() {
    return this.state.hasError ? this.props.fallback : this.props.children;
  }
}

// ─── Chart renderers ──────────────────────────────────────────────────────────

function CartesianChart({ spec }: { spec: ChartSpec }) {
  const height = spec.height ?? 260;
  const yKeys = resolveYKeys(spec);
  const colors = spec.colors ?? DEFAULT_COLORS;
  const data = spec.data.slice(0, MAX_DATA_ROWS);

  const xAxisProps = {
    dataKey: spec.xKey,
    tick: { fontSize: 11 },
    ...(spec.xLabel
      ? { label: { value: spec.xLabel, position: "insideBottom" as const, offset: -4 } }
      : {}),
  };

  const yAxisProps = {
    tick: { fontSize: 11 },
    width: 42,
    ...(spec.yLabel
      ? { label: { value: spec.yLabel, angle: -90, position: "insideLeft" as const, offset: 10 } }
      : {}),
  };

  if (spec.type === "bar") {
    return (
      <ResponsiveContainer width="100%" height={height}>
        <BarChart data={data}>
          <CartesianGrid strokeDasharray="3 3" stroke="#e2e8f0" />
          <XAxis {...xAxisProps} />
          <YAxis {...yAxisProps} />
          <Tooltip />
          <Legend />
          {yKeys.map((key, i) => (
            <Bar key={key} dataKey={key} fill={colors[i % colors.length]} />
          ))}
        </BarChart>
      </ResponsiveContainer>
    );
  }

  if (spec.type === "area") {
    return (
      <ResponsiveContainer width="100%" height={height}>
        <AreaChart data={data}>
          <CartesianGrid strokeDasharray="3 3" stroke="#e2e8f0" />
          <XAxis {...xAxisProps} />
          <YAxis {...yAxisProps} />
          <Tooltip />
          <Legend />
          {yKeys.map((key, i) => {
            const color = colors[i % colors.length];
            return (
              <Area
                key={key}
                type="monotone"
                dataKey={key}
                stroke={color}
                fill={color}
                fillOpacity={0.15}
                strokeWidth={2}
              />
            );
          })}
        </AreaChart>
      </ResponsiveContainer>
    );
  }

  // line (default)
  return (
    <ResponsiveContainer width="100%" height={height}>
      <LineChart data={data}>
        <CartesianGrid strokeDasharray="3 3" stroke="#e2e8f0" />
        <XAxis {...xAxisProps} />
        <YAxis {...yAxisProps} />
        <Tooltip />
        <Legend />
        {yKeys.map((key, i) => (
          <Line
            key={key}
            type="monotone"
            dataKey={key}
            stroke={colors[i % colors.length]}
            strokeWidth={2}
            dot={false}
          />
        ))}
      </LineChart>
    </ResponsiveContainer>
  );
}

function RadialChart({ spec }: { spec: ChartSpec }) {
  const height = spec.height ?? 260;
  const yKeys = resolveYKeys(spec);
  const colors = spec.colors ?? DEFAULT_COLORS;
  const data = spec.data.slice(0, MAX_DATA_ROWS);
  const valueKey = yKeys[0] ?? "value";
  const labelKey = spec.xKey ?? "name";
  const innerRadius = spec.type === "donut" ? "55%" : 0;

  return (
    <ResponsiveContainer width="100%" height={height}>
      <PieChart>
        <Pie
          data={data}
          dataKey={valueKey}
          nameKey={labelKey}
          cx="50%"
          cy="50%"
          innerRadius={innerRadius}
          outerRadius="75%"
          label={({ name }: { name: string }) => name}
        >
          {data.map((_entry, i) => (
            <Cell key={i} fill={colors[i % colors.length]} />
          ))}
        </Pie>
        <Tooltip />
        <Legend />
      </PieChart>
    </ResponsiveContainer>
  );
}

// ─── Public component ─────────────────────────────────────────────────────────

/**
 * Renders a `ChartSpec`-shaped object as an interactive Recharts chart.
 *
 * Pass the raw parsed JSON (or any unknown value) — the component validates
 * the spec internally and shows a user-friendly error for invalid inputs.
 */
export function ChartBlock({ spec }: { spec: unknown }) {
  if (!isValidSpec(spec)) {
    return (
      <div className="my-3 rounded-lg border border-amber-200 bg-amber-50 px-3 py-2 text-xs text-amber-700">
        Invalid chart spec — ensure <code>type</code>, <code>xKey</code>,{" "}
        <code>yKeys</code>, and <code>data</code> (non-empty array) are present.
      </div>
    );
  }

  const fallback = (
    <div className="my-3 rounded-lg border border-red-200 bg-red-50 px-3 py-2 text-xs text-red-700">
      Chart render error.
    </div>
  );

  const isPolar = spec.type === "pie" || spec.type === "donut";

  return (
    <div className="my-3 w-full">
      {spec.title ? (
        <p className="mb-2 text-xs font-semibold text-slate-600">{spec.title}</p>
      ) : null}
      <ChartErrorBoundary fallback={fallback}>
        {isPolar ? <RadialChart spec={spec} /> : <CartesianChart spec={spec} />}
      </ChartErrorBoundary>
    </div>
  );
}
