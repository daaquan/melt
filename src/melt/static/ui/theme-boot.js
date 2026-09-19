// Loaded synchronously in <head>, ahead of the module, so a pinned dark theme
// paints dark on the first frame instead of flashing light. The WASM client
// owns the setting after that; this only replays it.
(function () {
  try {
    var theme = window.localStorage.getItem("melt.theme");
    if (theme === "light" || theme === "dark") {
      document.documentElement.setAttribute("data-theme", theme);
    }
  } catch (err) {
    /* private mode, or storage disabled: fall back to prefers-color-scheme */
  }
})();
