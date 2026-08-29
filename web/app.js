const view = document.getElementById("view");
const boot = document.getElementById("boot");
const bootMsg = document.getElementById("boot-msg");
const bootBar = document.getElementById("boot-bar");
const bootPct = document.getElementById("boot-pct");
const bootBtn = document.getElementById("boot-btn");
const drop = document.getElementById("drop");
const gq = document.getElementById("gq");

let ready = false;
let bootTimer = null;
let searchClock;
let fantasyClock;
let viewGen = 0;

function foldTr(value) {
  return String(value ?? "")
    .toLocaleLowerCase("tr-TR")
    .replaceAll("ç", "c")
    .replaceAll("ğ", "g")
    .replaceAll("ı", "i")
    .replaceAll("ö", "o")
    .replaceAll("ş", "s")
    .replaceAll("ü", "u");
}

function tidyName(value) {
  const words = String(value ?? "").trim().split(/\s+/).filter(Boolean);
  if (words.length < 2) return words.join(" ");
  for (let len = Math.floor(words.length / 2); len >= 1; len--) {
    const a = words.slice(0, len).map(foldTr).join(" ");
    const b = words.slice(len, len * 2).map(foldTr).join(" ");
    if (a === b) {
      const chosen = words.slice(0, len).map((left, i) => {
        const right = words[len + i];
        const richer = [...right].filter((ch) => ch.charCodeAt(0) > 127).length >
          [...left].filter((ch) => ch.charCodeAt(0) > 127).length;
        return richer ? right : left;
      });
      return tidyName(chosen.concat(words.slice(len * 2)).join(" "));
    }
  }
  const kept = [];
  for (const word of words) {
    if (kept.length) {
      const fa = foldTr(kept[kept.length - 1]);
      const fb = foldTr(word);
      const same = fa === fb;
      const shortDup = fa && fb && (fa.startsWith(fb) || fb.startsWith(fa)) && Math.abs(fa.length - fb.length) <= 2 && Math.min(fa.length, fb.length) >= 3;
      if (same || shortDup) {
        const prev = kept[kept.length - 1];
        const richer = [...word].filter((ch) => ch.charCodeAt(0) > 127).length >
          [...prev].filter((ch) => ch.charCodeAt(0) > 127).length;
        if (richer || fb.length > fa.length) kept[kept.length - 1] = word;
        continue;
      }
    }
    kept.push(word);
  }
  return kept.join(" ");
}

function esc(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;");
}

function hideDrop() {
  drop.classList.add("hidden");
  drop.innerHTML = "";
  clearTimeout(searchClock);
}

function searchAnchor() {
  const el = document.activeElement;
  if (el && (el.id === "gq" || el.id === "hq" || el.id === "aq")) return el;
  if (document.body.classList.contains("on-home")) return document.getElementById("hq") || gq;
  return gq;
}

function placeDrop(anchor) {
  const el = anchor || searchAnchor();
  if (!el || !el.getBoundingClientRect) return;
  const r = el.getBoundingClientRect();
  const width = Math.min(Math.max(r.width, 340), window.innerWidth - 24);
  let left = r.left;
  if (left + width > window.innerWidth - 12) left = window.innerWidth - width - 12;
  if (left < 12) left = 12;
  drop.style.top = `${Math.round(r.bottom + 8)}px`;
  drop.style.left = `${Math.round(left)}px`;
  drop.style.width = `${Math.round(width)}px`;
}

function waitScreen(title, body) {
  return `<div class="wait official">
    <p class="kicker">Aurea</p>
    <b>${esc(title)}</b>
    <p>${esc(body)}</p>
    <div class="progress"><i class="indeterminate"></i></div>
  </div>`;
}

async function api(path, options) {
  const res = await fetch(path, options);
  const data = await res.json().catch(() => ({}));
  if (!res.ok) {
    const detail = data.detail;
    const msg = typeof detail === "string" ? detail : (data.message || `İstek başarısız (${res.status})`);
    throw new Error(msg);
  }
  return data;
}

