// Mobile nav toggle
document.addEventListener("DOMContentLoaded", () => {
  const toggle = document.querySelector(".nav-toggle");
  const links = document.querySelector(".nav-links");
  if (toggle && links) {
    toggle.addEventListener("click", () => {
      const isOpen = links.classList.toggle("open");
      toggle.setAttribute("aria-expanded", isOpen ? "true" : "false");
      toggle.textContent = isOpen ? "✕" : "☰";
    });
  }

  // Recipe filter buttons
  const filterButtons = document.querySelectorAll(".filter-btn");
  const recipeCards = document.querySelectorAll("[data-category]");
  filterButtons.forEach((btn) => {
    btn.addEventListener("click", () => {
      filterButtons.forEach((b) => b.classList.remove("active"));
      btn.classList.add("active");
      const category = btn.dataset.filter;
      recipeCards.forEach((card) => {
        const show = category === "all" || card.dataset.category === category;
        card.style.display = show ? "" : "none";
      });
    });
  });

  // Newsletter form (front-end only demo)
  const newsletterForm = document.querySelector(".newsletter-form");
  if (newsletterForm) {
    newsletterForm.addEventListener("submit", (e) => {
      e.preventDefault();
      const success = newsletterForm.parentElement.querySelector(".form-success");
      if (success) {
        success.classList.add("visible");
        success.textContent = "Thanks! Check your inbox to confirm your subscription.";
      }
      newsletterForm.reset();
    });
  }

  // Contact form (front-end only demo)
  const contactForm = document.querySelector(".contact-form");
  if (contactForm) {
    contactForm.addEventListener("submit", (e) => {
      e.preventDefault();
      const success = document.querySelector(".contact-success");
      if (success) success.classList.add("visible");
      contactForm.reset();
    });
  }
});
