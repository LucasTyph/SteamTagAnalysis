import {
  forceCenter,
  forceCollide,
  forceLink,
  forceManyBody,
  forceSimulation,
  forceX,
  forceY,
  type Simulation,
  type SimulationLinkDatum,
  type SimulationNodeDatum,
} from "d3-force";
import { useEffect, useMemo, useRef, useState } from "react";
import type { PairEdge, Tag } from "../data/queries";
import { scoreColor } from "../lib/colors";

interface Node extends SimulationNodeDatum {
  tag: Tag;
  r: number;
}
type Link = SimulationLinkDatum<Node> & { lift: number };

interface Props {
  tags: Tag[];
  edges: PairEdge[];
  totalGames: number;
  onSelect: (tag: Tag) => void;
  edgesPerNode?: number;
}

const W = 960;
const H = 640;
const MIN_ZOOM = 0.4;
const MAX_ZOOM = 4;
const CLICK_SLOP = 4; // px of movement before a press counts as a drag

interface View {
  k: number;
  x: number;
  y: number;
}

type Gesture =
  | { kind: "drag"; node: Node; startX: number; startY: number; moved: boolean }
  | { kind: "pan"; startX: number; startY: number; view: View };

function buildGraph(tags: Tag[], edges: PairEdge[], totalGames: number, edgesPerNode: number) {
  const byId = new Map(tags.map((t) => [t.tagid, t]));
  const maxGames = Math.max(...tags.map((t) => t.n_games));
  const nodes: Node[] = tags.map((tag) => ({ tag, r: 4 + 16 * Math.sqrt(tag.n_games / maxGames) }));
  const nodeOf = new Map(nodes.map((n) => [n.tag.tagid, n]));

  const scored = edges
    .filter((e) => byId.has(e.t1) && byId.has(e.t2) && e.n_games >= 30)
    .map((e) => {
      const a = byId.get(e.t1)!;
      const b = byId.get(e.t2)!;
      return { e, lift: (e.n_games * totalGames) / (a.n_games * b.n_games) };
    });
  const keep = new Set<(typeof scored)[number]>();
  for (const t of tags) {
    scored
      .filter((s) => s.e.t1 === t.tagid || s.e.t2 === t.tagid)
      .sort((a, b) => b.lift - a.lift)
      .slice(0, edgesPerNode)
      .forEach((s) => keep.add(s));
  }
  const links: Link[] = [...keep].map((s) => ({
    source: nodeOf.get(s.e.t1)!,
    target: nodeOf.get(s.e.t2)!,
    lift: s.lift,
  }));
  return { nodes, links };
}

function makeSimulation(nodes: Node[], links: Link[]): Simulation<Node, Link> {
  return forceSimulation(nodes)
    .force(
      "link",
      forceLink<Node, Link>(links)
        .distance(60)
        .strength((l) => Math.min(1, 0.15 * Math.log(1 + l.lift))),
    )
    .force("charge", forceManyBody().strength(-90))
    .force("collide", forceCollide<Node>().radius((n) => n.r + 2))
    .force("x", forceX(W / 2).strength(0.06))
    .force("y", forceY(H / 2).strength(0.09))
    .force("center", forceCenter(W / 2, H / 2))
    .velocityDecay(0.35);
}

/**
 * Tag co-occurrence map with a live force simulation, like Obsidian's graph view:
 * drag a tag and its neighbours follow while the rest rebalance; Ctrl/⌘ + scroll
 * (or pinch) zooms, dragging the background pans. Each tag keeps its strongest links
 * by lift (how much more often two tags appear together than chance). Node size =
 * number of games, color = average score.
 */
