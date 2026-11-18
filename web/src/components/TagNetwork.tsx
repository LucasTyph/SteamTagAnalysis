import {
  forceCenter,
  forceCollide,
  forceLink,
  forceManyBody,
  forceSimulation,
  forceX,
  forceY,
  type SimulationLinkDatum,
  type SimulationNodeDatum,
} from "d3-force";
import { useMemo, useState } from "react";
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

/**
 * Tag co-occurrence map. Each tag keeps its strongest links by lift (how much more
 * often two tags appear together than chance). Node size = number of games, color =
 * average score.
 */
export function TagNetwork({ tags, edges, totalGames, onSelect, edgesPerNode = 3 }: Props) {
  const [hover, setHover] = useState<number | null>(null);

  const layout = useMemo(() => {
    const byId = new Map(tags.map((t) => [t.tagid, t]));
    const maxGames = Math.max(...tags.map((t) => t.n_games));
    const nodes: Node[] = tags.map((tag) => ({
      tag,
      r: 4 + 16 * Math.sqrt(tag.n_games / maxGames),
    }));
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

    const sim = forceSimulation(nodes)
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
      .stop();
    for (let i = 0; i < 400; i++) sim.tick();
    for (const n of nodes) {
      n.x = Math.max(n.r, Math.min(W - n.r, n.x ?? 0));
      n.y = Math.max(n.r, Math.min(H - n.r, n.y ?? 0));
    }
    return { nodes, links };
  }, [tags, edges, totalGames, edgesPerNode]);

  const neighbors = useMemo(() => {
    const m = new Map<number, Set<number>>();
    for (const l of layout.links) {
      const a = (l.source as Node).tag.tagid;
      const b = (l.target as Node).tag.tagid;
      if (!m.has(a)) m.set(a, new Set());
      if (!m.has(b)) m.set(b, new Set());
      m.get(a)!.add(b);
      m.get(b)!.add(a);
    }
    return m;
  }, [layout]);

  const isLit = (id: number) => hover == null || id === hover || neighbors.get(hover)?.has(id);

  return (
    <figure className="network">
      <svg viewBox={`0 0 ${W} ${H}`} role="img" aria-label="Tag co-occurrence network">
        <g className="links">
          {layout.links.map((l, i) => {
            const s = l.source as Node;
            const t = l.target as Node;
            const lit = hover != null && (s.tag.tagid === hover || t.tag.tagid === hover);
            return (
              <line
                key={i}
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
          {layout.nodes.map((n) => (
            <g
              key={n.tag.tagid}
              transform={`translate(${n.x},${n.y})`}
              className={isLit(n.tag.tagid) ? undefined : "dim"}
              onMouseEnter={() => setHover(n.tag.tagid)}
              onMouseLeave={() => setHover(null)}
              onClick={() => onSelect(n.tag)}
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
      </svg>
      <figcaption>
        Node size: games with the tag · color: average score (
        <span className="swatch" style={{ background: scoreColor(70) }} /> 70%
        <span className="swatch" style={{ background: scoreColor(78.5) }} /> 78.5%
        <span className="swatch" style={{ background: scoreColor(87) }} /> 87%) · links: tags that
        appear together unusually often. Click a tag to explore it.
      </figcaption>
    </figure>
  );
}
