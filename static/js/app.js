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
      const old = button.innerHTML;  // innerHTML : conserve l'icône des boutons ronds
      button.textContent = button.querySelector("svg") ? "✓" : "Copié ✓";
      button.title = "Copié";
      setTimeout(() => { button.innerHTML = old; }, 1500);
    } catch (e) { /* presse-papiers indisponible (HTTP non sécurisé) */ }
  });

  // Ouvrir une modale : <button data-dialog="id-du-dialog">
  document.addEventListener("click", (event) => {
    const opener = event.target.closest("[data-dialog]");
    if (opener) document.getElementById(opener.dataset.dialog)?.showModal();
    const closer = event.target.closest("[data-close]");
    if (closer) closer.closest("dialog")?.close();
  });
  // Menu latéral : sur grand écran il se réduit en colonne d'icônes (choix mémorisé),
  // sur petit écran il s'ouvre par-dessus le contenu.
  const root = document.documentElement;
  const toggle = document.getElementById("drawerToggle");
  const scrim = document.getElementById("drawerScrim");
  const wide = window.matchMedia("(min-width: 1101px)");
  const closeDrawer = () => { root.classList.remove("drawer-open"); if (scrim) scrim.hidden = true; };
  if (toggle) {
    toggle.addEventListener("click", () => {
      if (wide.matches) {
        const rail = root.classList.toggle("drawer-rail");
        try { localStorage.setItem("sq-drawer", rail ? "rail" : "full"); } catch (e) { /* stockage indisponible */ }
      } else {
        const open = root.classList.toggle("drawer-open");
        if (scrim) scrim.hidden = !open;
      }
    });
  }
  if (scrim) scrim.addEventListener("click", closeDrawer);
  wide.addEventListener("change", closeDrawer);

  // Menus déroulants (<details> compte, « Créer », infos de classe) : se ferment au clic ailleurs ou avec Échap.
  const menus = () => document.querySelectorAll("details.account[open], details.create-menu[open], details.class-banner-info[open]");
  document.addEventListener("click", (event) => {
    menus().forEach((menu) => {
      if (!menu.contains(event.target) || event.target.closest(".menu button[data-dialog]")) menu.open = false;
    });
  });
  document.addEventListener("keydown", (event) => {
    if (event.key !== "Escape") return;
    menus().forEach((menu) => { menu.open = false; });
    closeDrawer();
  });
})();
