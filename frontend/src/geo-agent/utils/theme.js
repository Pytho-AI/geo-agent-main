/**
 * Theme sync for embedded geo-agent surfaces.
 *
 * The shell (pytho-vite) owns the theme: it puts `dark` or `light` on
 * <html> and every colour is a CSS variable (theme.css mirrors those
 * variables verbatim). An iframe cannot inherit that class, so the host
 * declares the theme on the URL (?theme=dark|light) and posts
 * {type:'geoagent.theme', theme} whenever the analyst toggles. Absent
 * both, follow the OS preference and keep following it.
 */
const apply = (theme) => {
  const root = document.documentElement;
  const next = theme === "light" ? "light" : "dark";
  root.classList.remove("light", "dark");
  root.classList.add(next);
  root.style.colorScheme = next;
};

export function initThemeSync() {
  const param = new URLSearchParams(window.location.search).get("theme");
  if (param === "light" || param === "dark") {
    apply(param);
  } else {
    const mq = window.matchMedia("(prefers-color-scheme: light)");
    apply(mq.matches ? "light" : "dark");
    mq.addEventListener("change", (e) => {
      // Only follow the OS while the host has not declared a theme.
      if (!document.documentElement.dataset.themeFromHost) {
        apply(e.matches ? "light" : "dark");
      }
    });
  }
  window.addEventListener("message", (event) => {
    const data = event.data || {};
    if (data.type === "geoagent.theme" && (data.theme === "light" || data.theme === "dark")) {
      document.documentElement.dataset.themeFromHost = "1";
      apply(data.theme);
    }
  });
}
