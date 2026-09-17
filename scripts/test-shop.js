#!/usr/bin/env node
/**
 * End-to-end checks for the shop.
 *   node scripts/test-shop.js
 *
 * Covers catalogue integrity, build freshness, server-side re-pricing
 * (the security-critical part), the cart flow, computed visibility,
 * links and accessibility. Exits non-zero on failure.
 */

const fs = require("fs");
const path = require("path");
const http = require("http");
const { execFileSync } = require("child_process");

const ROOT = path.join(__dirname, "..");
const SHOP = path.join(ROOT, "shop");
const PORT = 8921;
const BASE = `http://localhost:${PORT}`;

let failures = 0;
let checks = 0;
const check = (name, ok, extra = "") => {
  checks++;
  if (!ok) failures++;
  console.log(`${ok ? "  ok  " : "FAIL  "}${name}${extra ? ` — ${extra}` : ""}`);
};
const section = (t) => console.log(`\n${t}`);

const products = JSON.parse(fs.readFileSync(path.join(SHOP, "data", "products.json"), "utf8"));
const site = JSON.parse(fs.readFileSync(path.join(SHOP, "data", "site.json"), "utf8"));

/* ---------- 1. catalogue ---------- */

function dataChecks() {
  section("Catalogue");
  check("products present", products.length > 0, `${products.length}`);

  const slugs = products.map((p) => p.slug);
  check("slugs unique", new Set(slugs).size === slugs.length);
  check("slugs url-safe", slugs.every((s) => /^[a-z0-9-]+$/.test(s)));

  // Money must be integer cents everywhere — floats here become rounding bugs
  // at checkout, and a negative or zero price is a giveaway.
  const badPrice = products.filter(
    (p) => !Number.isInteger(p.priceCents) || p.priceCents <= 0
  );
  check("prices are positive integer cents", badPrice.length === 0, badPrice.map((p) => p.slug).join(", "));

  const required = ["name", "group", "category", "categoryLabel", "packSize", "packLabel", "emoji", "gradient", "blurb", "description", "storage", "leadDays"];
  const missing = [];
  for (const p of products) {
    for (const f of required) {
      if (p[f] === undefined || p[f] === null || p[f] === "") missing.push(`${p.slug}.${f}`);
    }
    if (!Array.isArray(p.gradient) || p.gradient.length !== 2) missing.push(`${p.slug}.gradient`);
    if (!Number.isInteger(p.leadDays) || p.leadDays < 1) missing.push(`${p.slug}.leadDays`);
  }
  check("required fields present", missing.length === 0, missing.slice(0, 5).join(", "));

  const groupIds = site.groups.map((g) => g.id);
  const strayGroup = products.filter((p) => !groupIds.includes(p.group));
  check("every product sits in a known group", strayGroup.length === 0, strayGroup.map((p) => p.slug).join(", "));

  // A product with options must offer real choices, or the picker renders empty.
  const badOptions = products.filter(
    (p) => p.options && p.options.some((o) => !o.id || !o.label || !Array.isArray(o.choices) || !o.choices.length)
  );
  check("option groups are complete", badOptions.length === 0, badOptions.map((p) => p.slug).join(", "));

  check(
    "every product has a page",
    products.every((p) => fs.existsSync(path.join(SHOP, "product", `${p.slug}.html`)))
  );
}

/* ---------- 2. links ---------- */

function walkHtml(dir, out = []) {
  for (const e of fs.readdirSync(dir, { withFileTypes: true })) {
    const p = path.join(dir, e.name);
    if (e.isDirectory()) walkHtml(p, out);
    else if (e.name.endsWith(".html")) out.push(p);
  }
  return out;
}

