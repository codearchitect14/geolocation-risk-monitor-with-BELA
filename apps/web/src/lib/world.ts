import raw from "@/content/world.json";

export const world = raw as {
  width: number;
  height: number;
  d: string;
  incidents: { x: number; y: number; lon: number; lat: number; level: number; type: string }[];
};
