// Petits comportements partagés (aucune dépendance externe).
(() => {
  // Confirmation avant envoi : <form data-confirm="Message ?">
  document.addEventListener("submit", (event) => {
    const form = event.target;
    const message = form.getAttribute && form.getAttribute("data-confirm");
    if (message && !window.confirm(message)) event.preventDefault();
  });

  // Copier un code : <button data-copy="ABC123">
  document.addEventListener("click", async (event) => {
    const button = event.target.closest("[data-copy]");
    if (!button) return;
    try {
      await navigator.clipboard.writeText(button.dataset.copy);
      const old = button.textContent;
      button.textContent = "Copié ✓";
      setTimeout(() => { button.textContent = old; }, 1500);
    } catch (e) { /* presse-papiers indisponible (HTTP non sécurisé) */ }
  });

  // Ouvrir une modale : <button data-dialog="id-du-dialog">
  document.addEventListener("click", (event) => {
    const opener = event.target.closest("[data-dialog]");
    if (opener) document.getElementById(opener.dataset.dialog)?.showModal();
    const closer = event.target.closest("[data-close]");
    if (closer) closer.closest("dialog")?.close();
  });
})();
