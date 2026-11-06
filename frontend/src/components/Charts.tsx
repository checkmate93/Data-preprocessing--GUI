/**
 * SVG charts for result sections. Palette = the validated reference palette (dataviz skill):
 * categorical slots in fixed order, sequential blue ramp, blue <-> red diverging with a gray midpoint.
 * Every chart: recessive hairline axes, hover tooltip, legend for >= 2 series, and a table view.
 */
import { useEffect, useLayoutEffect, useRef, useState, type ReactNode } from "react";
import { formatValue } from "../format";
import type { FrameData, Section } from "../types";
import { DataTable } from "./DataTable";

type Of<T extends Section["type"]> = Extract<Section, { type: T }>;

// ---------------------------------------------------------------- palette (light / dark)

const SERIES = {
  light: ["#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4", "#008300", "#6250d6", "#e34948"],
  dark: ["#3987e5", "#d95926", "#199e70", "#c98500", "#d55181", "#008300", "#9085e9", "#e66767"],
};
const SEQ = ["#cde2fb", "#b7d3f6", "#9ec5f4", "#86b6ef", "#6da7ec", "#5598e7", "#3987e5", "#2a78d6", "#256abf", "#1c5cab", "#184f95", "#104281", "#0d366b"];
const RED_ARM = { light: ["#f0efec", "#f3c3bd", "#ec9289", "#e34948", "#b8302f"], dark: ["#383835", "#6b2f2c", "#a33b39", "#e66767", "#f29a96"] };
const BLUE_ARM = { light: ["#f0efec", "#b7d3f6", "#6da7ec", "#2a78d6", "#1c5cab"], dark: ["#383835", "#1c3d66", "#256abf", "#3987e5", "#86b6ef"] };

function useDark() {
  const query = typeof window !== "undefined" ? window.matchMedia("(prefers-color-scheme: dark)") : null;
  const [dark, setDark] = useState(query?.matches ?? false);
  useEffect(() => {
    if (!query) return;
    const listener = (e: MediaQueryListEvent) => setDark(e.matches);
    query.addEventListener("change", listener);
    return () => query.removeEventListener("change", listener);
  }, [query]);
  return dark;
}

function hexToRgb(hex: string) {
  const n = parseInt(hex.slice(1), 16);
  return [(n >> 16) & 255, (n >> 8) & 255, n & 255];
}

function lerpRamp(ramp: string[], t: number) {
  const clamped = Math.min(1, Math.max(0, t));
  const pos = clamped * (ramp.length - 1);
  const i = Math.min(Math.floor(pos), ramp.length - 2);
  const a = hexToRgb(ramp[i]);
  const b = hexToRgb(ramp[i + 1]);
  const f = pos - i;
  return `rgb(${a.map((v, k) => Math.round(v + (b[k] - v) * f)).join(",")})`;
}

function inkOn(color: string) {
  const [r, g, b] = color.startsWith("#") ? hexToRgb(color) : color.slice(4, -1).split(",").map(Number);
  const lum = (0.2126 * r + 0.7152 * g + 0.0722 * b) / 255;
  return lum > 0.6 ? "#0b0b0b" : "#ffffff";
}

// ---------------------------------------------------------------- shared pieces

function useWidth<T extends HTMLElement>(): [React.RefObject<T | null>, number] {
  const ref = useRef<T>(null);
  const [width, setWidth] = useState(640);
  useLayoutEffect(() => {
    if (!ref.current) return;
    const observer = new ResizeObserver(([entry]) => setWidth(Math.max(280, Math.floor(entry.contentRect.width))));
    observer.observe(ref.current);
    return () => observer.disconnect();
  }, []);
  return [ref, width];
}

