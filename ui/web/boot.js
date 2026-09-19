// The CSP is `default-src 'self'`, so the module that starts the WASM client
// has to be a file rather than an inline block. init() with no argument reads
// the .wasm next to this module.
import init from "./melt.js";

init().catch((err) => {
  console.error("melt: failed to start the UI", err);
  const slot = document.getElementById("main");
  if (slot) slot.setAttribute("data-boot-error", "1");
});
