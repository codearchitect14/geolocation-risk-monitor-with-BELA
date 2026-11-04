"use client";

import "maplibre-gl/dist/maplibre-gl.css";
import type { GeoJSONSource, Map as MapLibreMap, MapGeoJSONFeature } from "maplibre-gl";
import { useEffect, useRef, useState } from "react";
import { SEVERITY_COLORS } from "@/components/art/severity-marker";

export type MapMarker = {
  id: string;
  lon: number;
  lat: number;
  level: 1 | 2 | 3 | 4;
  label: string;
  uncertaintyKm?: number;
};

type Props = {
  markers: MapMarker[];
  /** Camera. Defaults to the whole world. */
  center?: [number, number];
  zoom?: number;
  label: string;
  className?: string;
  showUncertainty?: boolean;
  onSelect?: (marker: MapMarker) => void;
};

const SHAPES = ["circle", "square", "triangle", "diamond"] as const;

function shapeImage(shape: (typeof SHAPES)[number], color: string, size = 28): ImageData {
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

/** Geodesic circle as a polygon ring, enough for an uncertainty radius on a flat basemap. */
function circle(lon: number, lat: number, km: number, steps = 48): [number, number][] {
  const ring: [number, number][] = [];
  const dLat = km / 111.32;
  const dLon = km / (111.32 * Math.max(0.05, Math.cos((lat * Math.PI) / 180)));
  for (let i = 0; i <= steps; i++) {
    const a = (i / steps) * Math.PI * 2;
    ring.push([lon + dLon * Math.cos(a), lat + dLat * Math.sin(a)]);
  }
  return ring;
}

/**
 * Shared map. The basemap is self-hosted country outlines, so no tile server or third-party origin is contacted.
 * Markers cluster, differ by shape as well as color, and every marker is also listed in a table below the map.
 */
export default function MapView({
  markers,
  center = [10, 25],
  zoom = 1.2,
  label,
  className,
  showUncertainty = true,
  onSelect,
}: Props) {
  const container = useRef<HTMLDivElement>(null);
  const mapRef = useRef<MapLibreMap | null>(null);
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    let disposed = false;
    (async () => {
      const maplibre = await import("maplibre-gl");
      maplibre.setWorkerUrl("/maplibre/maplibre-gl-worker.mjs");
      if (disposed || !container.current) return;
      try {
        const map = new maplibre.Map({
          container: container.current,
          center,
          zoom,
          minZoom: 0.8,
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
        map.addControl(new maplibre.NavigationControl({ showCompass: false }), "top-right");
        map.on("load", () => {
          SHAPES.forEach((shape, i) =>
            map.addImage(`sev-${i + 1}`, shapeImage(shape, SEVERITY_COLORS[i + 1] as string)),
          );
          map.addSource("incidents", {
            type: "geojson",
            cluster: true,
            clusterRadius: 40,
            clusterMaxZoom: 6,
            data: {
              type: "FeatureCollection",
              features: markers.map((m) => ({
                type: "Feature",
                id: m.id,
                properties: { id: m.id, level: m.level, label: m.label },
                geometry: { type: "Point", coordinates: [m.lon, m.lat] },
              })),
            },
          });
          map.addLayer({
            id: "clusters",
            type: "circle",
            source: "incidents",
            filter: ["has", "point_count"],
            paint: {
              "circle-color": "#12305A",
              "circle-radius": ["step", ["get", "point_count"], 14, 10, 18, 50, 24],
              "circle-stroke-color": "#FFFFFF",
              "circle-stroke-width": 2,
            },
          });
          map.addLayer({
            id: "points",
            type: "symbol",
            source: "incidents",
            filter: ["!", ["has", "point_count"]],
            layout: {
              "icon-image": ["concat", "sev-", ["to-string", ["get", "level"]]],
              "icon-size": ["match", ["get", "level"], 1, 0.7, 2, 0.85, 3, 1, 1.15],
              "icon-allow-overlap": true,
            },
          });
          if (showUncertainty) {
            map.addSource("uncertainty", {
              type: "geojson",
              data: {
                type: "FeatureCollection",
                features: markers
                  .filter((m) => m.uncertaintyKm)
                  .map((m) => ({
                    type: "Feature",
                    properties: {},
                    geometry: {
                      type: "Polygon",
                      coordinates: [circle(m.lon, m.lat, m.uncertaintyKm as number)],
                    },
                  })),
              },
            });
            map.addLayer(
              {
                id: "uncertainty-fill",
                type: "fill",
                source: "uncertainty",
                paint: { "fill-color": "#00A3A3", "fill-opacity": 0.12 },
              },
              "clusters",
            );
            map.addLayer(
              {
                id: "uncertainty-line",
                type: "line",
                source: "uncertainty",
                paint: { "line-color": "#007A7A", "line-width": 1.5, "line-dasharray": [3, 2] },
              },
              "clusters",
            );
          }
          map.on("click", "clusters", async (e) => {
            const feature = e.features?.[0] as MapGeoJSONFeature | undefined;
            if (!feature) return;
            const zoomTo = await (map.getSource("incidents") as GeoJSONSource).getClusterExpansionZoom(
              Number(feature.properties?.cluster_id),
            );
            const [lon, lat] = (feature.geometry as unknown as { coordinates: [number, number] }).coordinates;
            map.easeTo({ center: [lon, lat], zoom: zoomTo });
          });
          map.on("click", "points", (e) => {
            const id = e.features?.[0]?.properties?.id as string | undefined;
            const found = markers.find((m) => m.id === id);
            if (found) onSelect?.(found);
          });
          for (const layer of ["clusters", "points"]) {
            map.on("mouseenter", layer, () => (map.getCanvas().style.cursor = "pointer"));
            map.on("mouseleave", layer, () => (map.getCanvas().style.cursor = ""));
          }
        });
        map.on("error", () => undefined);
      } catch {
        setFailed(true);
      }
    })();
    return () => {
      disposed = true;
      mapRef.current?.remove();
      mapRef.current = null;
    };
    // The map is created once; marker data is fixed for the lifetime of the component on the marketing site.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  if (failed)
    return <div className={className} role="img" aria-label={`${label} (map could not be loaded)`} />;
  return <div ref={container} className={className} role="region" aria-label={label} />;
}