function niceTicks(min: number, max: number, count = 5): number[] {
  if (!isFinite(min) || !isFinite(max)) return [0];
  if (min === max) return [min];
  const raw = (max - min) / count;
  const mag = 10 ** Math.floor(Math.log10(raw));
  const step = [1, 2, 2.5, 5, 10].map((m) => m * mag).find((s) => s >= raw) ?? raw;
  const ticks: number[] = [];
  for (let v = Math.floor(min / step) * step; v <= max + step * 0.5; v += step) ticks.push(Number(v.toFixed(10)));
  return ticks;
}

const compact = new Intl.NumberFormat("el-GR", { notation: "compact", maximumFractionDigits: 1 });
const full = new Intl.NumberFormat("el-GR", { maximumFractionDigits: 2 });
const tick = (v: number) => (Math.abs(v) >= 10000 ? compact.format(v) : full.format(v));

interface Tip {
  x: number;
  y: number;
  content: ReactNode;
}

function ChartFrame(props: { title?: string | null; table: FrameData; legend?: ReactNode; children: (width: number, setTip: (t: Tip | null) => void) => ReactNode }) {
  const [ref, width] = useWidth<HTMLDivElement>();
  const [tip, setTip] = useState<Tip | null>(null);
  const [showTable, setShowTable] = useState(false);
  return (
    <div className="section chart">
      <div className="chart-head">
        {props.title ? <h3>{props.title}</h3> : <span />}
        <button className="link small" onClick={() => setShowTable((v) => !v)}>{showTable ? "Γράφημα" : "Πίνακας"}</button>
      </div>
      {props.legend}
      {showTable ? (
        <DataTable data={props.table} />
      ) : (
        <div className="chart-body" ref={ref} onMouseLeave={() => setTip(null)}>
          {props.children(width, setTip)}
          {tip && (
            <div className="chart-tip" style={{ left: Math.min(tip.x + 12, width - 200), top: tip.y + 12 }}>
              {tip.content}
            </div>
          )}
        </div>
      )}
    </div>
  );
}

function YAxis({ ticks, y, left, right }: { ticks: number[]; y: (v: number) => number; left: number; right: number }) {
  return (
    <g className="axis">
      {ticks.map((t) => (
        <g key={t}>
          <line x1={left} x2={right} y1={y(t)} y2={y(t)} className="grid" />
          <text x={left - 6} y={y(t)} dy="0.32em" textAnchor="end">{tick(t)}</text>
        </g>
      ))}
    </g>
  );
}

function roundedColumn(x: number, y: number, w: number, h: number, r = 4) {
  const rr = Math.min(r, w / 2, h);
  return `M${x},${y + h}V${y + rr}Q${x},${y} ${x + rr},${y}H${x + w - rr}Q${x + w},${y} ${x + w},${y + rr}V${y + h}Z`;
}

const columns = (...names: string[]) => names.map((name) => ({ name, dtype: "" }));

// ---------------------------------------------------------------- histogram

