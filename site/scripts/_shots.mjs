import { chromium } from "playwright";
const out = "/tmp/claude-0/-home-user-comebacktowns/b1d14665-f86e-59ac-b041-42148b5b7544/scratchpad/shots";
const browser = await chromium.launch({ executablePath: process.env.CHROMIUM_PATH });
const shots = [
  ["home", "/", 1280, 1400, false],
  ["town", "/town/saugerties-ny", 1280, 2600, false],
  ["ranking", "/rankings/strongest-momentum", 1280, 900, false],
  ["phone-town", "/town/saugerties-ny", 390, 1400, true],
  ["methodology", "/methodology", 1280, 1200, false],
];
for (const [name, path, width, height, mobile] of shots) {
  const page = await browser.newPage({ viewport: { width, height }, deviceScaleFactor: 1, isMobile: mobile });
  await page.goto(`http://127.0.0.1:4321${path}`, { waitUntil: "networkidle" });
  await page.evaluate(() => document.fonts.ready);
  await page.screenshot({ path: `${out}/${name}.png`, fullPage: false });
  await page.close();
  console.log("shot", name);
}
await browser.close();
