#!/usr/bin/env node
/**
 * End-to-end checks for the Sattva Table site.
 *   node scripts/test-site.js
 *
 * Covers: recipe data integrity, build freshness (generated HTML matches
 * recipes.json), search/filtering, saved recipes, the serving scaler,
 * structured data, and an accessibility pass. Exits non-zero on failure.
 */

const fs = require("fs");
const path = require("path");
const http = require("http");
const { execFileSync } = require("child_process");

const ROOT = path.join(__dirname, "..");
const SITE = path.join(ROOT, "site");
const PORT = 8911;

let failures = 0;
let checks = 0;

function check(name, ok, extra = "") {
  checks++;
  if (!ok) failures++;
  console.log(`${ok ? "  ok  " : "FAIL  "}${name}${extra ? ` — ${extra}` : ""}`);
}

function section(title) {
  console.log(`\n${title}`);
}

/* ---------- 1. data integrity (no browser needed) ---------- */

const recipes = JSON.parse(fs.readFileSync(path.join(SITE, "data", "recipes.json"), "utf8"));
const pantry = JSON.parse(fs.readFileSync(path.join(SITE, "data", "pantry.json"), "utf8"));
const ALLIUMS = ["onion", "garlic", "leek", "shallot", "chive", "scallion"];

function dataChecks() {
  section("Recipe data");

  check("recipes present", recipes.length > 0, `${recipes.length} recipes`);

  const slugs = recipes.map((r) => r.slug);
  check("slugs unique", new Set(slugs).size === slugs.length);
  check(
    "slugs are url-safe",
    slugs.every((s) => /^[a-z0-9-]+$/.test(s)),
    slugs.filter((s) => !/^[a-z0-9-]+$/.test(s)).join(", ")
  );

  // The entire premise of the site: no allium may appear in any ingredient.
  const violations = [];
  for (const r of recipes) {
    for (const ing of r.ingredients) {
      const name = ing.name.toLowerCase();
      for (const a of ALLIUMS) {
        if (name.includes(a)) violations.push(`${r.slug}: "${ing.name}"`);
      }
    }
  }
  check("no allium in any ingredient", violations.length === 0, violations.join("; "));

  const required = [
    "slug", "title", "category", "categoryLabel", "emoji", "gradient", "spice",
    "prepMin", "cookMin", "serves", "description", "intro", "swapNote", "ingredients", "steps",
  ];
  const missing = [];
  for (const r of recipes) {
    for (const f of required) {
      if (r[f] === undefined || r[f] === null || r[f] === "") missing.push(`${r.slug}.${f}`);
    }
    if (!Array.isArray(r.gradient) || r.gradient.length !== 2) missing.push(`${r.slug}.gradient`);
    if (!r.ingredients.length) missing.push(`${r.slug}.ingredients empty`);
    if (!r.steps.length) missing.push(`${r.slug}.steps empty`);
  }
  check("all required fields present", missing.length === 0, missing.slice(0, 5).join(", "));

  const badQty = recipes.flatMap((r) =>
    r.ingredients
      .filter((i) => i.qty !== null && (typeof i.qty !== "number" || i.qty <= 0))
      .map((i) => `${r.slug}: ${i.name}`)
  );
  check("ingredient quantities are positive numbers or null", badQty.length === 0, badQty.join("; "));

  check(
    "every recipe has a page",
    recipes.every((r) => fs.existsSync(path.join(SITE, "recipes", `${r.slug}.html`)))
  );

  section("Pantry data");
  const pantryRequired = ["name", "alsoKnownAs", "emoji", "replaces", "match", "description", "howToUse", "buying", "watchOut"];
  const pantryMissing = [];
  for (const item of pantry) {
    for (const f of pantryRequired) {
      if (!item[f]) pantryMissing.push(`${item.name}.${f}`);
    }
  }
  check("pantry entries complete", pantryMissing.length === 0, pantryMissing.join(", "));

  // A pantry entry whose keywords match nothing is a broken cross-link section.
  const orphans = pantry.filter(
    (item) =>
      !recipes.some((r) =>
        r.ingredients.some((ing) =>
          item.match.some((m) => ing.name.toLowerCase().includes(m.toLowerCase()))
        )
      )
  );
  check("every pantry item links to real recipes", orphans.length === 0, orphans.map((o) => o.name).join(", "));
}