export function HistogramChart({ section }: { section: Of<"histogram"> }) {
  const dark = useDark();
  const { edges, counts } = section;
  const table = { columns: columns("από", "έως", "πλήθος"), rows: counts.map((c, i) => [edges[i], edges[i + 1], c]) };
  return (
    <ChartFrame title={section.title} table={table}>
      {(width, setTip) => {
        const h = 240, m = { l: 48, r: 12, t: 10, b: 28 };
        const yTicks = niceTicks(0, Math.max(...counts, 1));
        const yMax = yTicks[yTicks.length - 1] || 1;
        const lo = edges[0], hi = edges[edges.length - 1];
        const x = (v: number) => m.l + ((v - lo) / (hi - lo || 1)) * (width - m.l - m.r);
        const y = (v: number) => m.t + (1 - v / yMax) * (h - m.t - m.b);
        const xTicks = niceTicks(lo, hi, Math.max(2, Math.floor(width / 90))).filter((t) => t >= lo && t <= hi);
        return (
          <svg width={width} height={h} role="img" aria-label={section.title ?? "Histogram"}>
            <YAxis ticks={yTicks} y={y} left={m.l} right={width - m.r} />
            {counts.map((c, i) => {
              const x0 = x(edges[i]) + 1, x1 = x(edges[i + 1]) - 1;
              return (
                <g key={i}
                  onMouseMove={(e) => setTip({ x: e.nativeEvent.offsetX, y: e.nativeEvent.offsetY,
                    content: <><b>{full.format(edges[i])} – {full.format(edges[i + 1])}</b><br />{full.format(c)} γραμμές</> })}>
                  <rect x={x(edges[i])} y={m.t} width={Math.max(1, x(edges[i + 1]) - x(edges[i]))} height={h - m.t - m.b} fill="transparent" />
                  {c > 0 && <path d={roundedColumn(x0, y(c), Math.max(1, x1 - x0), y(0) - y(c))} fill={SERIES[dark ? "dark" : "light"][0]} />}
                </g>
              );
            })}
            <line x1={m.l} x2={width - m.r} y1={y(0)} y2={y(0)} className="baseline" />
            <g className="axis">
              {xTicks.map((t) => <text key={t} x={x(t)} y={h - 8} textAnchor="middle">{tick(t)}</text>)}
            </g>
          </svg>
        );
      }}
    </ChartFrame>
  );
}

// ---------------------------------------------------------------- box plot

export function BoxChart({ section }: { section: Of<"box"> }) {
  const dark = useDark();
  const color = SERIES[dark ? "dark" : "light"][0];
  const items = section.items;
  const table = {
    columns: columns("στήλη", "min", "Q1", "median", "Q3", "max", "outliers"),
    rows: items.map((b) => [b.label, b.min, b.q1, b.median, b.q3, b.max, b.outlier_count]),
  };
  if (!items.length) return null;
  return (
    <ChartFrame title={section.title} table={table}>
      {(width, setTip) => {
        const row = 40, m = { l: Math.min(160, width * 0.3), r: 16, t: 8, b: 26 };
        const h = m.t + m.b + row * items.length;
        const lo = Math.min(...items.map((b) => b.min)), hi = Math.max(...items.map((b) => b.max));
        const ticks = niceTicks(lo, hi, Math.max(2, Math.floor(width / 110)));
        const t0 = Math.min(lo, ticks[0]), t1 = Math.max(hi, ticks[ticks.length - 1]);
        const x = (v: number) => m.l + ((v - t0) / (t1 - t0 || 1)) * (width - m.l - m.r);
        return (
          <svg width={width} height={h} role="img" aria-label={section.title ?? "Boxplot"}>
            <g className="axis">
              {ticks.map((t) => (
                <g key={t}>
                  <line x1={x(t)} x2={x(t)} y1={m.t} y2={h - m.b} className="grid" />
                  <text x={x(t)} y={h - 8} textAnchor="middle">{tick(t)}</text>
                </g>
              ))}
            </g>
            {items.map((b, i) => {
              const cy = m.t + row * i + row / 2;
              return (
                <g key={b.label}
                  onMouseMove={(e) => setTip({ x: e.nativeEvent.offsetX, y: e.nativeEvent.offsetY, content: (
                    <><b>{b.label}</b><br />median {full.format(b.median)} · Q1 {full.format(b.q1)} · Q3 {full.format(b.q3)}
                      <br />min {full.format(b.min)} · max {full.format(b.max)} · outliers {b.outlier_count}</>) })}>
                  <rect x={0} y={cy - row / 2} width={width} height={row} fill="transparent" />
                  <text x={m.l - 8} y={cy} dy="0.32em" textAnchor="end" className="label">{b.label.length > 22 ? b.label.slice(0, 21) + "…" : b.label}</text>
                  <line x1={x(b.whisker_low)} x2={x(b.whisker_high)} y1={cy} y2={cy} className="whisker" />
                  <line x1={x(b.whisker_low)} x2={x(b.whisker_low)} y1={cy - 6} y2={cy + 6} className="whisker" />
                  <line x1={x(b.whisker_high)} x2={x(b.whisker_high)} y1={cy - 6} y2={cy + 6} className="whisker" />
                  <rect x={x(b.q1)} y={cy - 9} width={Math.max(2, x(b.q3) - x(b.q1))} height={18} rx={4} fill={color} fillOpacity={0.22} />
                  <line x1={x(b.median)} x2={x(b.median)} y1={cy - 9} y2={cy + 9} stroke={color} strokeWidth={2} strokeLinecap="round" />
                  {b.outliers.map((o, k) => <circle key={k} cx={x(o)} cy={cy} r={4} fill={color} className="ringed" />)}
                </g>
              );
            })}
          </svg>
        );
      }}
    </ChartFrame>
  );
}

