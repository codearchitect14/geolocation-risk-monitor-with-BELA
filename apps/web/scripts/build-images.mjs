// Image pipeline: renders in-house scenes and converts every source image to AVIF and WebP at responsive widths.
// Sources: scripts/scenes.mjs (vector) and src-images/*.{jpg,jpeg,png} (raster, if any). Output: public/images/<name>-<width>.<fmt>
import fs from "node:fs";
import path from "node:path";
import sharp from "sharp";
import { scenes } from "./scenes.mjs";

const OUT = path.resolve("public/images");
const WIDTHS = [640, 960, 1440, 2400];
const manifest = {};
fs.mkdirSync(OUT, { recursive: true });

async function convert(name, input) {
  const meta = await sharp(input).metadata();
  const widths = WIDTHS.filter((w) => w <= (meta.width ?? 2400));
  for (const w of widths) {
    const base = sharp(input).resize({ width: w });
    await base
      .clone()
      .avif({ quality: 55, effort: 4 })
      .toFile(path.join(OUT, `${name}-${w}.avif`));
    await base
      .clone()
      .webp({ quality: 74 })
      .toFile(path.join(OUT, `${name}-${w}.webp`));
  }
  manifest[name] = { widths, ratio: (meta.height ?? 1350) / (meta.width ?? 2400) };
}

for (const [name, make] of Object.entries(scenes)) await convert(name, Buffer.from(make()));

const rasterDir = path.resolve("src-images");
if (fs.existsSync(rasterDir)) {
  for (const f of fs.readdirSync(rasterDir).filter((x) => /\.(jpe?g|png)$/i.test(x))) {
    await convert(f.replace(/\.[^.]+$/, ""), path.join(rasterDir, f));
  }
}
fs.writeFileSync(path.resolve("src/lib/image-manifest.json"), JSON.stringify(manifest, null, 1) + "\n");
console.log(`images: ${Object.keys(manifest).length} sources`);
