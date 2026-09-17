#!/usr/bin/env node
/**
 * Generates the static parts of the shop from shop/data/*.json:
 * product detail pages, the shop grid, category chips, shared header/footer,
 * homepage featured products, and sitemap.xml.
 *
 *   node scripts/build-shop.js
 */

const fs = require("fs");
const path = require("path");

const ROOT = path.join(__dirname, "..");
const SHOP = path.join(ROOT, "shop");

const site = JSON.parse(fs.readFileSync(path.join(SHOP, "data", "site.json"), "utf8"));
const products = JSON.parse(fs.readFileSync(path.join(SHOP, "data", "products.json"), "utf8"));

const SITE_URL = site.brand.domain;
const SYM = site.ordering.currencySymbol;

const esc = (s) =>
  String(s).replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;");

const money = (cents) => `${SYM}${(cents / 100).toFixed(2)}`;

/* Category chips are derived from the catalogue so they can never list an empty one. */
const categories = [];
for (const p of products) {
  if (!categories.some((c) => c.id === p.category)) {
    categories.push({ id: p.category, label: p.categoryLabel });
  }
}

const NAV = [
  ["index.html", "Home", "home"],
  ["menu.html", "Our Menu", "menu"],
  ["shop.html", "Shop", "shop"],
  ["about.html", "About Us", "about"],
  ["careers.html", "Careers", "careers"],
  ["contact.html", "Contact", "contact"],
];

/* ---------- SVG icons for the dark category band ---------- */
const ICONS = {
  pie: `<svg viewBox="0 0 40 40" aria-hidden="true"><path d="M4 22h32a16 16 0 0 1-32 0Z" stroke-linejoin="round"/><path d="M8 22a12 12 0 0 1 24 0" /><path d="M20 10v12M13 13l7 9M27 13l-7 9"/></svg>`,
  platter: `<svg viewBox="0 0 40 40" aria-hidden="true"><path d="M3 26h34a3 3 0 0 1-3 3H6a3 3 0 0 1-3-3Z" stroke-linejoin="round"/><path d="M7 26a13 13 0 0 1 26 0"/><circle cx="20" cy="9" r="2"/><path d="M14 20a4 4 0 0 1 8 0M23 22a3 3 0 0 1 6 0"/></svg>`,
  cake: `<svg viewBox="0 0 40 40" aria-hidden="true"><path d="M6 32h28V21a4 4 0 0 0-4-4H10a4 4 0 0 0-4 4v11Z" stroke-linejoin="round"/><path d="M6 25c3 0 3 3 6 3s3-3 6-3 3 3 6 3 3-3 6-3 4 3 4 3"/><path d="M20 17V9M14 17v-6M26 17v-6"/></svg>`,
};

/* ---------- shared chrome ---------- */

function head({ title, description, prefix, canonical, jsonLd, noindex }) {
  return `  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <title>${esc(title)}</title>
  <meta name="description" content="${esc(description)}" />${
    noindex ? '\n  <meta name="robots" content="noindex" />' : ""
  }
  <link rel="canonical" href="${SITE_URL}/${canonical}" />
  <meta property="og:type" content="website" />
  <meta property="og:site_name" content="${esc(site.brand.name)}" />
  <meta property="og:title" content="${esc(title)}" />
  <meta property="og:description" content="${esc(description)}" />
  <meta property="og:url" content="${SITE_URL}/${canonical}" />
  <meta name="twitter:card" content="summary_large_image" />
  <meta name="twitter:title" content="${esc(title)}" />
  <meta name="twitter:description" content="${esc(description)}" />
  <meta name="theme-color" content="#f4a748" />
  <link rel="preconnect" href="https://fonts.googleapis.com">
  <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
  <link href="https://fonts.googleapis.com/css2?family=Bebas+Neue&family=Poppins:wght@400;600;700&display=swap" rel="stylesheet">
  <link rel="icon" href="data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 100 100'%3E%3Crect width='100' height='100' rx='22' fill='%23f4a748'/%3E%3Ctext x='50' y='70' font-size='56' text-anchor='middle'%3E%F0%9F%A5%90%3C/text%3E%3C/svg%3E" />
  <link rel="stylesheet" href="${prefix}css/style.css" />
  <script>document.documentElement.classList.add("js");</script>${
    jsonLd ? `\n  <script type="application/ld+json">${JSON.stringify(jsonLd)}</script>` : ""
  }`;
}

function wordmark(prefix = "") {
  return `<a href="${prefix}index.html" class="brand">
        <span class="brand-prefix">${esc(site.brand.prefix)}</span>
        <span class="brand-mark">${esc(site.brand.wordmark)}</span>
        <span class="brand-suburb">${esc(site.brand.suburb)}</span>
      </a>`;
}

