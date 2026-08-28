// Loaded from /static because the `default-src 'self'` CSP blocks an inline
// <script> block. Localized strings arrive on data- attributes, which keeps
// template text out of JS source and out of the escaping rules that go with it.
(function () {
  "use strict";

  var copyBtn = document.getElementById("copy-btn");

  if (copyBtn) {
    copyBtn.addEventListener("click", async function () {
      var sourceId = copyBtn.dataset.source;
      try {
        var res = await fetch("/v1/sources/" + encodeURIComponent(sourceId));
        var data = await res.json();
        await navigator.clipboard.writeText(data.raw_body || "");
        await fetch("/v1/sources/" + encodeURIComponent(sourceId) + "/reuse", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ kind: "copy_source" }),
        });
        copyBtn.textContent = copyBtn.dataset.copiedLabel;
      } catch (err) {
        copyBtn.textContent = copyBtn.dataset.failedLabel;
      }
    });
  }

  // Any form carrying data-confirm asks before it submits.
  document.querySelectorAll("form[data-confirm]").forEach(function (form) {
    form.addEventListener("submit", function (event) {
      if (!window.confirm(form.dataset.confirm)) {
        event.preventDefault();
      }
    });
  });

  document.addEventListener("keydown", function (event) {
    if (event.target.tagName === "INPUT") return;
    if (event.key === "c" && copyBtn) copyBtn.click();
  });
})();