function hashParts() {
  const raw = (location.hash || "#/").replace(/^#/, "");
  const [path] = raw.split("?");
  return path.split("/").filter(Boolean);
}

function queryFromHash() {
  return Object.fromEntries(new URLSearchParams(location.hash.split("?")[1] || ""));
}

function setActiveNav() {
  const first = hashParts()[0] || "";
  const home = !first;
  document.body.classList.toggle("on-home", home);
  const searchForm = document.getElementById("global-search");
  if (searchForm) searchForm.classList.toggle("hidden", home);
  document.querySelectorAll(".links a").forEach((a) => {
    const href = a.getAttribute("href").replace("#/", "");
    const onHome = href === "" && !first;
    const onLig = href === "ligler" && (first === "ligler" || first === "lig");
    const onFantezi = href === "fantezi" && first === "fantezi";
    const onSuper = href === "superlig" && first === "superlig";
    const onScout = href === "scout" && first === "scout";
    a.classList.toggle("active", href === first || onHome || onLig || onFantezi || onSuper || onScout);
  });
}

function playerHref(id) {
  return `#/oyuncu/${id}`;
}

function gapWord(direction) {
  if (direction === "dusuk") return "Ucuz etiket";
  if (direction === "yuksek") return "Pahalı etiket";
  if (direction === "denge") return "Uyumlu";
  return "Belirsiz";
}

function pill(direction, label) {
  const word = gapWord(direction);
  const extra = label && label !== "—" && label !== "denge" ? ` · ${label}` : "";
  return `<span class="pill ${esc(direction || "belirsiz")}">${esc(word)}${esc(extra)}</span>`;
}

function tile(p) {
  return `<a class="tile ${esc(p.direction || "")}" href="${playerHref(p.player_id)}">
    ${pill(p.direction, p.gap_label)}
    <div class="who">${esc(tidyName(p.name))}</div>
    <div class="sub">${esc(p.club || "—")} · ${esc(p.position || "")}</div>
    <div class="price">${esc(p.true_label || "—")}<span>Transfermarkt ${esc(p.tm_label || "—")}</span></div>
  </a>`;
}

function playerRow(p) {
  return `<a class="row" href="${playerHref(p.player_id)}">
    <div class="who-col"><div class="name">${esc(tidyName(p.name))}</div><div class="meta">${esc(p.position || "")}${p.age != null && p.age !== "" ? " · " + esc(p.age) + " yaş" : ""}</div></div>
    <div class="club-col" title="${esc(p.club || "")}">${esc(properCase(p.club) || "—")}</div>
    <div class="league-col" title="${esc(p.league || "")}">${esc(p.league || "—")}</div>
    <div class="num">${esc(p.true_label || p.tm_label || "—")}${p.tm_label ? `<div class="meta">TM ${esc(p.tm_label)}</div>` : ""}</div>
    ${pill(p.direction, p.gap_label || "")}
  </a>`;
}

function listHead() {
  return `<div class="list-head"><span>Oyuncu</span><span>Takım</span><span class="h-league">Lig</span><span>Aurea</span><span></span></div>`;
}

function resultRow(p) {
  return `<a href="${playerHref(p.player_id)}">
    <div><div class="name">${esc(tidyName(p.name))}</div><div class="meta">${esc(p.club || "")} · ${esc(p.position || "")}</div></div>
    <div class="num">${esc(p.true_label || p.tm_label || "—")}</div>
  </a>`;
}

function bestMatch(rows, q) {
  const n = (q || "").trim().toLowerCase();
  if (!n || !rows.length) return null;
  const nameOf = (r) => String(r.name || "").toLowerCase();
  const exact = rows.filter((r) => nameOf(r) === n);
  if (exact.length === 1) return exact[0];
  const last = rows.filter((r) => nameOf(r).split(/[\s-]+/).pop() === n);
  if (last.length === 1) return last[0];
  if (last.length > 1) {
    const ranked = [...last].sort((a, b) => (Number(b.tm_value) || Number(b.true_value) || 0) - (Number(a.tm_value) || Number(a.true_value) || 0));
    const top = Number(ranked[0].tm_value) || Number(ranked[0].true_value) || 0;
    const next = Number(ranked[1].tm_value) || Number(ranked[1].true_value) || 0;
    if (top >= 1_000_000 && top >= next * 3) return ranked[0];
  }
  const token = rows.filter((r) => nameOf(r).split(/[\s-]+/).includes(n));
  if (token.length === 1) return token[0];
  const ranked = [...rows].sort((a, b) => (a.match ?? 9) - (b.match ?? 9));
  if (ranked.length === 1) return ranked[0];
  if ((ranked[0].match ?? 9) <= 1 && (ranked[1]?.match ?? 9) > 1) return ranked[0];
  return null;
}

async function openFromQuery(q) {
  hideDrop();
  gq.value = "";
  const query = (q || "").trim();
  if (query.length < 2) {
    location.hash = "#/ara";
    return;
  }
  try {
    const data = await api(`/api/search?q=${encodeURIComponent(query)}`);
    const rows = data.results || [];
    const hit = bestMatch(rows, query);
    if (hit?.player_id) {
      location.hash = playerHref(hit.player_id);
      return;
    }
  } catch (_ex) {
    /* motor henüz hazır değilse arama sayfasına düş */
  }
  location.hash = `#/ara?q=${encodeURIComponent(query)}`;
}

function fmtDate(value) {
  if (!value) return "";
  const s = String(value).trim();
  const iso = s.match(/^(\d{4})-(\d{2})-(\d{2})/);
  if (iso) return `${iso[3]}.${iso[2]}.${iso[1]}`;
  const eu = s.match(/^(\d{1,2})\/(\d{1,2})\/(\d{4})/);
  if (eu) return `${eu[1].padStart(2, "0")}.${eu[2].padStart(2, "0")}.${eu[3]}`;
  return s.slice(0, 10);
}

function blankish(value) {
  const s = String(value ?? "").trim();
  if (!s || s === "—" || s === "-" || s === "unknown" || s === "None" || s === "nan" || s === "Other") return true;
  return false;
}

function fact(label, value) {
  if (blankish(value)) return "";
  return `<div><span>${esc(label)}</span><b>${esc(value)}</b></div>`;
}

function sparkline(history) {
  const pts = (history || []).filter((h) => Number(h.marketValue) > 0);
  if (pts.length < 2) return `<p class="sub">Eğri yok.</p>`;
  const vals = pts.map((h) => Number(h.marketValue));
  const w = 640, h = 72;
  const min = Math.min(...vals), max = Math.max(...vals);
  const line = vals.map((v, i) => {
    const x = (i / (vals.length - 1)) * w;
    const y = h - 8 - ((v - min) / (max - min || 1)) * (h - 16);
    return `${x},${y}`;
  }).join(" ");
  const peak = pts.reduce((a, b) => Number(b.marketValue) > Number(a.marketValue) ? b : a);
  const last = pts[pts.length - 1];
  return `<svg class="spark" viewBox="0 0 ${w} ${h}" preserveAspectRatio="none"><polyline fill="none" stroke="#d4b56a" stroke-width="2" points="${line}" /></svg>
    <div class="spark-meta"><span>Tepe ${esc(fmtEur(peak.marketValue))} · ${esc(fmtDate(peak.date))}</span><span>Güncel ${esc(fmtEur(last.marketValue))} · ${esc(fmtDate(last.date))}</span></div>`;
}

function fmtEur(n) {
  const v = Number(n);
  if (!v) return "—";
  if (v >= 1_000_000) {
    let t = (v / 1_000_000).toFixed(1).replace(".", ",");
    if (t.endsWith(",0")) t = t.slice(0, -2);
    return `${t} milyon €`;
  }
  if (v >= 1_000) return `${Math.round(v / 1_000)} bin €`;
  return `${Math.round(v)} €`;
}

function histTable(history) {
  const pts = (history || []).filter((h) => Number(h.marketValue) > 0).slice(-6).reverse();
  if (!pts.length) return "";
  return `<table class="mini">
    <thead><tr><th>Tarih</th><th>Kulüp</th><th>Etiket</th></tr></thead>
    <tbody>${pts.map((h) => `<tr><td>${esc(fmtDate(h.date))}</td><td>${esc(h.clubName || "—")}</td><td>${esc(fmtEur(h.marketValue))}</td></tr>`).join("")}</tbody>
  </table>`;
}

function tmMove(history) {
  const vals = (history || []).map((h) => Number(h.marketValue || 0)).filter((n) => n > 0);
  if (vals.length < 2) return "";
  const prev = vals[vals.length - 2];
  const last = vals[vals.length - 1];
  if (!prev) return "";
  const ch = 100 * (last - prev) / prev;
  if (Math.abs(ch) < 1) return "";
  const sign = ch > 0 ? "+" : "−";
  return `Son adım ${sign}%${Math.abs(ch).toFixed(0)}`;
}

async function ensureReady() {
  const s = await api("/api/status");
  ready = !!s.ready;
  if (ready) {
    boot.classList.add("hidden");
    boot.setAttribute("aria-hidden", "true");
    if (bootTimer) clearInterval(bootTimer);
    return true;
  }
  boot.classList.remove("hidden");
  boot.setAttribute("aria-hidden", "false");
  bootMsg.textContent = s.error ? s.error : (s.message || "Hazırlanıyor.");
  const p = Math.round((s.progress || 0) * 100);
  bootBar.style.width = `${p}%`;
  bootPct.textContent = `%${p}`;
  return false;
}

bootBtn.addEventListener("click", async () => {
  await api("/api/bootstrap", { method: "POST" });
  if (bootTimer) clearInterval(bootTimer);
  bootTimer = setInterval(async () => {
    if (await ensureReady()) render();
  }, 1000);
});

async function runSearch(q, into) {
  if (q.length < 2) {
    into.innerHTML = "";
    into.classList.add("hidden");
    return;
  }
  try {
    const data = await api(`/api/search?q=${encodeURIComponent(q)}`);
    const active = document.activeElement;
    const typing = active === gq || active?.id === "hq" || active?.id === "aq" || active?.id === "gq";
    if (!typing && into === drop) {
      into.classList.add("hidden");
      return;
    }
    const rows = data.results || [];
    if (!rows.length) {
      into.innerHTML = `<p class="sub" style="padding:16px">Eşleşme yok.</p>`;
      into.classList.remove("hidden");
      if (into === drop) placeDrop(active);
      return;
    }
    into.innerHTML = rows.map(resultRow).join("");
    into.classList.remove("hidden");
    if (into === drop) placeDrop(active);
  } catch (ex) {
    into.innerHTML = `<p class="sub" style="padding:16px">${esc(ex.message || "Arama şu an kullanılamıyor.")}</p>`;
    into.classList.remove("hidden");
    if (into === drop) placeDrop(document.activeElement);
  }
}

gq.addEventListener("input", () => {
  clearTimeout(searchClock);
  searchClock = setTimeout(() => runSearch(gq.value.trim(), drop), 160);
});
document.getElementById("global-search").addEventListener("submit", (e) => {
  e.preventDefault();
  hideDrop();
  openFromQuery(gq.value.trim());
});
drop.addEventListener("click", (e) => {
  const a = e.target.closest("a");
  if (!a) return;
  hideDrop();
  gq.value = "";
});
document.addEventListener("click", (e) => {
  const hq = document.getElementById("hq");
  const aq = document.getElementById("aq");
  if (!drop.contains(e.target) && e.target !== gq && e.target !== hq && e.target !== aq) hideDrop();
});
window.addEventListener("resize", () => {
  if (!drop.classList.contains("hidden")) placeDrop();
});

function fmtCount(n) {
  if (n == null || n === "") return "—";
  return Number(n).toLocaleString("tr-TR");
}

function properCase(value) {
  const s = String(value ?? "").trim();
  if (!s) return "";
  if (s !== s.toLowerCase()) return s;
  return s.replace(/(^|[\s\-/,])(\S)/g, (_, a, b) => a + b.toLocaleUpperCase("tr-TR"));
}

function footLabel(value) {
  const key = String(value || "").toLowerCase().replace(/\s+/g, " ").trim();
  if (key.includes("right") || key === "sağ" || key === "sag") return "Sağ";
  if (key.includes("left") || key === "sol") return "Sol";
  if (key.includes("both") || key.includes("two") || key.includes("çift") || key.includes("iki")) return "İki ayak";
  if (!key || key === "unknown" || key === "—") return "—";
  return properCase(value);
}

function rowBlock(title, href, items) {
  if (!items || !items.length) return "";
  const link = href ? `<a href="${href}">Tümü</a>` : "";
  return `<div class="row-head"><h2>${esc(title)}</h2>${link}</div>
    <div class="scroll">${items.map(tile).join("")}</div>`;
}

function liveWhen(iso) {
  if (!iso) return "";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "";
  return d.toLocaleTimeString("tr-TR", { hour: "2-digit", minute: "2-digit" });
}

function leagueCrest(l) {
  const src = l.crest || "";
  const mark = esc(l.mark || l.id || "");
  const square = l.flag === "ch" || l.id === "C1";
  const cls = square ? "crest flag-ch" : "crest";
  const href = square ? "https://flagcdn.com/ch.svg" : src;
  if (!href) return `<span class="mark">${mark}</span>`;
  return `<span class="${cls}"><img src="${esc(href)}" alt="" width="36" height="36" onerror="this.replaceWith(Object.assign(document.createElement('span'),{className:'mark',textContent:'${mark}'}))"></span>`;
}

function renderHome(pulse) {
  const featured = (pulse.featured && pulse.featured.length) ? pulse.featured : (pulse.leagues || []).slice(0, 10);
  view.innerHTML = `
    <section class="panel hero home-hero">
      <h1 class="brand-mark">Aurea</h1>
      <form class="spotlight" id="home-search" autocomplete="off">
        <input id="hq" type="search" placeholder="Oyuncu ara" />
      </form>
      <p class="lede home-lede">Transfermarkt ve Aurea değeri.</p>
      <div class="chips">
        ${featured.map((l) => `<a class="chip" href="#/lig/${esc(l.id)}">${leagueCrest(l)}${esc(l.name)}</a>`).join("")}
      </div>
    </section>
    ${rowBlock("En yüksek tutar", "#/piyasa", pulse.stars)}
    ${rowBlock("Ucuz etiket", "#/piyasa?direction=dusuk", pulse.undervalued)}
    ${rowBlock("Pahalı etiket", "#/piyasa?direction=yuksek", pulse.overvalued)}
    ${rowBlock("Süper Lig", "#/lig/TR1", pulse.superlig)}
    ${rowBlock("Brasileirão", "#/lig/BRA1", pulse.brazil)}
    ${rowBlock("Liga Profesional", "#/lig/ARG1", pulse.argentina)}
    ${rowBlock("MLS", "#/lig/MLS1", pulse.mls)}
    ${rowBlock("J1 League", "#/lig/JAP1", pulse.japan)}
  `;
  document.getElementById("home-search").addEventListener("submit", (e) => {
    e.preventDefault();
    hideDrop();
    openFromQuery(document.getElementById("hq").value.trim());
  });
  const hq = document.getElementById("hq");
  hq.addEventListener("input", () => {
    clearTimeout(searchClock);
    searchClock = setTimeout(() => runSearch(hq.value.trim(), drop), 160);
  });
  hq.focus();
}

async function renderSearch(gen) {
  const q = queryFromHash().q || "";
  view.innerHTML = `
    <section class="hero center search-hero panel">
      <p class="kicker">Arama</p>
      <h1>Oyuncu</h1>
      <form id="ara-form"><input id="aq" value="${esc(q)}" placeholder="İsim" /></form>
    </section>
    <div id="ara-results" class="list"></div>
  `;
  const input = document.getElementById("aq");
  const box = document.getElementById("ara-results");
  const paint = (rows) => {
    box.innerHTML = rows.length
      ? listHead() + rows.map(playerRow).join("")
      : `<p class="sub">Sonuç yok.</p>`;
  };
  const go = async (submit) => {
    const query = input.value.trim();
    if (query.length < 2) { box.innerHTML = `<p class="sub">En az iki harf yazın.</p>`; return; }
    box.innerHTML = waitScreen("Aranıyor", "Transfermarkt ve ambar taranıyor.");
    try {
      const data = await api(`/api/search?q=${encodeURIComponent(query)}`);
      if (gen !== viewGen) return;
      const rows = data.results || [];
      if (submit) {
        const hit = bestMatch(rows, query);
        if (hit?.player_id) {
          location.hash = playerHref(hit.player_id);
          return;
        }
      }
      paint(rows);
    } catch (ex) {
      if (gen !== viewGen) return;
      box.innerHTML = `<p class="error">${esc(ex.message || "Arama şu an kullanılamıyor.")}</p>`;
    }
  };
  input.addEventListener("input", () => {
    clearTimeout(searchClock);
    searchClock = setTimeout(() => go(false), 180);
  });
  document.getElementById("ara-form").addEventListener("submit", (e) => {
    e.preventDefault();
    go(true);
  });
  if (q) go(false);
  input.focus();
}

async function renderMarket(preset = {}, gen) {
  const q = { ...queryFromHash(), ...preset };
  const params = new URLSearchParams();
  ["league", "position", "direction", "q", "sort", "order", "page"].forEach((k) => { if (q[k]) params.set(k, q[k]); });
  const data = await api(`/api/market?${params.toString()}`);
  if (gen !== viewGen) return;
  const leagues = (await api("/api/leagues")).leagues || [];
  if (gen !== viewGen) return;
  const leagueName = q.league ? (leagues.find((l) => l.id === q.league)?.name || q.league) : "Tüm ligler";
  view.innerHTML = `
    <section class="panel page-head">
      <h1>${esc(leagueName)}</h1>
      <p class="lede">${esc(fmtCount(data.total))} oyuncu</p>
    </section>
    <form class="filters" id="filt">
      <input name="q" value="${esc(q.q || "")}" placeholder="İsim" />
      <select name="league"><option value="">Ligler</option>${leagues.map((l) => `<option value="${esc(l.id)}" ${q.league === l.id ? "selected" : ""}>${esc(l.name)}</option>`).join("")}</select>
      <select name="position">
        <option value="">Mevki</option>
        <option value="Goalkeeper" ${q.position === "Goalkeeper" ? "selected" : ""}>Kaleci</option>
        <option value="Defender" ${q.position === "Defender" ? "selected" : ""}>Defans</option>
        <option value="Midfield" ${q.position === "Midfield" ? "selected" : ""}>Orta saha</option>
        <option value="Attack" ${q.position === "Attack" ? "selected" : ""}>Forvet</option>
      </select>
      <select name="direction">
        <option value="">Fiyat</option>
        <option value="dusuk" ${q.direction === "dusuk" ? "selected" : ""}>Ucuz</option>
        <option value="yuksek" ${q.direction === "yuksek" ? "selected" : ""}>Pahalı</option>
        <option value="denge" ${q.direction === "denge" ? "selected" : ""}>Dengeli</option>
      </select>
      <select name="sort">
        <option value="true_value">Aurea değeri</option>
        <option value="tm" ${q.sort === "tm" ? "selected" : ""}>Transfermarkt</option>
        <option value="gap" ${q.sort === "gap" ? "selected" : ""}>Fark</option>
        <option value="goals" ${q.sort === "goals" ? "selected" : ""}>Gol</option>
      </select>
      <select name="order">
        <option value="desc" ${!q.order || q.order === "desc" ? "selected" : ""}>Yüksekten düşüğe</option>
        <option value="asc" ${q.order === "asc" ? "selected" : ""}>Düşükten yükseğe</option>
      </select>
      <button class="btn" type="submit">Uygula</button>
    </form>
    <div class="list">
      ${listHead()}${(data.items || []).map(playerRow).join("")}
    </div>
    <div class="pager">
      <button class="btn ghost" id="prev" ${data.page <= 1 ? "disabled" : ""}>Önceki</button>
      <span>${data.page} / ${data.pages}</span>
      <button class="btn ghost" id="next" ${data.page >= data.pages ? "disabled" : ""}>Sonraki</button>
    </div>
  `;
  document.getElementById("filt").addEventListener("submit", (e) => {
    e.preventDefault();
    location.hash = `#/piyasa?${new URLSearchParams(new FormData(e.target))}`;
  });
  document.getElementById("prev").onclick = () => {
    const next = new URLSearchParams(location.hash.split("?")[1] || "");
    next.set("page", String(Math.max(1, (data.page || 1) - 1)));
    location.hash = `#/piyasa?${next}`;
  };
  document.getElementById("next").onclick = () => {
    const next = new URLSearchParams(location.hash.split("?")[1] || "");
    next.set("page", String((data.page || 1) + 1));
    location.hash = `#/piyasa?${next}`;
  };
}

async function renderLeagues(gen) {
  const data = await api("/api/leagues");
  if (gen !== viewGen) return;
  const card = (l) => `
    <a class="league" href="#/lig/${esc(l.id)}">
      ${leagueCrest(l)}
      <div>
        <b>${esc(l.name)}</b>
        <span>${esc(fmtCount(l.players))} oyuncu${l.country ? " · " + esc(l.country) : ""}</span>
      </div>
    </a>`;
  view.innerHTML = `
    <section class="panel page-head">
      <h1>Ligler</h1>
    </section>
    <div class="leagues">${(data.leagues || []).map(card).join("")}</div>
  `;
}

async function renderPlayer(id, gen) {
  view.innerHTML = waitScreen("Oyuncu dosyası", "Transfermarkt ve Aurea değeri okunuyor.");
  const data = await api(`/api/players/${id}`);
  if (gen !== viewGen) return;
  const p = data.player || {};
  const r = data.report || {};
  const live = data.live || {};
  const injuries = live.injuries || [];
  const ident = r.identity || {};
  const when = liveWhen(p.live_fetched_at || live.fetched_at);
  const move = tmMove(live.market_history);
  const season = live.season_totals || {};
  const seasonLine = season.apps
    ? `${season.apps} maç · ${season.goals || 0} gol · ${season.assists || 0} asist · ${fmtCount(season.minutes)} dk`
    : "";
  const foot = footLabel(p.foot);
  const facts = [
    fact("Boy", p.height_in_cm ? `${p.height_in_cm} cm` : ""),
    fact("Ayak", foot === "—" ? "" : foot),
    fact("Uyruk", properCase(p.nationality)),
    fact("Milli maç", p.intl_caps),
    fact("Milli gol", p.intl_goals),
    fact("Sözleşme", p.contract_years != null ? `${Number(p.contract_years).toFixed(1).replace(".", ",")} yıl` : ""),
    fact("Bu sezon", seasonLine),
  ].filter(Boolean).join("");
  const table = (data.season_table || []).filter((row) => Number(row.apps) > 0);
  const seasonHtml = table.length
    ? `<div class="group"><h3>Sezon</h3>
        <article><table class="mini">
          <thead><tr><th>Turnuva</th><th>Maç</th><th>Gol</th><th>Asist</th><th>Dakika</th></tr></thead>
          <tbody>${table.map((row) => `<tr>
            <td>${esc(row.competition || "—")}${row.season ? ` · ${esc(row.season)}` : ""}</td>
            <td>${esc(row.apps)}</td>
            <td>${esc(row.goals)}</td>
            <td>${esc(row.assists)}</td>
            <td>${esc(fmtCount(row.minutes))}</td>
          </tr>`).join("")}</tbody>
        </table></article>
      </div>`
    : "";
  view.innerHTML = `
    <section class="panel player-head">
      ${live.fetched_at ? `<div class="live-badge"><i></i> Canlı${when ? " · " + esc(when) : ""}</div>` : ""}
      <p class="kicker">${esc(ident.position || p.position || "")}${ident.league || p.league ? " · " + esc(ident.league || p.league) : ""}</p>
      <h1>${esc(tidyName(p.name))}</h1>
      <p class="sub">${esc(p.club || "—")}${p.shirt ? " · #" + esc(p.shirt) : ""}${p.age ? " · " + esc(p.age) + " yaş" : ""}</p>
      <div class="facts">${facts}</div>
    </section>
    <article class="read ${esc(p.direction || r.direction || "")}">
      <p class="kicker">${esc(gapWord(p.direction || r.direction))}</p>
      <h2>${esc(r.headline || "")}</h2>
      <p>${esc(r.summary || "")}</p>
    </article>
    <div class="duo">
      <div class="price-card">
        <div class="k">Transfermarkt</div>
        <div class="n">${esc(p.tm_label)}</div>
        <div class="hint">${move ? esc(move) : "Piyasa etiketi"}</div>
      </div>
      <div class="price-card hero">
        <div class="k">Aurea değeri</div>
        <div class="n">${esc(p.true_label)}</div>
        ${pill(p.direction, p.gap_label)}
        <div class="hint">Dakika, yaş ve lig</div>
      </div>
    </div>
    <div class="metrics">
      ${(r.metrics || []).filter((m) => m.k !== "Aralık" && m.k !== "Sözleşme").map((m) => `<div class="metric"><span>${esc(m.k)}</span><b>${esc(m.v)}</b></div>`).join("")}
    </div>
    <div class="group">
      <h3>Etiket eğrisi</h3>
      <article>${sparkline(live.market_history)}${histTable(live.market_history)}</article>
    </div>
    <div class="group">
      <h3>Analiz</h3>
      ${(r.sections || []).filter((s) => s.id !== "sofa" && s.title !== "Sofascore").map((s) => {
        const paras = (s.paragraphs && s.paragraphs.length) ? s.paragraphs : (s.body ? [s.body] : []);
        return `<article><b>${esc(s.title)}</b>${paras.map((t) => `<p>${esc(t)}</p>`).join("")}</article>`;
      }).join("")}
    </div>
    ${seasonHtml}
    ${injuries.length ? `<div class="group"><h3>Sakatlık</h3>${injuries.map((inj) => `<article><b>${esc(inj.injury)}</b><p>${esc(inj.season)} · ${esc(fmtDate(inj.fromDate))} – ${esc(fmtDate(inj.untilDate) || "devam")} · ${esc(inj.days)} gün</p></article>`).join("")}</div>` : ""}
    <div class="group">
      <h3>Emsaller</h3>
      <div class="comps">
        ${(data.similar || []).map((s) => `<a class="comp" href="${playerHref(s.player_id)}"><b>${esc(tidyName(s.name))}</b><div class="comp-meta"><span>${esc(s.club || "")}${s.age ? " · " + esc(Math.round(s.age)) + " yaş" : ""}</span><span>${esc(s.true_label || s.tm_label || "")}</span></div></a>`).join("")}
      </div>
    </div>
  `;
}

function fmtPts(n) {
  if (n == null || n === "") return "—";
  return Number(n).toLocaleString("tr-TR", { maximumFractionDigits: 1 });
}

function fxName(p) {
  return tidyName((p && (p.display_name || p.player)) || "");
}

function fxMatch(item, squad) {
  if (item && typeof item === "object" && (item.position || item.display_name || item.player)) return item;
  const name = String(typeof item === "string" ? item : (item?.display_name || item?.player || ""));
  const n = foldTr(tidyName(name));
  return (squad || []).find((p) => {
    const a = foldTr(fxName(p));
    const b = foldTr(tidyName(p.player || ""));
    return a === n || b === n;
  }) || { display_name: tidyName(name), player: name, position: "MF", team: "" };
}

function fxShirt(p, capName) {
  const name = fxName(p);
  const cap = String(p.player || "") === capName || String(p.display_name || "") === capName || foldTr(name) === foldTr(tidyName(capName));
  const pts = p.projected_pts != null ? Number(p.projected_pts).toFixed(1) : "—";
  const price = p.price_m != null ? `${Number(p.price_m).toFixed(1)} mn` : "";
  const opp = p.fixture_opponent ? "vs " + p.fixture_opponent : "";
  return `<a class="shirt${cap ? " captain" : ""}" href="#/ara?q=${encodeURIComponent(name)}">
    <b>${esc(name)}</b>
    <span>${esc(properCase(p.team) || "")}${opp ? " · " + esc(opp) : ""}</span>
    <span>${esc(price)}${price && pts ? " · " : ""}${esc(pts)} p${cap ? " · K" : ""}</span>
  </a>`;
}

function fxShape(form) {
  const parts = String(form || "").replace("–", "-").split("-").map((n) => Number(n)).filter((n) => n > 0);
  if (parts.length === 3) return { GK: 1, DF: parts[0], MF: parts[1], FW: parts[2] };
  if (parts.length >= 4) return { GK: 1, DF: parts[0], MF: parts.slice(1, -1).reduce((a, b) => a + b, 0), FW: parts[parts.length - 1] };
  return { GK: 1, DF: 4, MF: 3, FW: 3 };
}

function fxKey(p) {
  return foldTr(String((p && (p.player || p.display_name)) || ""));
}

function layoutSquad(squad, formation) {
  const need = fxShape(formation);
  const pool = [...(squad || [])].filter(Boolean).sort((a, b) => Number(b.projected_pts || 0) - Number(a.projected_pts || 0));
  const used = new Set();
  const xi = [];
  const take = (pos, n) => {
    for (const p of pool) {
      if (xi.filter((x) => (x.position || "") === pos).length >= n) break;
      const key = fxKey(p);
      if (!key || used.has(key)) continue;
      if ((p.position || "") === pos) {
        xi.push(p);
        used.add(key);
      }
    }
  };
  take("GK", need.GK);
  take("DF", need.DF);
  take("MF", need.MF);
  take("FW", need.FW);
  const slots = need.GK + need.DF + need.MF + need.FW;
  for (const p of pool) {
    if (xi.length >= slots) break;
    const key = fxKey(p);
    if (key && !used.has(key)) {
      xi.push(p);
      used.add(key);
    }
  }
  const bench = pool.filter((p) => !used.has(fxKey(p)));
  return { xi, bench };
}

function fxSolidXi(list) {
  return Array.isArray(list) && list.length && typeof list[0] === "object" && (list[0].position || list[0].player || list[0].display_name);
}

function orderBench(squad, xiList, originalBench) {
  const used = new Set((xiList || []).map(fxKey).filter(Boolean));
  const out = [];
  const seen = new Set();
  for (const p of originalBench || []) {
    const k = fxKey(p);
    if (k && !used.has(k) && !seen.has(k)) {
      out.push(p);
      seen.add(k);
    }
  }
  for (const p of squad || []) {
    const k = fxKey(p);
    if (k && !used.has(k) && !seen.has(k)) {
      out.push(p);
      seen.add(k);
    }
  }
  return out;
}

function fxPitchHtml(xiList, benchList, capName, squad) {
  const xi = (xiList || []).map((x) => fxMatch(x, squad));
  const byPos = { FW: [], MF: [], DF: [], GK: [] };
  xi.forEach((p) => {
    const pos = p.position || "";
    if (byPos[pos]) byPos[pos].push(p);
    else byPos.MF.push(p);
  });
  const row = (list) => list.length ? `<div class="pitch-row">${list.map((p) => fxShirt(p, capName)).join("")}</div>` : "";
  const bench = (benchList || []).map((x) => fxMatch(x, squad));
  const benchHtml = bench.length
    ? `<div class="group"><h3>Yedekler</h3>
        <div class="bench-list">${bench.map((p) => `<a class="bench-who" href="#/ara?q=${encodeURIComponent(fxName(p))}">
            <b>${esc(fxName(p))}</b>
            <span>${esc(properCase(p.team) || "")} · ${esc(p.position || "")}${p.projected_pts != null ? " · " + Number(p.projected_pts).toFixed(1) + " p" : ""}</span>
          </a>`).join("")}</div>
      </div>`
    : "";
  return { pitch: `${row(byPos.FW)}${row(byPos.MF)}${row(byPos.DF)}${row(byPos.GK)}`, benchHtml };
}

function fxBindShirts() {
  view.querySelectorAll(".shirt, .bench-who").forEach((a) => {
    a.addEventListener("click", (e) => {
      e.preventDefault();
      hideDrop();
      const href = a.getAttribute("href") || "";
      const q = new URLSearchParams(href.split("?")[1] || "").get("q") || "";
      if (q) openFromQuery(q);
    });
  });
}

async function renderFantasy(gen) {
  clearTimeout(fantasyClock);
  const pack = await api("/api/fantasy");
  if (gen !== viewGen) return;
  const st = pack.status || {};
  const account = pack.account || {};
  const payload = pack.payload;
  const running = !!st.running || st.phase === "run";
  const logged = !!(account && account.ok);
  if (!logged) {
    view.innerHTML = `
      <section class="panel auth-card">
        <h1>TFF Fantezi Lig</h1>
        <p class="lede">Hesabınıza girin. Kadro bu oturumda hesaplanır.</p>
        <form id="fx-login" class="auth-form">
          <label>E-posta<input name="email" type="email" autocomplete="username" required></label>
          <label>Şifre<input name="password" type="password" autocomplete="current-password" required></label>
          <button class="btn" type="submit">Giriş</button>
        </form>
        <p id="fx-login-err" class="error hidden"></p>
      </section>
    `;
    document.getElementById("fx-login").addEventListener("submit", async (e) => {
      e.preventDefault();
      const form = new FormData(e.target);
      const err = document.getElementById("fx-login-err");
      err.classList.add("hidden");
      const btn = e.target.querySelector("button");
      btn.disabled = true;
      try {
        await api("/api/fantasy/login", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ email: form.get("email"), password: form.get("password") }),
        });
        render();
      } catch (ex) {
        err.textContent = ex.message || "Giriş başarısız.";
        err.classList.remove("hidden");
        btn.disabled = false;
      }
    });
    return;
  }
  const result = payload?.result || {};
  const xi = result.xi || [];
  const bench = result.bench || [];
  const squad = result.squad || [...xi, ...bench];
  const capName = String(result.captain?.player || result.captain?.display_name || "");
  const card = payload?.manager_card || {};
  const analysis = payload?.analysis || [];
  const comps = payload?.formation_comparisons || [];
  const watch = payload?.watch || [];
  const firstPaint = fxPitchHtml(xi, bench, capName, squad);
  view.innerHTML = `
    <section class="panel account-strip">
      <div>
        <p class="kicker">Hesap</p>
        <h2>${esc(account.name || "TFF Fantezi Lig")}</h2>
        ${account.email ? `<p class="account-mail">${esc(account.email)}</p>` : ""}
      </div>
      <button class="btn ghost" id="fx-logout" type="button">Çıkış</button>
    </section>
    <section class="panel page-head fantasy-head">
      <div>
        <h1>TFF Fantezi Lig</h1>
        <p class="lede">${running ? esc(st.message || "Hesaplanıyor…") : (payload ? `Diziliş ${esc(result.formation || "")} · ${esc(Number(result.total_cost || 0).toFixed(1))} mn · kasa ${esc(Number(result.bank || 0).toFixed(1))} mn` : "Kadro henüz yok.")}</p>
      </div>
      <button class="btn" id="fx-run" type="button" ${running ? "disabled" : ""}>${running ? "Hesaplanıyor…" : (payload ? "Yeniden hesapla" : "Kadro hesapla")}</button>
    </section>
    ${running ? `<div class="progress fx-progress"><i style="width:${Math.round((st.progress || 0) * 100)}%"></i></div><p class="sub">${esc(st.message || "")}</p>` : ""}
    ${st.error ? `<p class="error">${esc(st.error)}</p>` : ""}
    ${payload ? `
      <div class="tri fantasy-meta">
        <div class="price-card hero"><div class="k">Beklenen puan</div><div class="n">${esc(Number(result.total_projected || 0).toFixed(1))}</div><div class="hint">İlk 11 ${esc(Number(result.xi_projected || 0).toFixed(1))} · yedek ${esc(Number(result.bench_projected || 0).toFixed(1))}</div></div>
        <div class="price-card"><div class="k">Kaptan</div><div class="n">${esc(tidyName(result.captain?.display_name || result.captain?.player || "—"))}</div><div class="hint">${esc(result.captain?.team || "")}${result.captain?.projected_pts != null ? " · " + Number(result.captain.projected_pts).toFixed(1) + " p" : ""}</div></div>
        <div class="price-card"><div class="k">Menajer kartı</div><div class="n">${esc(card.use ? (card.card || "Kullan") : "Kart yok")}</div><div class="hint">${esc(card.why || "Bu hafta kart önermiyoruz.")}</div></div>
      </div>
      ${comps.length ? `<div class="group"><h3>Diziliş karşılaştırması</h3>
        <div class="form-picks">${comps.map((c, i) => `<button type="button" class="form-pick${c.formation === result.formation ? " on" : ""}" data-i="${i}">
          <b>${esc(c.formation)}</b>
          <span>${esc(Number(c.expected_pts || 0).toFixed(1))} p${c.formation === result.formation ? " · seçildi" : ""}</span>
        </button>`).join("")}</div>
      </div>` : ""}
      <div class="pitch" id="fx-pitch">${firstPaint.pitch}</div>
      <div id="fx-bench">${firstPaint.benchHtml}</div>
      ${watch.length ? `<div class="group"><h3>Alınabilecekler</h3>
        <div class="comps">
          ${watch.map((p) => `<a class="comp" href="#/ara?q=${encodeURIComponent(fxName(p))}"><b>${esc(fxName(p))}</b><div class="comp-meta"><span>${esc(p.team || "")} · ${esc(p.position || "")}</span><span>${p.projected_pts != null ? Number(p.projected_pts).toFixed(1) + " p" : ""}</span></div></a>`).join("")}
        </div>
      </div>` : ""}
      ${analysis.length ? `<div class="group"><h3>Analiz</h3>${analysis.map((s) => `<article><b>${esc(s.title)}</b><p>${esc(s.body)}</p></article>`).join("")}</div>` : ""}
    ` : ""}
  `;
  const logout = document.getElementById("fx-logout");
  if (logout) {
    logout.addEventListener("click", async () => {
      await api("/api/fantasy/logout", { method: "POST" });
      render();
    });
  }
  const btn = document.getElementById("fx-run");
  if (btn) {
    btn.addEventListener("click", async () => {
      btn.disabled = true;
      try {
        await api("/api/fantasy/run", { method: "POST" });
      } catch (ex) {
        view.insertAdjacentHTML("afterbegin", `<p class="error">${esc(ex.message)}</p>`);
        btn.disabled = false;
        return;
      }
      render();
    });
  }
  const pitch = document.getElementById("fx-pitch");
  const benchBox = document.getElementById("fx-bench");
  let liveXi = xi;
  let liveBench = bench;
  const paintPitch = () => {
    const painted = fxPitchHtml(liveXi, liveBench, capName, squad);
    if (pitch) pitch.innerHTML = painted.pitch;
    if (benchBox) benchBox.innerHTML = painted.benchHtml;
    fxBindShirts();
  };
  view.querySelectorAll(".form-pick").forEach((el) => {
    el.addEventListener("click", (e) => {
      e.preventDefault();
      e.stopPropagation();
      const i = Number(el.getAttribute("data-i") || 0);
      const row = comps[i];
      if (!row) return;
      view.querySelectorAll(".form-pick").forEach((b) => b.classList.remove("on"));
      el.classList.add("on");
      if (row.formation === result.formation) {
        liveXi = xi;
        liveBench = bench;
      } else if (fxSolidXi(row.xi_players)) {
        liveXi = row.xi_players;
        liveBench = (row.bench_players && row.bench_players.length)
          ? row.bench_players
          : orderBench(squad, liveXi, bench);
      } else {
        const laid = layoutSquad(squad, row.formation);
        liveXi = laid.xi;
        liveBench = orderBench(squad, laid.xi, bench);
      }
      paintPitch();
    });
  });
  paintPitch();
  if (running) {
    fantasyClock = setTimeout(() => render(), 1400);
  }
}

