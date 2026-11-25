async function loadPending() {
  const list = document.getElementById("list");
  const empty = document.getElementById("empty");
  const status = document.getElementById("status");
  list.innerHTML = "";
  try {
    const r = await fetch("/api/owner-ops/pending");
    const data = await r.json();
    const items = (data.pending || []).filter((x) =>
      ["pending", "awaiting_owner_decision"].includes(String(x.status || ""))
    );
    if (!items.length) {
      empty.style.display = "block";
      status.textContent = "Actualizado " + new Date().toLocaleTimeString();
      return;
    }
    empty.style.display = "none";
    for (const item of items) {
      const tid = item.task_id || item._id;
      const nonce = item.nonce;
      const links = await fetch(
        `/api/owner-ops/sign-links?task_id=${encodeURIComponent(tid)}&nonce=${encodeURIComponent(nonce)}`
      ).then((x) => x.json());
      const card = document.createElement("div");
      card.className = "card";
      const provider = item.provider || "?";
      const alias = item.human_task_id || tid;
      const objective = (item.objective || item.title || "Autorizar ejecución IDE").slice(0, 200);
      card.innerHTML = `
        <div class="provider">${provider}</div>
        <div class="tid">${alias}</div>
        <div style="font-size:0.9rem;opacity:0.85">${objective}</div>
        <div class="row">
          <a class="btn approve" href="${links.approve}">Aprobar</a>
          <a class="btn cancel" href="${links.cancel}">Cancelar</a>
        </div>
      `;
      list.appendChild(card);
    }
    status.textContent = `${items.length} pendiente(s) · ${new Date().toLocaleTimeString()}`;
  } catch (e) {
    status.textContent = "Error de red: " + e.message;
  }
}

loadPending();
setInterval(loadPending, 15000);

if ("serviceWorker" in navigator) {
  navigator.serviceWorker.register("/owner-ops/static/sw.js").catch(() => {});
}