// Éditeur graphique des questions d'un examen en brouillon, façon Google Forms.
// - une carte par question ; cliquer dessus l'ouvre en édition ;
// - la bonne réponse se désigne en cliquant le cercle (réponse unique) ou la case (réponses multiples) ;
// - enregistrement automatique (points d'accès JSON de qcm/views/question_editor.py) ;
// - glisser-déposer ou flèches pour réordonner, dupliquer, supprimer.
// Sans JavaScript, la page garde le formulaire classique (_questions_classic.html).
(() => {
  const root = document.getElementById("questionEditor");
  const dataNode = document.getElementById("qeData");
  if (!root || !dataNode || !window.fetch) return;

  const MAX = Number(root.dataset.maxOptions) || 8;
  const pageCsrf = root.querySelector("input[name=csrfmiddlewaretoken]").value;
  // Django change le jeton à chaque connexion : après une reconnexion dans un autre onglet, celui de la page est périmé.
  const csrfToken = () => document.cookie.match(/(?:^|; )csrftoken=([^;]+)/)?.[1] || pageCsrf;
  const RETRY_MS = [3000, 6000, 15000, 30000];
  const urlFor = (template, id) => template.replace(/\/0\/(duplicate|delete)\/$/, `/${id}/$1/`);
  const SINGLE = "SINGLE", MULTIPLE = "MULTIPLE";
  const LETTERS = "ABCDEFGH";

  let seq = 0;
  let activeKey = null;
  let serverOrder = [];
  let orderQueue = Promise.resolve();   // les envois d'ordre partent l'un après l'autre
  let orderBusy = 0, orderError = "", orderRetry = null, orderAttempt = 0;
  const questions = JSON.parse(dataNode.textContent).map(fromServer);
  serverOrder = questions.map((q) => q.id);

  function fromServer(data) {
    const q = { key: ++seq, id: data.id, text: data.text, kind: data.kind, points: data.points,
                options: data.options.map((o) => ({ text: o.text, correct: o.correct })),
                status: "saved", error: "", saving: false, again: false, timer: null, retry: null, attempt: 0 };
    q.savedSnap = snapshot(q);
    return q;
  }
  function blank() {
    return { key: ++seq, id: null, text: "", kind: SINGLE, points: "1",
             options: [{ text: "", correct: false }, { text: "", correct: false }],
             status: "new", error: "", saving: false, again: false, timer: null, retry: null, attempt: 0,
             savedSnap: null };
  }
  function snapshot(q) {
    return JSON.stringify({ text: q.text.trim(), kind: q.kind, points: String(q.points).trim(),
      options: q.options.filter((o) => o.text.trim()).map((o) => [o.text.trim(), o.correct]) });
  }

  // ---------------------------------------------------------------- règles (mêmes que le serveur)
  function problem(q) {
    const filled = q.options.filter((o) => o.text.trim());
    const correct = filled.filter((o) => o.correct).length;
    const points = Number(String(q.points).replace(",", "."));
    if (!q.text.trim()) return "Saisissez l'énoncé de la question.";
    if (!(points >= 0.1 && points <= 100)) return "Le barème doit être un nombre entre 0,1 et 100.";
    if (filled.length < 2) return "Saisissez au moins deux propositions.";
    if (!correct) return "Désignez la bonne réponse en cliquant sur le cercle ou la case d'une proposition.";
    if (q.kind === SINGLE && correct > 1) return "Réponse unique : une seule bonne réponse.";
    return "";
  }
  const isEmpty = (q) => !q.text.trim() && q.options.every((o) => !o.text.trim());

  // ---------------------------------------------------------------- utilitaires DOM
  function h(tag, attrs = {}, ...children) {
    const node = document.createElement(tag);
    for (const [name, value] of Object.entries(attrs)) {
      if (value === false || value == null) continue;
      if (name === "class") node.className = value;
      else if (name === "value") node.value = value;  // <textarea> ignore l'attribut value
      else if (name.startsWith("on")) node.addEventListener(name.slice(2), value);
      else if (name in node && typeof value !== "string") node[name] = value;
      else node.setAttribute(name, value === true ? "" : value);
    }
    for (const child of children.flat()) if (child != null) node.append(child);
    return node;
  }
  const svg = (path) => {
    const ns = "http://www.w3.org/2000/svg";
    const node = document.createElementNS(ns, "svg");
    node.setAttribute("viewBox", "0 0 24 24"); node.setAttribute("aria-hidden", "true"); node.classList.add("qe-ico");
    const p = document.createElementNS(ns, "path"); p.setAttribute("d", path); node.append(p);
    return node;
  };
  const ICON = {
    up: "M7.41 15.41 12 10.83l4.59 4.58L18 14l-6-6-6 6z",
    down: "M7.41 8.59 12 13.17l4.59-4.58L18 10l-6 6-6-6z",
    copy: "M16 1H4c-1.1 0-2 .9-2 2v14h2V3h12V1zm3 4H8c-1.1 0-2 .9-2 2v14c0 1.1.9 2 2 2h11c1.1 0 2-.9 2-2V7c0-1.1-.9-2-2-2zm0 16H8V7h11v14z",
    trash: "M6 19c0 1.1.9 2 2 2h8c1.1 0 2-.9 2-2V7H6v12zM19 4h-3.5l-1-1h-5l-1 1H5v2h14V4z",
    close: "M19 6.41 17.59 5 12 10.59 6.41 5 5 6.41 10.59 12 5 17.59 6.41 19 12 13.41 17.59 19 19 17.59 13.41 12z",
    drag: "M9 4a2 2 0 1 0 0 .01zm6 0a2 2 0 1 0 0 .01zM9 12a2 2 0 1 0 0 .01zm6 0a2 2 0 1 0 0 .01zM9 20a2 2 0 1 0 0 .01zm6 0a2 2 0 1 0 0 .01z",
    add: "M19 13h-6v6h-2v-6H5v-2h6V5h2v6h6v2z",
  };
  const fmtPoints = (value) => {
    const n = Number(String(value).replace(",", "."));
    return Number.isFinite(n) ? n.toLocaleString("fr-FR", { maximumFractionDigits: 2 }) : "?";
  };

  // ---------------------------------------------------------------- structure de la page
  const summary = h("p", { class: "qe-summary" });
  const status = h("p", { class: "qe-status", role: "status", "aria-live": "polite" });
  const list = h("ol", { class: "qe-list" });
  const addBottom = h("button", { class: "btn ghost qe-add-bottom", type: "button", onclick: () => addQuestion() },
                      svg(ICON.add), "Ajouter une question");
  const fab = h("div", { class: "qe-fab" },
    h("button", { type: "button", class: "qe-fab-btn", title: "Ajouter une question",
                  "aria-label": "Ajouter une question après la question sélectionnée", onclick: () => addQuestion() },
      svg(ICON.add)));
  root.append(
    h("div", { class: "qe-head" },
      h("div", {}, h("h2", {}, "Questions"), summary),
      status),
    list, addBottom, fab);
  root.hidden = false;
  const fallback = document.querySelector(".qe-fallback");
  if (fallback) fallback.hidden = true;

  // ---------------------------------------------------------------- rendu d'une carte
  const byKey = (key) => questions.find((q) => q.key === key);
  const cardOf = (q) => list.querySelector(`.qe-card[data-key="${q.key}"]`);

  function renderCard(q) {
    const index = questions.indexOf(q);
    const active = q.key === activeKey;
    const card = h("li", { class: `qe-card${active ? " is-active" : ""}`, "data-key": q.key });
    card.append(h("div", { class: "qe-drag", draggable: "true", title: "Glisser pour déplacer" }, svg(ICON.drag)));
    card.append(active ? editView(q, index) : readView(q, index));
    card.append(h("p", { class: "qe-msg", "data-msg": "" }));
    paintMessage(q, card);
    return card;
  }

  function readView(q, index) {
    const view = h("div", { class: "qe-view", tabindex: "0", role: "button",
                            "aria-label": `Modifier la question ${index + 1}` });
    view.append(h("div", { class: "qe-view-head" },
      h("span", { class: "qe-view-text" }, h("span", { class: "qe-num" }, `${index + 1}. `),
        q.text.trim() || h("span", { class: "muted" }, "Question sans énoncé")),
      h("span", { class: "qe-pts" }, `${fmtPoints(q.points)} pt${Number(q.points) > 1 ? "s" : ""}`)));
    const options = h("ul", { class: "qe-view-options" });
    q.options.filter((o) => o.text.trim()).forEach((o) => {
      options.append(h("li", { class: o.correct ? "is-correct" : "" },
        h("span", { class: `qe-mark ${q.kind === SINGLE ? "radio" : "box"}${o.correct ? " on" : ""}` }),
        h("span", {}, o.text), o.correct ? h("span", { class: "qe-good" }, "Bonne réponse") : null));
    });
    view.append(options);
    const open = () => activate(q.key, ".qe-text");
    view.addEventListener("click", open);
    view.addEventListener("keydown", (e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); open(); } });
    return view;
  }

  function editView(q, index) {
    const edit = h("div", { class: "qe-edit" });
    const text = h("textarea", { class: "qe-text", rows: "1", placeholder: "Question", value: q.text,
                                 "aria-label": `Énoncé de la question ${index + 1}` });
    text.addEventListener("input", () => { q.text = text.value; autosize(text); changed(q); });
    const kind = h("select", { class: "qe-kind", "aria-label": "Type de question" },
      h("option", { value: SINGLE, selected: q.kind === SINGLE }, "◉  Réponse unique"),
      h("option", { value: MULTIPLE, selected: q.kind === MULTIPLE }, "☑  Réponses multiples"));
    kind.addEventListener("change", () => {
      q.kind = kind.value;
      if (q.kind === SINGLE) {  // une seule bonne réponse : on garde la première
        let seen = false;
        q.options.forEach((o) => { if (o.correct) { o.correct = !seen; seen = true; } });
      }
      redrawOptions(q); changed(q);
    });
    edit.append(h("div", { class: "qe-edit-head" }, text, kind));
    edit.append(h("ol", { class: "qe-options" }, optionRows(q)));
    edit.append(h("div", { class: "qe-add-option-row" },
      h("span", { class: `qe-mark ${q.kind === SINGLE ? "radio" : "box"}` }),
      h("button", { type: "button", class: "qe-add-option", disabled: q.options.length >= MAX,
                    onclick: () => addOption(q, q.options.length) },
        q.options.length >= MAX ? `${MAX} propositions au maximum` : "Ajouter une option")));
    edit.append(h("p", { class: "qe-help" },
      q.kind === SINGLE ? "Cliquez sur le cercle de la bonne réponse." : "Cochez toutes les bonnes réponses."));

    const points = h("input", { type: "number", min: "0.1", max: "100", step: "0.01", value: q.points,
                                class: "qe-points-input", "aria-label": "Points" });
    points.addEventListener("input", () => { q.points = points.value; changed(q); });
    const position = questions.indexOf(q);
    edit.append(h("div", { class: "qe-foot" },
      h("label", { class: "qe-points" }, points, "point(s)"),
      h("span", { class: "qe-foot-sep" }),
      iconButton(ICON.up, "Monter la question", () => move(q, -1), position === 0),
      iconButton(ICON.down, "Descendre la question", () => move(q, 1), position === questions.length - 1),
      iconButton(ICON.copy, "Dupliquer la question", () => duplicate(q)),
      iconButton(ICON.trash, "Supprimer la question", () => remove(q))));
    requestAnimationFrame(() => autosize(text));
    return edit;
  }

  function iconButton(icon, label, action, disabled = false) {
    return h("button", { type: "button", class: "qe-icon", title: label, "aria-label": label, disabled, onclick: action },
             svg(icon));
  }

  function optionRows(q) {
    return q.options.map((o, i) => {
      const mark = h("button", { type: "button", class: `qe-mark ${q.kind === SINGLE ? "radio" : "box"}${o.correct ? " on" : ""}`,
                                 role: q.kind === SINGLE ? "radio" : "checkbox", "aria-checked": String(o.correct),
                                 "aria-label": `Proposition ${LETTERS[i]} : bonne réponse`, title: "Bonne réponse" });
      mark.addEventListener("click", () => {
        if (q.kind === SINGLE) q.options.forEach((other) => { other.correct = other === o; });
        else o.correct = !o.correct;
        redrawOptions(q, `.qe-opt-text[data-i="${i}"]`); changed(q);
      });
      const input = h("input", { class: "qe-opt-text", value: o.text, placeholder: `Option ${i + 1}`, maxlength: "500",
                                 "data-i": i, "aria-label": `Proposition ${LETTERS[i]}` });
      input.addEventListener("input", () => { o.text = input.value; changed(q); });
      input.addEventListener("keydown", (e) => {
        if (e.key === "Enter") { e.preventDefault(); if (q.options.length < MAX) addOption(q, i + 1); }
        else if (e.key === "Backspace" && !input.value && q.options.length > 2) { e.preventDefault(); removeOption(q, i, true); }
      });
      const del = h("button", { type: "button", class: "qe-icon qe-opt-del", title: "Supprimer cette option",
                                "aria-label": `Supprimer la proposition ${LETTERS[i]}`, disabled: q.options.length <= 2,
                                onclick: () => removeOption(q, i) }, svg(ICON.close));
      return h("li", { class: `qe-option${o.correct ? " is-correct" : ""}` }, mark, input, del);
    });
  }

  function redrawOptions(q, focusSelector) {
    const card = cardOf(q);
    if (!card) return;
    const edit = card.querySelector(".qe-edit");
    const fresh = editView(q, questions.indexOf(q));
    edit.replaceWith(fresh);
    if (focusSelector) fresh.querySelector(focusSelector)?.focus();
  }
  function addOption(q, at) {
    q.options.splice(at, 0, { text: "", correct: false });
    redrawOptions(q, `.qe-opt-text[data-i="${at}"]`); changed(q);
  }
  function removeOption(q, i, focusPrevious = false) {
    q.options.splice(i, 1);
    redrawOptions(q, focusPrevious ? `.qe-opt-text[data-i="${Math.max(0, i - 1)}"]` : null); changed(q);
  }
  function autosize(area) { area.style.height = "auto"; area.style.height = `${area.scrollHeight}px`; }

  function paintMessage(q, card = cardOf(q)) {
    if (!card) return;
    const box = card.querySelector("[data-msg]");
    let text = "", tone = "";
    if (q.status === "error") { text = q.error; tone = "error"; }
    else if (q.status === "invalid" && !(q.id === null && isEmpty(q))) {
      text = (q.id ? "Modification non enregistrée : " : "Pas encore enregistrée : ") + q.error;
      tone = q.id ? "error" : "warn";
    }
    box.textContent = text;
    box.className = `qe-msg${tone ? ` is-${tone}` : ""}`;
    card.classList.toggle("has-problem", tone === "error");
  }

  function renderAll() {
    list.replaceChildren(...questions.map(renderCard));
    if (!questions.length) {
      list.append(h("li", { class: "qe-empty" }, "Aucune question. Cliquez sur « Ajouter une question » ou importez un sujet."));
    }
    refreshHeader();
  }
  function refreshNumbers() {
    questions.forEach((q, i) => {
      const card = cardOf(q);
      const num = card?.querySelector(".qe-num");
      if (num) num.textContent = `${i + 1}. `;
      const text = card?.querySelector(".qe-text");
      if (text) text.setAttribute("aria-label", `Énoncé de la question ${i + 1}`);
    });
  }

  const pageCount = document.getElementById("qeCount");
  const isPending = (q) => q.status === "invalid" && !(q.id === null && isEmpty(q));
  // Ce qui n'est pas (encore) en base : bloque la publication et avertit avant de quitter la page.
  function unsaved() {
    return questions.filter((q) => q.saving || q.timer || q.retry || q.status === "error" || q.status === "dirty"
      || isPending(q)).length + (orderBusy || orderError ? 1 : 0);
  }

  function refreshHeader() {
    const total = questions.reduce((sum, q) => sum + (Number(String(q.points).replace(",", ".")) || 0), 0);
    const count = `${questions.length} question${questions.length > 1 ? "s" : ""}`;
    summary.textContent = `${count} · ${fmtPoints(total)} point${total > 1 ? "s" : ""} au total`;
    if (pageCount) pageCount.textContent = count;
    const saving = questions.some((q) => q.saving || q.timer) || orderBusy;
    const failed = questions.filter((q) => q.status === "error").length;
    const pending = questions.filter(isPending).length;
    status.className = "qe-status";
    if (saving) status.textContent = "Enregistrement…";
    else if (failed) { status.textContent = "Des modifications n'ont pas pu être enregistrées."; status.classList.add("is-error"); }
    else if (orderError) { status.textContent = `Ordre des questions non enregistré : ${orderError}`; status.classList.add("is-error"); }
    else if (pending) { status.textContent = `${pending} question${pending > 1 ? "s" : ""} à compléter, non enregistrée${pending > 1 ? "s" : ""}.`; status.classList.add("is-warn"); }
    else status.textContent = "Toutes les modifications sont enregistrées.";
  }

  // ---------------------------------------------------------------- sélection de la carte active
  function activate(key, focusSelector) {
    if (activeKey === key) return;
    const previous = byKey(activeKey);
    activeKey = key;
    if (previous) { save(previous); cardOf(previous)?.replaceWith(renderCard(previous)); }
    const q = byKey(key);
    if (q) {
      const card = renderCard(q);
      cardOf(q).replaceWith(card);
      if (focusSelector) card.querySelector(focusSelector)?.focus();
      card.scrollIntoView({ block: "nearest", behavior: "smooth" });
      placeFab(card);
    }
  }
  function deactivate() {
    const previous = byKey(activeKey);
    activeKey = null;
    if (previous) { save(previous); cardOf(previous)?.replaceWith(renderCard(previous)); }
    placeFab(null);
  }
  document.addEventListener("pointerdown", (event) => {
    if (!activeKey || event.target.closest(".qe-card.is-active, .qe-fab, .qe-add-bottom, dialog")) return;
    if (event.target.closest(".qe-card")) return;  // une autre carte : son clic l'active
    deactivate();
  });
  function placeFab(card) {
    const top = card ? card.offsetTop : list.offsetTop;
    fab.style.top = `${Math.max(0, top)}px`;
  }

  // ---------------------------------------------------------------- serveur
  async function post(url, body) {
    let response;
    try {
      response = await fetch(url, { method: "POST", credentials: "same-origin", body: JSON.stringify(body || {}),
        headers: { "Content-Type": "application/json", "X-CSRFToken": csrfToken(), Accept: "application/json" } });
    } catch (e) {
      const error = new Error("Serveur injoignable : nouvel essai automatique dans quelques secondes.");
      error.network = true;
      throw error;
    }
    const json = (response.headers.get("content-type") || "").includes("application/json");
    const data = json ? await response.json().catch(() => ({})) : {};
    if (!json || response.redirected) throw new Error("Session expirée : reconnectez-vous dans un autre onglet, puis modifiez la question.");
    if (!response.ok) {
      const error = new Error(data.error || `Erreur du serveur (${response.status}).`);
      error.status = response.status;
      throw error;
    }
    if (Array.isArray(data.order)) serverOrder = data.order;
    return data;
  }

  function changed(q) {
    clearTimeout(q.timer);
    clearTimeout(q.retry); q.retry = null; q.attempt = 0;
    q.timer = setTimeout(() => { q.timer = null; save(q); }, 900);
    if (q.status === "error" || q.status === "invalid") { q.status = "dirty"; paintMessage(q); }
    refreshHeader();
  }

  async function save(q) {
    clearTimeout(q.timer); q.timer = null;
    clearTimeout(q.retry); q.retry = null;
    if (!questions.includes(q)) return;
    const error = problem(q);
    if (error) { q.status = "invalid"; q.error = error; paintMessage(q); refreshHeader(); return; }
    if (q.saving) { q.again = true; return; }
    const snap = snapshot(q);
    if (q.id && snap === q.savedSnap) { q.status = "saved"; paintMessage(q); refreshHeader(); return; }
    const body = { text: q.text, kind: q.kind, points: String(q.points), options: q.options };
    if (q.id) body.id = q.id;
    else {
      const index = questions.indexOf(q);
      const before = questions.slice(0, index).reverse().find((other) => other.id);
      if (before) body.after = before.id;
    }
    q.saving = true; refreshHeader();
    try {
      const data = await post(root.dataset.saveUrl, body);
      q.id = data.question.id;
      q.attempt = 0;
      q.error = "";
      if (!questions.includes(q)) { await dropDeleted(q); return; }  // supprimée pendant l'enregistrement
      if (snapshot(q) === snap) {
        q.points = data.question.points;  // barème normalisé par le serveur (« 2.50 » → « 2.5 »)
        q.savedSnap = snapshot(q);
        q.status = "saved";
      } else {  // modifiée pendant l'envoi : la base a `snap`, l'écran a plus récent
        q.savedSnap = snap;
        q.status = "dirty";
      }
      await syncOrder();
    } catch (e) {
      q.status = "error"; q.error = e.message;
      if (e.network && questions.includes(q)) {
        q.retry = setTimeout(() => { q.retry = null; save(q); }, RETRY_MS[Math.min(q.attempt++, RETRY_MS.length - 1)]);
      }
    } finally {
      q.saving = false;
      paintMessage(q);
      if (q.key !== activeKey) cardOf(q)?.replaceWith(renderCard(q));
      refreshHeader();
      if (q.again || q.status === "dirty") { q.again = false; save(q); }
    }
  }

  // Un envoi à la fois : le second part de l'ordre que le serveur a confirmé pour le premier.
  function syncOrder() {
    orderBusy++; refreshHeader();
    orderQueue = orderQueue.then(sendOrder).finally(() => { orderBusy--; refreshHeader(); });
    return orderQueue;
  }
  async function sendOrder() {
    clearTimeout(orderRetry); orderRetry = null;
    // Le serveur attend toutes ses questions : on n'envoie que si les deux listes contiennent les mêmes.
    const wanted = questions.filter((q) => q.id).map((q) => q.id);
    const same = wanted.length === serverOrder.length && serverOrder.every((id) => wanted.includes(id));
    if (!same || wanted.every((id, i) => id === serverOrder[i])) { orderError = ""; return; }
    try {
      await post(root.dataset.orderUrl, { order: wanted });
      orderError = ""; orderAttempt = 0;
    } catch (e) {
      orderError = e.message;
      if (e.network) orderRetry = setTimeout(syncOrder, RETRY_MS[Math.min(orderAttempt++, RETRY_MS.length - 1)]);
    }
  }

  // ---------------------------------------------------------------- actions
  function closeActive() {
    const previous = byKey(activeKey);
    activeKey = null;
    if (previous) save(previous);
  }

  function addQuestion() {
    const q = blank();
    const at = activeKey ? questions.indexOf(byKey(activeKey)) + 1 : questions.length;
    questions.splice(at, 0, q);
    closeActive();
    renderAll();
    activate(q.key, ".qe-text");
  }

  async function remove(q) {
    if (q.id && !isEmpty(q) && !window.confirm("Supprimer cette question ?")) return;
    clearTimeout(q.timer); q.timer = null;
    clearTimeout(q.retry); q.retry = null;
    q.removedAt = questions.indexOf(q);
    questions.splice(q.removedAt, 1);
    activeKey = null;
    renderAll();
    // Pas encore en base : si sa création est en cours, save() la supprimera dès qu'elle aura un identifiant.
    if (q.id) await dropDeleted(q);
  }

  async function dropDeleted(q) {
    try { await post(urlFor(root.dataset.deleteUrl, q.id)); }
    catch (e) {  // remise en place : la suppression a échoué, la question est toujours dans l'examen
      questions.splice(Math.min(q.removedAt, questions.length), 0, q);
      q.status = "error"; q.error = `Suppression non effectuée : ${e.message}`;
      renderAll();
    }
    refreshHeader();
  }

  async function duplicate(q) {
    const index = questions.indexOf(q);
    let copy;
    if (q.id && q.status === "saved" && snapshot(q) === q.savedSnap) {
      try { copy = fromServer((await post(urlFor(root.dataset.duplicateUrl, q.id))).question); }
      catch (e) { q.status = "error"; q.error = e.message; paintMessage(q); refreshHeader(); return; }
    } else {
      copy = blank();
      Object.assign(copy, { text: q.text, kind: q.kind, points: q.points, options: q.options.map((o) => ({ ...o })) });
    }
    questions.splice(index + 1, 0, copy);
    closeActive();
    renderAll();
    activate(copy.key, ".qe-text");
    if (!copy.id) save(copy);
  }

  function move(q, delta) {
    const from = questions.indexOf(q), to = from + delta;
    if (to < 0 || to >= questions.length) return;
    questions.splice(from, 1); questions.splice(to, 0, q);
    const key = activeKey; activeKey = null; renderAll(); activeKey = null; activate(key);
    cardOf(q)?.querySelector(`[aria-label="${delta < 0 ? "Monter" : "Descendre"} la question"]`)?.focus();
    syncOrder();
  }

  // Glisser-déposer : seule la poignée (⠿) est déplaçable, pour ne pas gêner la sélection de texte ;
  // l'image glissée est la carte entière. Au clavier et sur écran tactile : flèches du pied de carte.
  let dragged = null;
  list.addEventListener("dragstart", (e) => {
    const card = e.target.closest?.(".qe-drag") && e.target.closest(".qe-card");
    if (!card) return;
    e.dataTransfer.setDragImage(card, 24, 12);
    dragged = byKey(Number(card.dataset.key));
    card.classList.add("is-dragging");
    e.dataTransfer.effectAllowed = "move";
    e.dataTransfer.setData("text/plain", String(dragged.key));
  });
  list.addEventListener("dragover", (e) => {
    if (!dragged) return;
    const card = e.target.closest(".qe-card");
    if (!card || Number(card.dataset.key) === dragged.key) return;
    e.preventDefault();
    const box = card.getBoundingClientRect();
    const after = e.clientY > box.top + box.height / 2;
    const draggedCard = cardOf(dragged);
    card[after ? "after" : "before"](draggedCard);
  });
  list.addEventListener("dragend", () => {
    const card = dragged && cardOf(dragged);
    if (card) card.classList.remove("is-dragging");
    if (!dragged) return;
    const keys = [...list.querySelectorAll(".qe-card")].map((c) => Number(c.dataset.key));
    questions.sort((a, b) => keys.indexOf(a.key) - keys.indexOf(b.key));
    dragged = null;
    const key = activeKey; activeKey = null; renderAll(); if (key) activate(key);
    refreshNumbers();
    syncOrder();
  });

  window.addEventListener("beforeunload", (event) => {
    if (unsaved()) { event.preventDefault(); event.returnValue = ""; }
  });

  // 7 : la publication est définitive ; elle doit porter sur ce qui est affiché. Écoute en phase de capture,
  // avant la confirmation générique de app.js.
  document.addEventListener("submit", (event) => {
    if (!event.target.matches("form[data-publish]")) return;
    const active = byKey(activeKey);
    if (active) save(active);
    if (!unsaved()) return;
    event.preventDefault();
    event.stopImmediatePropagation();
    status.textContent = "Publication impossible : des questions ne sont pas encore enregistrées. "
      + "Complétez ou corrigez les questions signalées, attendez « Toutes les modifications sont enregistrées », puis publiez.";
    status.className = "qe-status is-error";
    (list.querySelector(".qe-card.has-problem, .qe-msg.is-warn") || root).scrollIntoView({ block: "center", behavior: "smooth" });
  }, true);

  renderAll();
  placeFab(null);
})();
