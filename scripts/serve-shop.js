#!/usr/bin/env node
/**
 * Local dev server for the shop: serves shop/ statically and runs the
 * /api/create-checkout-session function, so the full checkout flow is
 * testable without deploying.
 *
 *   node scripts/serve-shop.js [port]
 */

const http = require("http");
const fs = require("fs");
const path = require("path");

const ROOT = path.join(__dirname, "..");
const SHOP = path.join(ROOT, "shop");
const PORT = Number(process.argv[2]) || 8850;

const MIME = {
  ".html": "text/html; charset=utf-8",
  ".css": "text/css; charset=utf-8",
  ".js": "text/javascript; charset=utf-8",
  ".json": "application/json; charset=utf-8",
  ".xml": "application/xml; charset=utf-8",
  ".txt": "text/plain; charset=utf-8",
  ".svg": "image/svg+xml",
  ".png": "image/png",
  ".jpg": "image/jpeg",
  ".webp": "image/webp",
};

const checkout = require(path.join(ROOT, "api", "create-checkout-session.js"));

const server = http.createServer(async (req, res) => {
  const url = new URL(req.url, `http://localhost:${PORT}`);

  if (url.pathname === "/api/create-checkout-session") {
    return checkout(req, res);
  }

  // /shop/... and bare /... both resolve into the shop directory
  let rel = decodeURIComponent(url.pathname).replace(/^\/+/, "");
  if (rel.startsWith("shop/")) rel = rel.slice(5);
  if (rel === "") rel = "index.html";

  const file = path.join(SHOP, rel);
  if (!file.startsWith(SHOP) || !fs.existsSync(file) || fs.statSync(file).isDirectory()) {
    res.writeHead(404, { "Content-Type": "text/html; charset=utf-8" });
    const notFound = path.join(SHOP, "404.html");
    return res.end(fs.existsSync(notFound) ? fs.readFileSync(notFound) : "Not found");
  }

  res.writeHead(200, { "Content-Type": MIME[path.extname(file)] || "application/octet-stream" });
  res.end(fs.readFileSync(file));
});

server.listen(PORT, () => {
  console.log(`Shop running at http://localhost:${PORT}`);
  console.log(
    process.env.STRIPE_SECRET_KEY
      ? "Stripe key detected — real Checkout sessions will be created."
      : "No STRIPE_SECRET_KEY — checkout runs in demo mode (no payment taken)."
  );
});
