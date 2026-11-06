"use client";
import type * as GeoJSON from "geojson";

import "maplibre-gl/dist/maplibre-gl.css";
import type { GeoJSONSource, Map as MapLibreMap } from "maplibre-gl";
import { useEffect, useRef, useState } from "react";
import { SEVERITY_COLORS } from "@/components/art/severity-marker";

export type IncidentPoint = {
  id: string;
  lon: number;
  lat: number;
  level: 1 | 2 | 3 | 4;
  label: string;
  type: string;
  uncertaintyKm?: number;
  /** Original geometry when it is an area. */
  area?: GeoJSON.Geometry;
};
export type AssetPoint = {
  id: string;
  lon: number;
  lat: number;
  label: string;
  exposed: boolean;
  criticality: number;
};
export type Layers = { incidents: boolean; assets: boolean; zones: boolean; density: boolean };
export type View = { center: [number, number]; zoom: number };
export type Bbox = [number, number, number, number];
export type Drawn =
  { geometry: GeoJSON.Polygon } | { circle: { center: [number, number]; radius_km: number } };

type Props = {
  incidents?: IncidentPoint[];
  assets?: AssetPoint[];
  zones?: GeoJSON.FeatureCollection;
  rings?: { lon: number; lat: number; radiiKm: number[] } | null;
  layers?: Layers;
  view?: View;
  fit?: Bbox | null;
  selected?: { kind: "incident" | "asset"; id: string } | null;
  onSelect?: (kind: "incident" | "asset", id: string) => void;
  onMove?: (view: View, bbox: Bbox) => void;
  draw?: "polygon" | "circle" | null;
  onDraw?: (shape: Drawn) => void;
  label: string;
  className?: string;
};

const SHAPES = ["circle", "square", "triangle", "diamond"] as const;

function icon(shape: (typeof SHAPES)[number], color: string, size = 28): ImageData {
  const canvas = document.createElement("canvas");
  canvas.width = canvas.height = size;
  const ctx = canvas.getContext("2d") as CanvasRenderingContext2D;
  const c = size / 2;
  const r = size / 2 - 3;
  ctx.fillStyle = color;
  ctx.strokeStyle = "#FFFFFF";
  ctx.lineWidth = 2;
  ctx.beginPath();
  if (shape === "circle") ctx.arc(c, c, r - 2, 0, Math.PI * 2);
  if (shape === "square") ctx.rect(c - r + 2, c - r + 2, 2 * r - 4, 2 * r - 4);
  if (shape === "triangle") {
    ctx.moveTo(c, c - r);
    ctx.lineTo(c + r, c + r - 2);
    ctx.lineTo(c - r, c + r - 2);
    ctx.closePath();
  }
  if (shape === "diamond") {
    ctx.moveTo(c, c - r);
    ctx.lineTo(c + r, c);
    ctx.lineTo(c, c + r);
    ctx.lineTo(c - r, c);
    ctx.closePath();
  }
  ctx.fill();
  ctx.stroke();
  return ctx.getImageData(0, 0, size, size);
}

export function ring(lon: number, lat: number, km: number, steps = 64): [number, number][] {
  const dLat = km / 111.32;
  const dLon = km / (111.32 * Math.max(0.05, Math.cos((lat * Math.PI) / 180)));
  return Array.from({ length: steps + 1 }, (_, i) => {
    const a = (i / steps) * Math.PI * 2;
    return [lon + dLon * Math.cos(a), lat + dLat * Math.sin(a)];
  });
}

function haversineKm(a: [number, number], b: [number, number]): number {
  const R = 6371;
  const dLat = ((b[1] - a[1]) * Math.PI) / 180;
  const dLon = ((b[0] - a[0]) * Math.PI) / 180;
  const h =
    Math.sin(dLat / 2) ** 2 +
    Math.cos((a[1] * Math.PI) / 180) * Math.cos((b[1] * Math.PI) / 180) * Math.sin(dLon / 2) ** 2;
  return 2 * R * Math.asin(Math.sqrt(h));
}

const EMPTY: GeoJSON.FeatureCollection = { type: "FeatureCollection", features: [] };

/**
 * Application map. Incidents are symbols (shape and size change with level), assets are clustered GPU circles so
 * 5,000 markers pan smoothly, and the basemap is self-hosted country outlines. Every layer is also available as a
 * list on the page that hosts the map.
 */
