#!/usr/bin/env node
/**
 * Generates the static parts of the Sattva Table site from site/data/recipes.json:
 * recipe detail pages, the recipe grid, homepage featured cards, shared header/footer,
 * and sitemap.xml. Run `node scripts/build-site.js` after editing recipes.json.
 */

const fs = require("fs");
const path = require("path");

const ROOT = path.join(__dirname, "..");
const SITE = path.join(ROOT, "site");
const SITE_URL = "https://chamoweee.github.io/claude-code";

const recipes = JSON.parse(fs.readFileSync(path.join(SITE, "data", "recipes.json"), "utf8"));

const CATEGORIES = [
  { id: "all", label: "All" },
  { id: "breakfast", label: "Breakfast" },
  { id: "curry", label: "Curries & Dals" },
  { id: "rice", label: "Rice & Grains" },
  { id: "bread", label: "Breads" },
  { id: "snack", label: "Snacks" },
  { id: "side", label: "Sides & Chutneys" },
  { id: "dessert", label: "Sweets" },
  { id: "drink", label: "Drinks" },
];

const esc = (s) =>
  String(s).replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;");

const totalMin = (r) => r.prepMin + r.cookMin;

function fmtQty(qty) {
  if (qty === null || qty === undefined) return "";
  const fractions = { 0.25: "¼", 0.5: "½", 0.75: "¾", 0.33: "⅓", 0.67: "⅔" };
  const whole = Math.floor(qty);
  const frac = +(qty - whole).toFixed(2);
  if (frac === 0) return String(whole);
  if (fractions[frac]) return whole === 0 ? fractions[frac] : `${whole}${fractions[frac]}`;
  return String(+qty.toFixed(2));
}

function ingredientText(ing) {
  return [fmtQty(ing.qty), ing.unit, ing.name].filter(Boolean).join(" ");
}

/* ---------- shared chrome ---------- */

function head(opts) {
  const { title, description, prefix, canonical, jsonLd } = opts;
  return `  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <title>${esc(title)}</title>
  <meta name="description" content="${esc(description)}" />
  <link rel="canonical" href="${SITE_URL}/${canonical}" />
  <meta property="og:type" content="website" />
  <meta property="og:site_name" content="Sattva Table" />
  <meta property="og:title" content="${esc(title)}" />
  <meta property="og:description" content="${esc(description)}" />
  <meta property="og:url" content="${SITE_URL}/${canonical}" />
  <meta name="twitter:card" content="summary_large_image" />
  <meta name="twitter:title" content="${esc(title)}" />
  <meta name="twitter:description" content="${esc(description)}" />
  <meta name="theme-color" content="#fbf6ee" />
  <link rel="preconnect" href="https://fonts.googleapis.com">
  <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
  <link href="https://fonts.googleapis.com/css2?family=Playfair+Display:wght@600;700&family=Inter:wght@400;500;600;700&display=swap" rel="stylesheet">
  <link rel="icon" href="data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 100 100'%3E%3Ccircle cx='50' cy='50' r='50' fill='%237c8f6e'/%3E%3Ctext x='50' y='68' font-size='58' text-anchor='middle'%3E%F0%9F%8C%BF%3C/text%3E%3C/svg%3E" />
  <link rel="stylesheet" href="${prefix}css/style.css" />
  <script>
    (function () {
      try {
        var t = localStorage.getItem("st-theme");
        if (t === "dark" || (!t && matchMedia("(prefers-color-scheme: dark)").matches)) {
          document.documentElement.dataset.theme = "dark";
        }
      } catch (e) {}
    })();
  </script>${jsonLd ? `\n  <script type="application/ld+json">${JSON.stringify(jsonLd)}</script>` : ""}`;
}

function header(active, prefix = "") {
  const link = (href, label, id) =>
    `<li><a href="${prefix}${href}"${active === id ? ' aria-current="page"' : ""}>${label}</a></li>`;
  return `  <a class="skip-link" href="#main">Skip to content</a>
  <header class="site-header">
    <nav class="nav" aria-label="Main">
      <a href="${prefix}index.html" class="brand">
        <span class="brand-mark" aria-hidden="true">🌿</span> Sattva Table
      </a>
      <ul class="nav-links">
        ${link("index.html", "Home", "home")}
        ${link("recipes.html", "Recipes", "recipes")}
        ${link("about.html", "About No-Allium", "about")}
        ${link("saved.html", "Saved", "saved")}
        ${link("contact.html", "Contact", "contact")}
      </ul>
      <div class="nav-cta">
        <button class="theme-toggle" aria-label="Switch to dark theme" title="Toggle theme">
          <span class="theme-icon" aria-hidden="true">◐</span>
        </button>
        <a href="${prefix}recipes.html" class="btn btn-outline nav-browse">Browse Recipes</a>
        <button class="nav-toggle" aria-label="Open menu" aria-expanded="false" aria-controls="nav-links">&#9776;</button>
      </div>
    </nav>
  </header>`;
}