async function renderSuperLig(gen) {
  view.innerHTML = waitScreen("Süper Lig", "Transferler okunuyor.");
  const data = await api("/api/superlig");
  if (gen !== viewGen) return;
  const paint = (pack) => {
    const deals = pack.deals || [];
    const clubs = pack.clubs || [];
    const counts = pack.counts || {};
    const when = liveWhen(pack.fetched_at);
    const labels = { firsat: "Fırsat", uygun: "Uygun", pahali: "Pahalı", riskli: "Riskli" };
    const stamp = (v) => {
      const key = v || "uygun";
      return `<span class="stamp ${esc(key)}">${esc(labels[key] || "Uygun")}</span>`;
    };
    const card = (d) => {
      return `<article class="deal ${esc(d.verdict || "uygun")}">
        <div class="deal-head-row">
          <div>
            ${stamp(d.verdict)}
            <b>${esc(tidyName(d.name))}</b>
            <p class="deal-clubs">${d.left ? `<span class="from">${esc(properCase(d.left))}</span><i>→</i>` : ""}<b class="to">${esc(properCase(d.club) || "")}</b></p>
            <p class="deal-meta">${[d.age ? esc(d.age) + " yaş" : "", d.position_tr ? esc(d.position_tr) : ""].filter(Boolean).join(" · ")}</p>
          </div>
          <div style="text-align:right">
            <div class="fee">${esc(d.fee_label || "—")}</div>
          </div>
        </div>
        <div class="deal-detail">
          <div class="deal-money">
            <div><span>Bedel</span><b>${esc(d.fee_label || "—")}</b></div>
            <div><span>Transfermarkt</span><b>${esc(d.tm_label || "—")}</b></div>
            <div><span>Aurea değeri</span><b>${esc(d.true_label || "—")}</b></div>
          </div>
          <p class="deal-head">${esc(d.headline || "")}</p>
          <p>${esc(d.body || "")}</p>
          <p style="margin-top:12px"><a href="${esc(d.href || "#/superlig")}">Oyuncu dosyası</a></p>
        </div>
      </article>`;
    };
    view.innerHTML = `
      <section class="panel hero sl-hero">
        <p class="kicker">Türkiye · ${esc(pack.season || "")}</p>
        <h1>Süper Lig</h1>
        <p class="lede">${esc(pack.season || "")} gelen transferler.</p>
      </section>
      <div class="sl-toolbar">
        <div class="deal-counts">
          ${["firsat","uygun","pahali","riskli"].map((k) => counts[k] ? `<span class="stamp ${k}">${esc(labels[k])} ${esc(counts[k])}</span>` : "").join("")}
        </div>
        <div>
          ${when ? `<span class="sub">Son tarama ${esc(when)}</span> ` : ""}
          <button class="btn ghost" id="sl-refresh" type="button">Yenile</button>
        </div>
      </div>
      ${clubs.length ? `<div class="spend-row">${clubs.slice(0, 8).map((c) => `<div class="spend-card"><img src="${esc(c.crest || "")}" alt="" width="28" height="28"><div><b>${esc(properCase(c.club))}</b><span>Harcama ${esc(c.spend_label || "—")}</span></div></div>`).join("")}</div>` : ""}
      <div class="deals">${deals.map(card).join("")}</div>
      ${pack.note ? `<p class="sub sl-note">${esc(pack.note)}</p>` : ""}
    `;
    view.querySelector(".deals")?.addEventListener("click", (e) => {
      if (e.target.closest("a")) return;
      const art = e.target.closest(".deal");
      if (art) art.classList.toggle("open");
    });
    const refresh = document.getElementById("sl-refresh");
    if (refresh) {
      refresh.addEventListener("click", async () => {
        view.innerHTML = waitScreen("Süper Lig", "Transferler yenileniyor.");
        try {
          const fresh = await api("/api/superlig?refresh=1");
          if (gen !== viewGen) return;
          paint(fresh);
        } catch (ex) {
          if (gen === viewGen) view.innerHTML = `<p class="error">${esc(ex.message)}</p>`;
        }
      });
    }
  };
  paint(data);
}