// ---------------------------------------------------------------- scatter

export function ScatterChart({ section }: { section: Of<"scatter"> }) {
  const dark = useDark();
  const color = SERIES[dark ? "dark" : "light"][0];
  const pts = section.points;
  const [nearest, setNearest] = useState<number[] | null>(null);
  const table = { columns: columns(section.x_label, section.y_label), rows: pts.slice(0, 500) };
  return (
    <ChartFrame title={section.title} table={table}
      legend={section.sampled ? <p className="muted small">Δείγμα {pts.length} από {section.total} σημεία.</p> : null}>
      {(width, setTip) => {
        const h = 300, m = { l: 52, r: 16, t: 10, b: 40 };
        const xs = pts.map((p) => p[0]), ys = pts.map((p) => p[1]);
        const xt = niceTicks(Math.min(...xs), Math.max(...xs), Math.max(2, Math.floor(width / 100)));
        const yt = niceTicks(Math.min(...ys), Math.max(...ys));
        const x = (v: number) => m.l + ((v - xt[0]) / (xt[xt.length - 1] - xt[0] || 1)) * (width - m.l - m.r);
        const y = (v: number) => m.t + (1 - (v - yt[0]) / (yt[yt.length - 1] - yt[0] || 1)) * (h - m.t - m.b);
        return (
          <svg width={width} height={h} role="img" aria-label={section.title ?? "Scatter"}
            onMouseLeave={() => setNearest(null)}
            onMouseMove={(e) => {
              const mx = e.nativeEvent.offsetX, my = e.nativeEvent.offsetY;
              let best = 144, hit: number[] | null = null;
              for (const p of pts) {
                const d = (x(p[0]) - mx) ** 2 + (y(p[1]) - my) ** 2;
                if (d < best) { best = d; hit = p; }
              }
              setNearest(hit);
              setTip(hit ? { x: mx, y: my, content: <>{section.x_label}: <b>{full.format(hit[0])}</b><br />{section.y_label}: <b>{full.format(hit[1])}</b></> } : null);
            }}>
            <YAxis ticks={yt} y={y} left={m.l} right={width - m.r} />
            <g className="axis">
              {xt.map((t) => <text key={t} x={x(t)} y={h - 22} textAnchor="middle">{tick(t)}</text>)}
              <text x={(m.l + width - m.r) / 2} y={h - 4} textAnchor="middle" className="label">{section.x_label}</text>
            </g>
            {pts.map((p, i) => <circle key={i} cx={x(p[0])} cy={y(p[1])} r={3} fill={color} fillOpacity={0.55} />)}
            {nearest && <circle cx={x(nearest[0])} cy={y(nearest[1])} r={5} fill={color} className="ringed" />}
          </svg>
        );
      }}
    </ChartFrame>
  );
}

// ---------------------------------------------------------------- line