function linkChecks() {
  section("Links");
  const files = walkHtml(SHOP);
  const broken = [];
  let count = 0;
  for (const file of files) {
    const html = fs.readFileSync(file, "utf8");
    const dir = path.dirname(file);
    for (const m of html.matchAll(/(?:href|src)="([^"]+)"/g)) {
      const href = m[1];
      if (/^(https?:|mailto:|tel:|data:|#)/.test(href)) continue;
      const target = href.split("#")[0].split("?")[0];
      if (!target) continue;
      count++;
      if (!fs.existsSync(path.resolve(dir, target))) {
        broken.push(`${path.relative(SHOP, file)} -> ${href}`);
      }
    }
  }
  check(`internal links resolve (${count} checked)`, broken.length === 0, broken.slice(0, 5).join(", "));
}

/* ---------- 3. build freshness ---------- */

function freshnessCheck() {
  section("Build freshness");
  const tracked = ["index.html", "shop.html", "menu.html", "sitemap.xml", ...products.map((p) => `product/${p.slug}.html`)];
  const before = new Map(tracked.map((f) => [f, fs.readFileSync(path.join(SHOP, f), "utf8")]));
  execFileSync("node", [path.join(ROOT, "scripts", "build-shop.js")], { stdio: "pipe" });
  const stale = tracked.filter((f) => fs.readFileSync(path.join(SHOP, f), "utf8") !== before.get(f));
  check("generated files match products.json (run build-shop.js and commit)", stale.length === 0, stale.slice(0, 4).join(", "));
}

/* ---------- server ---------- */

const MIME = {
  ".html": "text/html; charset=utf-8", ".css": "text/css", ".js": "text/javascript",
  ".json": "application/json", ".xml": "application/xml", ".txt": "text/plain",
};

function serve() {
  const checkout = require(path.join(ROOT, "api", "create-checkout-session.js"));
  return new Promise((resolve) => {
    const server = http.createServer((req, res) => {
      const url = new URL(req.url, BASE);
      if (url.pathname === "/api/create-checkout-session") return checkout(req, res);
      let rel = decodeURIComponent(url.pathname).replace(/^\/+/, "");
      if (rel.startsWith("shop/")) rel = rel.slice(5);
      if (!rel) rel = "index.html";
      const file = path.join(SHOP, rel);
      if (!file.startsWith(SHOP) || !fs.existsSync(file) || fs.statSync(file).isDirectory()) {
        res.writeHead(404);
        return res.end("not found");
      }
      res.writeHead(200, { "Content-Type": MIME[path.extname(file)] || "application/octet-stream" });
      res.end(fs.readFileSync(file));
    });
    server.listen(PORT, () => resolve(server));
  });
}

function post(body) {
  return new Promise((resolve, reject) => {
    const data = JSON.stringify(body);
    const req = http.request(
      { hostname: "localhost", port: PORT, path: "/api/create-checkout-session", method: "POST",
        headers: { "Content-Type": "application/json", "Content-Length": Buffer.byteLength(data) } },
      (res) => {
        let raw = "";
        res.on("data", (c) => (raw += c));
        res.on("end", () => {
          try { resolve({ status: res.statusCode, body: JSON.parse(raw) }); }
          catch (e) { resolve({ status: res.statusCode, body: {} }); }
        });
      }
    );
    req.on("error", reject);
    req.end(data);
  });
}

/* ---------- 4. checkout security ---------- */

async function checkoutSecurity() {
  section("Checkout security");

  // The whole point: a client that posts its own price must not set it.
  const pricey = products.reduce((a, b) => (a.priceCents > b.priceCents ? a : b));
  const spoof = await post({ items: [{ slug: pricey.slug, qty: 1, priceCents: 1, price: 0.01 }] });
  check(
    "client-supplied price is ignored",
    spoof.body.subtotalCents === pricey.priceCents,
    `got ${spoof.body.subtotalCents}, expected ${pricey.priceCents}`
  );

  check("unknown product rejected", (await post({ items: [{ slug: "nope", qty: 1 }] })).status === 400);
  check("negative quantity rejected", (await post({ items: [{ slug: pricey.slug, qty: -3 }] })).status === 400);
  check("fractional quantity rejected", (await post({ items: [{ slug: pricey.slug, qty: 1.5 }] })).status === 400);
  check("oversized quantity rejected", (await post({ items: [{ slug: pricey.slug, qty: 100000 }] })).status === 400);
  check("empty cart rejected", (await post({ items: [] })).status === 400);

  const many = Array.from({ length: 60 }, () => ({ slug: pricey.slug, qty: 1 }));
  check("too many line items rejected", (await post({ items: many })).status === 400);

  // Delivery fee is computed here too, not trusted from the browser.
  const cheap = products.reduce((a, b) => (a.priceCents < b.priceCents ? a : b));
  const del = await post({ items: [{ slug: cheap.slug, qty: 1 }], fulfilment: "delivery" });
  check("delivery request accepted", del.status === 200);

  // An option value the product doesn't offer must not be echoed back.
  const withOpts = products.find((p) => p.options);
  if (withOpts) {
    const label = withOpts.options[0].label;
    const evil = await post({
      items: [{ slug: withOpts.slug, qty: 1, options: { [label]: "<script>alert(1)</script>" } }],
    });
    check("invalid option value dropped", evil.status === 200 && evil.body.subtotalCents === withOpts.priceCents);
  }
}

/* ---------- 5. browser ---------- */

async function browserChecks() {
  let chromium;
  try { ({ chromium } = require("playwright")); }
  catch (e) { console.log("\nPlaywright not installed — skipping browser checks."); return; }

  const local = process.env.CHROMIUM_PATH || "/opt/pw-browsers/chromium";
  const browser = await chromium.launch(fs.existsSync(local) ? { executablePath: local } : {});
  const ctx = await browser.newContext({ viewport: { width: 1400, height: 1000 } });
  const jsErrors = [];
  ctx.on("page", (p) => {
    p.on("pageerror", (e) => jsErrors.push(e.message));
    p.on("console", (m) => { if (m.type() === "error" && !m.text().includes("CERT")) jsErrors.push(m.text()); });
  });

  try {
    section("Shop page");
    const page = await ctx.newPage();
    await page.goto(`${BASE}/shop.html`, { waitUntil: "domcontentloaded" });
    const visible = () => page.$$eval(".product-card", (c) => c.filter((x) => !x.hidden).length);
    check("all products render", (await visible()) === products.length, `${await visible()}`);

    const cat = products[0].category;
    const expected = products.filter((p) => p.category === cat).length;
    await page.click(`[data-chip="${cat}"]`);
    await page.waitForTimeout(200);
    check("category chip filters", (await visible()) === expected, `${await visible()}/${expected}`);

    section("Cart");
    await page.click('[data-chip="all"]');
    await page.waitForTimeout(150);
    await page.click(".product-card:not([hidden]) [data-add]");
    await page.waitForTimeout(250);
    check("badge reflects cart", await page.$eval("[data-cart-count]", (e) => !e.hidden));

    await page.click(".product-card:not([hidden]) [data-add]");
    await page.waitForTimeout(200);
    const lines = await page.evaluate(() => JSON.parse(localStorage.getItem("fh-cart")));
    check("repeat add merges into one line", lines.length === 1 && lines[0].qty === 2);

    const cart = await ctx.newPage();
    await cart.goto(`${BASE}/cart.html`, { waitUntil: "networkidle" });
    await cart.waitForTimeout(500);
    const firstProduct = products.find((p) => p.slug === lines[0].slug);
    const expectSub = "$" + ((firstProduct.priceCents * 2) / 100).toFixed(2);
    check("subtotal computed", (await cart.textContent("#subtotal")) === expectSub, await cart.textContent("#subtotal"));

    section("Fulfilment visibility");
    // el.hidden is not enough — class rules that set `display` can override it,
    // so assert what actually renders.
    const disp = (sel) => cart.evaluate((s) => getComputedStyle(document.querySelector(s)).display, sel);
    check("delivery row hidden on pickup", (await disp("#delivery-row")) === "none");
    check("address hidden on pickup", (await disp("#address-field")) === "none");

    await cart.click('.fulfilment label:has(input[value="delivery"])');
    await cart.waitForTimeout(300);
    check("delivery radio checks", await cart.$eval('input[value="delivery"]', (e) => e.checked));
    check("delivery row shows", (await disp("#delivery-row")) !== "none");
    check("address shows", (await disp("#address-field")) !== "none");

    await cart.click('.fulfilment label:has(input[value="pickup"])');
    await cart.waitForTimeout(300);
    check("delivery row hides again", (await disp("#delivery-row")) === "none");

    section("Empty cart");
    await cart.evaluate(() => localStorage.removeItem("fh-cart"));
    await cart.reload({ waitUntil: "networkidle" });
    await cart.waitForTimeout(500);
    check("layout hidden when empty", (await disp("#cart-layout")) === "none");
    check("empty state shown", await cart.$eval("#cart-empty", (e) => !e.hidden));

    section("Validation & checkout");
    await cart.evaluate((slug) =>
      localStorage.setItem("fh-cart", JSON.stringify([{ slug, qty: 1, options: null }])), products[0].slug);
    await cart.reload({ waitUntil: "networkidle" });
    await cart.waitForTimeout(500);
    await cart.click("#checkout-btn");
    await cart.waitForTimeout(300);
    check("empty form blocks checkout", (await cart.$$eval(".form-field.invalid", (f) => f.length)) >= 3);
    check("stays on cart", cart.url().includes("cart.html"));

    await cart.fill("#name", "Test Customer");
    await cart.fill("#email", "test@example.com");
    await cart.fill("#phone", "0400000000");
    await cart.click("#checkout-btn");
    await cart.waitForTimeout(1500);
    check("checkout redirects", cart.url().includes("checkout-success"), cart.url());
    check("cart cleared after order", (await cart.evaluate(() => localStorage.getItem("fh-cart"))) === null);

    section("Without JavaScript");
    const noJs = await browser.newContext({ javaScriptEnabled: false, viewport: { width: 1400, height: 950 } });
    const nj = await noJs.newPage();
    await nj.goto(`${BASE}/shop.html`, { waitUntil: "domcontentloaded" });
    const cardBox = await (await nj.$(".product-card")).boundingBox();
    check("products render with JS disabled", !!cardBox && cardBox.height > 0);
    await noJs.close();

    section("Accessibility");
    const pages = ["index.html", "shop.html", "menu.html", "about.html", "careers.html", "contact.html", "cart.html", `product/${products[0].slug}.html`];
    const issues = [];
    for (const p of pages) {
      const ap = await ctx.newPage();
      await ap.goto(`${BASE}/${p}`, { waitUntil: "domcontentloaded" });
      const found = await ap.evaluate(() => {
        const out = [];
        document.querySelectorAll("img:not([alt])").forEach(() => out.push("img missing alt"));
        document.querySelectorAll("button, a").forEach((el) => {
          if (!(el.getAttribute("aria-label") || el.textContent || "").trim()) out.push(`unnamed ${el.tagName.toLowerCase()}`);
        });
        document.querySelectorAll("input:not([type=hidden]):not([type=radio]), select, textarea").forEach((el) => {
          const ok = (el.id && document.querySelector(`label[for="${el.id}"]`)) || el.closest("label") || el.getAttribute("aria-label");
          if (!ok) out.push(`unlabeled ${el.type || el.tagName.toLowerCase()}`);
        });
        const levels = [...document.querySelectorAll("h1,h2,h3,h4,h5,h6")].map((h) => +h.tagName[1]);
        if (levels.filter((l) => l === 1).length !== 1) out.push(`h1 count = ${levels.filter((l) => l === 1).length}`);
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
      if (found.length) issues.push(`${p}: ${[...new Set(found)].join(", ")}`);
      await ap.close();
    }
    check("no accessibility issues", issues.length === 0, issues.join(" | "));
    check("no JavaScript errors", jsErrors.length === 0, jsErrors.slice(0, 3).join(" | "));
  } finally {
    await browser.close();
  }
}

/* ---------- run ---------- */

(async () => {
  dataChecks();
  linkChecks();
  freshnessCheck();

  const server = await serve();
  try {
    await checkoutSecurity();
    await browserChecks();
  } finally {
    server.close();
  }

  console.log(`\n${checks - failures}/${checks} checks passed`);
  if (failures) {
    console.error(`${failures} FAILED`);
    process.exit(1);
  }
})();
