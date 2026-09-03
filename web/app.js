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
let searchAbort = null;
let fantasyClock;
let viewGen = 0;
let methodReturn = "/";
const apiMemo = new Map();
const apiInflight = new Map();
const API_MEMO_MS = 90000;

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

function clubTextMatch(name, q) {
  const nn = foldTr(name);
  const n = foldTr(q);
  if (!n) return true;
  if (nn === n || nn.startsWith(n)) return true;
  return nn.split(/[^a-z0-9]+/).some((w) => w && (w === n || (n.length >= 3 && w.startsWith(n))));
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
  syncNavSearch();
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
  const method = String(options?.method || "GET").toUpperCase();
  const cacheable = method === "GET" && !path.startsWith("/api/search") && !path.startsWith("/api/status") && !path.startsWith("/api/players/");
  if (cacheable) {
    const hit = apiMemo.get(path);
    if (hit && Date.now() - hit.t < API_MEMO_MS) return hit.data;
    const pending = apiInflight.get(path);
    if (pending) return pending;
  }
  const run = (async () => {
    try {
      const res = await fetch(path, options);
      if (options?.signal?.aborted) throw new DOMException("Aborted", "AbortError");
      const data = await res.json().catch(() => ({}));
      if (!res.ok) {
        const detail = data.detail;
        const msg = typeof detail === "string" ? detail : (data.message || `İstek başarısız (${res.status})`);
        throw new Error(msg);
      }
      if (cacheable) apiMemo.set(path, { t: Date.now(), data });
      return data;
    } finally {
      if (cacheable) apiInflight.delete(path);
    }
  })();
  if (cacheable) apiInflight.set(path, run);
  return run;
}

function prefetchTabs() {
  ["/api/pulse", "/api/clubs", "/api/leagues", "/api/scout", "/api/market?", "/api/yontem"].forEach((path) => {
    api(path).catch(() => {});
  });
}

