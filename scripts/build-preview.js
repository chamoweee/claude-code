#!/usr/bin/env node
/**
 * Builds shop/preview.html — the single-page, clickable version of the
 * storefront published as an Artifact.
 *
 *   node scripts/build-preview.js
 *
 * The multi-page site under shop/ is the real product; this collapses it into
 * one page (cart as a slide-over instead of its own route) because an Artifact
 * is a single page. It is generated from the same data/products.json and
 * data/site.json, so prices, pack sizes and lead times can't drift from the
 * shop they're previewing.
 */

const fs = require("fs");
const path = require("path");

const ROOT = path.join(__dirname, "..");
const SHOP = path.join(ROOT, "shop");

const products = JSON.parse(fs.readFileSync(path.join(SHOP, "data", "products.json"), "utf8"));
const site = JSON.parse(fs.readFileSync(path.join(SHOP, "data", "site.json"), "utf8"));
const template = fs.readFileSync(path.join(SHOP, "preview.template.html"), "utf8");

// Only the fields the preview actually renders — keeps the inlined payload small.
const slim = products.map((p) => ({
  slug: p.slug,
  name: p.name,
  group: p.group,
  category: p.category,
  categoryLabel: p.categoryLabel,
  priceCents: p.priceCents,
  packSize: p.packSize,
  packLabel: p.packLabel,
  emoji: p.emoji,
  gradient: p.gradient,
  blurb: p.blurb,
  description: p.description,
  allergens: p.allergens,
  storage: p.storage,
  leadDays: p.leadDays,
  options: p.options,
  glutenFree: !!p.glutenFree,
  vegan: !!p.vegan,
}));

let html = template
  .replace("__PRODUCTS__", JSON.stringify(slim))
  .replace("__GROUPS__", JSON.stringify(site.groups))
  .replace("__RULES__", JSON.stringify(site.ordering));

const leftover = html.match(/__[A-Z]+__/g);
if (leftover) throw new Error(`Unfilled placeholders: ${leftover.join(", ")}`);

// Artifacts cap the rendered page at 16MB; this should be nowhere near it.
const kb = Buffer.byteLength(html) / 1024;
if (kb > 15000) throw new Error(`Preview too large: ${kb.toFixed(0)}KB`);

const out = path.join(SHOP, "preview.html");
fs.writeFileSync(out, html);

console.log(`Built preview.html — ${slim.length} products, ${kb.toFixed(1)} KB`);
console.log("Publish shop/preview.html as the Artifact.");
