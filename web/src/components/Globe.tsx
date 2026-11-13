import { useEffect, useRef } from "react";
import { geoGraticule10, geoInterpolate, geoOrthographic, geoPath, geoRotation, geoDistance } from "d3-geo";
import { feature, mesh } from "topojson-client";
import type { Topology, GeometryCollection } from "topojson-specification";
import worldData from "world-atlas/countries-50m.json";
import type { CountryTotal } from "../types";
import { shortMoney } from "../format";

const world = worldData as unknown as Topology<{ countries: GeometryCollection; land: GeometryCollection }>;
const LAND = feature(world, world.objects.land);
const BORDERS = mesh(world, world.objects.countries, (a, b) => a !== b);
const GRATICULE = geoGraticule10();

const GOLD = "242, 184, 75";
const STEPS = 56;            // points along each arc
const TILT = -24;            // the globe leans so that California sits a little above the middle
const HOLD = 3.2;            // seconds the globe stays on California before it starts to turn
const TURN = 5.5;            // degrees per second once it is turning
const LABELLED = 7;          // how many of the largest countries get a label on the map

interface Arc {
  country: CountryTotal;
  path: [number, number][];  // longitude and latitude along the great circle
  lift: number;              // how far the arc rises above the surface at its middle, in globe radii
  width: number;
  strength: number;          // 0 to 1, by amount
  delay: number;
  phase: number;
}

interface Props {
  origin: { lat: number; lon: number; name: string };
  countries: CountryTotal[];
  /** Changing this number restarts the animation from the beginning. */
  run: number;
  still: boolean;
}

function buildArcs(origin: Props["origin"], countries: CountryTotal[]): Arc[] {
  const top = Math.max(...countries.map((c) => c.amount), 1);
  const from: [number, number] = [origin.lon, origin.lat];
  return countries.map((country, rank) => {
    const to: [number, number] = [country.lon, country.lat];
    const along = geoInterpolate(from, to);
    const path: [number, number][] = [];
    for (let i = 0; i <= STEPS; i++) path.push(along(i / STEPS));
    const strength = Math.sqrt(country.amount / top);
    return {
      country,
      path,
      lift: 0.05 + 0.27 * (geoDistance(from, to) / Math.PI),
      width: 0.6 + 6.4 * strength,
      strength,
      delay: 0.5 + Math.min(rank * 0.04, 3.4),
      phase: (rank * 0.618) % 1,
    };
  });
}

const ease = (x: number) => 1 - Math.pow(1 - Math.min(Math.max(x, 0), 1), 3);