export function TagNetwork({ tags, edges, totalGames, onSelect, edgesPerNode = 3 }: Props) {
  const [hover, setHover] = useState<number | null>(null);
  const svgRef = useRef<SVGSVGElement>(null);
  const viewportRef = useRef<SVGGElement>(null);
  const nodeEls = useRef(new Map<number, SVGGElement>());
  const linkEls = useRef<(SVGLineElement | null)[]>([]);
  const simRef = useRef<Simulation<Node, Link> | null>(null);
  const view = useRef<View>({ k: 1, x: 0, y: 0 });
  const gesture = useRef<Gesture | null>(null);

  const graph = useMemo(() => {
    const g = buildGraph(tags, edges, totalGames, edgesPerNode);
    // Settle offline first so the graph appears already laid out.
    const sim = makeSimulation(g.nodes, g.links).stop();
    for (let i = 0; i < 300; i++) sim.tick();
    return g;
  }, [tags, edges, totalGames, edgesPerNode]);

  const neighbors = useMemo(() => {
    const m = new Map<number, Set<number>>();
    for (const l of graph.links) {
      const a = (l.source as Node).tag.tagid;
      const b = (l.target as Node).tag.tagid;
      if (!m.has(a)) m.set(a, new Set());
      if (!m.has(b)) m.set(b, new Set());
      m.get(a)!.add(b);
      m.get(b)!.add(a);
    }
    return m;
  }, [graph]);

  // Live simulation: positions are written straight to the DOM on every tick.
  useEffect(() => {
    const sim = makeSimulation(graph.nodes, graph.links).alpha(0).alphaMin(0.002);
    sim.on("tick", () => {
      for (const n of graph.nodes) {
        nodeEls.current.get(n.tag.tagid)?.setAttribute("transform", `translate(${n.x},${n.y})`);
      }
      graph.links.forEach((l, i) => {
        const el = linkEls.current[i];
        if (!el) return;
        const s = l.source as Node;
        const t = l.target as Node;
        el.setAttribute("x1", String(s.x));
        el.setAttribute("y1", String(s.y));
        el.setAttribute("x2", String(t.x));
        el.setAttribute("y2", String(t.y));
      });
    });
    simRef.current = sim;
    return () => {
      sim.stop();
      simRef.current = null;
    };
  }, [graph]);

  const applyView = () => {
    const v = view.current;
    viewportRef.current?.setAttribute("transform", `translate(${v.x},${v.y}) scale(${v.k})`);
  };

  /** Screen point → SVG viewBox coordinates (before the zoom/pan transform). */
  const toSvg = (clientX: number, clientY: number) => {
    const svg = svgRef.current!;
    const pt = svg.createSVGPoint();
    pt.x = clientX;
    pt.y = clientY;
    return pt.matrixTransform(svg.getScreenCTM()!.inverse());
  };

  /** Screen point → graph coordinates (after undoing zoom/pan). */
  const toGraph = (clientX: number, clientY: number) => {
    const p = toSvg(clientX, clientY);
    const v = view.current;
    return { x: (p.x - v.x) / v.k, y: (p.y - v.y) / v.k };
  };

  const zoomAt = (factor: number, clientX?: number, clientY?: number) => {
    const v = view.current;
    const k = Math.max(MIN_ZOOM, Math.min(MAX_ZOOM, v.k * factor));
    const c = clientX == null ? { x: W / 2, y: H / 2 } : toSvg(clientX, clientY!);
    // Keep the point under the cursor fixed while zooming.
    view.current = { k, x: c.x - ((c.x - v.x) * k) / v.k, y: c.y - ((c.y - v.y) * k) / v.k };
    applyView();
  };

  // Wheel needs a non-passive listener to stop the page from scrolling while zooming.
  useEffect(() => {
    const svg = svgRef.current;
    if (!svg) return;
    const onWheel = (e: WheelEvent) => {
      if (!(e.ctrlKey || e.metaKey)) return; // plain scrolling keeps scrolling the page
      e.preventDefault();
      zoomAt(Math.exp(-e.deltaY * 0.0025), e.clientX, e.clientY);
    };
    svg.addEventListener("wheel", onWheel, { passive: false });
    return () => svg.removeEventListener("wheel", onWheel);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const startDrag = (e: React.PointerEvent, n: Node) => {
    if (e.button !== 0) return;
    e.stopPropagation();
    e.preventDefault(); // no focus ring from a mouse press; keyboard focus still shows one
    svgRef.current?.setPointerCapture(e.pointerId);
    gesture.current = { kind: "drag", node: n, startX: e.clientX, startY: e.clientY, moved: false };
    n.fx = n.x;
    n.fy = n.y;
    setHover(n.tag.tagid);
  };

  const startPan = (e: React.PointerEvent) => {
    if (e.button !== 0) return;
    svgRef.current?.setPointerCapture(e.pointerId);
    gesture.current = { kind: "pan", startX: e.clientX, startY: e.clientY, view: { ...view.current } };
  };

  const onPointerMove = (e: React.PointerEvent) => {
    const g = gesture.current;
    if (!g) return;
    if (g.kind === "drag") {
      if (!g.moved && Math.hypot(e.clientX - g.startX, e.clientY - g.startY) > CLICK_SLOP) {
        g.moved = true;
        simRef.current?.alphaTarget(0.3).restart();
      }
      if (g.moved) {
        const p = toGraph(e.clientX, e.clientY);
        g.node.fx = p.x;
        g.node.fy = p.y;
      }
    } else {
      const a = toSvg(g.startX, g.startY);
      const b = toSvg(e.clientX, e.clientY);
      view.current = { ...g.view, x: g.view.x + b.x - a.x, y: g.view.y + b.y - a.y };
      applyView();
    }
  };

  const endGesture = (e: React.PointerEvent) => {
    const g = gesture.current;
    gesture.current = null;
    if (svgRef.current?.hasPointerCapture(e.pointerId)) svgRef.current.releasePointerCapture(e.pointerId);
    if (g?.kind !== "drag") return;
    // Let go: the node rejoins the simulation and the graph settles, as in Obsidian.
    g.node.fx = null;
    g.node.fy = null;
    simRef.current?.alphaTarget(0);
    if (!g.moved) onSelect(g.node.tag);
    setHover(null);
  };

  const resetView = () => {
    view.current = { k: 1, x: 0, y: 0 };
    applyView();
    simRef.current?.alpha(0.6).restart();
  };

  const dragging = () => gesture.current?.kind === "drag";
  const isLit = (id: number) => hover == null || id === hover || neighbors.get(hover)?.has(id);

  return (
    <figure className="network">
      <div className="network-controls" role="group" aria-label="Graph view controls">
        <button type="button" onClick={() => zoomAt(1.25)} aria-label="Zoom in">
          +
        </button>
        <button type="button" onClick={() => zoomAt(0.8)} aria-label="Zoom out">
          −
        </button>
        <button type="button" onClick={resetView}>
          Reset view
        </button>
      </div>
      <svg
        ref={svgRef}
        viewBox={`0 0 ${W} ${H}`}
        role="img"
        aria-label="Tag co-occurrence network"
        className="network-canvas"
        onPointerDown={startPan}
        onPointerMove={onPointerMove}
        onPointerUp={endGesture}
        onPointerCancel={endGesture}
      >
        <g ref={viewportRef}>
          <g className="links">
            {graph.links.map((l, i) => {
              const s = l.source as Node;
              const t = l.target as Node;
              const lit = hover != null && (s.tag.tagid === hover || t.tag.tagid === hover);
              return (
                <line
                  key={i}
                  ref={(el) => {
                    linkEls.current[i] = el;
                  }}
                  x1={s.x}
                  y1={s.y}
                  x2={t.x}
                  y2={t.y}
                  className={lit ? "lit" : hover != null ? "dim" : undefined}
                />
              );
            })}
          </g>
          <g className="nodes">
            {graph.nodes.map((n) => (
              <g
                key={n.tag.tagid}
                ref={(el) => {
                  if (el) nodeEls.current.set(n.tag.tagid, el);
                  else nodeEls.current.delete(n.tag.tagid);
                }}
                transform={`translate(${n.x},${n.y})`}
                className={isLit(n.tag.tagid) ? undefined : "dim"}
                onPointerDown={(e) => startDrag(e, n)}
                onPointerEnter={() => !dragging() && setHover(n.tag.tagid)}
                onPointerLeave={() => !dragging() && setHover(null)}
                role="button"
                tabIndex={0}
                aria-label={`${n.tag.name}: ${n.tag.n_games} games, average score ${n.tag.mean_score.toFixed(1)}%`}
                onKeyDown={(e) => (e.key === "Enter" || e.key === " ") && onSelect(n.tag)}
              >
                <circle r={n.r} fill={scoreColor(n.tag.mean_score)} />
                {(n.r > 9 || hover === n.tag.tagid || neighbors.get(hover ?? -1)?.has(n.tag.tagid)) && (
                  <text y={n.r + 11}>{n.tag.name}</text>
                )}
                <title>
                  {`${n.tag.name}\n${n.tag.n_games.toLocaleString("en-US")} games · avg ${n.tag.mean_score.toFixed(1)}%`}
                </title>
              </g>
            ))}
          </g>
        </g>
      </svg>
      <figcaption>
        Drag tags to pull the graph around · drag the background to pan · zoom with the +/− buttons,
        Ctrl/⌘ + scroll or a trackpad pinch · click a tag to explore it. Node size: games with the tag · color: average score (
        <span className="swatch" style={{ background: scoreColor(70) }} /> 70%
        <span className="swatch" style={{ background: scoreColor(78.5) }} /> 78.5%
        <span className="swatch" style={{ background: scoreColor(87) }} /> 87%) · links: tags that
        appear together unusually often.
      </figcaption>
    </figure>
  );
}