async function renderScout(gen) {
  view.innerHTML = waitScreen("Scout", "Ucuz etiket taranıyor.");
  const data = await api("/api/scout");
  if (gen !== viewGen) return;
  const positions = data.positions || [];
  const row = (p) => `
    <article class="scout-row">
      <button type="button" class="scout-head">
        <div class="who">
          <b>${esc(tidyName(p.name))}</b>
          <span>${esc(properCase(p.club) || "—")} · ${esc(p.band || p.league || "")}${p.age ? " · " + esc(p.age) + " yaş" : ""}</span>
        </div>
        <div>
          ${pill(p.direction, p.gap_label)}
          <div class="sub" style="text-align:right;margin-top:4px">${esc(p.true_label || "—")}</div>
        </div>
      </button>
      <div class="scout-body">
        <p class="deal-head">${esc(p.headline || "")}</p>
        ${(p.facts || []).length ? `<div class="scout-facts">${p.facts.map((f) => `<div><span>${esc(f.k)}</span><b>${esc(f.v)}</b></div>`).join("")}</div>` : ""}
        ${(p.paragraphs || (p.why ? [p.why] : [])).map((t) => `<p>${esc(t)}</p>`).join("")}
        <a href="${playerHref(p.player_id)}">Oyuncu dosyası</a>
      </div>
    </article>`;
  view.innerHTML = `
    <section class="panel page-head">
      <h1>Scout</h1>
      <p class="lede">Transfermarkt etiketi Aurea değerinin altında kalan oyuncular.</p>
    </section>
    ${positions.map((pos) => `
      <section class="scout-block">
        <h2>${esc(pos.name)}</h2>
        <div class="scout-list">${(pos.items || []).length ? pos.items.map(row).join("") : `<p class="sub">Bu mevkide eşik üstü isim yok.</p>`}</div>
      </section>`).join("")}
  `;
  view.querySelectorAll(".scout-row").forEach((art) => {
    art.querySelector(".scout-head")?.addEventListener("click", () => art.classList.toggle("open"));
  });
}