export default function AppMap({
  incidents = [],
  assets = [],
  zones,
  rings,
  layers = { incidents: true, assets: true, zones: true, density: false },
  view,
  fit,
  selected,
  onSelect,
  onMove,
  draw,
  onDraw,
  label,
  className,
}: Props) {
  const box = useRef<HTMLDivElement>(null);
  const mapRef = useRef<MapLibreMap | null>(null);
  const [ready, setReady] = useState(false);
  const [failed, setFailed] = useState(false);
  const cb = useRef({ onSelect, onMove, onDraw, draw });
  cb.current = { onSelect, onMove, onDraw, draw };
  const drawPts = useRef<[number, number][]>([]);

  useEffect(() => {
    let disposed = false;
    (async () => {
      const maplibre = await import("maplibre-gl");
      maplibre.setWorkerUrl("/maplibre/maplibre-gl-worker.mjs");
      if (disposed || !box.current) return;
      try {
        const map = new maplibre.Map({
          container: box.current,
          center: view?.center ?? [10, 25],
          zoom: view?.zoom ?? 1.4,
          minZoom: 0.8,
          doubleClickZoom: false,
          attributionControl: { compact: true, customAttribution: "Boundaries: Natural Earth" },
          style: {
            version: 8,
            sources: { countries: { type: "geojson", data: "/geo/countries.geojson" } },
            layers: [
              { id: "bg", type: "background", paint: { "background-color": "#EEF3F9" } },
              { id: "land", type: "fill", source: "countries", paint: { "fill-color": "#DCE5F1" } },
              {
                id: "borders",
                type: "line",
                source: "countries",
                paint: { "line-color": "#FFFFFF", "line-width": 0.8 },
              },
            ],
          },
        });
        mapRef.current = map;
        const ro = new ResizeObserver(() => map.resize());
        ro.observe(box.current);
        map.on("remove", () => ro.disconnect());
        map.addControl(new maplibre.NavigationControl({ showCompass: false }), "top-right");
        map.addControl(new maplibre.ScaleControl({ unit: "metric" }), "bottom-left");
        map.on("load", () => {
          SHAPES.forEach((s, i) => map.addImage(`sev-${i + 1}`, icon(s, SEVERITY_COLORS[i + 1] as string)));
          for (const id of ["areas", "uncertainty", "assets", "density", "zones", "rings", "draw", "sel"])
            map.addSource(id, {
              type: "geojson",
              data: EMPTY,
              ...(id === "assets" ? { cluster: true, clusterRadius: 45, clusterMaxZoom: 9 } : {}),
            });
          map.addLayer({
            id: "zones-fill",
            type: "fill",
            source: "zones",
            paint: { "fill-color": "#8E5BD9", "fill-opacity": 0.12 },
          });
          map.addLayer({
            id: "zones-line",
            type: "line",
            source: "zones",
            paint: { "line-color": "#6B3FB5", "line-width": 1.5 },
          });
          map.addLayer({
            id: "areas-fill",
            type: "fill",
            source: "areas",
            paint: { "fill-color": "#D55E5E", "fill-opacity": 0.15 },
          });
          map.addLayer({
            id: "areas-line",
            type: "line",
            source: "areas",
            paint: { "line-color": "#B24545", "line-width": 1.2 },
          });
          map.addLayer({
            id: "unc-fill",
            type: "fill",
            source: "uncertainty",
            paint: { "fill-color": "#00A3A3", "fill-opacity": 0.12 },
          });
          map.addLayer({
            id: "unc-line",
            type: "line",
            source: "uncertainty",
            paint: { "line-color": "#007A7A", "line-width": 1.5, "line-dasharray": [3, 2] },
          });
          map.addLayer({
            id: "density",
            type: "heatmap",
            source: "density",
            paint: {
              "heatmap-radius": 30,
              "heatmap-weight": ["get", "level"],
              "heatmap-opacity": 0.65,
              "heatmap-color": [
                "interpolate",
                ["linear"],
                ["heatmap-density"],
                0,
                "rgba(122,166,216,0)",
                0.3,
                "#7AA6D8",
                0.6,
                "#E69F00",
                1,
                "#8E1B1B",
              ],
            },
          });
          map.addLayer({
            id: "rings",
            type: "line",
            source: "rings",
            paint: { "line-color": "#12305A", "line-width": 1.2, "line-dasharray": [2, 2] },
          });
          map.addLayer({
            id: "asset-clusters",
            type: "circle",
            source: "assets",
            filter: ["has", "point_count"],
            paint: {
              "circle-color": "#12305A",
              "circle-radius": ["step", ["get", "point_count"], 12, 25, 16, 200, 22],
              "circle-stroke-color": "#fff",
              "circle-stroke-width": 2,
            },
          });
          map.addLayer({
            id: "asset-points",
            type: "circle",
            source: "assets",
            filter: ["!", ["has", "point_count"]],
            paint: {
              "circle-radius": ["+", 3, ["get", "criticality"]],
              "circle-color": ["case", ["get", "exposed"], "#D55E5E", "#2F74D8"],
              "circle-stroke-color": ["case", ["get", "exposed"], "#8E1B1B", "#fff"],
              "circle-stroke-width": ["case", ["get", "exposed"], 2.5, 1.5],
            },
          });
          map.addLayer({
            id: "incident-points",
            type: "symbol",
            source: "incidents",
            layout: {
              "icon-image": ["concat", "sev-", ["to-string", ["get", "level"]]],
              "icon-size": ["match", ["get", "level"], 1, 0.7, 2, 0.85, 3, 1, 1.15],
              "icon-allow-overlap": true,
            },
          } as never);
          map.addLayer({
            id: "sel-ring",
            type: "circle",
            source: "sel",
            paint: {
              "circle-radius": 16,
              "circle-color": "rgba(0,0,0,0)",
              "circle-stroke-color": "#0B1B33",
              "circle-stroke-width": 3,
            },
          });
          map.addLayer({
            id: "draw-fill",
            type: "fill",
            source: "draw",
            paint: { "fill-color": "#2F74D8", "fill-opacity": 0.2 },
          });
          map.addLayer({
            id: "draw-line",
            type: "line",
            source: "draw",
            paint: { "line-color": "#1F5FBF", "line-width": 2 },
          });
          setReady(true);
        });
        map.on("click", "incident-points", (e) => {
          const id = e.features?.[0]?.properties?.id as string | undefined;
          if (id && !cb.current.draw) cb.current.onSelect?.("incident", id);
        });
        map.on("click", "asset-points", (e) => {
          const id = e.features?.[0]?.properties?.id as string | undefined;
          if (id && !cb.current.draw) cb.current.onSelect?.("asset", id);
        });
        map.on("click", "asset-clusters", async (e) => {
          const f = e.features?.[0];
          if (!f || cb.current.draw) return;
          const z = await (map.getSource("assets") as GeoJSONSource).getClusterExpansionZoom(
            Number(f.properties?.cluster_id),
          );
          map.easeTo({ center: (f.geometry as GeoJSON.Point).coordinates as [number, number], zoom: z });
        });
        for (const l of ["incident-points", "asset-points", "asset-clusters"]) {
          map.on("mouseenter", l, () => (map.getCanvas().style.cursor = "pointer"));
          map.on("mouseleave", l, () => (map.getCanvas().style.cursor = ""));
        }
        let timer = 0;
        map.on("moveend", () => {
          window.clearTimeout(timer);
          timer = window.setTimeout(() => {
            const b = map.getBounds();
            const c = map.getCenter();
            cb.current.onMove?.({ center: [c.lng, c.lat], zoom: map.getZoom() }, [
              b.getWest(),
              b.getSouth(),
              b.getEast(),
              b.getNorth(),
            ]);
          }, 300);
        });
        // Drawing: polygon (click vertices, double click or Enter to finish) and circle (center, then edge).
        const preview = (cursor?: [number, number]) => {
          const pts = drawPts.current;
          const src = map.getSource("draw") as GeoJSONSource | undefined;
          if (!src) return;
          const mode = cb.current.draw;
          if (!mode || !pts.length) return src.setData(EMPTY);
          if (mode === "circle") {
            const edge = cursor ?? pts[0]!;
            const km = haversineKm(pts[0]!, edge);
            return src.setData({
              type: "Feature",
              properties: {},
              geometry: { type: "Polygon", coordinates: [ring(pts[0]![0], pts[0]![1], Math.max(km, 0.01))] },
            });
          }
          const all = cursor ? [...pts, cursor] : pts;
          src.setData({
            type: "Feature",
            properties: {},
            geometry:
              all.length > 2
                ? { type: "Polygon", coordinates: [[...all, all[0]!]] }
                : { type: "LineString", coordinates: all },
          });
        };
        const finishPolygon = () => {
          const pts = drawPts.current;
          if (pts.length >= 3)
            cb.current.onDraw?.({ geometry: { type: "Polygon", coordinates: [[...pts, pts[0]!]] } });
          drawPts.current = [];
          preview();
        };
        map.on("click", (e) => {
          const mode = cb.current.draw;
          if (!mode) return;
          const p: [number, number] = [e.lngLat.lng, e.lngLat.lat];
          if (mode === "circle") {
            if (!drawPts.current.length) drawPts.current = [p];
            else {
              const km = haversineKm(drawPts.current[0]!, p);
              cb.current.onDraw?.({
                circle: { center: drawPts.current[0]!, radius_km: Math.max(1, Math.round(km)) },
              });
              drawPts.current = [];
            }
          } else drawPts.current = [...drawPts.current, p];
          preview();
        });
        map.on("dblclick", () => cb.current.draw === "polygon" && finishPolygon());
        map.on(
          "mousemove",
          (e) => cb.current.draw && drawPts.current.length && preview([e.lngLat.lng, e.lngLat.lat]),
        );
        const key = (e: KeyboardEvent) => {
          if (e.key === "Enter" && cb.current.draw === "polygon") finishPolygon();
          if (e.key === "Escape") {
            drawPts.current = [];
            preview();
          }
        };
        window.addEventListener("keydown", key);
        map.on("remove", () => window.removeEventListener("keydown", key));
        map.on("error", () => undefined);
      } catch {
        setFailed(true);
      }
    })();
    return () => {
      disposed = true;
      mapRef.current?.remove();
      mapRef.current = null;
      setReady(false);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const set = (id: string, data: GeoJSON.FeatureCollection) =>
    (mapRef.current?.getSource(id) as GeoJSONSource | undefined)?.setData(data);

  useEffect(() => {
    if (!ready) return;
    const pts = incidents.map((m) => ({
      type: "Feature" as const,
      properties: { id: m.id, level: m.level, label: m.label },
      geometry: { type: "Point" as const, coordinates: [m.lon, m.lat] },
    }));
    set("incidents", { type: "FeatureCollection", features: pts });
    set("density", { type: "FeatureCollection", features: pts });
    set("areas", {
      type: "FeatureCollection",
      features: incidents
        .filter((m) => m.area)
        .map((m) => ({ type: "Feature" as const, properties: {}, geometry: m.area as GeoJSON.Geometry })),
    });
    set("uncertainty", {
      type: "FeatureCollection",
      features: incidents
        .filter((m) => m.uncertaintyKm)
        .map((m) => ({
          type: "Feature" as const,
          properties: {},
          geometry: {
            type: "Polygon" as const,
            coordinates: [ring(m.lon, m.lat, m.uncertaintyKm as number)],
          },
        })),
    });
  }, [ready, incidents]);

  useEffect(() => {
    if (!ready) return;
    set("assets", {
      type: "FeatureCollection",
      features: assets.map((a) => ({
        type: "Feature" as const,
        properties: { id: a.id, exposed: a.exposed, criticality: a.criticality, label: a.label },
        geometry: { type: "Point" as const, coordinates: [a.lon, a.lat] },
      })),
    });
  }, [ready, assets]);

  useEffect(() => {
    if (ready) set("zones", zones ?? EMPTY);
  }, [ready, zones]);

  useEffect(() => {
    if (!ready) return;
    set("rings", {
      type: "FeatureCollection",
      features: rings
        ? rings.radiiKm.map((km) => ({
            type: "Feature" as const,
            properties: {},
            geometry: { type: "LineString" as const, coordinates: ring(rings.lon, rings.lat, km) },
          }))
        : [],
    });
  }, [ready, rings]);

  useEffect(() => {
    if (!ready) return;
    const hit =
      selected?.kind === "incident"
        ? incidents.find((i) => i.id === selected.id)
        : selected
          ? assets.find((a) => a.id === selected.id)
          : undefined;
    set("sel", {
      type: "FeatureCollection",
      features: hit
        ? [{ type: "Feature", properties: {}, geometry: { type: "Point", coordinates: [hit.lon, hit.lat] } }]
        : [],
    });
  }, [ready, selected, incidents, assets]);

  useEffect(() => {
    const map = mapRef.current;
    if (!ready || !map) return;
    const vis = (id: string, on: boolean) => map.setLayoutProperty(id, "visibility", on ? "visible" : "none");
    vis("incident-points", layers.incidents);
    for (const l of ["areas-fill", "areas-line", "unc-fill", "unc-line"]) vis(l, layers.incidents);
    for (const l of ["asset-clusters", "asset-points"]) vis(l, layers.assets);
    for (const l of ["zones-fill", "zones-line"]) vis(l, layers.zones);
    vis("density", layers.density);
  }, [ready, layers.incidents, layers.assets, layers.zones, layers.density]);

  useEffect(() => {
    if (ready && fit)
      mapRef.current?.fitBounds(
        [
          [fit[0], fit[1]],
          [fit[2], fit[3]],
        ],
        { padding: 50, maxZoom: 9, duration: 600 },
      );
  }, [ready, fit]);

  useEffect(() => {
    if (!ready) return;
    drawPts.current = [];
    (mapRef.current?.getSource("draw") as GeoJSONSource | undefined)?.setData(EMPTY);
    if (mapRef.current) mapRef.current.getCanvas().style.cursor = draw ? "crosshair" : "";
  }, [ready, draw]);

  if (failed)
    return <div className={className} role="img" aria-label={`${label} (map could not be loaded)`} />;
  return <div ref={box} className={className} role="region" aria-label={label} />;
}
