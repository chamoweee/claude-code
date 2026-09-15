# Sattva Table

A static site for vegetarian recipes made without onion, garlic, leeks, shallots, or chives —
for sattvic, Jain, Swaminarayan, and low-FODMAP kitchens.

No framework, no runtime dependencies. Plain HTML, CSS, and JavaScript, generated from JSON
and served straight from `site/`.

## Layout

```
site/
  data/recipes.json     source of truth for every recipe
  data/pantry.json      source of truth for the pantry guide
  index.html            hand-written, with generated regions
  recipes.html          listing + search/filter UI
  recipes/<slug>.html   generated, one per recipe
  pantry.html           generated from pantry.json
  css/style.css         all styles, including the dark theme
  js/script.js          nav, search, filters, saving, scaler, theme
  js/saved.js           renders the saved-recipes page
  sitemap.xml           generated
scripts/
  build-site.js         generates everything above
  test-site.js          30 checks across data, build, behavior, a11y
```

## Adding a recipe

1. Add an entry to `site/data/recipes.json`.
2. Run `node scripts/build-site.js`.
3. Run `node scripts/test-site.js`.
4. Commit both the JSON and the generated files.

The generated HTML is committed deliberately: GitHub Pages serves `site/` as-is, so the site
keeps working even if the build step is never run in CI.

### Recipe fields

| Field | Notes |
| --- | --- |
| `slug` | lowercase, hyphens only — becomes the URL |
| `category` | one of the ids in `CATEGORIES` in `build-site.js` |
| `gradient` | `[from, to]` hex pair for the card thumbnail |
| `spice` | `mild`, `medium`, or `sweet` — drives the filter chips |
| `prepMin` / `cookMin` | numbers; summed for the displayed total time |
| `ingredients[]` | `{ qty, unit, name }`. Use `qty: null` for "Salt, to taste" |
| `steps[]` | plain strings, one per numbered step |
| `swapNote` | what replaces the onion/garlic in this specific dish |
| `vegan` / `glutenFree` / `jainFriendly` | booleans; drive the badges and diet filters |
| `featured` | shows the recipe on the homepage |

`qty` must be a number so the serving scaler can recompute it. Anything unscalable
(`"Salt, to taste"`) uses `qty: null` and is left alone.

## Editing shared chrome

The header and footer live in `build-site.js`, not in the page files. Pages mark where
generated content goes:

```html
<!-- BUILD:header -->
<!-- /BUILD:header -->
```

Edit the template in `build-site.js`, rebuild, and every page updates. Content between the
markers is overwritten on each build — don't hand-edit it.

## Testing

```
node scripts/test-site.js
```

Runs without arguments and starts its own server. Covers:

- **Data integrity** — unique slugs, required fields, valid quantities, and a guard that no
  allium ever appears in an ingredient (the one thing this site must never get wrong).
- **Build freshness** — reruns the build and fails if the committed HTML doesn't match
  `recipes.json`, so the data and the pages can't drift apart.
- **Behavior** — search, category and diet filters, saving, the serving scaler, dark mode.
- **Structured data** — Recipe and BreadcrumbList JSON-LD match the underlying data.
- **Accessibility** — landmarks, heading order, labels, accessible names, duplicate ids.

Browser checks need Playwright; without it they're skipped and the data checks still run.

## Deploying

`.github/workflows/deploy-recipe-site.yml` runs the tests, then publishes `site/` to GitHub
Pages on every push to `main` that touches `site/` or `scripts/`. Pages must be set to deploy
from **GitHub Actions** in the repository settings.
