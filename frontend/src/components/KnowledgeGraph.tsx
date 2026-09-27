import { forceCenter, forceCollide, forceLink, forceManyBody, forceSimulation, type SimulationLinkDatum, type SimulationNodeDatum } from "d3-force";
import { useEffect, useMemo, useRef, useState } from "react";
import type { GraphData } from "../lib/types";

type N = SimulationNodeDatum & GraphData["nodes"][number];
type L = SimulationLinkDatum<N> & { rel: string };

export const NODE_STYLE: Record<string, { color: string; r: number; label: string }> = {
  stakeholder: { color: "#4f6fa8", r: 11, label: "Stakeholder" },
  constraint: { color: "#b0873a", r: 8, label: "Constraint" },
  session: { color: "#3f8290", r: 5, label: "Session" },
  room: { color: "#4a8a6a", r: 7, label: "Room" },
  group: { color: "#a84f5c", r: 8, label: "Section" },
  request: { color: "#8a8477", r: 5, label: "Request / rule" },
  rule: { color: "#8a8477", r: 5, label: "Request / rule" },
};

export const EDGE_STYLE: Record<string, { color: string; dash?: string; label: string }> = {
  owns: { color: "#4f6fa8", label: "owns" },
  references: { color: "#b0873a", label: "references" },
  has_authority_over: { color: "#7a7468", label: "has authority over" },
  reports_to: { color: "#5a62a8", dash: "4 3", label: "reports to" },
  derived_from: { color: "#8a8477", dash: "2 3", label: "derived from" },
  conflicts_with: { color: "#b3443a", dash: "6 3", label: "conflicts with (MUS)" },
  attended_by: { color: "#a84f5c", label: "attended by" },
  member_of: { color: "#a84f5c", dash: "2 2", label: "member of" },
  affects: { color: "#3f8290", label: "affects" },
};

function styleOf(n: GraphData["nodes"][number]) {
  const key = n.kind === "resource" ? n.type ?? "session" : n.kind;
  return NODE_STYLE[key] ?? NODE_STYLE.session;
}

export function KnowledgeGraph({ data, hidden }: { data: GraphData; hidden: Set<string> }) {
  const ref = useRef<SVGSVGElement>(null);
  const [size, setSize] = useState({ w: 900, h: 620 });
  const [, setTick] = useState(0);
  const [hover, setHover] = useState<string | null>(null);
  const [view, setView] = useState({ x: 0, y: 0, k: 1 });
  const drag = useRef<{ x: number; y: number } | null>(null);

  const { nodes, links } = useMemo(() => {
    const keep = data.edges.filter((e) => !hidden.has(e.rel));
    const used = new Set(keep.flatMap((e) => [e.source, e.target]));
    const nodes: N[] = data.nodes.filter((n) => used.has(n.id) || n.kind === "stakeholder").map((n) => ({ ...n }));
    const ids = new Set(nodes.map((n) => n.id));
    const links: L[] = keep.filter((e) => ids.has(e.source) && ids.has(e.target)).map((e) => ({ source: e.source, target: e.target, rel: e.rel }));
    return { nodes, links };
  }, [data, hidden]);

  useEffect(() => {
    const el = ref.current?.parentElement;
    if (!el) return;
    const ro = new ResizeObserver(([e]) => setSize({ w: e.contentRect.width, h: Math.max(520, e.contentRect.height) }));
    ro.observe(el);
    return () => ro.disconnect();
  }, []);

  useEffect(() => {
    const sim = forceSimulation<N>(nodes)
      .force("link", forceLink<N, L>(links).id((d) => d.id).distance((l) => (l.rel === "conflicts_with" ? 60 : l.rel === "attended_by" ? 34 : 48)).strength(0.5))
      .force("charge", forceManyBody().strength(-120))
      .force("center", forceCenter(size.w / 2, size.h / 2))
      .force("collide", forceCollide<N>().radius((d) => styleOf(d).r + 4))
      .alpha(1)
      .alphaDecay(0.03)
      .on("tick", () => setTick((t) => t + 1));
    return () => {
      sim.stop();
    };
  }, [nodes, links, size.w, size.h]);

  const neighbours = useMemo(() => {
    if (!hover) return null;
    const s = new Set([hover]);
    for (const l of links) {
      const a = (l.source as N).id;
      const b = (l.target as N).id;
      if (a === hover) s.add(b);
      if (b === hover) s.add(a);
    }
    return s;
  }, [hover, links]);

  return (
    <svg
      ref={ref}
      width="100%"
      height={size.h}
      className="cursor-grab touch-none select-none active:cursor-grabbing"
      onWheel={(e) => {
        const k = Math.min(3, Math.max(0.4, view.k * (e.deltaY < 0 ? 1.1 : 0.9)));
        setView((v) => ({ ...v, k }));
      }}
      onPointerDown={(e) => (drag.current = { x: e.clientX - view.x, y: e.clientY - view.y })}
      onPointerMove={(e) => drag.current && setView((v) => ({ ...v, x: e.clientX - drag.current!.x, y: e.clientY - drag.current!.y }))}
      onPointerUp={() => (drag.current = null)}
      onPointerLeave={() => (drag.current = null)}
    >
      <g transform={`translate(${view.x} ${view.y}) scale(${view.k})`} style={{ transformOrigin: `${size.w / 2}px ${size.h / 2}px` }}>
        {links.map((l, i) => {
          const a = l.source as N;
          const b = l.target as N;
          const st = EDGE_STYLE[l.rel] ?? { color: "#7a7468" };
          const dim = neighbours && !(neighbours.has(a.id) && neighbours.has(b.id));
          return (
            <line
              key={i}
              x1={a.x}
              y1={a.y}
              x2={b.x}
              y2={b.y}
              stroke={st.color}
              strokeWidth={l.rel === "conflicts_with" ? 2 : 1}
              strokeDasharray={st.dash}
              opacity={dim ? 0.06 : l.rel === "conflicts_with" ? 0.9 : 0.35}
            />
          );
        })}
        {nodes.map((n) => {
          const st = styleOf(n);
          const dim = neighbours && !neighbours.has(n.id);
          const big = n.kind === "stakeholder" || n.kind === "constraint";
          return (
            <g key={n.id} transform={`translate(${n.x ?? 0} ${n.y ?? 0})`} opacity={dim ? 0.15 : 1} onMouseEnter={() => setHover(n.id)} onMouseLeave={() => setHover(null)} className="cursor-pointer">
              <circle r={st.r} fill={st.color} stroke="var(--panel)" strokeWidth={2} />
              {(big || hover === n.id) && (
                <text y={-st.r - 5} textAnchor="middle" className="fill-ink-2 text-[10px] font-medium" style={{ paintOrder: "stroke", stroke: "var(--bg)", strokeWidth: 3 }}>
                  {n.label.length > 22 ? `${n.label.slice(0, 20)}…` : n.label}
                </text>
              )}
            </g>
          );
        })}
      </g>
    </svg>
  );
}
