/**
 * Creates a Stripe Checkout Session for a cart.
 *
 * Deploys as-is to Vercel (/api/*) and to Netlify via the redirect in
 * netlify.toml. GitHub Pages cannot run this — it needs a host that executes
 * server code. See shop/README.md.
 *
 * Required environment variable:
 *   STRIPE_SECRET_KEY   sk_test_... or sk_live_...
 * Optional:
 *   SITE_URL            public origin used for success/cancel redirects
 *
 * With no STRIPE_SECRET_KEY set the endpoint runs in demo mode and returns a
 * link to the success page, so the whole flow is testable before you have an
 * account. Demo mode never takes a payment.
 */

const fs = require("fs");
const path = require("path");

const MAX_QTY = 99;
const MAX_LINES = 50;

/* Prices come from the catalogue on disk, never from the request body — a
   client that posts its own prices must not be able to set them. */
let catalogue = null;
function loadCatalogue() {
  if (catalogue) return catalogue;
  const file = path.join(process.cwd(), "shop", "data", "products.json");
  const products = JSON.parse(fs.readFileSync(file, "utf8"));
  catalogue = {};
  for (const p of products) catalogue[p.slug] = p;
  return catalogue;
}

function bad(res, status, message) {
  res.statusCode = status;
  res.setHeader("Content-Type", "application/json");
  res.end(JSON.stringify({ error: message }));
}

function readBody(req) {
  if (req.body) {
    return Promise.resolve(typeof req.body === "string" ? JSON.parse(req.body) : req.body);
  }
  return new Promise((resolve, reject) => {
    let raw = "";
    req.on("data", (chunk) => {
      raw += chunk;
      if (raw.length > 100000) reject(new Error("Payload too large"));
    });
    req.on("end", () => {
      try {
        resolve(JSON.parse(raw || "{}"));
      } catch (e) {
        reject(new Error("Invalid JSON"));
      }
    });
    req.on("error", reject);
  });
}

module.exports = async function handler(req, res) {
  if (req.method !== "POST") return bad(res, 405, "Method not allowed");

  let payload;
  try {
    payload = await readBody(req);
  } catch (e) {
    return bad(res, 400, e.message);
  }

  const items = Array.isArray(payload.items) ? payload.items : [];
  if (!items.length) return bad(res, 400, "Cart is empty");
  if (items.length > MAX_LINES) return bad(res, 400, "Too many line items");

  const products = loadCatalogue();

  // Re-price every line from our own data.
  const lineItems = [];
  let subtotalCents = 0;
  for (const item of items) {
    const product = products[item.slug];
    if (!product) return bad(res, 400, `Unknown product: ${item.slug}`);

    const qty = Number(item.qty);
    if (!Number.isInteger(qty) || qty < 1 || qty > MAX_QTY) {
      return bad(res, 400, `Invalid quantity for ${item.slug}`);
    }

    // Only echo back option values the product actually offers.
    let optionSuffix = "";
    if (item.options && product.options) {
      const chosen = [];
      for (const opt of product.options) {
        const value = item.options[opt.label];
        if (value && opt.choices.includes(value)) chosen.push(`${opt.label}: ${value}`);
      }
      if (chosen.length) optionSuffix = ` (${chosen.join(", ")})`;
    }

    subtotalCents += product.priceCents * qty;
    lineItems.push({
      quantity: qty,
      price_data: {
        currency: "aud",
        unit_amount: product.priceCents,
        product_data: {
          name: product.name + optionSuffix,
          description: `${product.packSize} ${product.packLabel}`,
        },
      },
    });
  }

  // Delivery fee, also computed here rather than trusted from the client.
  const site = JSON.parse(
    fs.readFileSync(path.join(process.cwd(), "shop", "data", "site.json"), "utf8")
  );
  const { deliveryFeeCents, freeDeliveryOverCents } = site.ordering;
  if (payload.fulfilment === "delivery" && subtotalCents < freeDeliveryOverCents) {
    lineItems.push({
      quantity: 1,
      price_data: {
        currency: "aud",
        unit_amount: deliveryFeeCents,
        product_data: { name: "Delivery" },
      },
    });
  }

  const origin =
    process.env.SITE_URL ||
    (req.headers && req.headers.origin) ||
    site.brand.domain;

  const customer = payload.customer || {};
  const metadata = {
    fulfilment: String(payload.fulfilment || "pickup").slice(0, 40),
    when: String(payload.when || "").slice(0, 40),
    customer_name: String(customer.name || "").slice(0, 120),
    customer_phone: String(customer.phone || "").slice(0, 40),
    address: String(customer.address || "").slice(0, 300),
    notes: String(payload.notes || "").slice(0, 450),
  };

  const secret = process.env.STRIPE_SECRET_KEY;

  // Demo mode: exercise the full flow without a Stripe account.
  if (!secret) {
    res.statusCode = 200;
    res.setHeader("Content-Type", "application/json");
    return res.end(
      JSON.stringify({
        url: `${origin}/shop/checkout-success.html?demo=1`,
        demo: true,
        subtotalCents,
      })
    );
  }

  try {
    const stripe = require("stripe")(secret);
    const session = await stripe.checkout.sessions.create({
      mode: "payment",
      line_items: lineItems,
      customer_email: customer.email || undefined,
      success_url: `${origin}/shop/checkout-success.html?session_id={CHECKOUT_SESSION_ID}`,
      cancel_url: `${origin}/shop/cart.html`,
      metadata,
      payment_intent_data: { metadata },
    });
    res.statusCode = 200;
    res.setHeader("Content-Type", "application/json");
    res.end(JSON.stringify({ url: session.url }));
  } catch (err) {
    // Never leak Stripe internals to the browser.
    console.error("Stripe checkout failed:", err);
    bad(res, 502, "Payment provider unavailable");
  }
};
