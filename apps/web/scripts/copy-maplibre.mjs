// Self-host the map worker so the strict Content Security Policy (script and worker sources limited to this origin) holds.
import fs from "node:fs";
import path from "node:path";

const from = path.resolve("node_modules/maplibre-gl/dist");
const to = path.resolve("public/maplibre");
fs.mkdirSync(to, { recursive: true });
for (const f of ["maplibre-gl-worker.mjs", "maplibre-gl-shared.mjs"])
  fs.copyFileSync(path.join(from, f), path.join(to, f));
