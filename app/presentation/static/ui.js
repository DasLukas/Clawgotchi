(() => {
  const COPIED_LABEL = "Copied";
  const DEFAULT_LABEL = "Copy";

  async function copyText(value) {
    if (navigator.clipboard && typeof navigator.clipboard.writeText === "function") {
      await navigator.clipboard.writeText(value);
      return;
    }

    const helper = document.createElement("textarea");
    helper.value = value;
    helper.setAttribute("readonly", "readonly");
    helper.style.position = "absolute";
    helper.style.left = "-9999px";
    document.body.appendChild(helper);
    helper.select();
    document.execCommand("copy");
    document.body.removeChild(helper);
  }

  function resolveCopyText(button) {
    const root = button.closest("[data-copy-root]");
    if (!root) {
      return "";
    }

    const source = root.querySelector("[data-copy-source]");
    if (!source) {
      return "";
    }

    return source.textContent.trimEnd();
  }

  async function handleCopyClick(button) {
    const value = resolveCopyText(button);
    if (!value) {
      return;
    }

    const originalLabel = button.dataset.copyLabel || button.textContent || DEFAULT_LABEL;

    try {
      await copyText(value);
      button.dataset.copyLabel = originalLabel;
      button.textContent = COPIED_LABEL;
      button.classList.add("copy-success");
      window.setTimeout(() => {
        button.textContent = originalLabel;
        button.classList.remove("copy-success");
      }, 1400);
    } catch (_error) {
      button.textContent = "Error";
      window.setTimeout(() => {
        button.textContent = originalLabel;
      }, 1400);
    }
  }

  document.addEventListener("click", (event) => {
    const target = event.target;
    if (!(target instanceof HTMLElement)) {
      return;
    }

    const button = target.closest(".js-copy-button");
    if (!(button instanceof HTMLButtonElement)) {
      return;
    }

    event.preventDefault();
    void handleCopyClick(button);
  });
})();