/* ---------- 2. link integrity ---------- */

function walkHtml(dir, out = []) {
  for (const entry of fs.readdirSync(dir, { withFileTypes: true })) {
    const p = path.join(dir, entry.name);
    if (entry.isDirectory()) walkHtml(p, out);
    else if (entry.name.endsWith(".html")) out.push(p);
  }
  return out;
}

function linkChecks() {
  section("Links");

  const files = walkHtml(SITE);
  const brokenFiles = [];
  const brokenAnchors = [];
  let count = 0;

  for (const file of files) {
    const html = fs.readFileSync(file, "utf8");
    const dir = path.dirname(file);
    const ids = new Set([...html.matchAll(/id="([^"]+)"/g)].map((m) => m[1]));

    for (const m of html.matchAll(/(?:href|src)="([^"]+)"/g)) {
      const href = m[1];
      if (/^(https?:|mailto:|data:|tel:)/.test(href)) continue;

      if (href.startsWith("#")) {
        const id = href.slice(1);
        if (id && !ids.has(id)) brokenAnchors.push(`${path.relative(SITE, file)} -> ${href}`);
        continue;
      }

      const target = href.split("#")[0].split("?")[0];
      if (!target) continue;
      count++;
      if (!fs.existsSync(path.resolve(dir, target))) {
        brokenFiles.push(`${path.relative(SITE, file)} -> ${href}`);
      }
    }
  }

  check(`internal links resolve (${count} checked)`, brokenFiles.length === 0, brokenFiles.slice(0, 5).join(", "));
  check("in-page anchors resolve", brokenAnchors.length === 0, [...new Set(brokenAnchors)].slice(0, 5).join(", "));
}

/* ---------- 3. build freshness ---------- */

function buildFreshnessCheck() {
  section("Build freshness");

  const tracked = [
    "index.html",
    "recipes.html",
    "pantry.html",
    "sitemap.xml",
    ...recipes.map((r) => `recipes/${r.slug}.html`),
  ];
  const before = new Map(
    tracked.map((f) => [f, fs.readFileSync(path.join(SITE, f), "utf8")])
  );

  execFileSync("node", [path.join(ROOT, "scripts", "build-site.js")], { stdio: "pipe" });

  const stale = tracked.filter((f) => fs.readFileSync(path.join(SITE, f), "utf8") !== before.get(f));
  check(
    "generated files match recipes.json (run build-site.js and commit)",
    stale.length === 0,
    stale.slice(0, 5).join(", ")
  );
}

/* ---------- static server ---------- */

const MIME = {
  ".html": "text/html", ".css": "text/css", ".js": "text/javascript",
  ".json": "application/json", ".xml": "application/xml", ".txt": "text/plain",
};

function serve() {
  return new Promise((resolve) => {
    const server = http.createServer((req, res) => {
      const rel = decodeURIComponent(req.url.split("?")[0]).replace(/^\/+/, "") || "index.html";
      const file = path.join(SITE, rel);
      if (!file.startsWith(SITE) || !fs.existsSync(file) || fs.statSync(file).isDirectory()) {
        res.writeHead(404);
        return res.end("not found");
      }
      res.writeHead(200, { "Content-Type": MIME[path.extname(file)] || "application/octet-stream" });
      res.end(fs.readFileSync(file));
    });
    server.listen(PORT, () => resolve(server));
  });
}

/* ---------- 3. browser checks ---------- */

