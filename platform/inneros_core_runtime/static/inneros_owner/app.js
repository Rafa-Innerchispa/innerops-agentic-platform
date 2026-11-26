const TZ = "America/Guayaquil";

function fmtTime(ts) {
  if (!ts) return "";
  const d = typeof ts === "number" ? new Date(ts * 1000) : new Date(ts);
  return d.toLocaleString("es-EC", { timeZone: TZ, dateStyle: "short", timeStyle: "short" }) + " (Guayaquil)";
}

function switchTab(name) {
  document.querySelectorAll(".tabs button").forEach((b) => b.classList.toggle("on", b.dataset.tab === name));
  document.querySelectorAll(".panel").forEach((p) => p.classList.toggle("on", p.id === `panel-${name}`));
  scheduleRefresh();
  refreshAll();
}

document.querySelectorAll(".tabs button").forEach((b) => b.addEventListener("click", () => switchTab(b.dataset.tab)));

async function loadPending() {
  const list = document.getElementById("list-pending");
  const empty = document.getElementById("empty-pending");
  const status = document.getElementById("status");
  list.innerHTML = "";
  try {
    const r = await fetch("/api/owner-ops/pending");
    const data = await r.json();
    let items = (data.pending || []).filter((x) =>
      ["pending", "awaiting_owner_decision"].includes(String(x.status || ""))
    );
    if (!items.length && data.error) {
      status.textContent = "API pendientes: " + data.error;
    }
    empty.style.display = items.length ? "none" : "block";
    for (const item of items) {
      const tid = item.task_id || item._id;
      const nonce = item.nonce;
      if (!nonce) continue;
      const links = await fetch(
        `/api/owner-ops/sign-links?task_id=${encodeURIComponent(tid)}&nonce=${encodeURIComponent(nonce)}`
      ).then((x) => x.json());
      const card = document.createElement("div");
      card.className = "card";
      const provider = item.provider || "?";
      const alias = item.human_task_id || "";
      card.innerHTML = `
        <div class="provider">${provider}<span class="badge pend">pendiente</span></div>
        <div class="tid">${tid}</div>
        ${alias ? `<div class="msg" style="margin-top:0.25rem">${alias}</div>` : ""}
        <div class="msg">${(item.title || item.objective || "Autorizar ejecución IDE").toString().slice(0, 280)}</div>
        <div class="when">${fmtTime(item.created_at)}</div>
        <div class="row">
          <a class="btn approve" href="${links.approve}">Aprobar</a>
          <a class="btn cancel" href="${links.cancel}">Cancelar</a>
        </div>
      `;
      list.appendChild(card);
    }
    status.textContent = `Pendientes: ${items.length} · ${fmtTime(Date.now() / 1000)}`;
  } catch (e) {
    status.textContent = "Error: " + e.message;
  }
}

function renderHistoryItem(row) {
  const card = document.createElement("div");
  card.className = "card";
  let badge = "";
  if (row.kind === "auth_request") {
    const st = row.status || "pending";
    badge = `<span class="badge ${st === "pending" ? "pend" : st === "approved" ? "ok" : "bad"}">${st}</span>`;
  } else if (row.kind === "decision") {
    badge = `<span class="badge ${row.ok ? "ok" : "bad"}">${row.decision || "decision"}</span>`;
  } else if (row.kind === "lifecycle") {
    badge = `<span class="badge ok">${row.event || "evento"}</span>`;
  }
  const title = row.title || row.human_task_id || row.task_id || row.message || "Notificación";
  const body = row.message || row.title || "";
  card.innerHTML = `
    <div class="provider">${row.provider || "InnerOS"} ${badge}</div>
    <div class="tid">${title}</div>
    ${body && body !== title ? `<div class="msg">${body.slice(0, 400)}</div>` : ""}
    <div class="when">${fmtTime(row.created_at || row.time)}</div>
  `;
  return card;
}

async function loadActive() {
  const list = document.getElementById("list-active");
  const empty = document.getElementById("empty-active");
  if (!list) return;
  list.innerHTML = "";
  try {
    const r = await fetch("/api/owner-ops/active");
    const data = await r.json();
    const items = data.active || [];
    empty.style.display = items.length ? "none" : "block";
    for (const item of items) {
      const card = document.createElement("div");
      card.className = "card";
      const provider = String(item.assignee || "?").toUpperCase();
      const st = item.status || "?";
      card.innerHTML = `
        <div class="provider">${provider}<span class="badge ok">${st}</span></div>
        <div class="tid">${item.task_id || "?"}</div>
        <div class="msg">${item.human_task_id || item.correlation_id || ""}</div>
        <div class="msg" style="margin-top:0.35rem">${(item.title || "").slice(0, 220)}</div>
        <div class="when">Desde: ${item.from_agent || "?"} · ${fmtTime(item.updated_at || item.created_at)}</div>
      `;
      list.appendChild(card);
    }
  } catch (e) {
    empty.style.display = "block";
    empty.textContent = "No se pudo cargar en curso: " + e.message;
  }
}

async function loadHistory() {
  const list = document.getElementById("list-history");
  const empty = document.getElementById("empty-history");
  list.innerHTML = "";
  try {
    const r = await fetch("/api/owner-ops/history?limit=50");
    const data = await r.json();
    const mongo = (data.items || []).filter(
      (r) => !(r.kind === "auth_request" && String(r.status || "") === "pending")
    );
    const ntfy = (data.ntfy_cache || []).map((m) => ({
      kind: "ntfy",
      title: m.title || m.topic,
      message: m.message,
      created_at: m.time,
      provider: "ntfy",
    }));
    const merged = [...mongo, ...ntfy].sort((a, b) => (b.created_at || 0) - (a.created_at || 0));
    const seen = new Set();
    const unique = [];
    for (const row of merged) {
      const key = `${row.kind}|${row.task_id || ""}|${row.created_at}|${(row.message || "").slice(0, 40)}`;
      if (seen.has(key)) continue;
      seen.add(key);
      unique.push(row);
    }
    empty.style.display = unique.length ? "none" : "block";
    unique.slice(0, 60).forEach((row) => list.appendChild(renderHistoryItem(row)));
  } catch (e) {
    empty.style.display = "block";
    empty.textContent = "No se pudo cargar historial: " + e.message;
  }
}

const pwaUrl = document.getElementById("pwa-url");
if (pwaUrl) {
  fetch("/health")
    .then((r) => r.json())
    .then((d) => {
      pwaUrl.textContent = (d.public || window.location.origin) + "/owner-ops/";
    })
    .catch(() => {
      pwaUrl.textContent = window.location.origin + "/owner-ops/";
    });
}

let refreshTimer = null;

function scheduleRefresh() {
  if (refreshTimer) clearInterval(refreshTimer);
  const pendingTab = document.getElementById("panel-pending");
  const active = pendingTab && pendingTab.classList.contains("on");
  const ms = document.hidden ? 25000 : active ? 4000 : 12000;
  refreshTimer = setInterval(refreshAll, ms);
}

async function refreshAll() {
  await loadPending();
  await loadActive();
  await loadHistory();
  scheduleRefresh();
}

document.addEventListener("visibilitychange", () => {
  if (!document.hidden) refreshAll();
});

refreshAll();

if ("serviceWorker" in navigator) {
  navigator.serviceWorker.register("/owner-ops/static/sw.js").catch(() => {});
}