function header(active, prefix = "") {
  const items = NAV.map(
    ([href, label, id]) =>
      `        <li><a href="${prefix}${href}"${
        active === id ? ' aria-current="page"' : ""
      }>${label}</a></li>`
  ).join("\n");

  return `  <a class="skip-link" href="#main">Skip to content</a>
  <header class="site-header">
    <nav class="nav" aria-label="Main">
      <button class="nav-toggle" aria-label="Open menu" aria-expanded="false" aria-controls="nav-panel">
        <span></span><span></span><span></span>
      </button>
      ${wordmark(prefix)}
      <div class="nav-actions">
        <a class="icon-btn" href="${prefix}cart.html" aria-label="View cart">
          <span aria-hidden="true">🛒</span>
          <span class="cart-count" data-cart-count hidden>0</span>
        </a>
      </div>
    </nav>
    <div class="nav-panel" id="nav-panel">
      <ul>
${items}
      </ul>
    </div>
  </header>
  <div class="nav-scrim" hidden></div>`;
}

function footer(prefix = "") {
  const hours = site.hours
    .map((h) => `            <li><span>${esc(h.days)}</span><span>${esc(h.time)}</span></li>`)
    .join("\n");

  return `  <footer class="site-footer">
    <div class="container">
      <div class="footer-grid">
        <div class="footer-brand">
          ${wordmark(prefix)}
          <p>${esc(site.brand.tagline)}. ${esc(site.contact.address)}, ${esc(site.contact.suburb)}.</p>
        </div>
        <div>
          <h2>Shop</h2>
          <ul>
            <li><a href="${prefix}shop.html">All products</a></li>
${site.groups
  .map((g) => `            <li><a href="${prefix}shop.html#${g.id}">${esc(g.label)}</a></li>`)
  .join("\n")}
          </ul>
        </div>
        <div>
          <h2>Visit</h2>
          <ul class="hours-list">
${hours}
          </ul>
        </div>
        <div>
          <h2>Contact</h2>
          <ul>
            <li><a href="tel:${site.contact.phone.replace(/[^0-9+]/g, "")}">${esc(site.contact.phone)}</a></li>
            <li><a href="mailto:${esc(site.contact.email)}">${esc(site.contact.email)}</a></li>
            <li><a href="${prefix}contact.html">Find us</a></li>
            <li><a href="${prefix}careers.html">Work with us</a></li>
          </ul>
        </div>
      </div>
      <div class="footer-bottom">
        <span>&copy; 2026 ${esc(site.brand.name)}. ABN ${esc(site.contact.abn)}.</span>
        <span>${esc(site.brand.tagline)}.</span>
      </div>
    </div>
  </footer>
  <button class="back-to-top" aria-label="Back to top">&#8593;</button>
  <div class="toast" role="status" aria-live="polite"></div>`;
}

function categoryBand(activeGroup = "") {
  const groups = site.groups
    .map(
      (g) => `        <a class="group-link${g.id === activeGroup ? " active" : ""}" href="shop.html#${g.id}" data-group="${g.id}">
          <span class="group-icon">${ICONS[g.icon] || ICONS.pie}</span>
          <span class="group-label">${esc(g.label)}</span>
        </a>`
    )
    .join("\n");

  const chips = [{ id: "all", label: "All" }, ...categories]
    .map(
      (c) =>
        `        <button class="chip${c.id === "all" ? " active" : ""}" data-chip="${c.id}" aria-pressed="${
          c.id === "all"
        }">${esc(c.label)}</button>`
    )
    .join("\n");

  return `    <section class="cat-band" aria-label="Product categories">
      <div class="container">
        <div class="group-row">
${groups}
        </div>
      </div>
      <div class="chip-row" role="group" aria-label="Filter by category">
${chips}
      </div>
    </section>`;
}

/* ---------- product card ---------- */

function flags(p) {
  let out = "";
  if (p.glutenFree) out += '<span class="diet-flag">GF</span>';
  if (p.vegan) out += '<span class="diet-flag">Vegan</span>';
  return out;
}

function card(p, prefix = "") {
  const search = [p.name, p.categoryLabel, p.blurb].join(" ").toLowerCase();
  return `          <article class="product-card reveal" data-group="${p.group}" data-category="${p.category}" data-slug="${p.slug}" data-search="${esc(search)}">
            <a class="product-thumb" href="${prefix}product/${p.slug}.html" style="background:linear-gradient(155deg,${p.gradient[0]},${p.gradient[1]});" aria-label="${esc(p.name)}">
              <span aria-hidden="true">${p.emoji}</span>
              <span class="pack-badge"><strong>${p.packSize}</strong><span>${esc(p.packLabel)}</span></span>
            </a>
            <div class="product-body">
              <p class="product-cat">${esc(p.categoryLabel)}</p>
              <h3><a href="${prefix}product/${p.slug}.html">${esc(p.name)}</a>${flags(p)}</h3>
              <p class="product-blurb">${esc(p.blurb)}</p>
              <p class="product-price">${money(p.priceCents)}</p>
              <div class="product-actions">
                <a class="btn btn-outline" href="${prefix}product/${p.slug}.html">More info</a>
                ${
                  p.options
                    ? `<a class="btn btn-primary" href="${prefix}product/${p.slug}.html">Choose</a>`
                    : `<button class="btn btn-primary" data-add="${p.slug}">Add</button>`
                }
              </div>
            </div>
          </article>`;
}