async function render() {
  const gen = ++viewGen;
  hideDrop();
  setActiveNav();
  const parts = hashParts();
  if (parts[0] === "yontem") {
    location.hash = "#/";
    return;
  }
  if (parts[0] === "fantezi") {
    boot.classList.add("hidden");
    boot.setAttribute("aria-hidden", "true");
    try { await renderFantasy(gen); }
    catch (err) { if (gen === viewGen) view.innerHTML = `<p class="error">${esc(err.message)}</p>`; }
    return;
  }
  const ok = await ensureReady();
  if (gen !== viewGen) return;
  if (!ok) return;
  try {
    if (parts[0] === "ara") await renderSearch(gen);
    else if (parts[0] === "superlig") await renderSuperLig(gen);
    else if (parts[0] === "scout") await renderScout(gen);
    else if (parts[0] === "piyasa") await renderMarket({}, gen);
    else if (parts[0] === "ligler") await renderLeagues(gen);
    else if (parts[0] === "lig" && parts[1]) await renderMarket({ league: parts[1] }, gen);
    else if (parts[0] === "oyuncu" && parts[1]) await renderPlayer(parts[1], gen);
    else {
      const pulse = await api("/api/pulse");
      if (gen !== viewGen) return;
      renderHome(pulse);
    }
  } catch (err) {
    if (gen === viewGen) view.innerHTML = `<p class="error">${esc(err.message)}</p>`;
  }
}

window.addEventListener("hashchange", render);
ensureReady().then((ok) => {
  const first = hashParts()[0];
  if (first === "fantezi") {
    render();
    return;
  }
  if (ok) render();
  else bootTimer = setInterval(async () => { if (await ensureReady()) render(); }, 1200);
});