export function LineChart({ section }: { section: Of<"line"> }) {
  const dark = useDark();
  const palette = SERIES[dark ? "dark" : "light"];
  const series = section.series.slice(0, 8);
  const [hover, setHover] = useState<number | null>(null);
  const table = {
    columns: columns(section.x_label || "x", ...series.map((s) => s.name)),
    rows: section.x.map((xv, i) => [xv, ...series.map((s) => s.values[i])]),
  };
  const legend = series.length > 1 ? (
    <div className="legend">
      {series.map((s, i) => <span key={s.name}><i style={{ background: palette[i] }} />{s.name}</span>)}
    </div>
  ) : null;
  return (
    <ChartFrame title={section.title} table={table} legend={legend}>
      {(width, setTip) => {
        const h = 260, m = { l: 52, r: 16, t: 12, b: 28 };
        const n = section.x.length;
        const all = series.flatMap((s) => s.values.filter((v): v is number => v !== null));
        const yt = niceTicks(Math.min(0, ...all), Math.max(...all, 0));
        const x = (i: number) => m.l + (n <= 1 ? 0.5 : i / (n - 1)) * (width - m.l - m.r);
        const y = (v: number) => m.t + (1 - (v - yt[0]) / (yt[yt.length - 1] - yt[0] || 1)) * (h - m.t - m.b);
        const step = Math.max(1, Math.ceil(n / Math.floor(width / 90)));
        const path = (values: (number | null)[]) =>
          values.map((v, i) => (v === null ? "" : `${i === 0 || values[i - 1] === null ? "M" : "L"}${x(i)},${y(v)}`)).join("");
        return (
          <svg width={width} height={h} role="img" aria-label={section.title ?? "Line chart"}
            onMouseMove={(e) => {
              const i = Math.round(((e.nativeEvent.offsetX - m.l) / (width - m.l - m.r || 1)) * (n - 1));
              const idx = Math.min(n - 1, Math.max(0, i));
              setHover(idx);
              setTip({ x: e.nativeEvent.offsetX, y: e.nativeEvent.offsetY, content: (
                <><b>{String(section.x[idx])}</b>{series.map((s, k) => (
                  <div key={s.name} className="tip-row"><i style={{ background: palette[k] }} />{s.name}: <b>{formatValue(s.values[idx])}</b></div>
                ))}</>) });
            }}
            onMouseLeave={() => setHover(null)}>
            <YAxis ticks={yt} y={y} left={m.l} right={width - m.r} />
            <g className="axis">
              {section.x.map((xv, i) => (i % step === 0 ? <text key={i} x={x(i)} y={h - 8} textAnchor="middle">{String(xv)}</text> : null))}
            </g>
            {hover !== null && <line x1={x(hover)} x2={x(hover)} y1={m.t} y2={h - m.b} className="crosshair" />}
            {series.map((s, k) => (
              <path key={s.name} d={path(s.values)} fill="none" stroke={palette[k]} strokeWidth={2} strokeLinejoin="round" strokeLinecap="round" />
            ))}
            {series.map((s, k) => {
              const i = hover ?? s.values.length - 1;
              const v = s.values[i];
              return v === null || v === undefined ? null : <circle key={s.name} cx={x(i)} cy={y(v)} r={4} fill={palette[k]} className="ringed" />;
            })}
          </svg>
        );
      }}
    </ChartFrame>
  );
}

// ---------------------------------------------------------------- heatmap