/* ---------- product detail page ---------- */

function productJsonLd(p) {
  return {
    "@context": "https://schema.org",
    "@type": "Product",
    name: p.name,
    description: p.description,
    category: p.categoryLabel,
    brand: { "@type": "Brand", name: site.brand.name },
    offers: {
      "@type": "Offer",
      price: (p.priceCents / 100).toFixed(2),
      priceCurrency: site.ordering.currency.toUpperCase(),
      availability: "https://schema.org/InStock",
      url: `${SITE_URL}/product/${p.slug}.html`,
    },
  };
}

function productPage(p) {
  const related = products.filter((o) => o.slug !== p.slug && o.category === p.category).slice(0, 3);
  const fallback = products.filter((o) => o.slug !== p.slug).slice(0, 3);
  const relatedList = related.length ? related : fallback;

  const optionFields = (p.options || [])
    .map(
      (opt) => `            <div class="option-group">
              <label for="opt-${opt.id}">${esc(opt.label)}</label>
              <select id="opt-${opt.id}" data-option="${esc(opt.label)}">
${opt.choices.map((c) => `                <option>${esc(c)}</option>`).join("\n")}
              </select>
            </div>`
    )
    .join("\n");

  return `<!doctype html>
<html lang="en-AU">
<head>
${head({
  title: `${p.name} — ${site.brand.name}`,
  description: p.blurb,
  prefix: "../",
  canonical: `product/${p.slug}.html`,
  jsonLd: productJsonLd(p),
})}
</head>
<body>
${header("shop", "../")}

  <main id="main">
    <div class="container">
      <nav class="breadcrumb" aria-label="Breadcrumb">
        <a href="../index.html">Home</a><span aria-hidden="true">›</span>
        <a href="../shop.html">Shop</a><span aria-hidden="true">›</span>
        <a href="../shop.html#${p.category}">${esc(p.categoryLabel)}</a><span aria-hidden="true">›</span>
        <span aria-current="page">${esc(p.name)}</span>
      </nav>

      <div class="detail-grid">
        <div>
          <div class="gallery-main" style="background:linear-gradient(155deg,${p.gradient[0]},${p.gradient[1]});">
            <span aria-hidden="true">${p.emoji}</span>
            <button class="gallery-zoom" aria-label="Enlarge image">🔍</button>
            <span class="pack-badge"><strong>${p.packSize}</strong><span>${esc(p.packLabel)}</span></span>
          </div>
          <div class="gallery-thumbs">
            <button class="gallery-thumb active" style="background:linear-gradient(155deg,${p.gradient[0]},${p.gradient[1]});" aria-label="View 1">${p.emoji}</button>
            <button class="gallery-thumb" style="background:linear-gradient(200deg,${p.gradient[1]},${p.gradient[0]});" aria-label="View 2">${p.emoji}</button>
          </div>
        </div>

        <div>
          <p class="product-cat">${esc(p.categoryLabel)}</p>
          <h1 class="detail-title">${esc(p.name)}</h1>
          <p class="detail-price">${money(p.priceCents)}</p>
          <p class="detail-pack">${p.packSize} ${esc(p.packLabel)} per order</p>
          <p class="detail-desc">${esc(p.description)}</p>

          <div class="lead-note">Please allow ${p.leadDays} ${
    p.leadDays === 1 ? "day" : "days"
  } notice for this item.</div>

${optionFields}

          <div class="qty-row">
            <div class="qty-stepper">
              <button type="button" data-qty="down" aria-label="Decrease quantity">−</button>
              <label class="visually-hidden" for="qty">Quantity</label>
              <input type="number" id="qty" value="1" min="1" max="99" />
              <button type="button" data-qty="up" aria-label="Increase quantity">+</button>
            </div>
          </div>

          <button class="btn btn-primary btn-lg btn-block" data-add="${p.slug}" data-from-detail>Order</button>

          <a class="cat-backlink" href="../shop.html#${p.category}">${esc(p.categoryLabel)}</a>

          <div class="detail-meta">
            <dl>
              <dt>Allergens</dt><dd>${esc((p.allergens || []).join(", ") || "None declared")}</dd>
              <dt>Storage</dt><dd>${esc(p.storage)}</dd>
              <dt>Lead time</dt><dd>${p.leadDays} ${p.leadDays === 1 ? "day" : "days"}</dd>
            </dl>
          </div>
        </div>
      </div>

      <section class="section" style="padding-top:0;">
        <h2>Related products</h2>
        <div class="product-grid">
${relatedList.map((o) => card(o, "../")).join("\n")}
        </div>
      </section>
    </div>
  </main>

${footer("../")}
  <script src="../js/shop.js"></script>
</body>
</html>
`;
}

