/* Cart page: line rendering, totals, fulfilment rules, checkout handoff. */
(function () {
  "use strict";

  const FH = window.FlourHouse;
  const grid = document.getElementById("cart-lines");
  if (!grid || !FH) return;

  const empty = document.getElementById("cart-empty");
  const layout = document.getElementById("cart-layout");
  const form = document.getElementById("checkout-form");
  const checkoutBtn = document.getElementById("checkout-btn");

  let catalogue = {};
  let config = null;

  const money = FH.money;
  const esc = (s) => {
    const d = document.createElement("div");
    d.textContent = s;
    return d.innerHTML;
  };

  /* ---------- totals ---------- */

  function fulfilment() {
    const checked = document.querySelector('input[name="fulfilment"]:checked');
    return checked ? checked.value : "pickup";
  }

  function computeTotals(lines) {
    const subtotalCents = lines.reduce((sum, l) => {
      const p = catalogue[l.slug];
      return sum + (p ? p.priceCents * l.qty : 0);
    }, 0);

    let deliveryCents = 0;
    if (fulfilment() === "delivery" && subtotalCents > 0) {
      deliveryCents =
        subtotalCents >= config.freeDeliveryOverCents ? 0 : config.deliveryFeeCents;
    }

    return { subtotalCents, deliveryCents, totalCents: subtotalCents + deliveryCents };
  }

  /* The earliest date we can fulfil: the longest lead time in the cart. */
  function earliestDate(lines) {
    const maxLead = lines.reduce((max, l) => {
      const p = catalogue[l.slug];
      return p ? Math.max(max, p.leadDays || 1) : max;
    }, 1);
    const d = new Date();
    d.setDate(d.getDate() + maxLead);
    return d.toISOString().slice(0, 10);
  }

  /* ---------- rendering ---------- */

  function render() {
    const lines = FH.readCart().filter((l) => catalogue[l.slug]);

    if (!lines.length) {
      grid.innerHTML = "";
      if (layout) layout.hidden = true;
      if (empty) empty.hidden = false;
      return;
    }

    if (layout) layout.hidden = false;
    if (empty) empty.hidden = true;

    grid.innerHTML = lines
      .map((l, i) => {
        const p = catalogue[l.slug];
        const opts = l.options
          ? Object.entries(l.options)
              .map(([k, v]) => `${esc(k)}: ${esc(v)}`)
              .join(" · ")
          : "";
        return `<article class="cart-line" data-index="${i}">
          <div class="cart-line-thumb" style="background:linear-gradient(155deg,${esc(
            p.gradient[0]
          )},${esc(p.gradient[1])});" aria-hidden="true">${p.emoji}</div>
          <div>
            <h3><a href="product/${esc(p.slug)}.html">${esc(p.name)}</a></h3>
            ${opts ? `<p class="cart-line-opts">${opts}</p>` : ""}
            <p class="cart-line-opts">${money(p.priceCents)} · ${p.packSize} ${esc(p.packLabel)}</p>
            <div class="qty-stepper">
              <button type="button" data-line-qty="down" data-index="${i}" aria-label="Decrease quantity of ${esc(
          p.name
        )}">−</button>
              <label class="visually-hidden" for="line-qty-${i}">Quantity of ${esc(p.name)}</label>
              <input type="number" id="line-qty-${i}" value="${l.qty}" min="1" max="99" data-line-input data-index="${i}" />
              <button type="button" data-line-qty="up" data-index="${i}" aria-label="Increase quantity of ${esc(
          p.name
        )}">+</button>
            </div>
          </div>
          <div class="cart-line-right">
            <span class="cart-line-price">${money(p.priceCents * l.qty)}</span>
            <button type="button" class="remove-btn" data-remove="${i}">Remove</button>
          </div>
        </article>`;
      })
      .join("");

    paintTotals(lines);
    paintDateLimits(lines);
  }

  function paintTotals(lines) {
    const t = computeTotals(lines);
    const set = (id, value) => {
      const el = document.getElementById(id);
      if (el) el.textContent = value;
    };
    set("subtotal", money(t.subtotalCents));
    set("total", money(t.totalCents));

    const deliveryRow = document.getElementById("delivery-row");
    const deliveryEl = document.getElementById("delivery");
    if (deliveryRow && deliveryEl) {
      const isDelivery = fulfilment() === "delivery";
      deliveryRow.hidden = !isDelivery;
      deliveryEl.textContent = t.deliveryCents === 0 ? "Free" : money(t.deliveryCents);
    }

    const note = document.getElementById("fulfilment-note");
    if (note) {
      note.textContent =
        fulfilment() === "delivery" ? config.deliveryNote : config.pickupNote;
    }

    const addrField = document.getElementById("address-field");
    if (addrField) {
      const isDelivery = fulfilment() === "delivery";
      addrField.hidden = !isDelivery;
      const input = addrField.querySelector("input");
      if (input) input.required = isDelivery;
    }
  }

  function paintDateLimits(lines) {
    const dateInput = document.getElementById("when");
    if (!dateInput) return;
    const min = earliestDate(lines);
    dateInput.min = min;
    if (!dateInput.value || dateInput.value < min) dateInput.value = min;
    const hint = document.getElementById("date-hint");
    if (hint) {
      const d = new Date(min + "T00:00:00");
      hint.textContent =
        "Earliest available: " +
        d.toLocaleDateString("en-AU", { weekday: "long", day: "numeric", month: "long" });
    }
  }

  /* ---------- interactions ---------- */

  function mutate(index, fn) {
    const lines = FH.readCart();
    if (!lines[index]) return;
    fn(lines, index);
    FH.writeCart(lines.filter((l) => l.qty > 0));
  }

  grid.addEventListener("click", (e) => {
    const step = e.target.closest("[data-line-qty]");
    if (step) {
      const i = Number(step.dataset.index);
      const delta = step.dataset.lineQty === "up" ? 1 : -1;
      mutate(i, (lines) => {
        lines[i].qty = Math.max(0, Math.min(99, lines[i].qty + delta));
      });
      return;
    }

    const remove = e.target.closest("[data-remove]");
    if (remove) {
      const i = Number(remove.dataset.remove);
      mutate(i, (lines) => lines.splice(i, 1));
      FH.toast("Removed from cart");
    }
  });

  grid.addEventListener("change", (e) => {
    const input = e.target.closest("[data-line-input]");
    if (!input) return;
    const i = Number(input.dataset.index);
    const next = Math.max(1, Math.min(99, parseInt(input.value, 10) || 1));
    mutate(i, (lines) => {
      lines[i].qty = next;
    });
  });

  document.querySelectorAll('input[name="fulfilment"]').forEach((radio) =>
    radio.addEventListener("change", () => paintTotals(FH.readCart().filter((l) => catalogue[l.slug])))
  );

  document.addEventListener("fh:cart-changed", render);

  /* ---------- checkout ---------- */

  function validate() {
    let ok = true;
    form.querySelectorAll(".form-field").forEach((field) => {
      if (field.hidden) {
        field.classList.remove("invalid");
        return;
      }
      const control = field.querySelector("input, select, textarea");
      if (!control) return;
      const bad = control.required && !control.value.trim();
      const badEmail =
        control.type === "email" && control.value && !/^[^@\s]+@[^@\s]+\.[^@\s]+$/.test(control.value);
      field.classList.toggle("invalid", bad || badEmail);
      if (bad || badEmail) ok = false;
    });
    return ok;
  }

  if (form) {
    form.addEventListener("submit", async (e) => {
      e.preventDefault();
      if (!validate()) {
        form.querySelector(".form-field.invalid input, .form-field.invalid select")?.focus();
        return;
      }

      const lines = FH.readCart().filter((l) => catalogue[l.slug]);
      if (!lines.length) return;

      const data = Object.fromEntries(new FormData(form).entries());
      const payload = {
        items: lines.map((l) => ({ slug: l.slug, qty: l.qty, options: l.options })),
        fulfilment: fulfilment(),
        customer: {
          name: data.name,
          email: data.email,
          phone: data.phone,
          address: data.address || "",
        },
        when: data.when,
        notes: data.notes || "",
      };

      checkoutBtn.disabled = true;
      checkoutBtn.textContent = "Starting secure checkout…";

      try {
        const res = await fetch("/api/create-checkout-session", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(payload),
        });

        if (!res.ok) throw new Error("Checkout unavailable (" + res.status + ")");
        const body = await res.json();
        if (!body.url) throw new Error("No checkout URL returned");
        window.location.href = body.url;
      } catch (err) {
        checkoutBtn.disabled = false;
        checkoutBtn.textContent = "Proceed to payment";
        const box = document.getElementById("checkout-error");
        if (box) {
          box.hidden = false;
          box.textContent =
            "We couldn't start the payment session. " +
            err.message +
            ". Your cart is saved — please try again, or call us on " +
            (config.phone || "the shop") +
            " to order.";
        }
      }
    });
  }

  /* ---------- boot ---------- */

  Promise.all([
    fetch("data/catalogue.json").then((r) => r.json()),
    fetch("data/site.json").then((r) => r.json()),
  ])
    .then(([items, siteData]) => {
      items.forEach((p) => (catalogue[p.slug] = p));
      config = Object.assign({}, siteData.ordering, { phone: siteData.contact.phone });
      render();
    })
    .catch(() => {
      if (empty) {
        empty.hidden = false;
        empty.querySelector("h1").textContent = "Couldn't load your cart";
        empty.querySelector("p").textContent =
          "Something went wrong reading the product list. Please reload the page.";
      }
    });
})();