function hashParts() {
  const raw = (location.hash || "#/").replace(/^#/, "");
  const [path] = raw.split("?");
  return path.split("/").filter(Boolean);
}

function queryFromHash() {
  const fromPath = location.search ? location.search.slice(1) : "";
  const fromHash = location.hash.split("?")[1] || "";
  return Object.fromEntries(new URLSearchParams(fromPath || fromHash));
}

function routeParts() {
  const path = (location.pathname || "/").replace(/^\/+|\/+$/g, "");
  const segs = path.split("/").filter(Boolean);
  if (segs[0] && spaRoots().has(segs[0])) return segs;
  return hashParts();
}

function slugify(text) {
  return foldTr(text).replace(/[^a-z0-9]+/g, "-").replace(/^-|-$/g, "").slice(0, 56);
}

function parsePlayerToken(token) {
  const m = String(token || "").match(/^(\d+)/);
  return m ? m[1] : "";
}

function spaRoots() {
  return new Set([
    "oyuncu", "kulup", "kulupler", "karsilastir", "yontem", "olcum",
    "fantezi", "superlig", "scout", "piyasa", "ligler", "lig", "ara",
  ]);
}

function normalizeRoute() {
  const segs = (location.pathname || "/").split("/").filter(Boolean);
  if (segs[0] && spaRoots().has(segs[0])) {
    if (location.hash && location.hash !== "#") {
      history.replaceState({}, "", `${location.pathname}${location.search}`);
    }
    return;
  }
  if ((location.hash || "").startsWith("#/")) {
    const rest = location.hash.slice(2);
    history.replaceState({}, "", rest ? `/${rest}` : "/");
  }
}

function setTitle(parts) {
  const first = parts[0] || "";
  const labels = {
    ara: "Arama",
    piyasa: "Oyuncular",
    ligler: "Ligler",
    lig: "Lig",
    oyuncu: "Oyuncu",
    kulupler: "Kulüpler",
    kulup: "Kulüp",
    karsilastir: "Karşılaştır",
    yontem: "Yöntem",
    fantezi: "TFF Fantezi Lig",
    superlig: "Kulüpler",
    scout: "Scout",
  };
  document.title = first && labels[first] ? `${labels[first]} · Aurea` : "Aurea";
}

function go(href, replace) {
  if (!href) return;
  if (href.startsWith("http") || href.startsWith("mailto:")) {
    location.href = href;
    return;
  }
  if (href.endsWith(".pdf") || href.startsWith("/api/") || href.startsWith("/static/")) {
    location.href = href;
    return;
  }
  if (href.startsWith("#")) {
    const rest = href.replace(/^#\/?/, "");
    go(rest ? `/${rest}` : "/", replace);
    return;
  }
  const next = href.startsWith("/") ? href : `/${href}`;
  if (`${location.pathname}${location.search}` === next) {
    render();
    return;
  }
  if (replace) history.replaceState({}, "", next);
  else history.pushState({}, "", next);
  render();
}

function syncMethodFab() {
  const fab = document.querySelector(".method-fab");
  if (!fab) return;
  const on = document.body.classList.contains("on-yontem");
  fab.classList.toggle("is-close", on);
  fab.textContent = on ? "×" : "?";
  fab.title = on ? "Kapat" : "Yöntem";
  fab.setAttribute("aria-label", on ? "Kapat" : "Yöntem");
  fab.setAttribute("href", on ? (methodReturn || "/") : "/yontem");
}

function syncNavSearch() {
  const form = document.getElementById("global-search");
  if (!form || !gq) return;
  const open = document.activeElement === gq || Boolean(gq.value.trim()) || !drop.classList.contains("hidden");
  form.classList.toggle("is-open", open);
}

function setActiveNav() {
  const first = routeParts()[0] || "";
  const home = !first;
  document.body.classList.toggle("on-home", home);
  document.body.classList.toggle("on-yontem", first === "yontem");
  syncMethodFab();
  const searchForm = document.getElementById("global-search");
  if (searchForm) searchForm.classList.remove("hidden");
  document.querySelectorAll(".links a, .dock a").forEach((a) => {
    const nav = a.getAttribute("data-nav");
    const href = (a.getAttribute("href") || "").replace("#/", "");
    const key = nav == null ? href : nav;
    const onHome = key === "" && !first;
    const onLig = key === "ligler" && (first === "ligler" || first === "lig");
    const onClub = key === "kulupler" && (first === "kulupler" || first === "kulup" || first === "superlig");
    const onFantezi = key === "fantezi" && first === "fantezi";
    const onScout = key === "scout" && first === "scout";
    const onAra = key === "ara" && first === "ara";
    a.classList.toggle("active", key === first || onHome || onLig || onClub || onFantezi || onScout || onAra);
  });
}

function playerHref(id, name) {
  if (id == null || id === "") return "/ara";
  const s = slugify(name || "");
  return `/oyuncu/${id}${s ? "-" + s : ""}`;
}

const RECENT_KEY = "aurea.recent";

function rememberPlayer(p) {
  if (!p || p.player_id == null) return;
  const item = {
    id: p.player_id,
    name: p.name,
    club: p.club,
    true_label: p.true_label,
    tm_label: p.tm_label || "",
    direction: p.direction,
    href: p.href || playerHref(p.player_id, p.name),
  };
  let rows = [];
  try { rows = JSON.parse(localStorage.getItem(RECENT_KEY) || "[]"); } catch { rows = []; }
  if (!Array.isArray(rows)) rows = [];
  rows = rows.filter((r) => String(r.id) !== String(item.id));
  rows.unshift(item);
  try { localStorage.setItem(RECENT_KEY, JSON.stringify(rows.slice(0, 8))); } catch { /* yok */ }
}

function recentPlayers() {
  try {
    const rows = JSON.parse(localStorage.getItem(RECENT_KEY) || "[]");
    return Array.isArray(rows) ? rows : [];
  } catch {
    return [];
  }
}

function gapWord(direction) {
  if (direction === "dusuk") return "Ucuz etiket";
  if (direction === "yuksek") return "Piyasa primi";
  if (direction === "denge") return "Uyumlu";
  return "Belirsiz";
}

function pill(direction, label) {
  const word = gapWord(direction);
  const extra = label && label !== "—" && label !== "denge" ? ` · ${label}` : "";
  return `<span class="pill ${esc(direction || "belirsiz")}">${esc(word)}${esc(extra)}</span>`;
}

function tile(p) {
  return `<a class="tile ${esc(p.direction || "")}" href="${esc(p.href || playerHref(p.player_id, p.name))}">
    ${pill(p.direction, p.gap_label)}
    <div class="who">${esc(tidyName(p.name))}</div>
    <div class="sub">${esc(metaJoin(clubName(p.club), p.position || "") || "—")}</div>
    <div class="price">${esc(p.true_label || "—")}<span>Transfermarkt ${esc(p.tm_label || "—")}</span></div>
  </a>`;
}

function playerRow(p) {
  return `<a class="row" href="${esc(p.href || playerHref(p.player_id, p.name))}">
    <div class="who-col"><div class="name">${esc(tidyName(p.name))}</div><div class="meta">${esc(metaJoin(p.position || "", p.age != null && p.age !== "" ? p.age + " yaş" : ""))}</div></div>
    <div class="club-col" title="${esc(clubName(p.club) || "")}">${esc(clubName(p.club) || "—")}</div>
    <div class="league-col" title="${esc(p.league || "")}">${esc(p.league || "—")}</div>
    <div class="num">${esc(p.true_label || p.tm_label || "—")}${p.tm_label ? `<div class="meta">TM ${esc(p.tm_label)}</div>` : ""}</div>
    ${pill(p.direction, p.gap_label || "")}
  </a>`;
}

function tenureRow(p) {
  const mins = p.minutes_365 != null && p.minutes_365 !== "" ? `${fmtCount(p.minutes_365)} dk` : "";
  const arrived = p.arrived ? fmtDate(p.arrived) : "";
  const meta = metaJoin(p.position || "", p.age != null && p.age !== "" ? `${p.age} yaş` : "", mins, arrived ? `geliş ${arrived}` : "");
  const pid = p.player_id != null ? String(p.player_id) : "";
  return `<article class="tenure-row" data-pid="${esc(pid)}">
    <button type="button" class="tenure-head"${pid ? "" : " disabled"}>
      <div class="who-col"><div class="name">${esc(tidyName(p.name))}</div><div class="meta">${esc(meta || "—")}</div></div>
      <div class="num">${esc(p.true_label || p.tm_label || "—")}${p.tm_label ? `<div class="meta">TM ${esc(p.tm_label)}</div>` : ""}</div>
      ${pill(p.direction, p.gap_label || "")}
    </button>
    <div class="tenure-body" hidden></div>
  </article>`;
}

function tenureBlock(title, rows) {
  if (!rows || !rows.length) return "";
  return `<div class="group"><h3>${esc(title)}</h3><div class="tenure-list">${rows.map(tenureRow).join("")}</div></div>`;
}

function tenureCopy(p) {
  const joined = (p && p.arrived) || "";
  const joinedLabel = fmtDate(joined);
  const mins = Number(p && p.minutes_365) || 0;
  const dir = (p && p.direction) || "";
  const ageDays = daysSince(joined);
  const bits = [];
  if (joinedLabel) bits.push(`Kulübe geliş ${joinedLabel}.`);
  else bits.push("Bu kadroda geliş tarihi henüz okunamadı.");
  if (ageDays != null && ageDays >= 0 && ageDays < 50) {
    bits.push("Geliş yakın; kulüp içi verim için henüz erken.");
  } else if (mins >= 1800 && dir === "dusuk") {
    bits.push(`${fmtCount(mins)} dakika ve ucuz etiket: kulüpte verimli görünüyor.`);
  } else if (mins >= 1800 && dir === "yuksek") {
    bits.push(`${fmtCount(mins)} dakika var; piyasa primi duruyor, etiket üretimin önünde.`);
  } else if (mins >= 1800) {
    bits.push(`${fmtCount(mins)} dakika: kadroda düzenli kullanılıyor.`);
  } else if (ageDays != null && ageDays > 120 && mins < 600) {
    bits.push("Dakika düşük; rotasyon veya uyum baskın olabilir.");
  } else if (mins) {
    bits.push(`Son 12 ayda ${fmtCount(mins)} dakika.`);
  }
  return bits;
}

function toggleTenure(row, p) {
  const pid = row.getAttribute("data-pid");
  const body = row.querySelector(".tenure-body");
  if (!pid || !body) return;
  if (row.classList.contains("open")) {
    row.classList.remove("open");
    body.hidden = true;
    return;
  }
  row.classList.add("open");
  body.hidden = false;
  if (body.dataset.ready === "1") return;
  const paras = tenureCopy(p || {}).map((t) => `<p>${esc(t)}</p>`).join("");
  const href = (p && p.href) || playerHref(pid, p && p.name);
  body.innerHTML = `${paras}<p><a href="${esc(href)}">Oyuncu dosyası</a></p>`;
  body.dataset.ready = "1";
}

function bindTenure(root, rows) {
  const byId = new Map((rows || []).filter((p) => p && p.player_id != null).map((p) => [String(p.player_id), p]));
  root.querySelectorAll(".tenure-row").forEach((row) => {
    row.querySelector(".tenure-head")?.addEventListener("click", () => {
      const p = byId.get(row.getAttribute("data-pid")) || {};
      toggleTenure(row, p);
    });
  });
}

function careerCopy(s) {
  const club = clubName(s && s.club);
  const arrived = fmtDate(s && s.arrived);
  const from = s && s.from_club ? clubName(s.from_club) : "";
  const bits = [];
  if (s && s.kind === "baslangic") {
    bits.push(`${club} kariyer kaydındaki ilk kulüp.`);
    if (s.departed) bits.push(`Kayıt, ${fmtDate(s.departed)} tarihindeki ilk transferle kapanır.`);
  } else if (arrived) {
    let how = "geldi";
    if (s.kind === "kiralik") how = "kiralık olarak geldi";
    else if (s.kind === "bedelsiz") how = "bedelsiz geldi";
    else if (s.kind === "donus") how = "kiralık süresinin sonunda döndü";
    else if (s.kind === "bedel") how = "satın alma ile geldi";
    const via = from && from !== "Kulüpsüz" ? ` ${from} kulübünden` : "";
    bits.push(`${club} kadrosuna ${arrived} tarihinde${via} ${how}.`);
  }
  if (s && s.kind !== "baslangic" && s.ongoing && s.duration_label) bits.push(`Kulüpteki süre ${s.duration_label}; dönem devam ediyor.`);
  else if (s && s.kind !== "baslangic" && s.duration_label && s.departed) bits.push(`Kulüpteki süre ${s.duration_label}; ayrılış ${fmtDate(s.departed)}.`);
  else if (s && s.kind !== "baslangic" && s.duration_label) bits.push(`Kulüpteki süre ${s.duration_label}.`);
  if (s && s.market_label) bits.push(`Transfer günündeki Transfermarkt etiketi ${s.market_label}.`);
  if (s && s.wage_annual) {
    bits.push(`Açık rapordaki taban maaş ${s.wage_label}${s.wage_weekly_label ? ` (${s.wage_weekly_label})` : ""}.`);
    if (s.wage_total_label) bits.push(`Sözleşme süresine göre maaş yükü ${s.wage_total_label}.`);
    if (s && s.wage_bonus_label) bits.push(`Yıllık tutara ${s.wage_bonus_label} bonus dahil.`);
    if (s.total_scope === "tam") bits.push("Toplam maliyet, açıklanan bonservis ile bu maaş yükünün toplamıdır.");
    else bits.push("Bonservis bu dönem için yok veya açıklanmadı; toplam yalnızca maaş yüküdür.");
  } else {
    bits.push("Maaş bu dönem için açık raporda yok. Toplam maliyet yalnızca açıklanan bonservisi kapsar.");
  }
  return bits;
}

function careerWindow(s) {
  const a = fmtDate(s && s.arrived);
  const b = s && s.ongoing ? "devam ediyor" : fmtDate(s && s.departed);
  if (!a && b) return `${b} öncesi`;
  if (a && b) return `${a} — ${b}`;
  return a || b || "";
}

function careerRow(s) {
  const meta = [s.kind_label, careerWindow(s), s.duration_label].filter(Boolean).join(" · ");
  const crest = s.crest
    ? `<img class="career-crest" src="${esc(s.crest)}" alt="" />`
    : `<span class="career-crest empty" aria-hidden="true"></span>`;
  return `<div class="tenure-row career-row">
    <button type="button" class="tenure-head">
      ${crest}
      <div class="who-col"><div class="name">${esc(clubName(s.club))}</div><div class="meta">${esc(meta || "—")}</div></div>
      <div class="num">${esc(s.fee_label || "—")}</div>
    </button>
    <div class="tenure-body" hidden></div>
  </div>`;
}

function careerBlock(career) {
  if (!career) return "";
  const blocks = [
    ["Güncel kulüp", career.current || []],
    ["Eski kulüpler", career.former || []],
    ["Altyapı", career.youth || []],
  ].filter((pair) => pair[1].length);
  if (!blocks.length) return "";
  const lede = career.fee_sum_label
    ? `Açıklanan kariyer bonservisi ${career.fee_sum_label}. Kulübe basın; bonservis, süre ve toplam maliyet açılır.`
    : "Kulübe basın; bonservis, süre ve toplam maliyet açılır.";
  return `<div class="career-wrap print-hide">${blocks.map(([title, rows], i) =>
    `<div class="group"><h3>${esc(title)}</h3>${i === 0 ? `<p class="sub career-lede">${esc(lede)}</p>` : ""}<div class="tenure-list career-list">${rows.map(careerRow).join("")}</div></div>`
  ).join("")}</div>`;
}

function toggleCareer(row, s) {
  const body = row.querySelector(".tenure-body");
  if (!body) return;
  if (row.classList.contains("open")) {
    row.classList.remove("open");
    body.hidden = true;
    return;
  }
  row.classList.add("open");
  body.hidden = false;
  if (body.dataset.ready === "1") return;
  const dur = [s.duration_label || "", s.ongoing ? "devam ediyor" : ""].filter(Boolean).join(" · ");
  const money = `<div class="deal-money">
      <div><span>Bonservis</span><b>${esc(s.fee_label || "—")}</b></div>
      <div><span>Maaş</span><b>${esc(s.wage_label || "Açıklanmadı")}</b></div>
      <div><span>Süre</span><b>${esc(dur || "—")}</b></div>
      <div><span>Toplam maliyet</span><b>${esc(s.total_label || "—")}</b></div>
    </div>`;
  const paras = careerCopy(s || {}).map((t) => `<p>${esc(t)}</p>`).join("");
  const link = s && s.href ? `<p><a href="${esc(s.href)}">Kulüp sayfası</a></p>` : "";
  body.innerHTML = `${money}${paras}${link}`;
  body.dataset.ready = "1";
}

function bindCareer(root, career) {
  const all = [...(career && career.current || []), ...(career && career.former || []), ...(career && career.youth || [])];
  root.querySelectorAll(".career-row").forEach((row, i) => {
    row.querySelector("img.career-crest")?.addEventListener("error", (e) => {
      const img = e.target;
      img.classList.add("empty");
      img.removeAttribute("src");
    });
    row.querySelector(".tenure-head")?.addEventListener("click", () => {
      toggleCareer(row, all[i] || {});
    });
  });
}

function listHead() {
  return `<div class="list-head"><span>Oyuncu</span><span>Takım</span><span class="h-league">Lig</span><span>Aurea</span><span></span></div>`;
}

function resultRow(p) {
  if (p.kind === "club") {
    return `<a href="${esc(p.href || "/kulupler")}">
      <div><div class="name">${esc(clubName(p.name))}</div><div class="meta">Kulüp${p.league ? " · " + esc(p.league) : ""}</div></div>
      <div class="num">${esc(p.true_label || p.tm_label || "—")}</div>
    </a>`;
  }
  return `<a href="${esc(p.href || playerHref(p.player_id, p.name))}">
    <div><div class="name">${esc(tidyName(p.name))}</div><div class="meta">${esc(metaJoin(clubName(p.club) || "", p.position || ""))}</div></div>
    <div class="num">${esc(p.true_label || p.tm_label || "—")}</div>
  </a>`;
}

function worthOf(r) {
  const a = Number(r && r.tm_value);
  const b = Number(r && r.true_value);
  return Math.max(Number.isFinite(a) ? a : 0, Number.isFinite(b) ? b : 0);
}

function bestMatch(rows, q) {
  const n = foldTr(q || "");
  if (!n || !rows.length) return null;
  const clubs = rows.filter((r) => r.kind === "club");
  const clubHit = clubs.find((c) => clubTextMatch(c.name, n));
  if (clubHit) return clubHit;
  const players = rows.filter((r) => r.kind !== "club" && r.player_id != null);
  if (!players.length) return null;
  const ranked = [...players].sort((a, b) => worthOf(b) - worthOf(a));
  return ranked[0] || null;
}

async function openFromQuery(q) {
  hideDrop();
  gq.value = "";
  const query = (q || "").trim();
  if (query.length < 2) {
    go("/ara");
    return;
  }
  try {
    const data = await api(`/api/search?q=${encodeURIComponent(query)}`);
    const rows = data.results || [];
    const hit = bestMatch(rows, query);
    if (hit?.kind === "club" && hit.href) {
      go(hit.href);
      return;
    }
    if (hit?.player_id) {
      go(hit.href || playerHref(hit.player_id, hit.name));
      return;
    }
  } catch (_ex) {
    /* motor henüz hazır değilse arama sayfasına düş */
  }
  go(`/ara?q=${encodeURIComponent(query)}`);
}

function parseStamp(value) {
  if (!value) return null;
  const s = String(value).trim();
  const iso = s.match(/^(\d{4})-(\d{2})-(\d{2})/);
  if (iso) return Date.UTC(Number(iso[1]), Number(iso[2]) - 1, Number(iso[3]));
  const eu = s.match(/^(\d{1,2})[./](\d{1,2})[./](\d{4})/);
  if (eu) return Date.UTC(Number(eu[3]), Number(eu[2]) - 1, Number(eu[1]));
  const months = { jan: 0, feb: 1, mar: 2, apr: 3, may: 4, jun: 5, jul: 6, aug: 7, sep: 8, oct: 9, nov: 10, dec: 11 };
  const named = s.match(/^([A-Za-zçğıöşüİĞÜŞÖÇ]+)\.?\s+(\d{1,2}),?\s+(\d{4})$/i);
  if (named) {
    const key = foldTr(named[1]).slice(0, 3);
    if (Object.prototype.hasOwnProperty.call(months, key)) {
      return Date.UTC(Number(named[3]), months[key], Number(named[2]));
    }
  }
  const named2 = s.match(/^(\d{1,2})\s+([A-Za-zçğıöşüİĞÜŞÖÇ]+)\.?\s+(\d{4})$/i);
  if (named2) {
    const key = foldTr(named2[2]).slice(0, 3);
    if (Object.prototype.hasOwnProperty.call(months, key)) {
      return Date.UTC(Number(named2[3]), months[key], Number(named2[1]));
    }
  }
  return null;
}

function fmtDate(value) {
  if (!value) return "";
  const ms = parseStamp(value);
  if (ms == null) return String(value).trim().slice(0, 16);
  const d = new Date(ms);
  const dd = String(d.getUTCDate()).padStart(2, "0");
  const mm = String(d.getUTCMonth() + 1).padStart(2, "0");
  return `${dd}.${mm}.${d.getUTCFullYear()}`;
}

function daysSince(value) {
  const ms = parseStamp(value);
  if (ms == null) return null;
  return Math.floor((Date.now() - ms) / 86400000);
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

function injuryFact(live) {
  const days = Number(live && live.injury_days) || 0;
  if (days) return `Açık kayıt · yaklaşık ${days} gün`;
  const last = ((live && live.injuries) || [])[0];
  if (last && last.injury) {
    const season = last.season ? ` · ${last.season}` : "";
    return `${last.injury}${season}`;
  }
  if (live && live.fotmob && live.fotmob.injured) return "Açık kayıt";
  return "";
}

function playerPayloadThin(data) {
  const live = (data && data.live) || {};
  if (live.partial) return true;
  const career = live.career || {};
  const n = (career.current || []).length + (career.former || []).length + (career.youth || []).length;
  return n === 0;
}

async function loadPlayerPack(id) {
  let data;
  try {
    data = await api(`/api/players/${id}`);
  } catch (err) {
    data = await api(`/api/players/${id}`);
  }
  if (playerPayloadThin(data)) {
    try {
      const again = await api(`/api/players/${id}`);
      if (again && again.player) data = again;
    } catch (_) {}
  }
  return data;
}

function metric(label, value, className = "") {
  const shown = value == null || value === "" ? "—" : value;
  return `<div class="metric ${esc(className)}"><span>${esc(label)}</span><b>${esc(shown)}</b></div>`;
}

function fmtSmallNumber(value) {
  const n = Number(value);
  if (!Number.isFinite(n) || n <= 0) return "—";
  return n.toLocaleString("tr-TR", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
}

function moneyAmount(value) {
  if (value == null || value === "") return 0;
  if (typeof value === "string") {
    const raw = value.replace(/\s/g, "").replace("€", "").toLowerCase();
    const million = /mio|million|mill|mil\.?|m$/.test(raw);
    const thousand = /thousand|bin|k$/.test(raw);
    const cleaned = raw.replace(/[^\d,.-]/g, "");
    const normalized = cleaned.includes(",") && cleaned.includes(".")
      ? cleaned.replaceAll(".", "").replace(",", ".")
      : /^\d{1,3}(\.\d{3})+$/.test(cleaned)
        ? cleaned.replaceAll(".", "")
      : cleaned.replace(",", ".");
    const parsed = Number(normalized);
    if (!Number.isFinite(parsed) || parsed <= 0) return 0;
    if (million) return parsed * 1_000_000;
    if (thousand) return parsed * 1_000;
    if (parsed < 1000) return parsed * 1_000_000;
    return parsed;
  }
  const n = Number(value);
  if (!Number.isFinite(n) || n <= 0) return 0;
  return n < 1000 ? n * 1_000_000 : n;
}

function sparkline(history) {
  const pts = (history || [])
    .map((h) => ({ ...h, _value: moneyAmount(h.marketValue) }))
    .filter((h) => h._value > 0)
    .sort((a, b) => String(a.date || "").localeCompare(String(b.date || "")));
  if (pts.length < 2) return `<p class="sub">Etiket geçmişi için yeterli veri yok.</p>`;
  const vals = pts.map((h) => h._value);
  const w = 640, h = 72;
  const min = Math.min(...vals), max = Math.max(...vals);
  const line = vals.map((v, i) => {
    const x = (i / (vals.length - 1)) * w;
    const y = h - 8 - ((v - min) / (max - min || 1)) * (h - 16);
    return `${x},${y}`;
  }).join(" ");
  const peak = pts.reduce((a, b) => b._value > a._value ? b : a);
  const last = pts[pts.length - 1];
  return `<svg class="spark" viewBox="0 0 ${w} ${h}" preserveAspectRatio="none" role="img" aria-label="Transfermarkt etiket geçmişi">
      <polyline fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round" points="${line}" />
    </svg>
    <div class="spark-meta"><span>Tepe ${esc(fmtEur(peak._value))} · ${esc(fmtDate(peak.date))}</span><span>Güncel ${esc(fmtEur(last._value))} · ${esc(fmtDate(last.date))}</span></div>`;
}

function fmtEur(n) {
  const v = moneyAmount(n);
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
  const pts = (history || [])
    .map((h) => ({ ...h, _value: moneyAmount(h.marketValue) }))
    .filter((h) => h._value > 0)
    .sort((a, b) => String(a.date || "").localeCompare(String(b.date || "")))
    .slice(-6)
    .reverse();
  if (!pts.length) return "";
  return `<table class="mini">
    <thead><tr><th>Tarih</th><th>Kulüp</th><th>Etiket</th></tr></thead>
    <tbody>${pts.map((h) => `<tr><td>${esc(fmtDate(h.date))}</td><td>${esc(clubName(h.clubName) || "—")}</td><td>${esc(fmtEur(h._value))}</td></tr>`).join("")}</tbody>
  </table>`;
}

function tmMove(history) {
  const vals = (history || []).map((h) => moneyAmount(h.marketValue)).filter((n) => n > 0);
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
  const skipBoot = routeParts()[0] === "fantezi" || routeParts()[0] === "yontem";
  if (ready) {
    boot.classList.add("hidden");
    boot.setAttribute("aria-hidden", "true");
    return true;
  }
  const s = await api("/api/status");
  ready = !!s.ready;
  if (ready || skipBoot) {
    boot.classList.add("hidden");
    boot.setAttribute("aria-hidden", "true");
    if (bootTimer) clearInterval(bootTimer);
    if (ready) prefetchTabs();
    return ready;
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
    if (into === drop) syncNavSearch();
    return;
  }
  try {
    if (searchAbort) searchAbort.abort();
    searchAbort = new AbortController();
    const data = await api(`/api/search?q=${encodeURIComponent(q)}`, { signal: searchAbort.signal });
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
    if (into === drop) {
      syncNavSearch();
      placeDrop(active);
    }
  } catch (ex) {
    if (ex && (ex.name === "AbortError" || ex.message === "Aborted")) return;
    into.innerHTML = `<p class="sub" style="padding:16px">${esc(ex.message || "Arama şu an kullanılamıyor.")}</p>`;
    into.classList.remove("hidden");
    if (into === drop) {
      syncNavSearch();
      placeDrop(document.activeElement);
    }
  }
}

gq.addEventListener("input", () => {
  syncNavSearch();
  clearTimeout(searchClock);
  searchClock = setTimeout(() => runSearch(gq.value.trim(), drop), 80);
});
gq.addEventListener("focus", () => {
  syncNavSearch();
  requestAnimationFrame(() => {
    if (!drop.classList.contains("hidden")) placeDrop(gq);
  });
});
gq.addEventListener("blur", () => {
  setTimeout(syncNavSearch, 160);
});
document.getElementById("global-search").addEventListener("submit", (e) => {
  e.preventDefault();
  hideDrop();
  openFromQuery(gq.value.trim());
});
document.getElementById("global-search").addEventListener("transitionend", () => {
  if (!drop.classList.contains("hidden")) placeDrop(gq);
});
drop.addEventListener("click", (e) => {
  const a = e.target.closest("a");
  if (!a) return;
  hideDrop();
  gq.value = "";
  syncNavSearch();
});
document.addEventListener("click", (e) => {
  const a = e.target.closest("a[href]");
  if (a && a.target !== "_blank" && !a.hasAttribute("download") && !e.metaKey && !e.ctrlKey && !e.shiftKey && !e.altKey) {
    const href = a.getAttribute("href") || "";
    if (a.classList.contains("method-fab")) {
      e.preventDefault();
      if (document.body.classList.contains("on-yontem")) {
        go(methodReturn || "/");
      } else {
        const here = `${location.pathname}${location.search}` || "/";
        if (!here.startsWith("/yontem")) methodReturn = here;
        go("/yontem");
      }
      return;
    }
    if (href.startsWith("#/")) {
      e.preventDefault();
      const rest = href.slice(2);
      go(rest ? `/${rest}` : "/");
      return;
    }
    if (href.startsWith("/") && !href.startsWith("//") && !href.startsWith("/api/") && !href.startsWith("/static/") && !href.endsWith(".pdf")) {
      e.preventDefault();
      go(href);
      return;
    }
  }
  const hq = document.getElementById("hq");
  const aq = document.getElementById("aq");
  const cmp = document.getElementById("cmp-right");
  if (!drop.contains(e.target) && e.target !== gq && e.target !== hq && e.target !== aq) hideDrop();
  document.querySelectorAll(".drop.local").forEach((box) => {
    const field = box.previousElementSibling?.querySelector?.("input") || cmp;
    if (!box.contains(e.target) && e.target !== field && e.target !== cmp) {
      box.classList.add("hidden");
    }
  });
});
window.addEventListener("resize", () => {
  if (!drop.classList.contains("hidden")) placeDrop();
});

function fmtCount(n) {
  if (n == null || n === "") return "—";
  return Number(n).toLocaleString("tr-TR");
}

function fmtOne(value) {
  const n = Number(value);
  if (!Number.isFinite(n)) return "—";
  return n.toLocaleString("tr-TR", { minimumFractionDigits: 1, maximumFractionDigits: 1 });
}

function properCase(value) {
  const s = String(value ?? "").trim();
  if (!s) return "";
  const allUpper = s === s.toLocaleUpperCase("tr-TR") && s !== s.toLocaleLowerCase("tr-TR") && s.length > 3;
  if (!allUpper && s !== s.toLowerCase()) return s;
  return s.toLocaleLowerCase("tr-TR").replace(/(^|[\s\-/,])(\S)/g, (_, a, b) => a + b.toLocaleUpperCase("tr-TR"));
}

function clubName(value) {
  const raw = String(value ?? "").trim().replace(/[\s·•]+$/g, "").replace(/^[·•\s]+/, "");
  const n = foldTr(raw).replace(/[\s-]/g, "");
  if (
    !raw ||
    n.includes("withoutclub") ||
    n.includes("vereinslos") ||
    n.includes("ohneverein") ||
    n.includes("freeagent") ||
    n.includes("unattached") ||
    n.includes("kulupsuz") ||
    n.includes("retired") ||
    n.includes("karrierebeendet") ||
    n.includes("careerended") ||
    n === "emekli"
  ) {
    return "Kulüpsüz";
  }
  return properCase(raw);
}

function metaJoin(...parts) {
  return parts
    .map((p) => String(p ?? "").trim())
    .filter((p) => p && p !== "—" && p !== "·" && p !== ".")
    .join(" · ");
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

function clubMini(c) {
  return `<a class="tile" href="${esc(c.href || "/kulup/" + c.id)}">
    <div class="who">${esc(clubName(c.name))}</div>
    <div class="sub">${esc(c.league || "")}</div>
    <div class="price">${esc(c.true_label || "—")}<span>Transfermarkt ${esc(c.tm_label || "—")}</span></div>
  </a>`;
}

function pulseTm(pulse, id) {
  const bags = [pulse.stars, pulse.undervalued, pulse.overvalued, pulse.young, pulse.superlig];
  for (const bag of bags) {
    for (const p of bag || []) {
      if (String(p.player_id) === String(id) && p.tm_label && p.tm_label !== "—") return p.tm_label;
    }
  }
  return "";
}

function renderHome(pulse) {
  const recent = recentPlayers().map((r) => ({
    player_id: r.id,
    name: r.name,
    club: r.club,
    true_label: r.true_label,
    tm_label: r.tm_label || pulseTm(pulse, r.id),
    direction: r.direction || "",
    href: r.href,
    gap_label: "",
  }));
  const clubs = [...(pulse.clubs || [])].sort((a, b) => (Number(b.true_sum) || 0) - (Number(a.true_sum) || 0)).slice(0, 12);
  view.innerHTML = `
    <section class="panel hero home-hero">
      <h1 class="brand-mark">Aurea</h1>
      <form class="spotlight" id="home-search" autocomplete="off">
        <input id="hq" type="search" placeholder="Oyuncu, kulüp veya Transfermarkt adresi" />
      </form>
      <p class="lede home-lede">Transfermarkt etiketini, oyunun ürettiği Aurea değeriyle yan yana okuyun.</p>
    </section>
    ${recent.length ? rowBlock("Son bakılanlar", "", recent) : ""}
    ${clubs.length ? `<div class="row-head"><h2>Kulüpler</h2><a href="/kulupler">Tümü</a></div>
      <div class="scroll">${clubs.map(clubMini).join("")}</div>` : ""}
    ${rowBlock("En yüksek tutar", "/piyasa", pulse.stars)}
    ${rowBlock("Ucuz etiket", "/piyasa?direction=dusuk", pulse.undervalued)}
    ${rowBlock("Piyasa primi", "/piyasa?direction=yuksek", pulse.overvalued)}
  `;
  document.getElementById("home-search").addEventListener("submit", (e) => {
    e.preventDefault();
    hideDrop();
    openFromQuery(document.getElementById("hq").value.trim());
  });
  const hq = document.getElementById("hq");
  hq.addEventListener("input", () => {
    clearTimeout(searchClock);
    searchClock = setTimeout(() => runSearch(hq.value.trim(), drop), 80);
  });
  hq.focus();
}

async function renderSearch(gen) {
  const q = queryFromHash();
  view.innerHTML = `
    <section class="hero center search-hero panel">
      <p class="kicker">Arama</p>
      <h1>Oyuncu ara</h1>
      <p class="lede">İsim, kulüp veya Transfermarkt bağlantısı.</p>
      <form id="ara-form" class="filters search-filters">
        <input id="aq" name="q" value="${esc(q.q || "")}" placeholder="Oyuncu, kulüp veya adres" />
        <select name="position" id="aq-pos">
          <option value="">Mevki</option>
          <option value="Goalkeeper" ${q.position === "Goalkeeper" ? "selected" : ""}>Kaleci</option>
          <option value="Defender" ${q.position === "Defender" ? "selected" : ""}>Defans</option>
          <option value="Midfield" ${q.position === "Midfield" ? "selected" : ""}>Orta saha</option>
          <option value="Attack" ${q.position === "Attack" ? "selected" : ""}>Forvet</option>
        </select>
        <button class="btn" type="submit">Ara</button>
      </form>
    </section>
    <div id="ara-results" class="list"></div>
  `;
  const input = document.getElementById("aq");
  const box = document.getElementById("ara-results");
  const paint = (rows) => {
    const clubs = rows.filter((r) => r.kind === "club");
    const players = rows.filter((r) => r.kind !== "club");
    const clubHtml = clubs.length ? `<div class="search-clubs">${clubs.map(resultRow).join("")}</div>` : "";
    const playerHtml = players.length ? listHead() + players.map(playerRow).join("") : "";
    box.innerHTML = (clubHtml + playerHtml) || `<p class="sub">Sonuç yok.</p>`;
  };
  const paramsOf = () => {
    const pos = document.getElementById("aq-pos")?.value || "";
    const extra = new URLSearchParams();
    extra.set("q", input.value.trim());
    if (pos) extra.set("position", pos);
    return extra;
  };
  const syncUrl = () => {
    const vis = new URLSearchParams();
    const query = input.value.trim();
    const pos = document.getElementById("aq-pos")?.value || "";
    if (query) vis.set("q", query);
    if (pos) vis.set("position", pos);
    const next = vis.toString() ? `/ara?${vis}` : "/ara";
    if (`${location.pathname}${location.search}` !== next) {
      history.replaceState({}, "", next);
    }
  };
  const run = async (submit) => {
    const extra = paramsOf();
    const query = extra.get("q") || "";
    if (query.length < 2) { box.innerHTML = `<p class="sub">En az iki harf yazın veya bir Transfermarkt adresi yapıştırın.</p>`; return; }
    box.innerHTML = waitScreen("Aranıyor", "Kayıtlar ve Transfermarkt taranıyor.");
    try {
      const data = await api(`/api/search?${extra.toString()}&live=1`);
      if (gen !== viewGen) return;
      const rows = data.results || [];
      if (submit) {
        const hit = bestMatch(rows, query);
        if (hit?.kind === "club" && hit.href) {
          go(hit.href);
          return;
        }
        if (hit?.player_id) {
          go(hit.href || playerHref(hit.player_id, hit.name));
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
    searchClock = setTimeout(() => { syncUrl(); run(false); }, 140);
  });
  document.getElementById("ara-form").addEventListener("submit", (e) => {
    e.preventDefault();
    syncUrl();
    run(true);
  });
  document.getElementById("aq-pos").addEventListener("change", () => { syncUrl(); run(false); });
  if (q.q) run(false);
  input.focus();
}

async function renderMarket(preset = {}, gen) {
  const q = { ...queryFromHash(), ...preset };
  const params = new URLSearchParams();
  ["league", "position", "direction", "q", "sort", "page"].forEach((k) => { if (q[k]) params.set(k, q[k]); });
  const marketPath = `/api/market?${params.toString()}`;
  if (!apiMemo.has(marketPath)) view.innerHTML = waitScreen("Piyasa", "Liste hazırlanıyor.");
  const data = await api(marketPath);
  if (gen !== viewGen) return;
  const leagues = (await api("/api/leagues")).leagues || [];
  if (gen !== viewGen) return;
  const leagueName = q.league ? (leagues.find((l) => l.id === q.league)?.name || q.league) : "Tüm ligler";
  view.innerHTML = `
    <section class="panel page-head">
      <h1>${esc(leagueName)}</h1>
      <p class="lede">${esc(fmtCount(data.total))} oyuncu. Listeyi lig ve mevkiye göre daraltın.</p>
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
        <option value="dusuk" ${q.direction === "dusuk" ? "selected" : ""}>Ucuz etiket</option>
        <option value="yuksek" ${q.direction === "yuksek" ? "selected" : ""}>Piyasa primi</option>
        <option value="denge" ${q.direction === "denge" ? "selected" : ""}>Uyumlu</option>
      </select>
      <select name="sort">
        <option value="true_value">Aurea değeri</option>
        <option value="tm" ${q.sort === "tm" ? "selected" : ""}>Transfermarkt</option>
        <option value="gap" ${q.sort === "gap" ? "selected" : ""}>Fark</option>
        <option value="goals" ${q.sort === "goals" ? "selected" : ""}>Gol</option>
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
  const toMarket = (form) => {
    const next = new URLSearchParams(form instanceof URLSearchParams ? form : new FormData(form));
    next.delete("age");
    next.delete("age_min");
    next.delete("age_max");
    const league = next.get("league");
    const keys = [...next.keys()].filter((k) => k !== "league" && k !== "page" && next.get(k));
    if (league && !keys.length) {
      const page = next.get("page");
      go(page && page !== "1" ? `/lig/${league}?page=${encodeURIComponent(page)}` : `/lig/${league}`);
      return;
    }
    go(`/piyasa?${next}`);
  };
  document.getElementById("filt").addEventListener("submit", (e) => {
    e.preventDefault();
    toMarket(e.target);
  });
  document.getElementById("prev").onclick = () => {
    const next = new URLSearchParams(location.search.replace(/^\?/, "") || location.hash.split("?")[1] || "");
    if (q.league && !next.get("league")) next.set("league", q.league);
    next.set("page", String(Math.max(1, (data.page || 1) - 1)));
    toMarket(next);
  };
  document.getElementById("next").onclick = () => {
    const next = new URLSearchParams(location.search.replace(/^\?/, "") || location.hash.split("?")[1] || "");
    if (q.league && !next.get("league")) next.set("league", q.league);
    next.set("page", String((data.page || 1) + 1));
    toMarket(next);
  };
}

async function renderLeagues(gen) {
  if (!apiMemo.has("/api/leagues")) view.innerHTML = waitScreen("Ligler", "Ligler hazırlanıyor.");
  const data = await api("/api/leagues");
  if (gen !== viewGen) return;
  const leagues = data.leagues || [];
  const card = (l) => `
    <a class="league" href="/lig/${esc(l.id)}">
      ${leagueCrest(l)}
      <div>
        <b>${esc(l.name)}</b>
        <span>${esc(fmtCount(l.players))} oyuncu${l.country ? " · " + esc(l.country) : ""}</span>
      </div>
    </a>`;
  const paint = (rows) => {
    const box = document.getElementById("league-list");
    if (!box) return;
    box.innerHTML = rows.map(card).join("") || `<p class="sub">Lig yok.</p>`;
  };
  view.innerHTML = `
    <section class="panel page-head">
      <h1>Ligler</h1>
      <p class="lede">Bir lige girin. Piyasa listesi o ligin oyuncularını açar.</p>
      <form class="filters" id="league-filt">
        <input id="league-q" placeholder="Lig ara" />
      </form>
    </section>
    <div id="league-list" class="leagues"></div>
  `;
  paint(leagues);
  document.getElementById("league-q").addEventListener("input", (e) => {
    const n = foldTr(e.target.value.trim());
    paint(n ? leagues.filter((l) => clubTextMatch(l.name, n) || clubTextMatch(l.country, n) || clubTextMatch(l.id, n)) : leagues);
  });
}

async function renderPlayer(id, gen) {
  view.innerHTML = waitScreen("Oyuncu dosyası", "Transfermarkt, FotMob ve Aurea değeri okunuyor.");
  const data = await loadPlayerPack(id);
  if (gen !== viewGen) return;
  paintPlayerView(data);
}

function paintPlayerView(data) {
  const p = data.player || {};
  rememberPlayer(p);
  const r = data.report || {};
  const live = data.live || {};
  const fm = live.fotmob || {};
  const ident = r.identity || {};
  const when = liveWhen(p.live_fetched_at || live.fetched_at);
  const move = tmMove(live.market_history);
  const season = live.season_totals || {};
  const seasonLine = season.apps
    ? `${season.apps} maç · ${season.goals || 0} gol · ${season.assists || 0} asist · ${fmtCount(season.minutes)} dk`
    : "";
  const foot = footLabel(p.foot);
  const intlLine = [p.intl_caps ? `${p.intl_caps} maç` : "", p.intl_goals ? `${p.intl_goals} gol` : ""].filter(Boolean).join(" · ");
  const cardLine = [p.yellow_2y ? `${p.yellow_2y} sarı` : "", p.red_2y ? `${p.red_2y} kırmızı` : ""].filter(Boolean).join(" · ");
  const production = [
    metric("12 ay", p.minutes_365 ? `${fmtCount(p.minutes_365)} dk` : "—"),
    metric("Maç", p.apps_2y || "—"),
    metric("Gol", p.goals_2y ?? "—"),
    metric("Asist", p.assists_2y ?? "—"),
    metric("Gol/90", fmtSmallNumber(p.goals_p90), "rate"),
    metric("Asist/90", fmtSmallNumber(p.assists_p90), "rate"),
    metric("G+A/90", fmtSmallNumber(p.contrib_p90), "rate main"),
    metric("Kart", cardLine || "—"),
    fm.xg ? metric("xG", fmtSmallNumber(fm.xg), "rate") : "",
    fm.xa ? metric("xA", fmtSmallNumber(fm.xa), "rate") : "",
    fm.shots ? metric("Şut", fm.shots) : "",
    fm.sot ? metric("İsabet", fm.sot) : "",
  ].filter(Boolean).join("");
  const facts = [
    fact("Mevki", ident.position || p.position),
    fact("Lig", ident.league || p.league),
    fact("Boy", p.height_in_cm ? `${p.height_in_cm} cm` : ""),
    fact("Ayak", foot === "—" ? "" : foot),
    fact("Uyruk", properCase(p.nationality)),
    fact("Doğum yeri", properCase(p.birthplace)),
    fact("Milli takım", intlLine),
    fact("Sözleşme", p.contract_years != null ? `${Number(p.contract_years).toFixed(1).replace(".", ",")} yıl` : ""),
    fact("Kariyer tepesi", p.peak_label),
    fact("Kart", cardLine),
    fact("Bu sezon", seasonLine),
    fact("Sakatlık", injuryFact(live)),
  ].filter(Boolean).join("");
  const table = (data.season_table || []).filter((row) => Number(row.apps) > 0);
  const seasonHtml = table.length
    ? `<div class="group print-hide"><h3>Sezon</h3>
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
  const clubShown = clubName(p.club);
  const clubHref = (p.club_href || "") && clubShown !== "Kulüpsüz" ? p.club_href : "";
  document.title = `${tidyName(p.name)} · Aurea`;
  const leagueShown = properCase(ident.league || p.league || "");
  const posShown = ident.position || p.position || "";
  const karar = (r.sections || []).find((s) => s.id === "karar");
  const kararLine = karar && ((karar.paragraphs && karar.paragraphs[0]) || karar.body) || "";
  view.innerHTML = `
    <section class="print-sheet">
      <div class="print-brand"><i></i><b>Aurea</b></div>
      <h1>${esc(tidyName(p.name))}</h1>
      <p class="print-meta">${[clubShown, leagueShown, posShown, p.age ? p.age + " yaş" : ""].filter(Boolean).map(esc).join(" · ")}</p>
      <div class="print-prices">
        <div><span>Transfermarkt</span><b>${esc(p.tm_label || "—")}</b></div>
        <div><span>Aurea değeri</span><b>${esc(p.true_label || "—")}</b></div>
      </div>
      <p class="print-kicker">${esc(gapWord(p.direction || r.direction))}</p>
      <p class="print-verdict">${esc(r.headline || "")}</p>
      ${r.summary ? `<p class="print-sum">${esc(r.summary)}</p>` : ""}
      ${kararLine ? `<p class="print-sum">${esc(kararLine)}</p>` : ""}
      <div class="print-facts">
        <div><span>12 ay</span><b>${esc(p.minutes_365 ? fmtCount(p.minutes_365) + " dk" : "—")}</b></div>
        <div><span>G+A/90</span><b>${esc(fmtSmallNumber(p.contrib_p90))}</b></div>
        <div><span>Gol</span><b>${esc(p.goals_2y ?? "—")}</b></div>
        <div><span>Asist</span><b>${esc(p.assists_2y ?? "—")}</b></div>
      </div>
    </section>
    <div class="screen-only">
    <section class="panel player-head player-compact">
      ${live.fetched_at ? `<div class="live-badge print-hide"><i></i> Canlı${when ? " · " + esc(when) : ""}</div>` : ""}
      <p class="kicker">${esc(metaJoin(posShown, leagueShown))}</p>
      <h1>${esc(tidyName(p.name))}</h1>
      <p class="sub">${clubHref ? `<a href="${esc(clubHref)}">${esc(clubShown || "—")}</a>` : esc(clubShown || "—")}${p.shirt ? " · #" + esc(p.shirt) : ""}${p.age ? " · " + esc(p.age) + " yaş" : ""}</p>
      <div class="player-actions no-print">
        <button class="btn" type="button" id="pdf-player">PDF indir</button>
        <button class="btn ghost" type="button" id="share-player">Paylaş</button>
      </div>
    </section>
    <article class="read verdict-first ${esc(p.direction || r.direction || "")}">
      <p class="kicker">${esc(gapWord(p.direction || r.direction))}</p>
      <h2>${esc(r.headline || "")}</h2>
      <p>${esc(r.summary || "")}</p>
    </article>
    <div class="duo player-prices">
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
    <div class="facts player-facts">${facts}</div>
    <div class="metric-title">Üretim özeti</div>
    <div class="metrics production-metrics">
      ${production}
    </div>
    ${careerBlock(live.career)}
    ${((live.market_history || []).filter((h) => moneyAmount(h.marketValue) > 0).length >= 2) ? `<div class="group print-hide">
      <h3>Etiket eğrisi</h3>
      <article>${sparkline(live.market_history)}${histTable(live.market_history)}</article>
    </div>` : ""}
    <div class="group analysis-prose">
      <h3>Analiz</h3>
      ${(r.sections || []).filter((s) => s.id !== "sofa" && s.title !== "Sofascore").map((s) => {
        const paras = (s.paragraphs && s.paragraphs.length) ? s.paragraphs : (s.body ? [s.body] : []);
        return `<article><h4>${esc(s.title)}</h4>${paras.map((t) => `<p>${esc(t)}</p>`).join("")}</article>`;
      }).join("")}
    </div>
    ${seasonHtml}
    <div class="group print-hide">
      <h3>Emsaller</h3>
      <div class="comps">
        ${(data.similar || []).map((s) => `<a class="comp" href="${esc(s.href || playerHref(s.player_id, s.name))}"><b>${esc(tidyName(s.name))}</b><div class="comp-meta"><span>${esc(metaJoin(clubName(s.club) || "", s.age ? Math.round(s.age) + " yaş" : "") || "—")}</span><span>${esc(s.true_label || s.tm_label || "")}</span></div></a>`).join("")}
      </div>
    </div>
    </div>
  `;
  document.getElementById("pdf-player")?.addEventListener("click", () => window.print());
  document.getElementById("share-player")?.addEventListener("click", () => sharePlayerCard(p, ident, r));
  bindCareer(view, live.career || {});
}

function wrapCanvas(ctx, text, maxWidth, maxLines) {
  const words = String(text || "").split(/\s+/).filter(Boolean);
  const lines = [];
  let cur = "";
  for (const word of words) {
    const test = cur ? `${cur} ${word}` : word;
    if (ctx.measureText(test).width > maxWidth && cur) {
      lines.push(cur);
      if (lines.length >= maxLines) return lines;
      cur = word;
    } else {
      cur = test;
    }
  }
  if (cur && lines.length < maxLines) lines.push(cur);
  return lines;
}

function sharePlayerCard(p, ident) {
  const name = tidyName(p.name || ident?.name || "Oyuncu");
  const club = clubName(p.club || ident?.club || "");
  const pos = ident?.position || p.position || "";
  const league = properCase(ident?.league || p.league || "");
  const w = 1080;
  const h = 1080;
  const canvas = document.createElement("canvas");
  canvas.width = w;
  canvas.height = h;
  const ctx = canvas.getContext("2d");
  if (!ctx) return;
  ctx.fillStyle = "#0b0c10";
  ctx.fillRect(0, 0, w, h);
  ctx.fillStyle = "#d4b56a";
  ctx.fillRect(0, 0, 14, h);
  ctx.fillRect(72, 86, 18, 18);
  ctx.fillStyle = "#f0ebe0";
  ctx.font = "600 28px Outfit, sans-serif";
  ctx.fillText("AUREA", 108, 103);
  ctx.strokeStyle = "rgba(235,230,218,0.16)";
  ctx.lineWidth = 2;
  ctx.beginPath();
  ctx.moveTo(72, 140);
  ctx.lineTo(1008, 140);
  ctx.stroke();
  ctx.fillStyle = "#f0ebe0";
  ctx.font = "500 72px Cormorant Garamond, Georgia, serif";
  let y = 240;
  wrapCanvas(ctx, name, 900, 2).forEach((line) => {
    ctx.fillText(line, 72, y);
    y += 80;
  });
  ctx.fillStyle = "#b7b0a3";
  ctx.font = "400 28px Outfit, sans-serif";
  const meta = [club, league, pos, p.age ? p.age + " yaş" : ""].filter(Boolean).join("  ·  ");
  wrapCanvas(ctx, meta, 900, 2).forEach((line) => {
    ctx.fillText(line, 72, y);
    y += 40;
  });
  y += 48;
  ctx.fillStyle = "#14151c";
  ctx.fillRect(72, y, 456, 280);
  ctx.fillStyle = "#1b160e";
  ctx.fillRect(552, y, 456, 280);
  ctx.strokeStyle = "rgba(235,230,218,0.14)";
  ctx.strokeRect(72, y, 456, 280);
  ctx.strokeStyle = "#d4b56a";
  ctx.strokeRect(552, y, 456, 280);
  ctx.fillStyle = "#8d877c";
  ctx.font = "500 20px Outfit, sans-serif";
  ctx.fillText("TRANSFERMARKT", 100, y + 64);
  ctx.fillStyle = "#d4b56a";
  ctx.fillText("AUREA DEĞERİ", 580, y + 64);
  ctx.fillStyle = "#f0ebe0";
  ctx.font = "500 54px Cormorant Garamond, Georgia, serif";
  ctx.fillText(String(p.tm_label || "—"), 100, y + 168);
  ctx.fillText(String(p.true_label || "—"), 580, y + 168);
  ctx.fillStyle = "#6d685f";
  ctx.font = "400 20px Outfit, sans-serif";
  ctx.fillText("Adil değer", 72, 1012);
  canvas.toBlob(async (blob) => {
    if (!blob) return;
    const file = new File([blob], `aurea-${slugify(name) || "oyuncu"}.png`, { type: "image/png" });
    if (navigator.share && navigator.canShare && navigator.canShare({ files: [file] })) {
      try {
        await navigator.share({ files: [file], title: name, text: `${name} · TM ${p.tm_label || "—"} · Aurea ${p.true_label || "—"}` });
        return;
      } catch {
        /* kullanıcı iptal */
      }
    }
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = file.name;
    a.click();
    URL.revokeObjectURL(url);
  }, "image/png");
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

function fxPts(p) {
  const n = p && (p.pts_if_plays != null ? p.pts_if_plays : p.projected_pts);
  return n == null || n === "" ? null : Number(n);
}

function fxPtsLabel(p) {
  const n = fxPts(p);
  return n == null || !Number.isFinite(n) ? "—" : fmtOne(n);
}

function shortOpp(name) {
  return String(name || "")
    .replace(/\s+Sportif Faaliyetler$/i, "")
    .replace(/\s+\b(FK|JK|SK|AS)\b$/i, "")
    .trim();
}

function fxShirt(p, capName, viceName) {
  const name = fxName(p);
  const cap = String(p.player || "") === capName || String(p.display_name || "") === capName || foldTr(name) === foldTr(tidyName(capName));
  const vice = !cap && viceName && (String(p.player || "") === viceName || String(p.display_name || "") === viceName || foldTr(name) === foldTr(tidyName(viceName)));
  const pts = fxPtsLabel(p);
  const price = p.price_m != null ? `${fmtOne(p.price_m)} mn` : "";
  const opp = p.fixture_opponent ? "vs " + shortOpp(p.fixture_opponent) : "";
  const mark = cap ? "K" : (vice ? "YK" : "");
  return `<a class="shirt${cap ? " captain" : ""}${vice ? " vice" : ""}" href="/ara?q=${encodeURIComponent(name)}">
    <b>${esc(name)}</b>
    <span>${esc(opp)}</span>
    <span>${esc(metaJoin(price, pts !== "—" ? pts + " p" : "", mark))}</span>
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
  const pool = [...(squad || [])].filter(Boolean).sort((a, b) => (fxPts(b) || 0) - (fxPts(a) || 0));
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
  const push = (item) => {
    const p = fxMatch(item, squad);
    const k = fxKey(p);
    if (k && !used.has(k) && !seen.has(k)) {
      out.push(p);
      seen.add(k);
    }
  };
  for (const p of originalBench || []) push(p);
  for (const p of squad || []) push(p);
  return out.sort((a, b) => {
    const ga = String(a.position || "") === "GK" ? 0 : 1;
    const gb = String(b.position || "") === "GK" ? 0 : 1;
    if (ga !== gb) return ga - gb;
    const ra = Number(a.bench_rank);
    const rb = Number(b.bench_rank);
    const aRank = Number.isFinite(ra) ? ra : 99;
    const bRank = Number.isFinite(rb) ? rb : 99;
    if (aRank !== bRank) return aRank - bRank;
    const pa = Number(a.play_probability);
    const pb = Number(b.play_probability);
    const aPlay = Number.isFinite(pa) ? pa : 0.85;
    const bPlay = Number.isFinite(pb) ? pb : 0.85;
    if (aPlay !== bPlay) return bPlay - aPlay;
    return (fxPts(b) || 0) - (fxPts(a) || 0);
  });
}

function fxPitchHtml(xiList, benchList, capName, squad, viceName) {
  const xi = (xiList || []).map((x) => fxMatch(x, squad));
  const byPos = { FW: [], MF: [], DF: [], GK: [] };
  xi.forEach((p) => {
    const pos = p.position || "";
    if (byPos[pos]) byPos[pos].push(p);
    else byPos.MF.push(p);
  });
  const row = (list) => list.length ? `<div class="pitch-row">${list.map((p) => fxShirt(p, capName, viceName)).join("")}</div>` : "";
  const bench = orderBench(squad, xi, benchList);
  const benchHtml = bench.length
    ? `<div class="group bench-panel"><h3>Yedekler</h3>
        <p class="sub bench-note">Yedek kaleci ayrı, ardından sıra 1-2-3. Süre almayan 1 atlanır; 2 girer. Formasyon bozulursa o değişiklik yapılmaz.</p>
        <div class="bench-list">${bench.map((p, i) => {
          const isGk = String(p.position || "") === "GK";
          const slot = isGk ? "KL" : String(p.bench_rank > 0 ? p.bench_rank : (i + 1));
          const opp = p.fixture_opponent ? "vs " + p.fixture_opponent : "";
          const pts = fxPts(p) != null ? fxPtsLabel(p) + " p" : "";
          return `<a class="bench-who" href="/ara?q=${encodeURIComponent(fxName(p))}">
            <span class="bench-slot">${esc(String(slot))}</span>
            <span class="bench-copy">
              <b>${esc(fxName(p))}</b>
              <span>${esc(opp)}</span>
              <span class="bench-pts">${esc(pts)}</span>
            </span>
          </a>`;
        }).join("")}</div>
      </div>`
    : "";
  return { pitch: `${row(byPos.FW)}${row(byPos.MF)}${row(byPos.DF)}${row(byPos.GK)}`, benchHtml };
}

function fxBindShirts() {
  view.querySelectorAll(".shirt, .bench-who").forEach((a) => {
    a.addEventListener("click", (e) => {
      e.preventDefault();
      e.stopPropagation();
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
        <p class="lede">Hesabınıza girin. Kadro, bu oturumda hesaplanır.</p>
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
  const viceName = String(result.vice_captain?.player || result.vice_captain?.display_name || "");
  const viceLabel = tidyName(result.vice_captain?.display_name || result.vice_captain?.player || "");
  const card = payload?.manager_card || {};
  const analysis = payload?.analysis || [];
  const comps = payload?.formation_comparisons || [];
  const watch = payload?.watch || [];
  const firstPaint = fxPitchHtml(xi, bench, capName, squad, viceName);
  const fetchedAt = payload?.fetched_at ? new Date(payload.fetched_at) : null;
  const fresh = fetchedAt && !Number.isNaN(fetchedAt.getTime())
    ? `Güncellendi ${fetchedAt.toLocaleString("tr-TR", { day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" })} · 2026/27 puan durumu, fikstür ve iddia kotası`
    : "2026/27 puan durumu, fikstür ve iddia kotası";
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
        <p class="lede">${running ? esc(st.message || "Hesaplanıyor…") : (payload ? `Diziliş ${esc(result.formation || "")} · ${esc(fmtOne(result.total_cost || 0))} mn · kasa ${esc(fmtOne(result.bank || 0))} mn` : "Kadro henüz yok.")}</p>
        ${payload && !running ? `<p class="fresh-stamp">${esc(fresh)}</p>` : ""}
      </div>
      <button class="btn" id="fx-run" type="button" ${running ? "disabled" : ""}>${running ? "Hesaplanıyor…" : (payload ? "Yeniden hesapla" : "Kadro hesapla")}</button>
    </section>
    ${running ? `<div class="progress fx-progress"><i style="width:${Math.round((st.progress || 0) * 100)}%"></i></div><p class="sub">${esc(st.message || "")}</p>` : ""}
    ${st.error ? `<p class="error">${esc(st.error)}</p>` : ""}
    ${payload ? `
      <div class="tri fantasy-meta">
        <div class="price-card hero"><div class="k">İlk 11</div><div class="n">${esc(fmtOne(result.xi_if_plays || result.total_projected || 0))}</div><div class="hint">Seçim değeri ${esc(fmtOne(result.total_projected || 0))} · yedek ${esc(fmtOne(result.bench_projected || 0))}</div></div>
        <div class="price-card"><div class="k">Kaptan</div><div class="n">${esc(tidyName(result.captain?.display_name || result.captain?.player || "—"))}</div><div class="hint">${esc(metaJoin(result.captain?.team || "", fxPts(result.captain) != null ? fxPtsLabel(result.captain) + " p" : "") || "—")}${viceLabel ? `<br>Yedek kaptan ${esc(viceLabel)}.` : ""}</div></div>
        <div class="price-card"><div class="k">Menajer kartı</div><div class="n">${esc(card.use ? (card.card || "Kullan") : "Bu hafta yok")}</div><div class="hint">${esc(card.why || "Bu hafta menajer kartı kullanmayın.")}</div></div>
      </div>
      ${comps.length ? `<div class="group"><h3>Diziliş karşılaştırması</h3>
        <div class="form-picks">${comps.map((c, i) => `<button type="button" class="form-pick${c.formation === result.formation ? " on" : ""}" data-i="${i}">
          <b>${esc(c.formation)}</b>
          <span>${esc(fmtOne(c.expected_pts || 0))} p${c.formation === result.formation ? " · seçildi" : ""}</span>
        </button>`).join("")}</div>
      </div>` : ""}
      <div class="pitch" id="fx-pitch">${firstPaint.pitch}</div>
      <div id="fx-bench">${firstPaint.benchHtml}</div>
      ${watch.length ? `<div class="group"><h3>Alınabilecekler</h3>
        <div class="comps">
          ${watch.map((p) => `<a class="comp" href="/ara?q=${encodeURIComponent(fxName(p))}"><b>${esc(fxName(p))}</b><div class="comp-meta"><span>${esc(metaJoin(properCase(p.team) || "", p.position || "") || "—")}</span><span>${fxPts(p) != null ? fxPtsLabel(p) + " p" : ""}</span></div></a>`).join("")}
        </div>
      </div>` : ""}
      ${analysis.length ? `<div class="group analysis-prose"><h3>Analiz</h3>${analysis.map((s) => {
        const paras = (s.paragraphs && s.paragraphs.length) ? s.paragraphs : (s.body ? [s.body] : []);
        return `<article><h4>${esc(s.title)}</h4>${paras.map((t) => `<p>${esc(t)}</p>`).join("")}</article>`;
      }).join("")}</div>` : ""}
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
    const painted = fxPitchHtml(liveXi, liveBench, capName, squad, viceName);
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

async function renderScout(gen) {
  view.innerHTML = waitScreen("Scout", "Ucuz etiket listesi hazırlanıyor.");
  const data = await api("/api/scout");
  if (gen !== viewGen) return;
  const positions = data.positions || [];
  const row = (p) => `
    <article class="scout-row">
      <button type="button" class="scout-head">
        <div class="who">
          <b>${esc(tidyName(p.name))}</b>
          <span>${esc(metaJoin(clubName(p.club), p.band || p.league || "", p.age ? p.age + " yaş" : "") || "—")}</span>
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
      <p class="lede">Transfermarkt etiketi, üretim temelli Aurea değerinin altında kalan oyuncular.</p>
    </section>
    ${positions.map((pos) => `
      <section class="scout-block">
        <h2>${esc(pos.name)}</h2>
        <div class="scout-list">${(pos.items || []).length ? pos.items.map(row).join("") : `<p class="sub">Bu mevkide eşiği geçen oyuncu yok.</p>`}</div>
      </section>`).join("")}
  `;
  view.querySelectorAll(".scout-row").forEach((art) => {
    art.querySelector(".scout-head")?.addEventListener("click", () => art.classList.toggle("open"));
  });
}

async function renderMethod(gen) {
  const data = await api("/api/yontem");
  if (gen !== viewGen) return;
  view.innerHTML = `
    <section class="panel page-head method-head">
      <p class="kicker">Güven</p>
      <h1>${esc(data.title || "Yöntem")}</h1>
      <p class="lede">${esc(data.lede || "")}</p>
    </section>
    <div class="method-prose">
      ${(data.sections || []).map((s) => `
        <article class="panel method-block">
          <h2>${esc(s.title || "")}</h2>
          ${(s.paragraphs || []).map((t) => `<p>${esc(t)}</p>`).join("")}
        </article>`).join("")}
    </div>
  `;
}

function pickColumn(p) {
  if (!p) {
    return `<div class="compare-card empty"><p class="sub">Oyuncu seçin.</p></div>`;
  }
  const r = p.report || {};
  const live = p.live || {};
  const fm = live.fotmob || {};
  const row = p.player || {};
  return `<article class="compare-card">
    <p class="kicker">${esc(metaJoin(row.position || "", row.league || ""))}</p>
    <h2><a href="${esc(row.href || playerHref(row.player_id, row.name))}">${esc(tidyName(row.name))}</a></h2>
    <p class="sub">${esc(metaJoin(clubName(row.club), row.age ? row.age + " yaş" : "") || "—")}</p>
    ${pill(row.direction, row.gap_label)}
    <div class="duo tight">
      <div class="price-card"><div class="k">Transfermarkt</div><div class="n">${esc(row.tm_label || "—")}</div></div>
      <div class="price-card hero"><div class="k">Aurea</div><div class="n">${esc(row.true_label || "—")}</div></div>
    </div>
    <p class="compare-sum">${esc(r.headline || "")}</p>
    <div class="facts compact">
      ${fact("12 ay", row.minutes_365 ? fmtCount(row.minutes_365) + " dk" : "")}
      ${fact("G+A/90", fmtSmallNumber(row.contrib_p90) === "—" ? "" : fmtSmallNumber(row.contrib_p90))}
      ${fact("xG", fm.xg ? fmtSmallNumber(fm.xg) : "")}
      ${fact("Gol", fm.goals != null ? fm.goals : "")}
      ${fact("Şut", fm.shots || "")}
    </div>
  </article>`;
}

function bindPicker(inputId, boxId, onPick) {
  const input = document.getElementById(inputId);
  const box = document.getElementById(boxId);
  if (!input || !box) return;
  let clock;
  const paint = (rows) => {
    const usable = rows.filter((p) => p.player_id != null && String(p.player_id) !== "");
    box.innerHTML = usable.length
      ? usable.map((p) => `<button type="button" class="pick-row" data-id="${esc(p.player_id)}">
          <span><span class="name">${esc(tidyName(p.name))}</span><span class="meta">${esc(metaJoin(clubName(p.club), p.position || "") || "—")}</span></span>
          <span class="num">${esc(p.true_label || p.tm_label || "—")}</span>
        </button>`).join("")
      : `<p class="sub" style="padding:12px">Eşleşme yok.</p>`;
    box.classList.remove("hidden");
    box.querySelectorAll(".pick-row").forEach((btn) => {
      btn.addEventListener("click", (e) => {
        e.preventDefault();
        e.stopPropagation();
        const id = btn.getAttribute("data-id");
        if (id && id !== "null" && id !== "undefined") onPick(id);
      });
    });
  };
  const run = async () => {
    const q = input.value.trim();
    if (q.length < 2) { box.innerHTML = ""; box.classList.add("hidden"); return; }
    try {
      if (searchAbort) searchAbort.abort();
      searchAbort = new AbortController();
      const data = await api(`/api/search?q=${encodeURIComponent(q)}`, { signal: searchAbort.signal });
      paint(data.results || []);
    } catch (ex) {
      if (ex && (ex.name === "AbortError" || ex.message === "Aborted")) return;
      box.innerHTML = `<p class="error">${esc(ex.message)}</p>`;
      box.classList.remove("hidden");
    }
  };
  input.addEventListener("input", () => {
    clearTimeout(clock);
    clock = setTimeout(run, 80);
  });
  input.addEventListener("keydown", (e) => {
    if (e.key !== "Enter") return;
    e.preventDefault();
    const first = box.querySelector(".pick-row");
    const id = first?.getAttribute("data-id");
    if (id && id !== "null" && id !== "undefined") onPick(id);
    else run();
  });
}

async function renderCompare(gen) {
  const q = queryFromHash();
  const leftId = q.left || "";
  const rightId = q.right || "";
  view.innerHTML = `
    <section class="panel page-head">
      <p class="kicker">Yan yana</p>
      <h1>Karşılaştır</h1>
      <p class="lede">${leftId ? "Soldaki oyuncu sabit. Sağdaki ismi seçince karşılaştırma açılır." : "Bir oyuncu dosyasındaki emsali seçin; başlanan isim solda kalır."}</p>
      ${leftId ? "" : `<p class="sub">Karşılaştırma, oyuncu dosyasındaki emsallerden başlar.</p>`}
      <div class="compare-search">
        <div class="${leftId ? "locked-slot" : ""}">
          ${leftId ? `<p class="kicker">Soldaki oyuncu</p><p class="sub">Dosyadan geldi. Sağdaki isim ayrı seçilir.</p>` : ""}
        </div>
        <div>
          <label>Karşılaştırılacak oyuncu
            <input id="cmp-right" type="search" placeholder="İsim veya adres" autocomplete="off" />
          </label>
          <div id="cmp-right-box" class="drop local hidden"></div>
        </div>
      </div>
    </section>
    <div id="cmp-body">${waitScreen("Karşılaştırma", leftId && rightId ? "İki dosya okunuyor." : "Soldaki oyuncu yükleniyor.")}</div>
  `;
  bindPicker("cmp-right", "cmp-right-box", (id) => {
    if (leftId) go(`/karsilastir?left=${encodeURIComponent(leftId)}&right=${encodeURIComponent(id)}`);
    else go(`/karsilastir?left=${encodeURIComponent(id)}`);
  });
  const body = document.getElementById("cmp-body");
  try {
    if (leftId && rightId) {
      const data = await api(`/api/compare?left=${encodeURIComponent(leftId)}&right=${encodeURIComponent(rightId)}`);
      if (gen !== viewGen) return;
      const leftName = tidyName((data.left?.player || {}).name || "Birinci");
      const rightName = tidyName((data.right?.player || {}).name || "İkinci");
      document.title = `${leftName} / ${rightName} · Aurea`;
      body.innerHTML = `
        <article class="read verdict-first analysis-prose">
          <p class="kicker">Hüküm</p>
          <h2>${esc(leftName)} ve ${esc(rightName)}</h2>
          ${(data.verdict || []).map((t) => `<p>${esc(t)}</p>`).join("")}
        </article>
        <div class="compare-grid">
          ${pickColumn(data.left)}
          ${pickColumn(data.right)}
        </div>
      `;
      return;
    }
    if (leftId) {
      const data = await api(`/api/players/${encodeURIComponent(leftId)}`);
      if (gen !== viewGen) return;
      body.innerHTML = `
        <div class="compare-grid">
          ${pickColumn(data)}
          <div class="compare-card empty"><p class="sub">Sağdaki oyuncuyu yazın, ismine basın.</p></div>
        </div>
      `;
      return;
    }
    body.innerHTML = `<p class="sub">Önce bir oyuncu dosyasına gidin, emsal listesinden bir isme basın. Başlanan oyuncu solda kalır.</p>`;
  } catch (ex) {
    if (body && gen === viewGen) body.innerHTML = `<p class="error">${esc(ex.message)}</p>`;
  }
}

async function renderClubs(gen) {
  if (!apiMemo.has("/api/clubs")) view.innerHTML = waitScreen("Kulüpler", "Kulüp listesi hazırlanıyor.");
  const data = await api("/api/clubs");
  if (gen !== viewGen) return;
  const clubs = data.clubs || [];
  const paint = (rows) => {
    const box = document.getElementById("club-list");
    if (!box) return;
    box.innerHTML = rows.map((c) => `
      <a class="club-card" href="${esc(c.href || "/kulup/" + c.id)}">
        <b>${esc(clubName(c.name))}</b>
        <span>${esc(c.league || "")} · ${esc(fmtCount(c.players))} oyuncu</span>
        <span>Aurea ${esc(c.true_label || "—")} · TM ${esc(c.tm_label || "—")}</span>
        <span class="club-gaps">${c.cheap ? `<em class="dusuk">${esc(c.cheap)} ucuz etiket</em>` : ""}${c.rich ? `<em class="yuksek">${esc(c.rich)} piyasa primi</em>` : ""}</span>
      </a>`).join("") || `<p class="sub">Kulüp yok.</p>`;
  };
  view.innerHTML = `
    <section class="panel page-head">
      <h1>Kulüpler</h1>
      <p class="lede">Bir kulübe girin. Gelenler ve kadro, her kulüp için ayrı tutulur.</p>
      <form class="filters" id="club-filt">
        <input id="club-q" placeholder="Kulüp ara" />
      </form>
    </section>
    <div id="club-list" class="club-grid"></div>
  `;
  paint(clubs);
  document.getElementById("club-q").addEventListener("input", (e) => {
    const n = foldTr(e.target.value.trim());
    paint(n ? clubs.filter((c) => clubTextMatch(c.name, n) || clubTextMatch(c.league, n)) : clubs);
  });
}

async function renderClub(token, gen) {
  view.innerHTML = waitScreen("Kulüp kadrosu", "Kadro hazırlanıyor.");
  const data = await api(`/api/clubs/${encodeURIComponent(token)}`);
  if (gen !== viewGen) return;
  document.title = `${data.name || "Kulüp"} · Aurea`;
  const known = new Set([...(data.cheap || []), ...(data.rich || []), ...(data.even || [])].map((p) => p.player_id));
  const rest = (data.items || []).filter((p) => !known.has(p.player_id));
  const moves = data.transfers || {};
  const labels = { firsat: "Fırsat", uygun: "Uygun", pahali: "Pahalı", riskli: "Riskli" };
  const dealCard = (d) => `<article class="deal ${esc(d.verdict || "uygun")}">
      <div class="deal-head-row">
        <div>
          <span class="stamp ${esc(d.verdict || "uygun")}">${esc(d.verdict_label || labels[d.verdict] || "Uygun")}</span>
          <b>${esc(tidyName(d.name))}</b>
          <p class="deal-clubs">${d.other ? `<span class="from">${esc(clubName(d.other))}</span><i>→</i>` : ""}<b class="to">${esc(clubName(data.name) || "")}</b>${d.date ? `<span class="deal-date">${esc(fmtDate(d.date))}</span>` : ""}</p>
        </div>
        <div class="fee">${esc(d.fee_label || "—")}</div>
      </div>
      <div class="deal-detail">
        <div class="deal-money">
          <div><span>Bedel</span><b>${esc(d.fee_label || "—")}</b></div>
          <div><span>Transfermarkt</span><b>${esc(d.tm_label || "—")}</b></div>
          <div><span>Aurea değeri</span><b>${esc(d.true_label || "—")}</b></div>
          ${d.date ? `<div><span>Geliş</span><b>${esc(fmtDate(d.date))}</b></div>` : ""}
        </div>
        <p class="deal-head">${esc(d.headline || "")}</p>
        <p>${esc(d.body || "")}</p>
        <p style="margin-top:12px"><a href="${esc(d.href || "/ara")}">Oyuncu dosyası</a></p>
      </div>
    </article>`;
  view.innerHTML = `
    <section class="panel page-head">
      <p class="kicker">${esc(data.league || "")}${moves.season ? " · " + esc(moves.season) : ""}</p>
      <h1>${esc(clubName(data.name) || "Kulüp")}</h1>
      <p class="lede">${esc(fmtCount(data.players))} oyuncu · Aurea ${esc(data.true_label || "—")} · Transfermarkt ${esc(data.tm_label || "—")}. İsme basın; geliş tarihi ve kulüp verimi açılır.</p>
    </section>
    ${(moves.in || []).length ? `<div class="group"><h3>Gelenler</h3><div class="deals deals-pad">${(moves.in || []).map(dealCard).join("")}</div></div>` : `<p class="sub">Bu sezon için gelen kaydı henüz yok veya okunamadı.</p>`}
    <div class="duo">
      <div class="price-card hero"><div class="k">Aurea toplamı</div><div class="n">${esc(data.true_label || "—")}</div></div>
      <div class="price-card"><div class="k">Transfermarkt toplamı</div><div class="n">${esc(data.tm_label || "—")}</div></div>
    </div>
    ${tenureBlock("Ucuz etiket", data.cheap)}
    ${tenureBlock("Pahalı etiket", data.rich)}
    ${tenureBlock("Uyumlu", data.even)}
    ${tenureBlock("Diğer", rest)}
  `;
  bindTenure(view, data.items || []);
  view.querySelector(".deals")?.addEventListener("click", (e) => {
    if (e.target.closest("a")) return;
    const art = e.target.closest(".deal");
    if (art) art.classList.toggle("open");
  });
}

async function render() {
  const gen = ++viewGen;
  hideDrop();
  normalizeRoute();
  const parts = routeParts();
  setTitle(parts);
  setActiveNav();
  if (parts[0] === "fantezi") {
    boot.classList.add("hidden");
    boot.setAttribute("aria-hidden", "true");
    try { await renderFantasy(gen); }
    catch (err) { if (gen === viewGen) view.innerHTML = `<p class="error">${esc(err.message)}</p>`; }
    return;
  }
  if (parts[0] === "yontem") {
    boot.classList.add("hidden");
    boot.setAttribute("aria-hidden", "true");
    try { await renderMethod(gen); }
    catch (err) { if (gen === viewGen) view.innerHTML = `<p class="error">${esc(err.message)}</p>`; }
    return;
  }
  const ok = await ensureReady();
  if (gen !== viewGen) return;
  if (!ok) return;
  try {
    if (parts[0] === "ara") await renderSearch(gen);
    else if (parts[0] === "superlig") { go("/kulupler", true); return; }
    else if (parts[0] === "olcum") { go("/", true); return; }
    else if (parts[0] === "scout") await renderScout(gen);
    else if (parts[0] === "piyasa") await renderMarket({}, gen);
    else if (parts[0] === "ligler") await renderLeagues(gen);
    else if (parts[0] === "lig" && parts[1]) await renderMarket({ league: parts[1] }, gen);
    else if (parts[0] === "oyuncu" && parts[1]) await renderPlayer(parsePlayerToken(parts[1]) || parts[1], gen);
    else if (parts[0] === "kulupler") await renderClubs(gen);
    else if (parts[0] === "kulup" && parts[1]) await renderClub(parts[1], gen);
    else if (parts[0] === "karsilastir") { go("/", true); return; }
    else {
      if (!apiMemo.has("/api/pulse")) view.innerHTML = waitScreen("Pano", "Özet hazırlanıyor.");
      const pulse = await api("/api/pulse");
      if (gen !== viewGen) return;
      renderHome(pulse);
    }
  } catch (err) {
    if (gen === viewGen) view.innerHTML = `<p class="error">${esc(err.message)}</p>`;
  }
}

window.addEventListener("hashchange", render);
window.addEventListener("popstate", render);
ensureReady().then((ok) => {
  const first = routeParts()[0];
  if (first === "fantezi" || first === "yontem") {
    render();
    return;
  }
  if (ok) render();
  else bootTimer = setInterval(async () => { if (await ensureReady()) render(); }, 1200);
});