function footer(prefix = "") {
  return `  <footer class="site-footer">
    <div class="container">
      <div class="footer-grid">
        <div class="footer-brand">
          <a href="${prefix}index.html" class="brand footer-brand-link">
            <span class="brand-mark" aria-hidden="true">🌿</span> Sattva Table
          </a>
          <p>Vegetarian recipes made without onion, garlic, leeks, shallots, or chives — for sattvic, Jain, and allium-sensitive kitchens.</p>
        </div>
        <div>
          <h2>Explore</h2>
          <ul>
            <li><a href="${prefix}index.html">Home</a></li>
            <li><a href="${prefix}recipes.html">All recipes</a></li>
            <li><a href="${prefix}about.html">About no-allium</a></li>
            <li><a href="${prefix}saved.html">Saved recipes</a></li>
          </ul>
        </div>
        <div>
          <h2>Recipe types</h2>
          <ul>
            <li><a href="${prefix}recipes.html#breakfast">Breakfast</a></li>
            <li><a href="${prefix}recipes.html#curry">Curries &amp; dals</a></li>
            <li><a href="${prefix}recipes.html#snack">Snacks</a></li>
            <li><a href="${prefix}recipes.html#dessert">Sweets</a></li>
          </ul>
        </div>
        <div>
          <h2>Connect</h2>
          <ul>
            <li><a href="${prefix}contact.html">Contact us</a></li>
            <li><a href="${prefix}contact.html">Submit a recipe</a></li>
          </ul>
        </div>
      </div>
      <div class="footer-bottom">
        <span>&copy; 2026 Sattva Table. ${recipes.length} recipes, all vegetarian &amp; allium-free.</span>
        <span>Made with ginger, not garlic.</span>
      </div>
    </div>
  </footer>
  <button class="back-to-top" aria-label="Back to top">&#8593;</button>`;
}

/* ---------- recipe card ---------- */

function dietBadges(r) {
  const badges = [];
  if (r.vegan) badges.push('<span class="diet-badge" title="Vegan">Vegan</span>');
  if (r.glutenFree) badges.push('<span class="diet-badge" title="Gluten free">GF</span>');
  if (r.jainFriendly) badges.push('<span class="diet-badge" title="Jain-friendly">Jain</span>');
  return badges.join("");
}

function card(r, prefix = "") {
  const searchBlob = [r.title, r.categoryLabel, r.description, ...r.ingredients.map((i) => i.name)]
    .join(" ")
    .toLowerCase();
  return `          <article class="recipe-card reveal" data-category="${r.category}" data-spice="${r.spice}" data-time="${totalMin(r)}" data-vegan="${r.vegan}" data-gf="${r.glutenFree}" data-jain="${r.jainFriendly}" data-slug="${r.slug}" data-search="${esc(searchBlob)}">
            <a class="recipe-card-link" href="${prefix}recipes/${r.slug}.html">
              <div class="recipe-thumb" style="background:linear-gradient(160deg,${r.gradient[0]},${r.gradient[1]});"><span>${r.emoji}</span></div>
            </a>
            <div class="recipe-body">
              <div class="recipe-tags">
                <span class="tag">${esc(r.categoryLabel)}</span>
                <span class="tag spice">${esc(r.spice)}</span>
              </div>
              <h3><a href="${prefix}recipes/${r.slug}.html">${esc(r.title)}</a></h3>
              <div class="recipe-meta"><span>⏱ ${totalMin(r)} min</span><span>🍽 Serves ${r.serves}</span></div>
              <p>${esc(r.description)}</p>
              <div class="recipe-foot">
                <div class="diet-badges">${dietBadges(r)}</div>
                <button class="save-btn" data-slug="${r.slug}" aria-label="Save ${esc(r.title)}" title="Save recipe">
                  <span class="save-icon" aria-hidden="true">♥</span>
                </button>
              </div>
            </div>
          </article>`;
}

/* ---------- recipe detail page ---------- */

function breadcrumbFor(r) {
  return {
    "@context": "https://schema.org",
    "@type": "BreadcrumbList",
    itemListElement: [
      { "@type": "ListItem", position: 1, name: "Home", item: `${SITE_URL}/index.html` },
      { "@type": "ListItem", position: 2, name: "Recipes", item: `${SITE_URL}/recipes.html` },
      { "@type": "ListItem", position: 3, name: r.title, item: `${SITE_URL}/recipes/${r.slug}.html` },
    ],
  };
}

