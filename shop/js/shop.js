/* The Flour House — storefront behaviour (nav, cart, product pages) */
(function () {
  "use strict";

  const CART_KEY = "fh-cart";

  /* ---------------- storage ---------------- */

  function readCart() {
    try {
      const raw = localStorage.getItem(CART_KEY);
      const parsed = raw ? JSON.parse(raw) : [];
      if (!Array.isArray(parsed)) return [];
      // Drop anything malformed rather than rendering NaN prices later.
      return parsed.filter(
        (l) => l && typeof l.slug === "string" && Number.isFinite(l.qty) && l.qty > 0
      );
    } catch (e) {
      return [];
    }
  }

  function writeCart(lines) {
    try {
      localStorage.setItem(CART_KEY, JSON.stringify(lines));
    } catch (e) {
      /* private browsing — cart just won't persist */
    }
    paintCount();
    document.dispatchEvent(new CustomEvent("fh:cart-changed"));
  }

  function cartQty() {
    return readCart().reduce((n, l) => n + l.qty, 0);
  }

  /* A line is identified by slug + chosen options, so a vanilla cake and a
     chocolate one are separate lines rather than merging into one. */
  function lineKey(slug, options) {
    const opts = options && Object.keys(options).length ? JSON.stringify(options) : "";
    return slug + "|" + opts;
  }

  function addToCart(slug, qty, options) {
    const lines = readCart();
    const key = lineKey(slug, options);
    const existing = lines.find((l) => lineKey(l.slug, l.options) === key);
    if (existing) {
      existing.qty = Math.min(99, existing.qty + qty);
    } else {
      lines.push({ slug: slug, qty: Math.min(99, qty), options: options || null });
    }
    writeCart(lines);
  }

  function money(cents) {
    return "$" + (cents / 100).toFixed(2);
  }

  /* ---------------- header ---------------- */

  function paintCount() {
    const n = cartQty();
    document.querySelectorAll("[data-cart-count]").forEach((el) => {
      el.textContent = String(n);
      el.hidden = n === 0;
      if (n > 0) {
        el.classList.remove("bump");
        void el.offsetWidth;
        el.classList.add("bump");
      }
    });
  }

  function initNav() {
    const toggle = document.querySelector(".nav-toggle");
    const panel = document.getElementById("nav-panel");
    const scrim = document.querySelector(".nav-scrim");
    if (!toggle || !panel) return;

    function setOpen(open) {
      panel.classList.toggle("open", open);
      toggle.setAttribute("aria-expanded", String(open));
      toggle.setAttribute("aria-label", open ? "Close menu" : "Open menu");
      if (scrim) {
        scrim.hidden = !open;
        scrim.classList.toggle("visible", open);
      }
    }

    toggle.addEventListener("click", () => setOpen(!panel.classList.contains("open")));
    if (scrim) scrim.addEventListener("click", () => setOpen(false));
    document.addEventListener("keydown", (e) => {
      if (e.key === "Escape" && panel.classList.contains("open")) {
        setOpen(false);
        toggle.focus();
      }
    });
  }

  /* ---------------- toast ---------------- */

  let toastTimer;
  function toast(message) {
    const el = document.querySelector(".toast");
    if (!el) return;
    el.textContent = message;
    el.classList.add("visible");
    clearTimeout(toastTimer);
    toastTimer = setTimeout(() => el.classList.remove("visible"), 2600);
  }

  /* ---------------- add to cart ---------------- */

  function initAddButtons() {
    document.addEventListener("click", (e) => {
      const btn = e.target.closest("[data-add]");
      if (!btn) return;
      e.preventDefault();

      const slug = btn.dataset.add;
      let qty = 1;
      let options = null;

      // On a detail page, read the quantity stepper and any option selects.
      if (btn.hasAttribute("data-from-detail")) {
        const qtyInput = document.getElementById("qty");
        qty = Math.max(1, Math.min(99, parseInt(qtyInput && qtyInput.value, 10) || 1));
        const selects = document.querySelectorAll("[data-option]");
        if (selects.length) {
          options = {};
          selects.forEach((s) => (options[s.dataset.option] = s.value));
        }
      }

      addToCart(slug, qty, options);
      toast(qty > 1 ? `${qty} added to cart` : "Added to cart");
    });
  }

  function initQtyStepper() {
    const input = document.getElementById("qty");
    if (!input) return;
    document.querySelectorAll("[data-qty]").forEach((btn) =>
      btn.addEventListener("click", () => {
        const delta = btn.dataset.qty === "up" ? 1 : -1;
        const next = Math.max(1, Math.min(99, (parseInt(input.value, 10) || 1) + delta));
        input.value = String(next);
      })
    );
    input.addEventListener("change", () => {
      input.value = String(Math.max(1, Math.min(99, parseInt(input.value, 10) || 1)));
    });
  }

  /* ---------------- gallery ---------------- */

  function initGallery() {
    const main = document.querySelector(".gallery-main");
    const thumbs = document.querySelectorAll(".gallery-thumb");
    if (!main || !thumbs.length) return;

    thumbs.forEach((thumb) =>
      thumb.addEventListener("click", () => {
        thumbs.forEach((t) => t.classList.remove("active"));
        thumb.classList.add("active");
        main.style.background = thumb.style.background;
      })
    );

    const zoom = document.querySelector(".gallery-zoom");
    if (zoom) {
      zoom.addEventListener("click", () => {
        main.classList.toggle("zoomed");
        main.style.fontSize = main.classList.contains("zoomed") ? "11rem" : "";
      });
    }
  }

  /* ---------------- shop filtering ---------------- */

  function initFilters() {
    const cards = Array.from(document.querySelectorAll(".product-card[data-category]"));
    const chips = Array.from(document.querySelectorAll(".chip"));
    const groupLinks = Array.from(document.querySelectorAll(".group-link"));
    const countEl = document.querySelector("[data-result-count]");
    const empty = document.querySelector(".empty-state");
    if (!cards.length || !chips.length) return;

    let category = "all";
    let group = "all";

    function apply() {
      let visible = 0;
      cards.forEach((c) => {
        const okCat = category === "all" || c.dataset.category === category;
        const okGroup = group === "all" || c.dataset.group === group;
        const show = okCat && okGroup;
        c.hidden = !show;
        if (show) visible++;
      });
      if (countEl) {
        countEl.textContent = String(visible);
        countEl.parentElement.lastChild.textContent = visible === 1 ? " product" : " products";
      }
      if (empty) empty.hidden = visible !== 0;
    }

    chips.forEach((chip) =>
      chip.addEventListener("click", () => {
        category = chip.dataset.chip;
        chips.forEach((c) => {
          const on = c === chip;
          c.classList.toggle("active", on);
          c.setAttribute("aria-pressed", String(on));
        });
        apply();
      })
    );

    groupLinks.forEach((link) =>
      link.addEventListener("click", (e) => {
        e.preventDefault();
        const id = link.dataset.group;
        group = group === id ? "all" : id;
        groupLinks.forEach((l) => l.classList.toggle("active", l.dataset.group === group));
        apply();
      })
    );

    // shop.html#danish-pastries or #catering both deep-link correctly
    const hash = decodeURIComponent(window.location.hash.replace("#", ""));
    if (hash) {
      const chip = chips.find((c) => c.dataset.chip === hash);
      const grp = groupLinks.find((l) => l.dataset.group === hash);
      if (chip) chip.click();
      else if (grp) grp.click();
    }

    apply();
  }

  /* ---------------- reveal + back to top ---------------- */

  function initReveal() {
    const els = document.querySelectorAll(".reveal");
    if (!els.length) return;
    if (!("IntersectionObserver" in window)) {
      els.forEach((el) => el.classList.add("in-view"));
      return;
    }
    const obs = new IntersectionObserver(
      (entries) => {
        entries.forEach((en) => {
          if (en.isIntersecting) {
            en.target.classList.add("in-view");
            obs.unobserve(en.target);
          }
        });
      },
      { threshold: 0.1, rootMargin: "0px 0px -6% 0px" }
    );
    els.forEach((el) => obs.observe(el));
  }

  function initBackToTop() {
    const btn = document.querySelector(".back-to-top");
    if (!btn) return;
    window.addEventListener("scroll", () => btn.classList.toggle("visible", window.scrollY > 500), {
      passive: true,
    });
    btn.addEventListener("click", () => window.scrollTo({ top: 0, behavior: "smooth" }));
  }

  /* ---------------- boot ---------------- */

  document.addEventListener("DOMContentLoaded", () => {
    initNav();
    paintCount();
    initAddButtons();
    initQtyStepper();
    initGallery();
    initFilters();
    initReveal();
    initBackToTop();
  });

  window.FlourHouse = { readCart, writeCart, addToCart, lineKey, money, toast, paintCount };
})();