export default function Globe({ origin, countries, run, still }: Props) {
  const canvasRef = useRef<HTMLCanvasElement>(null);

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const ctx = canvas.getContext("2d");
    if (!ctx) return;
    const arcs = buildArcs(origin, countries);
    const projection = geoOrthographic().clipAngle(90).precision(0.4);
    const path = geoPath(projection, ctx);
    let width = 0;
    let height = 0;
    let frame = 0;
    const started = performance.now();

    const resize = () => {
      const box = canvas.getBoundingClientRect();
      const ratio = Math.min(window.devicePixelRatio || 1, 2);
      width = box.width;
      height = box.height;
      canvas.width = Math.round(width * ratio);
      canvas.height = Math.round(height * ratio);
      ctx.setTransform(ratio, 0, 0, ratio, 0, 0);
    };
    resize();
    const observer = new ResizeObserver(resize);
    observer.observe(canvas);

    const draw = (now: number) => {
      const t = still ? 60 : (now - started) / 1000;
      const turning = still ? 0 : Math.max(0, t - HOLD);
      // The turn starts gently: speed rises to full over the first three seconds.
      const turned = TURN * (turning < 3 ? (turning * turning) / 6 : turning - 1.5);
      const rotate: [number, number, number] = [-origin.lon + turned, TILT, 0];
      const radius = Math.min(width, height) * 0.385;
      const cx = width / 2;
      const cy = height / 2;
      projection.rotate(rotate).translate([cx, cy]).scale(radius);
      const spin = geoRotation(rotate);

      // A point on or above the globe, as the viewer sees it. `front` is false when it is behind the globe.
      const place = (lonLat: [number, number], lift: number) => {
        const [lon, lat] = spin(lonLat);
        const l = (lon * Math.PI) / 180;
        const p = (lat * Math.PI) / 180;
        const k = 1 + lift;
        const x = Math.cos(p) * Math.sin(l) * k;
        const y = Math.sin(p) * k;
        const z = Math.cos(p) * Math.cos(l) * k;
        const outside = x * x + y * y > 1;
        return { x: cx + x * radius, y: cy - y * radius, front: z >= 0, seen: z >= 0 || outside };
      };

      ctx.clearRect(0, 0, width, height);

      // A soft glow behind the globe, then the sea.
      const halo = ctx.createRadialGradient(cx, cy, radius * 0.9, cx, cy, radius * 1.35);
      halo.addColorStop(0, "rgba(70, 110, 190, 0.20)");
      halo.addColorStop(1, "rgba(70, 110, 190, 0)");
      ctx.fillStyle = halo;
      ctx.fillRect(0, 0, width, height);
      const sea = ctx.createRadialGradient(cx - radius * 0.35, cy - radius * 0.4, radius * 0.1, cx, cy, radius);
      sea.addColorStop(0, "#15264a");
      sea.addColorStop(1, "#0b1730");
      ctx.beginPath();
      path({ type: "Sphere" });
      ctx.fillStyle = sea;
      ctx.fill();

      ctx.beginPath();
      path(GRATICULE);
      ctx.strokeStyle = "rgba(160, 185, 230, 0.07)";
      ctx.lineWidth = 1;
      ctx.stroke();

      ctx.beginPath();
      path(LAND);
      ctx.fillStyle = "#24385f";
      ctx.fill();
      ctx.beginPath();
      path(BORDERS);
      ctx.strokeStyle = "rgba(10, 19, 38, 0.75)";
      ctx.lineWidth = 0.7;
      ctx.stroke();

      ctx.beginPath();
      path({ type: "Sphere" });
      ctx.strokeStyle = "rgba(160, 190, 240, 0.28)";
      ctx.lineWidth = 1.2;
      ctx.stroke();

      // The arcs, smallest first so the largest sit on top.
      const size = radius / 400;
      ctx.lineCap = "round";
      ctx.lineJoin = "round";
      for (let i = arcs.length - 1; i >= 0; i--) {
        const arc = arcs[i];
        const grown = ease((t - arc.delay) / 1.9);
        if (grown <= 0) continue;
        const last = Math.floor(grown * STEPS);
        const alpha = 0.1 + 0.68 * arc.strength;
        ctx.lineWidth = Math.max(0.5, arc.width * size);
        let open = false;
        let dim = false;
        ctx.beginPath();
        for (let s = 0; s <= last; s++) {
          const point = place(arc.path[s], arc.lift * Math.sin((Math.PI * s) / STEPS));
          if (!point.seen) {
            open = false;
            continue;
          }
          if (open && point.front === !dim) ctx.lineTo(point.x, point.y);
          else {
            // Start a new stroke when the arc passes behind the edge of the globe, where it is drawn fainter.
            if (open) {
              ctx.lineTo(point.x, point.y);
              ctx.strokeStyle = `rgba(${GOLD}, ${dim ? alpha * 0.35 : alpha})`;
              ctx.stroke();
              ctx.beginPath();
            }
            ctx.moveTo(point.x, point.y);
            dim = !point.front;
            open = true;
          }
        }
        ctx.strokeStyle = `rgba(${GOLD}, ${dim ? alpha * 0.35 : alpha})`;
        ctx.stroke();

        // Money moving along the arc once it has landed.
        if (grown >= 1 && !still) {
          const dots = arc.strength > 0.25 ? 2 : 1;
          for (let d = 0; d < dots; d++) {
            const u = (t * 0.16 + arc.phase + d / dots) % 1;
            const s = u * STEPS;
            const a = arc.path[Math.floor(s)];
            const b = arc.path[Math.min(STEPS, Math.floor(s) + 1)];
            const f = s - Math.floor(s);
            let step = b[0] - a[0];             // the short way round when the arc crosses the date line
            if (step > 180) step -= 360;
            if (step < -180) step += 360;
            const point = place([a[0] + step * f, a[1] + (b[1] - a[1]) * f], arc.lift * Math.sin(Math.PI * u));
            if (!point.seen) continue;
            ctx.beginPath();
            ctx.arc(point.x, point.y, Math.max(1, (1 + arc.width * 0.45) * size), 0, Math.PI * 2);
            ctx.fillStyle = `rgba(255, 226, 160, ${point.front ? 0.95 : 0.4})`;
            ctx.fill();
          }
        }
      }

      // Where each arc lands, with a name beside the largest.
      ctx.font = `500 ${Math.round(Math.max(12, 14 * size))}px "Inter Variable", system-ui, sans-serif`;
      ctx.textBaseline = "middle";
      const taken: { x: number; y: number }[] = [];
      arcs.forEach((arc, rank) => {
        if (ease((t - arc.delay) / 1.9) < 1) return;
        const end = place([arc.country.lon, arc.country.lat], 0);
        if (!end.front) return;
        ctx.beginPath();
        ctx.arc(end.x, end.y, Math.max(1.4, (1.2 + arc.width * 0.5) * size), 0, Math.PI * 2);
        ctx.fillStyle = `rgba(${GOLD}, ${0.5 + 0.5 * arc.strength})`;
        ctx.fill();
        if (rank >= LABELLED) return;
        const edge = Math.hypot(end.x - cx, end.y - cy) / radius;
        if (edge > 0.93) return;
        if (taken.some((p) => Math.abs(p.y - end.y) < 20 * size + 8 && Math.abs(p.x - end.x) < 150 * size)) return;
        taken.push(end);
        const text = `${arc.country.name}  ${shortMoney(arc.country.amount)}`;
        const left = end.x + 10 * size + 4;
        ctx.fillStyle = "rgba(8, 15, 32, 0.72)";
        const w = ctx.measureText(text).width;
        ctx.fillRect(left - 5, end.y - 11 * size - 2, w + 10, 22 * size + 4);
        ctx.fillStyle = "rgba(240, 236, 226, 0.95)";
        ctx.fillText(text, left, end.y + 1);
      });

      // California itself.
      const home = place([origin.lon, origin.lat], 0);
      if (home.front) {
        const pulse = still ? 0.5 : (t % 2.4) / 2.4;
        ctx.beginPath();
        ctx.arc(home.x, home.y, (6 + 20 * pulse) * size, 0, Math.PI * 2);
        ctx.strokeStyle = `rgba(${GOLD}, ${0.6 * (1 - pulse)})`;
        ctx.lineWidth = 1.5;
        ctx.stroke();
        ctx.beginPath();
        ctx.arc(home.x, home.y, 5 * size + 1, 0, Math.PI * 2);
        ctx.fillStyle = "#ffe2a0";
        ctx.fill();
      }

      if (!still) frame = requestAnimationFrame(draw);
    };
    frame = requestAnimationFrame(draw);
    const redraw = () => {
      if (still) requestAnimationFrame(draw);
    };
    const stillObserver = new ResizeObserver(redraw);
    stillObserver.observe(canvas);

    return () => {
      cancelAnimationFrame(frame);
      observer.disconnect();
      stillObserver.disconnect();
    };
  }, [origin, countries, run, still]);

  return (
    <canvas
      ref={canvasRef}
      className="globe"
      role="img"
      aria-label={`A globe with lines from ${origin.name} to the countries where the owners of unclaimed money last lived.`}
    />
  );
}