function jsonLdFor(r) {
  return {
    "@context": "https://schema.org",
    "@type": "Recipe",
    name: r.title,
    description: r.description,
    image: `${SITE_URL}/recipes/${r.slug}.html`,
    author: { "@type": "Organization", name: "Sattva Table" },
    recipeCategory: r.categoryLabel,
    recipeCuisine: "Indian",
    prepTime: `PT${r.prepMin}M`,
    cookTime: `PT${r.cookMin}M`,
    totalTime: `PT${totalMin(r)}M`,
    recipeYield: `${r.serves} servings`,
    suitableForDiet: [
      "https://schema.org/VegetarianDiet",
      ...(r.vegan ? ["https://schema.org/VeganDiet"] : []),
      ...(r.glutenFree ? ["https://schema.org/GlutenFreeDiet"] : []),
    ],
    recipeIngredient: r.ingredients.map(ingredientText),
    recipeInstructions: r.steps.map((s, i) => ({
      "@type": "HowToStep",
      position: i + 1,
      text: s,
    })),
    keywords: `no onion no garlic, allium free, vegetarian, ${r.categoryLabel.toLowerCase()}, sattvic, jain`,
  };
}

function recipePage(r) {
  const related = recipes
    .filter((o) => o.slug !== r.slug && o.category === r.category)
    .slice(0, 3);
  const fallback = recipes.filter((o) => o.slug !== r.slug).slice(0, 3);
  const relatedList = related.length ? related : fallback;

  const ingredientItems = r.ingredients
    .map((ing) => {
      const data =
        ing.qty !== null && ing.qty !== undefined
          ? ` data-qty="${ing.qty}" data-unit="${esc(ing.unit || "")}" data-name="${esc(ing.name)}"`
          : "";
      return `            <li><label class="ing-check"><input type="checkbox" /><span class="ing-text"${data}>${esc(
        ingredientText(ing)
      )}</span></label></li>`;
    })
    .join("\n");

  const stepItems = r.steps
    .map((s) => `            <li><label class="step-check"><input type="checkbox" /><span>${esc(s)}</span></label></li>`)
    .join("\n");

  const tipItems = (r.tips || []).map((t) => `            <li>${esc(t)}</li>`).join("\n");

  return `<!doctype html>
<html lang="en">
<head>
${head({
  title: `${r.title} — No Onion, No Garlic | Sattva Table`,
  description: r.description,
  prefix: "../",
  canonical: `recipes/${r.slug}.html`,
  jsonLd: jsonLdFor(r),
})}
  <script type="application/ld+json">${JSON.stringify(breadcrumbFor(r))}</script>
</head>
<body>
${header("recipes", "../")}

  <main id="main">
    <nav class="breadcrumb container" aria-label="Breadcrumb">
      <a href="../index.html">Home</a>
      <span aria-hidden="true">›</span>
      <a href="../recipes.html">Recipes</a>
      <span aria-hidden="true">›</span>
      <span aria-current="page">${esc(r.title)}</span>
    </nav>

    <article class="recipe-page container">
      <header class="recipe-hero">
        <div class="recipe-hero-text">
          <span class="eyebrow">${esc(r.categoryLabel)}</span>
          <h1>${esc(r.title)}</h1>
          <p class="recipe-lede">${esc(r.intro)}</p>
          <div class="diet-badges lg">${dietBadges(r)}</div>
          <div class="recipe-stats">
            <div><span class="rs-num">${r.prepMin}</span><span class="rs-label">min prep</span></div>
            <div><span class="rs-num">${r.cookMin}</span><span class="rs-label">min cook</span></div>
            <div><span class="rs-num" data-serving-display>${r.serves}</span><span class="rs-label">servings</span></div>
            <div><span class="rs-num">${esc(r.spice)}</span><span class="rs-label">spice</span></div>
          </div>
          <div class="recipe-actions">
            <button class="btn btn-primary save-btn save-btn-lg" data-slug="${r.slug}" aria-label="Save ${esc(r.title)}">
              <span class="save-icon" aria-hidden="true">♥</span> <span class="save-label">Save recipe</span>
            </button>
            <button class="btn btn-outline print-btn">🖨 Print</button>
          </div>
        </div>
        <div class="recipe-hero-visual" style="background:linear-gradient(160deg,${r.gradient[0]},${r.gradient[1]});" aria-hidden="true">
          <span>${r.emoji}</span>
        </div>
      </header>

      <aside class="swap-callout">
        <strong>What replaces the onion &amp; garlic here:</strong> ${esc(r.swapNote)}
      </aside>

      <div class="recipe-columns">
        <section class="recipe-ingredients" aria-labelledby="ing-h">
          <div class="ing-header">
            <h2 id="ing-h">Ingredients</h2>
            <div class="serving-scaler" role="group" aria-label="Adjust servings">
              <button class="scale-btn" data-scale="down" aria-label="Fewer servings">−</button>
              <span class="scale-value"><span data-serving-display>${r.serves}</span> servings</span>
              <button class="scale-btn" data-scale="up" aria-label="More servings">+</button>
            </div>
          </div>
          <ul class="ingredient-list" data-base-serves="${r.serves}">
${ingredientItems}
          </ul>
        </section>

        <section class="recipe-steps" aria-labelledby="steps-h">
          <h2 id="steps-h">Method</h2>
          <ol class="step-list">
${stepItems}
          </ol>
          ${
            tipItems
              ? `<div class="tips-box">
            <h3>Cook's notes</h3>
            <ul>
${tipItems}
            </ul>
          </div>`
              : ""
          }
        </section>
      </div>

      <section class="related-recipes" aria-labelledby="related-h">
        <h2 id="related-h">More like this</h2>
        <div class="recipe-grid">
${relatedList.map((o) => card(o, "../")).join("\n")}
        </div>
      </section>
    </article>
  </main>

${footer("../")}
  <script src="../js/script.js"></script>
</body>
</html>
`;
}

