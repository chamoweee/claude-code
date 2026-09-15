/* Renders the saved-recipes page from localStorage + the recipe dataset. */
(function () {
  "use strict";

  const grid = document.getElementById("saved-grid");
  const empty = document.getElementById("saved-empty");
  if (!grid) return;

  function dietBadges(r) {
    let html = "";
    if (r.vegan) html += '<span class="diet-badge" title="Vegan">Vegan</span>';
    if (r.glutenFree) html += '<span class="diet-badge" title="Gluten free">GF</span>';
    if (r.jainFriendly) html += '<span class="diet-badge" title="Jain-friendly">Jain</span>';
    return html;
  }

  function escapeHtml(s) {
    const div = document.createElement("div");
    div.textContent = s;
    return div.innerHTML;
  }

  function cardHtml(r) {
    return `<article class="recipe-card reveal in-view" data-slug="${escapeHtml(r.slug)}">
      <a class="recipe-card-link" href="recipes/${escapeHtml(r.slug)}.html">
        <div class="recipe-thumb" style="background:linear-gradient(160deg,${escapeHtml(
          r.gradient[0]
        )},${escapeHtml(r.gradient[1])});"><span>${r.emoji}</span></div>
      </a>
      <div class="recipe-body">
        <div class="recipe-tags">
          <span class="tag">${escapeHtml(r.categoryLabel)}</span>
          <span class="tag spice">${escapeHtml(r.spice)}</span>
        </div>
        <h3><a href="recipes/${escapeHtml(r.slug)}.html">${escapeHtml(r.title)}</a></h3>
        <div class="recipe-meta"><span>⏱ ${r.prepMin + r.cookMin} min</span><span>🍽 Serves ${
      r.serves
    }</span></div>
        <p>${escapeHtml(r.description)}</p>
        <div class="recipe-foot">
          <div class="diet-badges">${dietBadges(r)}</div>
          <button class="save-btn saved" data-slug="${escapeHtml(r.slug)}" aria-pressed="true" aria-label="Remove ${escapeHtml(
      r.title
    )} from saved"><span class="save-icon" aria-hidden="true">♥</span></button>
        </div>
      </div>
    </article>`;
  }

  function render(recipes) {
    const saved = window.SattvaTable.readSaved();
    const bySlug = {};
    recipes.forEach((r) => (bySlug[r.slug] = r));

    const found = saved.map((slug) => bySlug[slug]).filter(Boolean);

    grid.innerHTML = found.map(cardHtml).join("");
    grid.hidden = found.length === 0;
    if (empty) empty.hidden = found.length !== 0;
  }

  fetch("data/recipes.json")
    .then((res) => res.json())
    .then((recipes) => {
      render(recipes);
      document.addEventListener("st:saved-changed", () => render(recipes));
    })
    .catch(() => {
      if (empty) {
        empty.hidden = false;
        empty.querySelector("h2").textContent = "Couldn't load your saved recipes";
        empty.querySelector("p").textContent =
          "Something went wrong reading the recipe list. Try reloading the page.";
      }
    });
})();