export function HeatmapChart({ section }: { section: Of<"heatmap"> }) {
  const dark = useDark();
  const flat = section.values.flat().filter((v): v is number => v !== null);
  const min = Math.min(...flat), max = Math.max(...flat);
  const bound = Math.max(Math.abs(min), Math.abs(max)) || 1;
  const mode = dark ? "dark" : "light";
  const sequential = dark ? SEQ.slice(3).reverse() : SEQ;
  const colorOf = (v: number) =>
    section.diverging
      ? v >= 0 ? lerpRamp(BLUE_ARM[mode], v / bound) : lerpRamp(RED_ARM[mode], -v / bound)
      : lerpRamp(sequential, (v - min) / (max - min || 1));
  const table = {
    columns: columns("", ...section.x_labels),
    rows: section.y_labels.map((label, i) => [label, ...section.values[i]]),
  };
  const gradient = section.diverging
    ? [...RED_ARM[mode].slice().reverse(), ...BLUE_ARM[mode].slice(1)]
    : sequential;
  const legend = (
    <div className="scale-legend">
      <span>{full.format(section.diverging ? -bound : min)}</span>
      <i style={{ background: `linear-gradient(90deg, ${gradient.join(",")})` }} />
      <span>{full.format(section.diverging ? bound : max)}</span>
    </div>
  );
  return (
    <ChartFrame title={section.title} table={table} legend={legend}>
      {(width, setTip) => {
        const nx = section.x_labels.length, ny = section.y_labels.length;
        const left = Math.min(150, Math.max(...section.y_labels.map((l) => l.length)) * 7 + 12);
        const cell = Math.max(14, Math.min(48, (width - left - 8) / nx));
        const top = 8, bottom = 90;
        const h = top + ny * cell + bottom;
        const showValues = cell >= 34 && nx * ny <= 225;
        return (
          <svg width={Math.min(width, left + nx * cell + 8)} height={h} role="img" aria-label={section.title ?? "Heatmap"}>
            {section.values.map((row, i) => row.map((v, j) => {
              const fill = v === null ? "transparent" : colorOf(v);
              return (
                <g key={`${i}-${j}`}
                  onMouseMove={(e) => setTip({ x: e.nativeEvent.offsetX, y: e.nativeEvent.offsetY,
                    content: <>{section.y_labels[i]} × {section.x_labels[j]}<br /><b>{formatValue(v)}</b></> })}>
                  <rect x={left + j * cell + 1} y={top + i * cell + 1} width={cell - 2} height={cell - 2} rx={3} fill={fill} />
                  {showValues && v !== null && (
                    <text x={left + j * cell + cell / 2} y={top + i * cell + cell / 2} dy="0.32em" textAnchor="middle"
                      className="cell-value" fill={inkOn(fill)}>{Number.isInteger(v) || Math.abs(v) >= 10 ? tick(v) : v.toFixed(2)}</text>
                  )}
                </g>
              );
            }))}
            <g className="axis">
              {section.y_labels.map((label, i) => (
                <text key={label + i} x={left - 6} y={top + i * cell + cell / 2} dy="0.32em" textAnchor="end">
                  {label.length > 20 ? label.slice(0, 19) + "…" : label}
                </text>
              ))}
              {section.x_labels.map((label, j) => (
                <text key={label + j} transform={`translate(${left + j * cell + cell / 2},${top + ny * cell + 8}) rotate(-45)`} textAnchor="end">
                  {label.length > 14 ? label.slice(0, 13) + "…" : label}
                </text>
              ))}
            </g>
          </svg>
        );
      }}
    </ChartFrame>
  );
}

// ---------------------------------------------------------------- bar (horizontal)

export function BarChart({ section }: { section: Of<"bar"> }) {
  const dark = useDark();
  const color = SERIES[dark ? "dark" : "light"][0];
  const max = Math.max(...section.values, 0) || 1;
  const table = { columns: columns("κατηγορία", "τιμή"), rows: section.labels.map((l, i) => [l, section.values[i]]) };
  return (
    <ChartFrame title={section.title} table={table}>
      {() => (
        <div className="bars">
          {section.labels.map((label, i) => (
            <div className="bar-row" key={`${label}-${i}`} title={`${label}: ${formatValue(section.values[i])}${section.unit}`}>
              <span className="bar-label">{label}</span>
              <div className="bar-track">
                <div className="bar-fill" style={{ width: `${(Math.max(section.values[i], 0) / max) * 100}%`, background: color }} />
              </div>
              <span className="bar-value">{formatValue(section.values[i])}{section.unit}</span>
            </div>
          ))}
        </div>
      )}
    </ChartFrame>
  );
}