/* ---------- injection helper ---------- */

function inject(html, marker, content) {
  const start = `<!-- BUILD:${marker} -->`;
  const end = `<!-- /BUILD:${marker} -->`;
  const re = new RegExp(`${start}[\\s\\S]*?${end}`);
  if (!re.test(html)) {
    throw new Error(`Marker "${marker}" not found`);
  }
  return html.replace(re, `${start}\n${content}\n${end}`);
}

function buildPage(file, active, transforms = []) {
  const p = path.join(SITE, file);
  let html = fs.readFileSync(p, "utf8");
  html = inject(html, "header", header(active));
  html = inject(html, "footer", footer());
  for (const t of transforms) html = t(html);
  fs.writeFileSync(p, html);
  return file;
}

/* ---------- run ---------- */

const written = [];

// 1. Recipe detail pages
const recipeDir = path.join(SITE, "recipes");
fs.mkdirSync(recipeDir, { recursive: true });
for (const r of recipes) {
  fs.writeFileSync(path.join(recipeDir, `${r.slug}.html`), recipePage(r));
  written.push(`recipes/${r.slug}.html`);
}

// 2. Recipes listing: filter chips + full grid
const filterChips = CATEGORIES.map(
  (c) =>
    `          <button class="filter-btn${c.id === "all" ? " active" : ""}" data-filter="${c.id}" aria-pressed="${
      c.id === "all"
    }">${c.label}</button>`
).join("\n");

const grid = recipes.map((r) => card(r)).join("\n");

buildPage("recipes.html", "recipes", [
  (h) => inject(h, "filters", filterChips),
  (h) => inject(h, "grid", grid),
  (h) => inject(h, "count", `        <p class="result-count"><span data-result-count>${recipes.length}</span> recipes</p>`),
]);
written.push("recipes.html");

// 3. Homepage featured cards + recipe count
const featured = recipes.filter((r) => r.featured).slice(0, 6);
buildPage("index.html", "home", [
  (h) => inject(h, "featured", featured.map((r) => card(r)).join("\n")),
  (h) => inject(h, "stat-count", `<div class="stat-num">${recipes.length}</div>`),
]);
written.push("index.html");

// 4. Remaining static pages
for (const [file, active] of [
  ["about.html", "about"],
  ["contact.html", "contact"],
  ["saved.html", "saved"],
  ["404.html", ""],
]) {
  if (fs.existsSync(path.join(SITE, file))) {
    buildPage(file, active);
    written.push(file);
  }
}

// 5. sitemap.xml
const today = new Date().toISOString().slice(0, 10);
const urls = [
  "index.html",
  "recipes.html",
  "about.html",
  "contact.html",
  "saved.html",
  ...recipes.map((r) => `recipes/${r.slug}.html`),
];
const sitemap = `<?xml version="1.0" encoding="UTF-8"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
${urls
  .map(
    (u) => `  <url>
    <loc>${SITE_URL}/${u}</loc>
    <lastmod>${today}</lastmod>
    <changefreq>weekly</changefreq>
    <priority>${u === "index.html" ? "1.0" : u.startsWith("recipes/") ? "0.8" : "0.6"}</priority>
  </url>`
  )
  .join("\n")}
</urlset>
`;
fs.writeFileSync(path.join(SITE, "sitemap.xml"), sitemap);
written.push("sitemap.xml");

// 6. robots.txt
fs.writeFileSync(
  path.join(SITE, "robots.txt"),
  `User-agent: *\nAllow: /\n\nSitemap: ${SITE_URL}/sitemap.xml\n`
);
written.push("robots.txt");

console.log(`Built ${recipes.length} recipes → ${written.length} files`);
console.log(`  ${recipes.length} recipe pages, ${featured.length} featured on home`);