async function browserChecks() {
  let chromium;
  try {
    ({ chromium } = require("playwright"));
  } catch (e) {
    console.log("\nPlaywright not installed — skipping browser checks.");
    return;
  }

  const server = await serve();
  const base = `http://localhost:${PORT}`;
  // Use a preinstalled Chromium when one exists (this sandbox), otherwise let
  // Playwright resolve its own download (CI).
  const localChromium = process.env.CHROMIUM_PATH || "/opt/pw-browsers/chromium";
  const launchOpts = fs.existsSync(localChromium) ? { executablePath: localChromium } : {};
  const browser = await chromium.launch(launchOpts);
  const ctx = await browser.newContext({ viewport: { width: 1400, height: 950 } });
  const jsErrors = [];
  ctx.on("page", (p) => {
    p.on("pageerror", (e) => jsErrors.push(e.message));
    p.on("console", (m) => {
      if (m.type() === "error" && !m.text().includes("CERT")) jsErrors.push(m.text());
    });
  });

  try {
    /* --- listing: search + filters --- */
    section("Recipe listing");
    const page = await ctx.newPage();
    await page.goto(`${base}/recipes.html`, { waitUntil: "domcontentloaded" });

    const visible = () => page.$$eval(".recipe-card", (c) => c.filter((x) => !x.hidden).length);

    check("all recipes render", (await visible()) === recipes.length, `${await visible()}`);

    await page.click('[data-filter="curry"]');
    await page.waitForTimeout(150);
    const curryExpected = recipes.filter((r) => r.category === "curry").length;
    check("category filter", (await visible()) === curryExpected, `${await visible()}/${curryExpected}`);

    await page.click('[data-filter="all"]');
    await page.fill("#recipe-search", "tamarind");
    await page.waitForTimeout(250);
    check("search matches ingredients", (await visible()) > 0, `${await visible()}`);

    await page.fill("#recipe-search", "qqqzzz");
    await page.waitForTimeout(250);
    check("empty state on no match", await page.$eval(".empty-state", (e) => !e.hidden));

    await page.click(".empty-state .reset-filters");
    await page.waitForTimeout(250);
    check("reset restores everything", (await visible()) === recipes.length);

    await page.click(".advanced-filters summary");
    await page.check('[data-diet="vegan"]');
    await page.waitForTimeout(200);
    const veganExpected = recipes.filter((r) => r.vegan).length;
    check("vegan filter", (await visible()) === veganExpected, `${await visible()}/${veganExpected}`);

    /* --- category deep links (footer uses recipes.html#curry etc.) --- */
    for (const cat of ["breakfast", "curry", "dessert"]) {
      const expected = recipes.filter((r) => r.category === cat).length;
      const dl = await ctx.newPage();
      await dl.goto(`${base}/recipes.html#${cat}`, { waitUntil: "domcontentloaded" });
      await dl.waitForTimeout(250);
      const shown = await dl.$$eval(".recipe-card", (c) => c.filter((x) => !x.hidden).length);
      check(`#${cat} deep link filters on load`, shown === expected, `${shown}/${expected}`);
      await dl.close();
    }

    /* --- saving --- */
    section("Saved recipes");
    await page.click(".advanced-filters .reset-filters");
    await page.waitForTimeout(150);
    await page.click(".recipe-card:not([hidden]) .save-btn");
    await page.waitForTimeout(150);
    check(
      "save persists to localStorage",
      (await page.evaluate(() => JSON.parse(localStorage.getItem("st-saved") || "[]").length)) === 1
    );

    const savedPage = await ctx.newPage();
    await savedPage.goto(`${base}/saved.html`, { waitUntil: "networkidle" });
    await savedPage.waitForTimeout(400);
    const savedCount = await savedPage.$$eval("#saved-grid .recipe-card", (c) => c.length);
    check("saved page lists them", savedCount === 1, `${savedCount}`);

    await savedPage.click("#saved-grid .save-btn");
    await savedPage.waitForTimeout(300);
    check(
      "unsaving updates the page",
      (await savedPage.$$eval("#saved-grid .recipe-card", (c) => c.length)) === 0
    );

    /* --- detail page --- */
    section("Recipe detail");
    const sample = recipes[0];
    const detail = await ctx.newPage();
    await detail.goto(`${base}/recipes/${sample.slug}.html`, { waitUntil: "domcontentloaded" });

    check(
      "ingredients match data",
      (await detail.$$eval(".ingredient-list li", (l) => l.length)) === sample.ingredients.length
    );
    check(
      "steps match data",
      (await detail.$$eval(".step-list li", (l) => l.length)) === sample.steps.length
    );

    const ld = await detail.$$eval('script[type="application/ld+json"]', (s) =>
      s.map((x) => JSON.parse(x.textContent))
    );
    const recipeLd = ld.find((x) => x["@type"] === "Recipe");
    check("Recipe JSON-LD present", !!recipeLd);
    check(
      "JSON-LD ingredient count matches",
      recipeLd && recipeLd.recipeIngredient.length === sample.ingredients.length
    );
    check("BreadcrumbList JSON-LD present", ld.some((x) => x["@type"] === "BreadcrumbList"));

    const original = await detail.textContent(".ing-text[data-qty]");
    await detail.click('[data-scale="up"]');
    await detail.waitForTimeout(150);
    check("scaler changes quantities", (await detail.textContent(".ing-text[data-qty]")) !== original);
    await detail.click('[data-scale="down"]');
    await detail.waitForTimeout(150);
    check("scaler restores quantities", (await detail.textContent(".ing-text[data-qty]")) === original);

    /* --- theme --- */
    section("Theme");
    await detail.click(".theme-toggle");
    await detail.waitForTimeout(150);
    check("dark mode engages", await detail.evaluate(() => document.documentElement.dataset.theme === "dark"));
    await detail.goto(`${base}/index.html`, { waitUntil: "domcontentloaded" });
    check("theme persists across pages", await detail.evaluate(() => document.documentElement.dataset.theme === "dark"));

    /* --- accessibility --- */
    section("Accessibility");
    const pages = ["index.html", "recipes.html", "about.html", "pantry.html", "contact.html", "saved.html", "404.html", `recipes/${sample.slug}.html`];
    const a11y = [];
    for (const p of pages) {
      const ap = await ctx.newPage();
      await ap.goto(`${base}/${p}`, { waitUntil: "domcontentloaded" });
      const found = await ap.evaluate(() => {
        const out = [];
        document.querySelectorAll("img:not([alt])").forEach(() => out.push("img missing alt"));
        document.querySelectorAll("button, a").forEach((el) => {
          if (!(el.getAttribute("aria-label") || el.textContent || "").trim())
            out.push(`unnamed ${el.tagName.toLowerCase()}`);
        });
        document.querySelectorAll("input:not([type=checkbox]):not([type=hidden]), select, textarea").forEach((el) => {
          const labelled = (el.id && document.querySelector(`label[for="${el.id}"]`)) || el.closest("label") || el.getAttribute("aria-label");
          if (!labelled) out.push(`unlabeled ${el.type || el.tagName.toLowerCase()}`);
        });
        const levels = [...document.querySelectorAll("h1,h2,h3,h4,h5,h6")].map((h) => +h.tagName[1]);
        if (levels.filter((l) => l === 1).length !== 1) out.push("needs exactly one h1");
        for (let i = 1; i < levels.length; i++) {
          if (levels[i] - levels[i - 1] > 1) out.push(`heading jump h${levels[i - 1]}->h${levels[i]}`);
        }
        if (!document.querySelector("main")) out.push("no main landmark");
        if (!document.documentElement.lang) out.push("no lang");
        const ids = {};
        document.querySelectorAll("[id]").forEach((el) => (ids[el.id] = (ids[el.id] || 0) + 1));
        Object.entries(ids).forEach(([id, n]) => n > 1 && out.push(`duplicate id ${id}`));
        return out;
      });
      if (found.length) a11y.push(`${p}: ${found.join(", ")}`);
      await ap.close();
    }
    check("no accessibility issues", a11y.length === 0, a11y.join(" | "));

    check("no JavaScript errors", jsErrors.length === 0, jsErrors.slice(0, 3).join(" | "));
  } finally {
    await browser.close();
    server.close();
  }
}

/* ---------- run ---------- */

(async () => {
  dataChecks();
  linkChecks();
  buildFreshnessCheck();
  await browserChecks();

  console.log(`\n${checks - failures}/${checks} checks passed`);
  if (failures) {
    console.error(`${failures} FAILED`);
    process.exit(1);
  }
})();
