# The Flour House — bakery storefront

A static bakery shop with a real cart and Stripe card checkout. No framework and
no runtime dependencies in the browser: plain HTML, CSS and JavaScript generated
from JSON.

## Rebranding it

Everything brand-specific lives in `shop/data/site.json` — name, wordmark,
suburb, address, phone, ABN, opening hours, delivery rules. Change it there and
run the build; every page updates. The palette is six CSS custom properties at
the top of `css/style.css`.

## Layout

```
shop/
  data/site.json        brand, contact, hours, ordering rules
  data/products.json    the catalogue — source of truth for prices
  data/catalogue.json   generated; the trimmed copy the cart reads
  index.html            hand-written, with generated regions
  shop.html             catalogue with category band and chips
  menu.html             everything grouped by category
  product/<slug>.html   generated, one per product
  cart.html             cart, customer details, checkout
  css/style.css         all styles
  js/shop.js            nav, cart storage, filtering, product pages
  js/cart.js            cart page: lines, totals, fulfilment, checkout
api/
  create-checkout-session.js   the only server-side code
scripts/
  build-shop.js         generates the pages
  build-preview.js      generates the single-page Artifact preview
  serve-shop.js         local dev server (static + the API)
  test-shop.js          40 checks
```

## Running it locally

```
npm install          # only needed for real Stripe checkout
node scripts/build-shop.js
node scripts/serve-shop.js     # http://localhost:8850
```

Without a `STRIPE_SECRET_KEY` the checkout endpoint runs in **demo mode**: it
validates and prices the cart exactly as it would in production, then redirects
to the success page without taking a payment. The whole flow is testable before
you have a Stripe account.

## Adding a product

1. Add an entry to `shop/data/products.json`.
2. `node scripts/build-shop.js`
3. `node scripts/test-shop.js`
4. Commit the JSON and the generated files.

Prices are **integer cents** (`"priceCents": 2700` is $27.00). Floats here become
rounding errors at checkout, and the test suite rejects them.

`leadDays` drives the earliest pickup date — the cart takes the largest lead time
across the whole order, so adding a cake (3 days) to a croissant order (1 day)
correctly pushes the date out to three days.

Give a product an `options` array to turn it into a build-your-own item; the
detail page renders a select per option group, and each distinct combination
becomes its own cart line.

## Payments — read this before going live

**Card payments cannot run on GitHub Pages.** Taking a payment requires a server
holding a secret key, and Pages only serves static files. The storefront, cart
and catalogue are all static, but `api/create-checkout-session.js` needs a host
that runs server code.

Deploy to either (both have a free tier that covers a small shop):

**Netlify** — `netlify.toml` and the function wrapper are already committed.
Connect the repo, then set `STRIPE_SECRET_KEY` under Site settings → Environment
variables.

**Vercel** — `vercel.json` is committed and `api/` is picked up automatically.
Set `STRIPE_SECRET_KEY` under Project settings → Environment variables.

Also set `SITE_URL` to your public origin so the success and cancel redirects
point at the right place.

### Why the server re-prices the cart

The endpoint looks every line up in `products.json` and uses **its own** price,
ignoring anything the browser sent. It also rejects unknown products, non-integer
or out-of-range quantities, oversized carts, and option values the product does
not offer.

This is not optional. Anyone can edit the request in devtools; if the server
trusted the posted price, a $125 grazing board could be bought for one cent. The
test suite asserts this specifically, by posting a forged price and checking the
server ignores it.

### Going live

1. Swap the test key for a live one.
2. Verify your business in the Stripe dashboard.
3. Test a real card end to end, then refund it.
4. Set up Stripe email receipts, or handle the `checkout.session.completed`
   webhook if you want order emails to yourself.

Order details the payment doesn't cover — pickup date, delivery address, cake
message — are attached to the session as metadata and appear on the payment in
your Stripe dashboard.

## The clickable preview

`shop/preview.html` is a single-page version of the storefront, published as a
Claude Artifact so the shop can be clicked through without deploying:

https://claude.ai/artifact/JdLNUDY345N3bmJyeEhs1P

An Artifact is one page, so the preview collapses the multi-page site into a
single screen with the cart as a slide-over instead of its own route. It is
generated from the same `products.json`, so prices, pack sizes and lead times
can't drift from the real shop.

```
node scripts/build-preview.js
```

Then republish `shop/preview.html` to the URL above. The test suite fails if the
committed preview no longer matches the catalogue, so a price change can't leave
a stale demo quoting the old figure.

Edit `shop/preview.template.html` to change the preview itself — the `__PRODUCTS__`,
`__GROUPS__` and `__RULES__` placeholders are filled at build time.

## Testing

```
node scripts/test-shop.js
```

Starts its own server; no arguments. Covers:

- **Catalogue integrity** — unique slugs, integer cent prices, required fields,
  complete option groups, every product has a page.
- **Build freshness** — reruns the build and fails if committed HTML has drifted
  from `products.json`.
- **Checkout security** — forged prices, unknown products, bad quantities,
  oversized carts, injected option values.
- **Cart flow** — add, merge, quantity steppers, totals, delivery fees and
  thresholds, validation, redirect, cart clearing.
- **Computed visibility** — asserts what actually renders, not just the `hidden`
  property, because a class that sets `display` silently overrides it.
- **No-JS rendering** and an accessibility pass.

Browser checks need Playwright; without it they're skipped and the data and
security checks still run.

## What is deliberately not built

- **Accounts and order history.** Guest checkout only. Stripe holds the record.
- **Live stock levels.** Lead times are used instead, which suits a bakery that
  bakes to order.
- **Product photography.** Cards use a warm gradient and an emoji. Drop real
  photos into `shop/images/` and swap the `.product-thumb` markup in
  `build-shop.js` — the layout already reserves a 4:3 box for them.
