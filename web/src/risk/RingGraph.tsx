import { useState } from "react";
import { exact } from "../format";
import type { RiskGroup, RiskStatus } from "./types";

export const STATUS_WORDS: Record<RiskStatus, string> = {
  held: "Held",
  suspended: "Approval suspended",
  paid_before: "Paid before the link showed",
  released: "Released",
  closed: "Rejected",
  clear: "Clear",
};

const NODE_W = 232;
const NODE_H = 68;
const ROW = 82;
const HUB_H = 42;
const HUB_ROW = 52;
const WIDTH = 1080;

/** One group as a picture: the claims down both sides, and in the middle each thing they share, joined to the
 *  claims that share it. A solid line is a signal that links claims; a dashed line only adds to the points. */
export default function RingGraph({ group, chosen, onChoose }: { group: RiskGroup; chosen: string | null; onChoose: (id: string) => void }) {
  const [lit, setLit] = useState<number | null>(null);
  const left = group.nodes.filter((_, i) => i % 2 === 0);
  const right = group.nodes.filter((_, i) => i % 2 === 1);
  const rows = Math.max(left.length, right.length);
  const height = Math.max(rows * ROW, group.shared.length * HUB_ROW) + 12;
  const place = new Map<string, { x: number; y: number; side: "left" | "right" }>();
  const column = (nodes: typeof group.nodes, side: "left" | "right") =>
    nodes.forEach((n, i) => {
      const top = (height - nodes.length * ROW) / 2 + i * ROW + (ROW - NODE_H) / 2;
      place.set(n.id, { x: side === "left" ? 8 : WIDTH - NODE_W - 8, y: top, side });
    });
  column(left, "left");
  column(right, "right");
  const hubW = 470;
  const hubX = (WIDTH - hubW) / 2;
  const hubs = group.shared.map((s, i) => ({ ...s, y: (height - group.shared.length * HUB_ROW) / 2 + i * HUB_ROW + (HUB_ROW - HUB_H) / 2 }));
  return (
    <svg className="ring-graph" viewBox={`0 0 ${WIDTH} ${height}`} role="img"
      aria-label={`${group.nodes.length} linked claims and the ${group.shared.length} things they share`}>
      {hubs.map((hub, h) =>
        hub.claims.map((id) => {
          const at = place.get(id);
          if (!at) return null;
          const x1 = at.side === "left" ? at.x + NODE_W : at.x;
          const x2 = at.side === "left" ? hubX : hubX + hubW;
          const y1 = at.y + NODE_H / 2;
          const y2 = hub.y + HUB_H / 2;
          const bend = (x2 - x1) * 0.5;
          return (
            <path key={`${h}-${id}`} d={`M ${x1} ${y1} C ${x1 + bend} ${y1}, ${x2 - bend} ${y2}, ${x2} ${y2}`}
              className={`ring-line${hub.linking ? " ring-line-linking" : ""}${lit === h ? " ring-line-lit" : lit !== null ? " ring-line-dim" : ""}`} />
          );
        }),
      )}
      {hubs.map((hub, h) => (
        <g key={h} className={`ring-hub${hub.linking ? " ring-hub-linking" : ""}${lit === h ? " ring-hub-lit" : ""}`}
          onMouseEnter={() => setLit(h)} onMouseLeave={() => setLit(null)}>
          <rect x={hubX} y={hub.y} width={hubW} height={HUB_H} rx={HUB_H / 2} />
          <text x={hubX + 22} y={hub.y + HUB_H / 2 + 6} className="ring-hub-kind">{hub.label}</text>
          <text x={hubX + hubW - 22} y={hub.y + HUB_H / 2 + 6} textAnchor="end" className="ring-hub-element">{short(hub.element, hub.label)}</text>
        </g>
      ))}
      {group.nodes.map((n) => {
        const at = place.get(n.id)!;
        return (
          <g key={n.id} className={`ring-node ring-node-${n.status}${chosen === n.id ? " ring-node-on" : ""}`} onClick={() => onChoose(n.id)}
            role="button" tabIndex={0} onKeyDown={(e) => e.key === "Enter" && onChoose(n.id)}>
            <rect x={at.x} y={at.y} width={NODE_W} height={NODE_H} rx={12} />
            <text x={at.x + 16} y={at.y + 28} className="ring-node-name">{n.claimant}</text>
            <text x={at.x + NODE_W - 16} y={at.y + 28} textAnchor="end" className="ring-node-amount">{exact(n.amount, n.currency)}</text>
            <text x={at.x + 16} y={at.y + 52} className="ring-node-status">{STATUS_WORDS[n.status]}</text>
          </g>
        );
      })}
    </svg>
  );
}

/** The shared element, cut so that it fits beside the signal's name in the middle of the picture. */
function short(element: string, label: string): string {
  const room = 44 - label.length;
  return element.length > room ? `${element.slice(0, room - 1).trimEnd()}…` : element;
}
