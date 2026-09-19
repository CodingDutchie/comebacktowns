// Renders the social card (1200x630) and the Apple touch icon (180x180) from the Return
// mark with the pre-installed Chromium. Run from site/: `node scripts/render-images.mjs`.
// Both files are committed, so this only needs to run again when the mark or copy changes.
import { chromium } from "playwright";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { parse } from "yaml";

const site = parse(readFileSync(fileURLToPath(new URL("../../config/site.yml", import.meta.url)), "utf8"));
const mark = (size, ink, accent, width = 8) => `<svg width="${size}" height="${size}" viewBox="0 0 64 64" xmlns="http://www.w3.org/2000/svg"><path d="M10 46 L26 26 L36 36" fill="none" stroke="${ink}" stroke-width="${width}" stroke-linecap="round" stroke-linejoin="round"/><path d="M36 36 L54 18 M42 18 H54 V30" fill="none" stroke="${accent}" stroke-width="${width}" stroke-linecap="round" stroke-linejoin="round"/></svg>`;
const font = `<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=IBM+Plex+Mono:wght@500&family=IBM+Plex+Sans:wght@500;700&display=block">`;

const card = `<!doctype html><html><head><meta charset="utf-8">${font}<style>
body{margin:0;width:1200px;height:630px;background:#15191e;color:#f5f6f7;font-family:"IBM Plex Sans",sans-serif;display:flex;flex-direction:column;justify-content:space-between;padding:72px 80px;box-sizing:border-box}
h1{margin:0;font-size:78px;line-height:1.02;font-weight:700;letter-spacing:-.03em;max-width:980px}
.top{display:flex;align-items:center;gap:22px;font-size:34px;font-weight:700}
.bottom{display:flex;justify-content:space-between;align-items:flex-end;gap:40px}
.sub{font-size:26px;color:#c5cdd8;max-width:760px;line-height:1.35}
.mono{font-family:"IBM Plex Mono",monospace;font-size:20px;color:#9aa4b2}
.chips{display:flex;gap:12px}.chip{font-family:"IBM Plex Mono",monospace;font-size:22px;font-weight:500;padding:10px 16px;border-radius:8px}
</style></head><body>
<div class="top">${mark(56, "#f5f6f7", "#f2c14e")}<span>${site.SITE_NAME}</span><span class="mono">${site.SITE_DOMAIN}</span></div>
<h1>Which New York towns are ready for a comeback?</h1>
<div class="bottom"><div class="sub">Readiness grades and momentum labels for 148 cities and villages, every figure with its source and date.</div>
<div class="chips"><span class="chip" style="background:#1c7c54;color:#fff">▲ RISING</span><span class="chip" style="background:#f2c14e;color:#15191e">▶ STEADY</span><span class="chip" style="background:#b8322e;color:#fff">▼ FADING</span></div></div>
</body></html>`;

const icon = `<!doctype html><html><head><meta charset="utf-8"><style>body{margin:0;width:180px;height:180px;background:#15191e;display:flex;align-items:center;justify-content:center}</style></head><body>${mark(150, "#f5f6f7", "#f2c14e", 9)}</body></html>`;

const browser = await chromium.launch({ executablePath: process.env.CHROMIUM_PATH || undefined });
const shots = [
  ["public/social-card.png", card, 1200, 630],
  ["public/apple-touch-icon.png", icon, 180, 180],
];
for (const [path, html, width, height] of shots) {
  const page = await browser.newPage({ viewport: { width, height }, deviceScaleFactor: 1 });
  await page.setContent(html, { waitUntil: "networkidle" });
  await page.evaluate(() => document.fonts.ready);
  await page.screenshot({ path, type: "png" });
  await page.close();
  console.log("wrote", path);
}
await browser.close();
