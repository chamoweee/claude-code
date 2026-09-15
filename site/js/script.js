/* Sattva Table — site behavior */
(function () {
  "use strict";

  const SAVED_KEY = "st-saved";
  const THEME_KEY = "st-theme";

  /* ---------- storage helpers (degrade quietly if blocked) ---------- */

  function readSaved() {
    try {
      const raw = localStorage.getItem(SAVED_KEY);
      const parsed = raw ? JSON.parse(raw) : [];
      return Array.isArray(parsed) ? parsed : [];
    } catch (e) {
      return [];
    }
  }

  function writeSaved(list) {
    try {
      localStorage.setItem(SAVED_KEY, JSON.stringify(list));
    } catch (e) {
      /* private mode — saving just won't persist */
    }
  }

  /* ---------- quantity formatting for the serving scaler ---------- */

  const FRACTIONS = [
    [0.125, "⅛"],
    [0.25, "¼"],
    [0.333, "⅓"],
    [0.375, "⅜"],
    [0.5, "½"],
    [0.625, "⅝"],
    [0.667, "⅔"],
    [0.75, "¾"],
    [0.875, "⅞"],
  ];

  function formatQty(qty) {
    if (!isFinite(qty) || qty <= 0) return "";
    const whole = Math.floor(qty);
    const frac = qty - whole;
    let best = null;
    let bestDiff = 0.06;
    for (const [value, glyph] of FRACTIONS) {
      const diff = Math.abs(frac - value);
      if (diff < bestDiff) {
        bestDiff = diff;
        best = glyph;
      }
    }
    if (frac < 0.06) return String(whole);
    if (best) return whole === 0 ? best : whole + best;
    return String(Math.round(qty * 100) / 100);
  }

  /* ---------- theme ---------- */

  function initTheme() {
    const toggles = document.querySelectorAll(".theme-toggle");
    if (!toggles.length) return;

    const sync = () => {
      const isDark = document.documentElement.dataset.theme === "dark";
      toggles.forEach((btn) => {
        btn.setAttribute("aria-label", isDark ? "Switch to light theme" : "Switch to dark theme");
        const icon = btn.querySelector(".theme-icon");
        if (icon) icon.textContent = isDark ? "☀" : "☾";
      });
    };

    toggles.forEach((btn) =>
      btn.addEventListener("click", () => {
        const isDark = document.documentElement.dataset.theme === "dark";
        if (isDark) {
          delete document.documentElement.dataset.theme;
        } else {
          document.documentElement.dataset.theme = "dark";
        }
        try {
          localStorage.setItem(THEME_KEY, isDark ? "light" : "dark");
        } catch (e) {}
        sync();
      })
    );

    sync();
  }

  /* ---------- mobile navigation ---------- */

  function initNav() {
    const toggle = document.querySelector(".nav-toggle");
    const links = document.querySelector(".nav-links");
    if (!toggle || !links) return;

    toggle.addEventListener("click", () => {
      const isOpen = links.classList.toggle("open");
      toggle.setAttribute("aria-expanded", String(isOpen));
      toggle.setAttribute("aria-label", isOpen ? "Close menu" : "Open menu");
      toggle.textContent = isOpen ? "✕" : "☰";
    });

    document.addEventListener("keydown", (e) => {
      if (e.key === "Escape" && links.classList.contains("open")) {
        toggle.click();
        toggle.focus();
      }
    });
  }

  /* ---------- scroll reveal ---------- */

  function initReveal() {
    const els = document.querySelectorAll(".reveal");
    if (!els.length) return;

    if (!("IntersectionObserver" in window)) {
      els.forEach((el) => el.classList.add("in-view"));
      return;
    }

    const observer = new IntersectionObserver(
      (entries) => {
        entries.forEach((entry) => {
          if (entry.isIntersecting) {
            entry.target.classList.add("in-view");
            observer.unobserve(entry.target);
          }
        });
      },
      { threshold: 0.1, rootMargin: "0px 0px -8% 0px" }
    );

    els.forEach((el) => observer.observe(el));
  }

  /* ---------- back to top ---------- */

  function initBackToTop() {
    const btn = document.querySelector(".back-to-top");
    if (!btn) return;

    window.addEventListener(
      "scroll",
      () => btn.classList.toggle("visible", window.scrollY > 500),
      { passive: true }
    );
    btn.addEventListener("click", () => window.scrollTo({ top: 0, behavior: "smooth" }));
  }

  /* ---------- saved recipes ---------- */

  function initSaveButtons() {
    // No early return on an empty page: saved.html renders its cards after a fetch,
    // so the delegated listener has to exist before they arrive.
    const paint = () => {
      const saved = readSaved();
      document.querySelectorAll(".save-btn").forEach((btn) => {
        const isSaved = saved.indexOf(btn.dataset.slug) !== -1;
        btn.classList.toggle("saved", isSaved);
        btn.setAttribute("aria-pressed", String(isSaved));
        const label = btn.querySelector(".save-label");
        if (label) label.textContent = isSaved ? "Saved" : "Save recipe";
      });
    };

    document.addEventListener("click", (e) => {
      const btn = e.target.closest(".save-btn");
      if (!btn) return;
      e.preventDefault();

      const slug = btn.dataset.slug;
      const saved = readSaved();
      const idx = saved.indexOf(slug);
      if (idx === -1) {
        saved.push(slug);
        btn.classList.add("pop");
        setTimeout(() => btn.classList.remove("pop"), 320);
      } else {
        saved.splice(idx, 1);
      }
      writeSaved(saved);
      paint();
      document.dispatchEvent(new CustomEvent("st:saved-changed"));
    });

    paint();
  }

  /* ---------- recipe search + filtering ---------- */

  function initFilters() {
    const grid = document.getElementById("recipe-grid");
    if (!grid) return;

    const cards = Array.from(grid.querySelectorAll(".recipe-card"));
    const searchInput = document.getElementById("recipe-search");
    const searchClear = document.querySelector(".search-clear");
    const categoryButtons = Array.from(document.querySelectorAll(".filter-btn"));
    const dietBoxes = Array.from(document.querySelectorAll("[data-diet]"));
    const spiceBoxes = Array.from(document.querySelectorAll("[data-spice]"));
    const timeInput = document.getElementById("time-filter");
    const timeOutput = document.getElementById("time-output");
    const countEl = document.querySelector("[data-result-count]");
    const emptyState = document.querySelector(".empty-state");

    let category = "all";

    function apply() {
      const query = searchInput ? searchInput.value.trim().toLowerCase() : "";
      const diets = dietBoxes.filter((b) => b.checked).map((b) => b.dataset.diet);
      const spices = spiceBoxes.filter((b) => b.checked).map((b) => b.dataset.spice);
      const maxTime = timeInput ? Number(timeInput.value) : Infinity;
      const timeIsCapped = timeInput && maxTime < Number(timeInput.max);

      let visible = 0;

      cards.forEach((card) => {
        const matchesCategory = category === "all" || card.dataset.category === category;
        const matchesQuery = !query || card.dataset.search.indexOf(query) !== -1;
        const matchesSpice = !spices.length || spices.indexOf(card.dataset.spice) !== -1;
        const matchesTime = !timeIsCapped || Number(card.dataset.time) <= maxTime;
        const matchesDiet = diets.every((d) => {
          if (d === "vegan") return card.dataset.vegan === "true";
          if (d === "gf") return card.dataset.gf === "true";
          if (d === "jain") return card.dataset.jain === "true";
          return true;
        });

        const show = matchesCategory && matchesQuery && matchesSpice && matchesTime && matchesDiet;
        card.hidden = !show;
        if (show) visible++;
      });

      if (countEl) {
        countEl.textContent = String(visible);
        countEl.parentElement.lastChild.textContent = visible === 1 ? " recipe" : " recipes";
      }
      if (emptyState) emptyState.hidden = visible !== 0;
      if (searchClear) searchClear.hidden = !query;
    }

    categoryButtons.forEach((btn) =>
      btn.addEventListener("click", () => {
        category = btn.dataset.filter;
        categoryButtons.forEach((b) => {
          const active = b === btn;
          b.classList.toggle("active", active);
          b.setAttribute("aria-pressed", String(active));
        });
        apply();
      })
    );

    if (searchInput) {
      let debounce;
      searchInput.addEventListener("input", () => {
        clearTimeout(debounce);
        debounce = setTimeout(apply, 120);
      });
    }

    if (searchClear) {
      searchClear.addEventListener("click", () => {
        searchInput.value = "";
        searchInput.focus();
        apply();
      });
    }

    // "/" focuses search, Escape clears it — but never while the user is typing elsewhere.
    if (searchInput) {
      document.addEventListener("keydown", (e) => {
        const typing = /^(INPUT|TEXTAREA|SELECT)$/.test(document.activeElement.tagName);
        if (e.key === "/" && !typing && !e.metaKey && !e.ctrlKey) {
          e.preventDefault();
          searchInput.focus();
          searchInput.select();
        } else if (e.key === "Escape" && document.activeElement === searchInput) {
          searchInput.value = "";
          apply();
        }
      });
    }

    dietBoxes.concat(spiceBoxes).forEach((box) => box.addEventListener("change", apply));

    if (timeInput) {
      timeInput.addEventListener("input", () => {
        const max = Number(timeInput.max);
        if (timeOutput) {
          timeOutput.textContent = Number(timeInput.value) >= max ? "any" : timeInput.value + " min";
        }
        apply();
      });
    }

    document.querySelectorAll(".reset-filters").forEach((btn) =>
      btn.addEventListener("click", () => {
        category = "all";
        categoryButtons.forEach((b) => {
          const active = b.dataset.filter === "all";
          b.classList.toggle("active", active);
          b.setAttribute("aria-pressed", String(active));
        });
        if (searchInput) searchInput.value = "";
        dietBoxes.concat(spiceBoxes).forEach((b) => (b.checked = false));
        if (timeInput) {
          timeInput.value = timeInput.max;
          if (timeOutput) timeOutput.textContent = "any";
        }
        apply();
      })
    );

    // Deep link: recipes.html#curry opens that category
    const hash = window.location.hash.replace("#", "");
    if (hash) {
      const match = categoryButtons.find((b) => b.dataset.filter === hash);
      if (match) match.click();
    }

    apply();
  }

  /* ---------- serving scaler ---------- */

  function initScaler() {
    const list = document.querySelector(".ingredient-list");
    if (!list) return;

    const base = Number(list.dataset.baseServes) || 1;
    const displays = document.querySelectorAll("[data-serving-display]");
    let servings = base;

    function render() {
      const ratio = servings / base;
      list.querySelectorAll(".ing-text[data-qty]").forEach((span) => {
        const qty = parseFloat(span.dataset.qty);
        if (!isFinite(qty)) return;
        const scaled = formatQty(qty * ratio);
        span.textContent = [scaled, span.dataset.unit, span.dataset.name].filter(Boolean).join(" ");
      });
      displays.forEach((el) => (el.textContent = String(servings)));
      list.classList.toggle("scaled", servings !== base);
    }

    document.querySelectorAll(".scale-btn").forEach((btn) =>
      btn.addEventListener("click", () => {
        const delta = btn.dataset.scale === "up" ? 1 : -1;
        servings = Math.min(24, Math.max(1, servings + delta));
        render();
      })
    );

    render();
  }

  /* ---------- print ---------- */

  function initPrint() {
    document.querySelectorAll(".print-btn").forEach((btn) =>
      btn.addEventListener("click", () => window.print())
    );
  }

  /* ---------- demo forms (no backend) ---------- */

  function initForms() {
    const newsletter = document.querySelector(".newsletter-form");
    if (newsletter) {
      newsletter.addEventListener("submit", (e) => {
        e.preventDefault();
        const success = newsletter.parentElement.querySelector(".form-success");
        if (success) success.classList.add("visible");
        newsletter.reset();
      });
    }

    const contact = document.querySelector(".contact-form");
    if (contact) {
      contact.addEventListener("submit", (e) => {
        e.preventDefault();
        const success = document.querySelector(".contact-success");
        if (success) success.classList.add("visible");
        contact.reset();
      });
    }
  }

  /* ---------- boot ---------- */

  document.addEventListener("DOMContentLoaded", () => {
    initTheme();
    initNav();
    initReveal();
    initBackToTop();
    initSaveButtons();
    initFilters();
    initScaler();
    initPrint();
    initForms();
  });

  window.SattvaTable = { readSaved, writeSaved, formatQty };
})();
