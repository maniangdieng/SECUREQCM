(() => {
  document.addEventListener("submit", (event) => {
    const form = event.target;
    const message = form && form.getAttribute && form.getAttribute("data-confirm");
    if (message && !window.confirm(message)) event.preventDefault();
  });

  document.addEventListener("click", async (event) => {
    const target = event.target instanceof Element ? event.target : null;
    if (!target) return;

    const copyButton = target.closest("[data-copy]");
    if (copyButton) {
      const oldText = copyButton.textContent;
      try {
        await navigator.clipboard.writeText(copyButton.getAttribute("data-copy") || "");
        copyButton.textContent = "Copié";
        setTimeout(() => { copyButton.textContent = oldText; }, 1500);
      } catch (error) {
        copyButton.textContent = "Copier";
      }
      return;
    }

    const opener = target.closest("[data-dialog]");
    if (opener) {
      const dialog = document.getElementById(opener.getAttribute("data-dialog"));
      if (dialog && typeof dialog.showModal === "function") dialog.showModal();
    }

    const closer = target.closest("[data-close]");
    if (closer) {
      const dialog = closer.closest("dialog");
      if (dialog) dialog.close();
    }
  });
})();
