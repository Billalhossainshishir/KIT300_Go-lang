"use strict";

// Behaviour for the About and Help pages: content eases in as it scrolls into
// view, the demo figures count up once, the decision path steps through its
// stages, and Help can be searched. Everything degrades to a plain, fully
// visible page without JavaScript or when the reader prefers reduced motion.

function initInfoPage() {
  const reduceMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  initReveal(reduceMotion);
  initCountUp(reduceMotion);
  initPipeline(reduceMotion);
  initHelpSearch();
  initFaqToggle();
}

function initReveal(reduceMotion) {
  const items = [...document.querySelectorAll("[data-reveal]")];
  if (reduceMotion || !("IntersectionObserver" in window)) return;
  document.body.classList.add("reveal-ready");
  const observer = new IntersectionObserver((entries) => {
    entries.forEach((entry) => {
      if (!entry.isIntersecting) return;
      entry.target.classList.add("revealed");
      observer.unobserve(entry.target);
    });
  }, { rootMargin: "0px 0px -8% 0px", threshold: 0.08 });
  // Siblings stagger slightly so a grid arrives as a sequence, not a block.
  items.forEach((item) => {
    const siblings = [...item.parentElement.children].filter((el) => el.hasAttribute("data-reveal"));
    item.style.setProperty("--reveal-delay", `${Math.min(siblings.indexOf(item), 6) * 60}ms`);
    observer.observe(item);
  });
}

function initCountUp(reduceMotion) {
  const figures = [...document.querySelectorAll("[data-count]")];
  if (!figures.length || reduceMotion || !("IntersectionObserver" in window)) return;
  const run = (el) => {
    const target = Number(el.dataset.count);
    const started = performance.now();
    const step = (time) => {
      const progress = Math.min(1, (time - started) / 900);
      const eased = 1 - Math.pow(1 - progress, 3);
      el.textContent = String(Math.round(target * eased));
      if (progress < 1) requestAnimationFrame(step);
    };
    el.textContent = "0";
    requestAnimationFrame(step);
  };
  const observer = new IntersectionObserver((entries) => {
    entries.forEach((entry) => {
      if (!entry.isIntersecting) return;
      run(entry.target);
      observer.unobserve(entry.target);
    });
  }, { threshold: 0.6 });
  figures.forEach((el) => observer.observe(el));
}

function initPipeline(reduceMotion) {
  const pipeline = document.querySelector("[data-pipeline]");
  if (!pipeline) return;
  const stages = [...pipeline.children];
  if (reduceMotion) {
    stages.forEach((stage) => stage.classList.add("done"));
    return;
  }
  let index = 0;
  let timer = null;
  const tick = () => {
    stages.forEach((stage, i) => {
      stage.classList.toggle("active", i === index);
      stage.classList.toggle("done", i < index);
    });
    index = (index + 1) % (stages.length + 2); // a short rest on the finished path
  };
  const start = () => { if (!timer) { tick(); timer = setInterval(tick, 900); } };
  const stop = () => { clearInterval(timer); timer = null; };
  new IntersectionObserver(([entry]) => (entry.isIntersecting ? start() : stop()), { threshold: 0.3 })
    .observe(pipeline);
}

function initHelpSearch() {
  const input = document.getElementById("help-search");
  if (!input) return;
  const items = [...document.querySelectorAll("[data-search-item]")];
  const groups = [...document.querySelectorAll("[data-search-group]")];
  const empty = document.getElementById("help-empty");
  input.addEventListener("input", () => {
    const words = input.value.trim().toLowerCase().split(/\s+/).filter(Boolean);
    let shown = 0;
    items.forEach((item) => {
      const match = words.every((word) => item.textContent.toLowerCase().includes(word));
      item.hidden = !match;
      if (match) shown += 1;
      // Open matching answers so the reader sees why they matched.
      if (item.tagName === "DETAILS") item.open = Boolean(words.length) && match;
    });
    groups.forEach((group) => {
      group.hidden = words.length > 0 && !group.querySelector("[data-search-item]:not([hidden])");
    });
    if (empty) {
      empty.hidden = shown > 0;
      if (!shown) empty.closest("[data-search-group]").hidden = false;
    }
  });
}

function initFaqToggle() {
  const button = document.getElementById("faq-toggle");
  if (!button) return;
  button.addEventListener("click", () => {
    const panels = [...document.querySelectorAll(".faq details:not([hidden])")];
    const openAll = panels.some((panel) => !panel.open);
    panels.forEach((panel) => { panel.open = openAll; });
    button.textContent = openAll ? "Collapse all" : "Expand all";
  });
}