/* ---------- injection ---------- */

function inject(html, marker, content) {
  const re = new RegExp(`<!-- BUILD:${marker} -->[\\s\\S]*?<!-- /BUILD:${marker} -->`);
  if (!re.test(html)) throw new Error(`Marker "${marker}" not found`);
  return html.replace(re, `<!-- BUILD:${marker} -->\n${content}\n<!-- /BUILD:${marker} -->`);
}

function buildPage(file, active, transforms = []) {
  const p = path.join(SHOP, file);
  let html = fs.readFileSync(p, "utf8");
  html = inject(html, "header", header(active));
  html = inject(html, "footer", footer());
  for (const t of transforms) html = t(html);
  fs.writeFileSync(p, html);
}

/* ---------- run ---------- */

const written = [];

const productDir = path.join(SHOP, "product");
fs.mkdirSync(productDir, { recursive: true });
for (const p of products) {
  fs.writeFileSync(path.join(productDir, `${p.slug}.html`), productPage(p));
  written.push(`product/${p.slug}.html`);
}

// Shop page: category band + full grid
buildPage("shop.html", "shop", [
  (h) => inject(h, "band", categoryBand()),
  (h) => inject(h, "grid", products.map((p) => card(p)).join("\n")),
  (h) =>
    inject(
      h,
      "count",
      `        <p class="result-count"><span data-result-count>${products.length}</span> products</p>`
    ),
]);
written.push("shop.html");

// Homepage: featured products
const featured = products.filter((p) => p.featured);
buildPage("index.html", "home", [
  (h) => inject(h, "featured", featured.map((p) => card(p)).join("\n")),
]);
written.push("index.html");

// Menu page groups everything by category
const menuSections = categories
  .map(
    (c) => `        <section class="section" id="${c.id}">
          <div class="section-head reveal"><h2>${esc(c.label)}</h2></div>
          <div class="product-grid">
${products
  .filter((p) => p.category === c.id)
  .map((p) => card(p))
  .join("\n")}
          </div>
        </section>`
  )
  .join("\n");

buildPage("menu.html", "menu", [(h) => inject(h, "menu", menuSections)]);
written.push("menu.html");

for (const [file, active] of [
  ["about.html", "about"],
  ["careers.html", "careers"],
  ["contact.html", "contact"],
  ["cart.html", ""],
  ["checkout-success.html", ""],
  ["404.html", ""],
]) {
  if (fs.existsSync(path.join(SHOP, file))) {
    buildPage(file, active);
    written.push(file);
  }
}

// sitemap + robots
const today = new Date().toISOString().slice(0, 10);
const urls = [
  "index.html",
  "menu.html",
  "shop.html",
  "about.html",
  "careers.html",
  "contact.html",
  ...products.map((p) => `product/${p.slug}.html`),
];
fs.writeFileSync(
  path.join(SHOP, "sitemap.xml"),
  `<?xml version="1.0" encoding="UTF-8"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
${urls
  .map(
    (u) => `  <url>
    <loc>${SITE_URL}/${u}</loc>
    <lastmod>${today}</lastmod>
    <priority>${u === "index.html" ? "1.0" : u.startsWith("product/") ? "0.8" : "0.6"}</priority>
  </url>`
  )
  .join("\n")}
</urlset>
`
);
fs.writeFileSync(
  path.join(SHOP, "robots.txt"),
  `User-agent: *\nAllow: /\nDisallow: /cart.html\nDisallow: /checkout-success.html\n\nSitemap: ${SITE_URL}/sitemap.xml\n`
);
written.push("sitemap.xml", "robots.txt");

// Public catalogue for the cart to re-read names/prices
fs.writeFileSync(
  path.join(SHOP, "data", "catalogue.json"),
  JSON.stringify(
    products.map((p) => ({
      slug: p.slug,
      name: p.name,
      priceCents: p.priceCents,
      packSize: p.packSize,
      packLabel: p.packLabel,
      emoji: p.emoji,
      gradient: p.gradient,
      leadDays: p.leadDays,
    })),
    null,
    2
  ) + "\n"
);
written.push("data/catalogue.json");

console.log(`Built ${products.length} products → ${written.length} files`);
console.log(`  ${categories.length} categories, ${featured.length} featured, ${site.groups.length} groups`);
