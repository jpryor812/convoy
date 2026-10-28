/* The menus of the 3D game: the top strip, the unit panel, the advisors down
   the right, and the framed panel they open -- a place, a building, a person,
   a list, or a form for any action. Every button is one call to `/api/act`:
   the same dispatcher, and the same refusals, as an agent's tool call. */

export function createUI(ctx){
  const {api, S, walkToPlace, walkToBuilding, fastTravel, short} = ctx;
  const G = window.GAME;
  const $ = id => document.getElementById(id);
  const esc = s => String(s == null ? "" : s).replace(/[&<>"']/g, ch => ({"&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;"}[ch]));
  const money = v => (+v || 0).toLocaleString(undefined, {maximumFractionDigits: 0});
  const money2 = v => (+v || 0).toLocaleString(undefined, {minimumFractionDigits: 0, maximumFractionDigits: 2});
  const VEHICLES = ["Camel", "Horse", "Donkey Cart", "2-Horse Chariot", "4-Horse Chariot"];

  let TOOLS = {}, FEED = [], FEED_SEQ = 0, CARDS = null, cardsAt = 0;
  let view = null;                   // {kind: "tab"|"building"|"person"|"form", ref, back}
  const seen = {chat: 0, news: 0};

  /* ---------------------------------------------------------- talking to the server */
  function toast(msg, kind, onClick){
    const el = document.createElement("div");
    el.className = "toast" + (kind ? " " + kind : "") + (onClick ? " click" : "");
    el.textContent = msg; $("toasts").appendChild(el);
    if (onClick) el.onclick = () => { el.remove(); onClick(); };
    while ($("toasts").children.length > 4) $("toasts").firstChild.remove();
    setTimeout(() => el.remove(), kind === "bad" ? 7000 : 4500);
  }
  async function act(action, args){
    let r;
    try { r = await api.post("/api/act", {action, args: Object.assign({why: ""}, args || {})}); }
    catch (e) { toast("The server did not answer.", "bad"); return {ok: false}; }
    toast(r.ok ? r.message : `Can't: ${r.message || r.error}`, r.ok ? "" : "bad");
    CARDS = null;
    refreshSoon();
    return r;
  }
  /* Fetch an order yourself: order with no courier fee (if given a seller)
     and claim the haul. The server loads it when you walk into the seller's
     place and hands it over when you walk into yours; the compass points. */
  async function fetchIt(args){
    let r;
    try { r = await api.post("/api/fetch", args); }
    catch (e) { toast("The server did not answer.", "bad"); return {ok: false}; }
    toast(r.ok ? r.message : `Can't: ${r.message || r.error}`, r.ok ? "" : "bad");
    // You ride there yourself (2026-10-18): the compass points the way.
    if (r.ok && r.go){ close(); toast("Follow the compass at the top of the screen."); }
    CARDS = null; refreshSoon();
    return r;
  }
  let soon = null;
  function refreshSoon(){
    clearTimeout(soon);
    soon = setTimeout(() => { pollState(); pollStatus(); pollFeed(); pollBoard(); pollAdvisor(); }, 150);
  }
  async function cards(){
    if (CARDS && performance.now() - cardsAt < 2500) return CARDS;
    try { CARDS = (await api.get("/cards")).cards || {}; cardsAt = performance.now(); }
    catch (e) { CARDS = CARDS || {}; }
    return CARDS;
  }

  /* ---------------------------------------------------------- the strip, the ribbon, the unit */
  const clock = h => {
    const day = Math.floor(h / 24) + 1, m = Math.floor((h % 24) * 60);
    return `DAY ${day} · ${String(Math.floor(m / 60)).padStart(2, "0")}:${String(m % 60).padStart(2, "0")}`;
  };
  setInterval(() => { $("t-clock").textContent = clock(S.HOUR); }, 250);

  /* COMING UP (2026-10-18): every countdown you have running, soonest
     first -- the "one more turn" list. */
  const dur = h => h < 1 / 60 ? "now" : h < 1 ? `${Math.round(h * 60)}m` : h < 24 ? `${Math.floor(h)}h ${Math.round((h % 1) * 60)}m` : `${(h / 24).toFixed(1)} days`;
  function renderComing(list){
    const box = $("coming"); if (!box) return;
    if (!list || !list.length){
      box.style.display = "";
      $("cu-body").innerHTML = `<div class="cu-empty">Nothing counting down. <a href="#" data-tab="knowhow">Study something</a> or start a project at a business.</div>`;
    } else {
      box.style.display = "";
      $("cu-body").innerHTML = list.map(x => `<div class="cu ${esc(x.kind)}"><span>${esc(x.what)}</span><b>${dur(x.hours)}</b></div>`).join("");
    }
    $("cu-body").querySelectorAll("[data-tab]").forEach(a => a.onclick = e => { e.preventDefault(); openTab(a.dataset.tab); });
  }
  function renderHUD(){
    const st = S.ST; if (!st) return;
    const y = st.you;
    renderComing(st.upcoming);
    $("t-cash").textContent = money2(y.denari);
    $("t-worth").textContent = money(y.net_worth);
    $("t-rank").textContent = `#${st.your_rank} of ${st.population}`;
    const hungry = st.hunger !== "Normal", left = st.fed_hours_left;
    $("t-food").textContent = hungry ? st.hunger.toUpperCase() : left > 0 ? `Fed ${left.toFixed(0)}h` : "Eat now";
    $("t-foodbox").classList.toggle("warn", hungry || left < 3);
    if (st.cities && st.cities.length > 1){
      const order = st.cities.slice().sort((a, b) => b.total - a.total);
      const i = order.findIndex(c => c.key === st.city);
      $("t-citybox").style.display = "";
      $("t-city").textContent = `${st.city_name} ${["1st", "2nd", "3rd"][i] || ""}`;
      $("t-citybox").title = order.map(c => `${c.name}: ${money(c.total)}`).join("\n");
    }
    $("t-spend").textContent = `$${st.spent.toFixed(2)} / $${st.budget.toFixed(0)}`;
    $("t-pause").textContent = st.paused ? "PLAY" : "PAUSE";
    if ([...$("t-pace").options].every(o => o.value !== String(st.pace)))
      $("t-pace").insertAdjacentHTML("beforeend", `<option value="${st.pace}">x${st.pace}</option>`);
    if (document.activeElement !== $("t-pace")) $("t-pace").value = String(st.pace);
    $("r-main").textContent = (st.paused ? "PAUSED · " : "") + st.activity.toUpperCase();
    $("r-sub").textContent = st.vehicle ? `Riding a ${st.vehicle}` : "";
    $("note").style.display = st.note ? "block" : "none"; $("note").textContent = st.note || "";
    $("prompt").style.display = "none";      // the Next move card does this job now
    renderUnit();
  }
  function renderUnit(){
    const st = S.ST, o = S.OBS; if (!st) return;
    $("u-name").textContent = short(st.you.name).toUpperCase();
    $("u-sub").textContent = `${st.city_name} · ${st.location}`;
    $("u-doing").textContent = st.activity.replace(/ · .*/, "");
    const left = Math.max(0, st.fed_hours_left), hungry = st.hunger !== "Normal";
    $("u-food").textContent = hungry ? st.hunger : `${left.toFixed(1)}h left`;
    $("u-foodbar").style.width = `${hungry ? 4 : Math.min(100, left / 24 * 100)}%`;
    if ($("u-hp")){ const hp = st.health ?? 100; $("u-hp").textContent = `${Math.round(hp)} / 100`; $("u-hpbar").style.width = `${hp}%`; }
    if (o){
      // A load you are hauling for a business takes room too.
      const haul = ((S.BOARD && S.BOARD.hauls) || []).find(h => h.carrying);
      const n = Object.values(o.you.carrying || {}).reduce((a, b) => a + b, 0) + (haul ? haul.qty : 0);
      $("u-carry").textContent = `${n} / ${o.you.capacity}${haul ? ` · ${haul.qty} ${haul.item} to deliver` : ""}${st.vehicle ? " · " + st.vehicle : ""}`;
    }
    const acts = [];
    const working = /^Working/.test(st.activity);
    if (working) acts.push(B("Stop work", "end_shift"));
    else if (o && o.you.job) acts.push(B("Work 4h", "start_shift", {hours: 4}, true));
    const tavernHere = o && (o.here.businesses || []).some(b => b.sells && b.sells.Meal);
    if (tavernHere && (hungry || left < 8)) acts.push(B("Eat here", "buy_meal", {}, !working));
    acts.push(`<button class="btn" data-me="1" title="Health, food and eating">Eat${hungry ? " \u26a0\ufe0f" : ""}</button>`);
    acts.push(`<button class="btn" data-tab="here">Here</button>`);
    acts.push(`<button class="btn" data-cam="1">${ctx.mode && ctx.mode() === "third" ? "Overview (Tab)" : "Take control (Tab)"}</button>`);
    $("unitacts").innerHTML = acts.join("");
    wire($("unitacts"));
    const me = $("unitacts").querySelector("[data-me]");
    if (me) me.onclick = () => openMe();
    const cam = $("unitacts").querySelector("[data-cam]");
    if (cam) cam.onclick = () => { ctx.toggleCamera && ctx.toggleCamera(); renderUnit(); };
  }

  async function pollStatus(){
    let st; try { st = await api.get("/api/status"); } catch (e) { return; }
    if (st.error){ location.reload(); return; }
    S.ST = st; S.base = {hour: st.hour, at: performance.now()};
    renderHUD(); ctx.onStatus && ctx.onStatus();
  }
  async function pollState(){
    let r; try { r = await api.get("/api/state"); } catch (e) { return; }
    if (!r || !r.obs) return;
    S.OBS = r.obs; S.OBS_TEXT = r.text;
    renderUnit(); badges(); refreshPanel();
  }
  async function pollBoard(){
    try { S.BOARD = await api.get("/api/board"); } catch (e) { return; }
    badges();
  }
  async function pollFeed(){
    let r; try { r = await api.get(`/api/feed?since=${FEED_SEQ}`); } catch (e) { return; }
    for (const f of r.feed || []){
      if (f.seq <= FEED_SEQ) continue;
      FEED_SEQ = f.seq; FEED.push(f);
      if (f.kind === "alert") toast(f.text, "bad");
      else if (f.kind === "message"){
        toast(f.text, "msg", f.ref ? () => openThread(f.ref) : null);
        if (THREAD && f.ref === THREAD) loadThread();
      }
      else if (f.kind === "wake" && !/^You arrived/.test(f.text)) toast(f.text);
      else if (f.kind === "rival"){
        toast(short(f.text), "rival");
        if (f.ref && window.convoyLife) window.convoyLife.callout(f.ref, short(f.text));
      }
      else if (f.kind === "milestone") toast(f.text, "milestone");
      // The market: something you could buy, someone who wants what you hold,
      // and one of your buy orders filled. Click to go straight there.
      else if (f.kind === "family") toast(f.text, "milestone", () => { view = null; openTab("house"); });
      else if (f.kind === "offer") toast(f.text, "offer", () => openMarket("buy", f.ref));
      else if (f.kind === "wanted") toast(f.text, "offer", () => openMarket("sell"));
      else if (f.kind === "you" && /filled your buy order/.test(f.text)) toast(f.text, "", () => openMarket("deliveries"));
    }
    while (FEED.length > 250) FEED.shift();
    if (view && view.kind === "tab" && view.ref === "news") { seen.news = FEED.length; refreshPanel(); }
    badges();
  }
  function badge(id, n){ const el = $(id); if (!el) return; el.textContent = n > 99 ? "99+" : n; el.style.display = n > 0 ? "flex" : "none"; }
  function badges(){
    const onTab = t => view && view.kind === "tab" && view.ref === t;
    if (S.OBS) badge("b-chat", onTab("chat") ? 0 : Math.max(0, (S.OBS.chat || []).length - seen.chat));
    badge("b-news", onTab("news") ? 0 : Math.max(0, FEED.length - seen.news));
    // A mission waiting to be started.
    if (S.ST) badge("b-missions", S.ST.mission ? 0 : (S.ADV && S.ADV.advice || []).some(m => m.button && m.button.kind === "mission" && m.button.mission_action === "start") ? 1 : 0);
    // SOMETHING NEW ON THE MARKET (2026-10-18): a red count on its button until you look.
    if (S.ST && S.ST.market_keys){
      if (seen.market == null || onTab("market")) seen.market = new Set(S.ST.market_keys);
      badge("b-market", S.ST.market_keys.filter(k => !seen.market.has(k)).length);
    }
    if (S.BOARD) badge("b-jobs", S.BOARD.jobs.filter(j => j.to_me || (j.mine && Array.isArray(j.applicants) && j.applicants.length)).length);
  }

  $("t-pause").onclick = async () => { await api.post("/api/control", {paused: !(S.ST && S.ST.paused)}); pollStatus(); };
  $("t-pace").onchange = async () => { await api.post("/api/control", {pace: +$("t-pace").value}); pollStatus(); };
  $("t-menu").onclick = () => openTab("menu");
  $("prompt").onclick = () => openTab("here");
  document.querySelectorAll("#advisors button").forEach(b => b.onclick = () => openTab(b.dataset.tab));
  $("p-close").onclick = () => close();

  /* ---------------------------------------------------------- buttons */
  const B = (label, action, args, go) =>
    `<button class="btn${go ? " go" : ""}" data-act="${esc(action)}" data-args='${esc(JSON.stringify(args || {}))}'>${esc(label)}</button>`;
  const F = (label, action, args, title) =>
    `<button class="btn" data-form="${esc(action)}" data-args='${esc(JSON.stringify(args || {}))}' data-title="${esc(title || label)}">${esc(label)}&hellip;</button>`;
  function wire(root){
    root.querySelectorAll("[data-act]").forEach(b => b.onclick = e => {
      e.stopPropagation(); act(b.dataset.act, JSON.parse(b.dataset.args));
    });
    root.querySelectorAll("[data-form]").forEach(b => b.onclick = e => {
      e.stopPropagation(); openForm(b.dataset.form, JSON.parse(b.dataset.args), b.dataset.title);
    });
    root.querySelectorAll("[data-tab]").forEach(b => { if (!b.closest("#advisors")) b.onclick = e => { e.stopPropagation(); view = null; openTab(b.dataset.tab); }; });
    root.querySelectorAll("[data-walk]").forEach(b => b.onclick = e => { e.stopPropagation(); walkToPlace(b.dataset.walk); close(); });
    root.querySelectorAll("[data-fast]").forEach(b => b.onclick = e => { e.stopPropagation(); close(); fastTravel(b.dataset.fast); });
    root.querySelectorAll("[data-gobiz]").forEach(b => b.onclick = e => {
      e.stopPropagation(); const id = b.dataset.gobiz; close(); walkToBuilding(id, () => openBuilding(id));
    });
    root.querySelectorAll("[data-building]").forEach(b => b.onclick = e => { e.stopPropagation(); openBuilding(b.dataset.building); });
    root.querySelectorAll("[data-person]").forEach(b => b.onclick = e => { e.stopPropagation(); openPerson(b.dataset.person); });
    root.querySelectorAll("[data-msg]").forEach(b => b.onclick = e => { e.stopPropagation(); openThread(b.dataset.msg); });
    root.querySelectorAll("[data-assets]").forEach(b => b.onclick = e => { e.stopPropagation(); openAssets(b.dataset.assets); });
    // Point the way without walking you there: the compass shows it.
    root.querySelectorAll("[data-point]").forEach(b => b.onclick = e => {
      e.stopPropagation(); S.errand = {place: b.dataset.point, label: b.dataset.label || `Go to ${b.dataset.point}`}; close();
      toast(`${S.errand.label}: follow the compass.`);
    });
  }

  /* ---------------------------------------------------------- the panel */
  const TITLES = {here: "Where you stand", travel: "Travel", business: "Businesses & land", jobs: "Jobs",
    market: "Market", chat: "Chat", news: "News", ranks: "Rankings", menu: "Orders & game",
    ledger: "Ledger", guide: "Guide: what makes what", people: "People",
    knowhow: "Know-how", house: "Your house", missions: "Missions"};
  function show(title, html){
    if ($("p-title").textContent !== title) $("pbody").scrollTop = 0;   // a new panel opens at its top
    $("p-title").textContent = title;
    $("pbody").innerHTML = html;
    $("panel").classList.add("open");
    wire($("pbody"));
    document.querySelectorAll("#advisors button").forEach(b => b.classList.toggle("on", view && view.kind === "tab" && b.dataset.tab === view.ref));
    $("prompt").style.display = "none";
  }
  function close(){
    view = null; $("panel").classList.remove("open");
    document.querySelectorAll("#advisors button").forEach(b => b.classList.remove("on"));
    renderHUD();
  }
  function openMarket(tab, item){
    mkTab = tab || "buy"; mkItem = item || ""; mkCity = "";
    if (view && view.kind === "tab" && view.ref === "market") renderView(true);
    else { view = null; openTab("market"); }
  }
  function openTab(tab){
    if (view && view.kind === "tab" && view.ref === tab){ close(); return; }
    view = {kind: "tab", ref: tab};
    if (tab === "chat") seen.chat = (S.OBS && S.OBS.chat || []).length;
    if (tab === "news") seen.news = FEED.length;
    badges();
    renderView(true);
  }
  function refreshPanel(){
    if (!view || view.kind === "form") return;
    const body = $("pbody");
    if (body.contains(document.activeElement) && /INPUT|SELECT|TEXTAREA/.test(document.activeElement.tagName)) {
      if (view.ref === "chat") updateChat();
      return;
    }
    renderView(false);
  }
  async function renderView(force){
    if (!view || !S.OBS || !S.BOARD) return;
    const top = $("pbody").scrollTop;
    if (view.kind === "tab"){
      if (view.ref === "chat" && !force){ updateChat(); return; }
      if (view.ref === "market"){
        const data = await api.get("/api/market");
        if (!view || view.ref !== "market") return;
        if (!force && $("pbody").contains(document.activeElement) && /INPUT|SELECT/.test(document.activeElement.tagName)) return;
        show(TITLES.market, marketPanel(data));
        wireMarket(data);
        if (!force) $("pbody").scrollTop = top;
        return;
      }
      if (view.ref === "missions"){
        const data = await api.get("/api/missions");
        if (!view || view.ref !== "missions") return;
        show(TITLES.missions, missionsPanel(data));
        $("pbody").querySelectorAll("[data-mission]").forEach(b => b.onclick = () => missionAct(b.dataset.mission, b.dataset.id));
        if (!force) $("pbody").scrollTop = top;
        return;
      }
      if (view.ref === "knowhow" || view.ref === "house"){
        const ref = view.ref, data = await api.get(ref === "knowhow" ? "/api/knowhow" : "/api/household");
        if (!view || view.ref !== ref) return;
        if (!force && $("pbody").contains(document.activeElement) && /INPUT|SELECT/.test(document.activeElement.tagName)) return;
        show(TITLES[ref], ref === "knowhow" ? knowhowPanel(data) : housePanel(data));
        if (ref === "house") wireHouse(data);
        if (!force) $("pbody").scrollTop = top;
        return;
      }
      if (view.ref === "people"){
        const data = await api.get(`/api/citizens?city=${encodeURIComponent(pplCity)}`);
        if (!view || view.ref !== "people") return;
        if (!force && $("pbody").contains(document.activeElement) && /INPUT|SELECT/.test(document.activeElement.tagName)) return;
        show(TITLES.people, peoplePanel(data));
        wirePeople(data);
        if (!force) $("pbody").scrollTop = top;
        return;
      }
      if (view.ref === "ledger" || view.ref === "guide"){
        if (!force) return;                     // fetched on open; not every poll
        const ref = view.ref, data = await api.get(ref === "ledger" ? "/api/ledger" : "/api/chains");
        if (!view || view.ref !== ref) return;
        show(TITLES[ref], ref === "ledger" ? ledgerPanel(data) : guidePanel(data));
        if (ref === "ledger") drawCharts(data);
        return;
      }
      show(TITLES[view.ref], TABS[view.ref]());
      if (view.ref === "chat") wireChat();
      if (view.ref === "menu") wireMenu();
    } else if (view.kind === "building"){
      const c = (await cards())[view.ref];
      if (!view || view.kind !== "building") return;
      if (c && c.owner_id === G.you){
        // Your own: everything on one screen. See ownPanel.
        const det = await api.get(`/api/business?id=${encodeURIComponent(view.ref)}`);
        if (!view || view.kind !== "building" || det.error) return;
        const typeName = {"Tavern / Inn": "Tavern", "Vehicle Dealer / Stable": "Stable", "Weaponsmith / Armory": "Armory"}[det.type] || det.type;
        show(`Your ${typeName} \u00b7 ${det.location}`, ownPanel(det));
        wireOwn(det);
        if (!force) $("pbody").scrollTop = top;
        return;
      }
      const typeName = c ? ({"Tavern / Inn": "Tavern", "Vehicle Dealer / Stable": "Stable", "Weaponsmith / Armory": "Armory"}[c.type] || c.type) : "Building";
      show(c ? `${typeName} \u2014 ${c.owner_id === G.you ? "yours" : short(c.owner)}` : "Building", buildingPanel(view.ref, c));
    } else if (view.kind === "report"){
      show(`Day ${view.ref.day} report`, reportPanel(view.ref));
    } else if (view.kind === "land"){
      show(`Land at ${view.ref}`, landPanel(view.ref));
    } else if (view.kind === "person"){
      const c = (await cards())[view.ref];
      if (!view || view.kind !== "person") return;
      show(c ? short(c.name) : "Citizen", personPanel(view.ref, c));
    } else if (view.kind === "assets"){
      const a = await api.get(`/api/assets?id=${encodeURIComponent(view.ref)}`);
      if (!view || view.kind !== "assets" || a.error) return;
      show(a.you ? "What you own" : `What ${short(a.name)} owns`, assetsPanel(a));
      if (!force) $("pbody").scrollTop = top;
    } else if (view.kind === "me"){
      const m = await api.get("/api/me");
      if (!view || view.kind !== "me" || m.error) return;
      show("You", mePanel(m));
      $("pbody").querySelectorAll("[data-eat]").forEach(b => b.onclick = async () => {
        const body = b.dataset.eat === "carried" ? {carried: true, meal: b.dataset.meal}
          : b.dataset.order ? {order: b.dataset.order} : {tavern: b.dataset.eat};
        const r = await api.post("/api/eat", body);
        toast(r.ok ? r.message : `Can't: ${r.message}`, r.ok ? "" : "bad");
        refreshSoon(); setTimeout(() => renderView(true), 300);
      });
      if (!force) $("pbody").scrollTop = top;
    }
    if (!force) $("pbody").scrollTop = top;
  }
  function openBuilding(id){ view = {kind: "building", ref: id}; CARDS = null; renderView(true); }
  function openLand(place){ view = {kind: "land", ref: place}; renderView(true); }
  function openPerson(id){ view = {kind: "person", ref: id}; CARDS = null; renderView(true); }
  function openAssets(id){ view = {kind: "assets", ref: id}; renderView(true); }
  function openMe(){ if (view && view.kind === "me"){ close(); return; } view = {kind: "me", ref: ""}; renderView(true); }

  /* WHY ARE THEY RICH (designer request, 2026-10-18): tap anyone on the
     leaderboard and see what their net worth is made of. */
  function assetsPanel(a){
    const total = Math.max(1, a.worth);
    let out = `<div class="howto">${esc(a.house || "")}${a.house ? " \u00b7 " : ""}${esc(a.calling || "")} in ${esc(a.city_name)}${a.job ? ` \u00b7 works at a ${esc(a.job.split(" /")[0])}` : ""}. Net worth <b>${money(a.worth)}</b>.</div>`;
    out += `<div class="worthbar">` + a.lines.filter(l => l[1] > 0).map((l, i) => `<span class="wb${i}" style="width:${l[1] / total * 100}%" title="${esc(l[0])}: ${money(l[1])}"></span>`).join("") + `</div>`;
    out += a.lines.map((l, i) => `<div class="row"><div class="grow"><i class="wbdot wb${i}"></i>${esc(l[0])}</div><b>${money(l[1])}</b></div>`).join("");
    out += `<h3>Businesses (${a.businesses.length})</h3>`;
    out += a.businesses.length ? a.businesses.map(b => `<div class="row"><div class="grow"><b>${esc(b.type.split(" /")[0])}</b> <span class="dim">at ${esc(b.place)}</span><small>${b.making ? `making ${esc(b.making)}` : "idle"} \u00b7 ${b.staff} working \u00b7 ${b.profit_day > 0 ? `<span class="c-good">+${money(b.profit_day)}/day</span>` : b.profit_day < 0 ? `<span class="c-bad">${money(b.profit_day)}/day</span>` : "no profit yet"} \u00b7 stock ${money(b.stock)}</small></div><b>${money(b.worth)}</b></div>`).join("")
      : `<div class="empty">None. ${a.you ? "You" : "They"} earn by working for others.</div>`;
    const goods = Object.entries(a.goods || {});
    out += `<h3>Carrying</h3>` + (goods.length ? `<div class="dim">${goods.map(([i, q]) => `${q} ${esc(i)}`).join(", ")}</div>` : `<div class="empty">Nothing.</div>`);
    out += `<h3>Other</h3><div class="row"><div class="grow">Land plots</div><b>${a.plots}</b></div>`
      + `<div class="row"><div class="grow">Vehicles</div><b>${a.vehicles.length ? esc(a.vehicles.join(", ")) : "none"}</b></div>`
      + `<div class="row"><div class="grow">Weapon</div><b>${esc(a.weapon)}</b></div>`
      + `<div class="row"><div class="grow">Household</div><b>${a.family}</b></div>`;
    if (!a.you) out += `<div class="dim" style="margin-top:8px">What they buy and sell, and from whom, is in a town report (People page).</div>`;
    return out;
  }

  /* YOU (designer request, 2026-10-18): tap your portrait to see your health
     and food, and eat. */
  function mePanel(m){
    const hungry = m.stage !== "Normal";
    let out = `<div class="row"><div class="grow">Health</div><b>${Math.round(m.health)} / 100</b></div><div class="bar hp"><i style="width:${m.health}%"></i></div>`;
    out += `<div class="row"><div class="grow">Food</div><b class="${hungry ? "c-bad" : ""}">${hungry ? esc(m.stage) : `fed for ${m.fed_hours.toFixed(1)}h`}</b></div><div class="bar"><i style="width:${hungry ? 4 : Math.min(100, m.fed_hours / 24 * 100)}%"></i></div>`;
    out += `<div class="dim">Health comes back slowly while you are fed. Hungry, you work and fight slower; starving costs health.</div>`;
    out += m.outposts
      ? `<h3>Eat</h3><div class="tip">\u{1F37A} <b>Food comes from taverns</b>, and only there -- you cannot cook. Walk in and eat, or have a meal brought to you for a fee by distance; it arrives in what you carry and you eat it from this card.</div>`
      : `<h3>Eat</h3><div class="tip">\u{1F37A} <b>Food is sold at taverns</b>, and only there -- you cannot cook. Walk into a tavern and eat there, or buy a Meal there to carry and eat later from this card.</div>`;
    for (const d of m.on_way || []) out += `<div class="row"><div class="grow"><b>${esc(d.meal)}</b> <span class="dim">on its way to you \u00b7 about ${d.minutes} min</span></div></div>`;
    let any = false;
    for (const c of m.carried){ any = true; out += `<div class="row"><div class="grow"><b>${esc(c.meal)}</b> <span class="dim">you carry ${c.qty} \u00b7 ${c.hours}h</span></div><button class="btn go" data-eat="carried" data-meal="${esc(c.meal)}">Eat</button></div>`; }
    for (const t of m.menu){ any = true; out += `<div class="row"><div class="grow"><b>${esc(t.meal)}</b> <span class="dim">at ${esc(t.name)} \u00b7 ${t.hours}h${t.staffed ? "" : " \u00b7 nobody serving"}</span></div><button class="btn go" data-eat="${esc(t.tavern)}" ${t.staffed && m.coins >= t.price ? "" : "disabled"}>Eat (${money(t.price)})</button></div>`; }
    if (!any) out += `<div class="empty">No food where you stand and none on you.</div>`;
    const away = (m.taverns || []).filter(t => !t.here);
    if (away.length && !away.some(t => t.home) && !m.outposts) out += `<div class="dim">Your town has no tavern yet. The nearest food is in the next town -- or found a tavern yourself.</div>`;
    if (away.length) out += `<h3>Where to eat</h3>` + away.map(t => `<div class="row"><div class="grow"><b>${esc(t.name)}</b> <span class="dim">at ${esc(t.place)}${t.home ? "" : ", " + esc(t.city_name)} \u00b7 ${esc(t.meal)} ${money(t.price)} \u00b7 ${t.hours}h${t.open ? "" : " \u00b7 not serving now"}</span></div>${t.brought ? `<button class="btn go" data-eat="order" data-order="${esc(t.id)}" ${t.open && m.coins >= t.brought ? "" : "disabled"} title="Brought to you in about ${t.minutes} min">Have it brought (${money(t.brought)})</button>` : ""}<button class="btn" data-point="${esc(t.place)}" data-label="To the tavern at ${esc(t.place)}">Show me the way</button></div>`).join("");
    else if (!(m.taverns || []).length) out += `<div class="empty">There is no tavern anywhere yet -- found one.</div>`;
    out += `<h3>Kit</h3><div class="row"><div class="grow">Weapon</div><b>${esc(m.weapon)}</b></div>`
      + `<div class="row"><div class="grow">Armour</div><b>${Object.values(m.armour).length ? esc(Object.values(m.armour).join(", ")) : "none"}</b></div>`
      + `<div class="dim"><b>R</b> swings, hold <b>F</b> to block.</div>`;
    return out;
  }

  /* ---------------------------------------------------------- what each panel says */
  const placeOf = name => S.places[name] || {};
  const atPlace = name => S.OBS && S.OBS.you.location === name && !/^Travelling/.test((S.ST || {}).activity || "");
  const ownerLabel = id => id === G.you ? "you" : short(nameOf(id));
  function nameOf(id){
    if (!id) return "";
    const a = S.BOARD && S.BOARD.agents.find(x => x.id === id);
    return a ? a.name : id;
  }
  const kindOf = name => { const k = placeOf(name).kind; return k === "spur" ? "spur road" : k ? "main road" : ""; };

  function goButtons(place, buildingId){
    const p = placeOf(place), me = placeOf(S.OBS.you.location);
    const far = !me.city || p.city !== me.city;
    return (buildingId ? `<button class="btn go" data-gobiz="${esc(buildingId)}">Walk there</button>`
                       : `<button class="btn go" data-walk="${esc(place)}">Walk there</button>`)
      + `<button class="btn${far ? " go" : ""}" data-fast="${esc(place)}">Fast travel</button>`;
  }

  function buildingPanel(id, c){
    if (!c) return `<div class="empty">Nothing is known about this building yet.</div>`;
    const mine = c.owner_id === G.you, here = atPlace(c.place);
    const staffed = c.government || (c.staff || []).some(s => /working/.test(s.doing || ""));
    let out = `<div class="card"><div class="t">${esc(c.type)}${mine ? ' <span class="yours">(yours)</span>' : ""}</div>
      <div class="m">${mine ? "Owned by you" : c.government ? "The state's: always open, sells high, buys low, hires at a fixed wage" : `Owned by ${esc(short(c.owner))}`} · ${esc(c.place)}, ${esc(kindOf(c.place))}</div>
      <div class="m">${c.closed ? '<span class="warn">Closed for good</span>' : c.government ? '<span class="good">Always open</span>' : staffed ? '<span class="good">Open: someone is at work</span>'
        : '<span class="warn">Nobody on shift: it will not sell to you right now</span>'}${c.producing ? ` · making ${esc(c.producing)}` : ""}${c.blocked ? ' <span class="warn">(stalled)</span>' : ""}</div></div>`;
    if (c.land && c.land.item) out += `<div class="card rich-card"><div class="t">Rich ground</div><div class="m">This land makes <b>${esc(c.land.item)}</b> ${Math.round(c.land.pct * 100)}% faster.${mine ? " Making it here pays best." : ""}</div></div>`;
    else if (c.land) out += `<div class="tip">Ordinary ground: no bonus here.</div>`;
    else if (mine && (c.type === "Farm" || c.type === "Mining Operation")) out += `<div class="tip">The ground shows what it is with the first harvest.</div>`;
    if (!here && !mine) out += `<div class="tip">You are at ${esc(S.OBS.you.location)}. Go there to buy or sell in person.</div><div class="acts">${goButtons(c.place, id)}</div>`;
    const stock = (c.stock || []).filter(s => s.unlimited || s.qty > 0);
    out += `<h3>For sale</h3>`;
    const forSale = stock.filter(s => s.price != null);
    out += forSale.length ? forSale.map(s => {
      let btn = "";
      if (here && !mine){
        if (s.item === "Meal") btn = B(`Eat — ${money2(s.price)}`, "buy_meal", {business_id: id}, true);
        else if (VEHICLES.includes(s.item)) btn = B(`Buy — ${money2(s.price)}`, "buy_vehicle", {vehicle_type: s.item}, true);
        else btn = B(`Buy 1 — ${money2(s.price)}`, "buy_from_business", {business_id: id, item: s.item, qty: 1}, true)
                 + F("More", "buy_from_business", {business_id: id, item: s.item}, `Buy ${s.item}`);
      }
      return `<div class="row"><div class="grow"><b>${esc(s.item)}</b> <span class="dim">${s.unlimited ? "as many as you want" : `${s.qty} in stock`}</span></div><b>${money2(s.price)}</b>${btn}</div>`;
    }).join("") : `<div class="empty">Nothing is priced for sale here.</div>`;
    const held = stock.filter(s => s.price == null);
    if (held.length) out += `<div class="tip">Also holds: ${esc(held.map(s => `${s.qty} ${s.item}`).join(", "))}</div>`;
    if (!mine){
      out += `<h3>Trade</h3><div class="acts">`
        + (here ? F("Sell to them", "sell_to_business", {business_id: id}, `Sell to ${short(c.name)}`) : "")
        + ((S.OBS.you.businesses || []).length ? F("Order a delivery to my business", "order_from_business", {seller_business_id: id, my_business_id: S.OBS.you.businesses[0].id}, `Order from ${short(c.name)}`) : "")
        + `</div>`;
      if ((c.state_jobs || []).length) out += `<h3>Work here</h3>` + c.state_jobs.map(j => `<div class="row"><div class="grow"><b>${esc(j.role)}</b> <span class="dim">the state's fixed wage</span></div><b>${money2(j.wage)}/hr</b>`
        + (here ? B("Take the job", "apply_for_job", {business_id: id, role: j.role}, true) : "") + `</div>`).join("");
      const jobs = (S.BOARD.jobs || []).filter(j => j.business_id === id && !j.mine);
      if (jobs.length) out += `<h3>Hiring</h3>` + jobs.map(j => `<div class="row"><div class="grow"><b>${esc(j.role)}</b></div><b>${money2(j.wage)}/hr</b>`
        + (j.to_me ? B("Accept offer", "accept_job_offer", {posting_id: j.id}, true) : j.applied ? `<span class="dim">applied</span>` : B("Apply", "apply_to_job", {posting_id: j.id})) + `</div>`).join("");
    } else {
      const b = (S.OBS.you.businesses || []).find(x => x.id === id);
      if (b) out += `<h3>Manage</h3>` + manageCard(b, true);
    }
    if ((c.staff || []).length) out += `<h3>Staff</h3>` + c.staff.map(s => `<div class="row"><div class="grow">${esc(short(s.who))}${s.id === G.you ? " (you)" : ""} <span class="dim">${esc(s.role)}</span></div><span class="dim">${esc(s.doing || "")}</span></div>`).join("");
    return out;
  }

  /* ---------------------------------------------------------- the ledger */
  const sign = v => v == null ? "" : `${v > 0 ? "+" : ""}${money2(v)}`;
  function ledgerPanel(L){
    const pct = L.city.your_share_pct;
    let out = `<div class="card"><div class="t">Rank ${L.rank} of ${L.population} \u00b7 worth ${money(L.worth)}</div>
      <div class="m">${L.worth_per_hour ? `${sign(L.worth_per_hour)} an hour lately` : "No change yet"}${L.worth_change_24h != null ? ` \u00b7 ${sign(L.worth_change_24h)} over the last day` : ""}
      \u00b7 ${pct}% of ${esc(L.city.name)}'s total (${money(L.city.total)})</div></div>`;
    out += `<h3>Net worth over time</h3><canvas class="chart" id="ch-worth" width="1100" height="340"></canvas>
      <div class="legend"><span><i style="background:#e9d18c"></i>You</span><span><i style="background:#7ab6e8"></i>Average</span><span><i style="background:#8fcf6a"></i>Richest</span></div>
      <h3>Your rank over time</h3><canvas class="chart" id="ch-rank" width="1100" height="240" style="height:120px"></canvas>`;
    out += `<h3>You against everyone</h3><table class="kpi"><tr><th>Measure</th><th>You</th><th>Average</th><th>Best</th><th>Worst</th><th>Rank</th></tr>`
      + L.metrics.map(m => `<tr title="${esc(m.note)}"><td>${esc(m.name)}</td><td class="you">${money2(m.you)}</td><td>${money2(m.average)}</td><td>${money2(m.best)}</td><td>${money2(m.worst)}</td><td>${m.rank}</td></tr>`).join("")
      + `</table>`;
    out += `<h3>Your businesses, last 24 hours</h3>` + (L.businesses.length ? `<table class="kpi"><tr><th>Business</th><th>Takings</th><th>Supplies</th><th>Wages</th><th>Profit</th><th>/hour</th><th>Return</th></tr>`
      + L.businesses.map(b => `<tr><td><span class="hp ${b.health}"></span>${esc(b.type)} <span class="dim">${esc(b.location)}</span></td><td>${money2(b.revenue)}</td><td>${money2(b.supplies)}</td><td>${money2(b.wages)}</td>`
        + `<td class="${b.profit > 0 ? "good" : b.profit < 0 ? "warn" : ""}">${sign(b.profit) || 0}</td><td>${sign(b.profit_per_hour) || 0}</td><td>${b.return_pct}%</td></tr>`).join("") + `</table>
        <div class="tip">Return is the day's profit against what the business cost to found. Value now: ${L.businesses.map(b => `${esc(b.type)} ${money(b.value)}`).join(", ")}.</div>`
      : `<div class="empty">You own no business. Found one from the Business menu.</div>`);
    if (L.city.standings.length > 1) out += `<h3>The cities</h3>` + L.city.standings.map(c => `<div class="row"><div class="grow">${esc(c.name)}</div><b>${money(c.total)}</b></div>`).join("");
    return out;
  }
  function drawCharts(L){
    const line = (cv, sets, opts) => {
      if (!cv) return;
      const g = cv.getContext("2d"), W = cv.width, H = cv.height, P = 46;
      g.clearRect(0, 0, W, H);
      const pts = sets.flatMap(s => s.data);
      if (pts.length < 2){ g.fillStyle = "#7c8a93"; g.font = "26px sans-serif"; g.fillText("The chart fills in as the hours pass.", P, H / 2); return; }
      const x0 = Math.min(...pts.map(p => p[0])), x1 = Math.max(...pts.map(p => p[0])) || x0 + 1;
      let y0 = Math.min(...pts.map(p => p[1])), y1 = Math.max(...pts.map(p => p[1]));
      if (y1 - y0 < 1){ y0 -= 1; y1 += 1; }
      const X = x => P + (x - x0) / Math.max(1e-6, x1 - x0) * (W - P - 14);
      const Y = y => opts.invert ? 14 + (y - y0) / (y1 - y0) * (H - 46) : H - 32 - (y - y0) / (y1 - y0) * (H - 46);
      g.strokeStyle = "#ffffff18"; g.fillStyle = "#a9b4ba"; g.font = "22px sans-serif"; g.lineWidth = 1;
      for (let i = 0; i <= 3; i++){
        const v = y0 + (y1 - y0) * i / 3, y = Y(v);
        g.beginPath(); g.moveTo(P, y); g.lineTo(W - 10, y); g.stroke();
        g.fillText(opts.int ? Math.round(v) : (y1 - y0 < 20 ? v.toFixed(1) : money(v)), 2, y + 7);
      }
      g.fillText(`hour ${x0}`, P, H - 4); const lab = `hour ${x1}`; g.fillText(lab, W - 14 - g.measureText(lab).width, H - 4);
      for (const s of sets){
        if (s.data.length < 1) continue;
        g.strokeStyle = s.colour; g.lineWidth = s.width || 3; g.beginPath();
        s.data.forEach((p, i) => i ? g.lineTo(X(p[0]), Y(p[1])) : g.moveTo(X(p[0]), Y(p[1])));
        g.stroke();
      }
    };
    line($("ch-worth"), [
      {data: L.best_series, colour: "#8fcf6a", width: 2},
      {data: L.average_series, colour: "#7ab6e8", width: 2},
      {data: L.series.map(r => [r[0], r[1]]), colour: "#e9d18c", width: 4},
    ], {});
    line($("ch-rank"), [{data: L.series.map(r => [r[0], r[3]]), colour: "#e9d18c", width: 4}], {invert: true, int: true});
  }

  /* ---------------------------------------------------------- the guide */
  function guidePanel(C){
    let out = `<div class="tip">Every good is made from other goods, by a particular kind of business. Find the link your city is missing and build it.</div><h3>The three chains</h3>`;
    out += C.paths.map(p => `<div><b>${esc(p.name)}</b><div class="chainrow">${p.steps.map(st => `<span class="step">${esc(st)}</span>`).join('<span class="arr">\u2192</span>')}</div></div>`).join("");
    out += `<h3>Every business</h3>`;
    out += C.types.map(t => `<div class="card"><div class="t">${esc(t.type)} <span class="dim">${t.spur ? "spur road" : "main road"} \u00b7 costs ${money(t.cost)} \u00b7 ${t.in_your_city ? `${t.in_your_city} in your city` : '<span class="warn">none in your city</span>'}</span></div>`
      + t.makes.map(m => `<div class="row"><div class="grow"><b>${esc(m.item)}</b>${Object.keys(m.from).length ? ` <span class="dim">from ${esc(Object.entries(m.from).map(([i, q]) => `${q} ${i}`).join(" + "))}</span>` : ' <span class="dim">from the land</span>'}</div><span class="dim">sells ~${money2(m.price)}</span></div>`).join("")
      + `</div>`).join("");
    return out;
  }

  /* ---------------------------------------------------------- the day's report */
  function reportPanel(R){
    let out = `<div class="card"><div class="t">Worth ${money(R.worth)}${R.worth_change != null ? ` <span class="${R.worth_change >= 0 ? "good" : "warn"}">(${sign(R.worth_change)} today)</span>` : ""}</div>
      <div class="m">${R.rank ? `Rank ${R.rank}` : ""}${R.rank_change ? ` <span class="${R.rank_change > 0 ? "good" : "warn"}">(${R.rank_change > 0 ? "up" : "down"} ${Math.abs(R.rank_change)})</span>` : ""}</div></div>`;
    if (R.best) out += `<h3>Best business</h3><div class="tip">${esc(R.best.type)} at ${esc(R.best.location)}: profit ${sign(R.best.profit)}, takings ${money2(R.best.revenue)}.</div>`;
    if (R.worst) out += `<h3>Weakest</h3><div class="tip">${esc(R.worst.type)} at ${esc(R.worst.location)}: profit ${sign(R.worst.profit)}.</div>`;
    if (R.missed) out += `<h3>A missed opportunity</h3><div class="tip">${esc(R.missed.item)} traded ${money(R.missed.traded)} today at about ${money2(R.missed.price)} each, and nobody in your city makes it.</div>`;
    return out + `<div class="acts" style="margin-top:10px"><button class="btn go" data-tab="ledger">Open the ledger</button></div>`;
  }

  function landPanel(place){
    const row = S.BOARD.places.find(p => p.name === place) || {};
    const here = atPlace(place), spur = placeOf(place).kind === "spur";
    let out = `<div class="card"><div class="t">${esc(place)} <span class="dim">${esc(kindOf(place))}</span></div>
      <div class="m">${row.plots_free ?? "?"} of ${row.plots_total ?? "?"} plots unsold, ${money(S.BOARD.land_price)} each.</div>
      <div class="m">${spur ? "Spur land: farms and mines are founded here, four plots included in the price." : "Main-road land: shops, taverns and workshops stand here."}</div></div>`;
    if (!here) return out + `<div class="tip">Go there to buy land or build.</div><div class="acts">${goButtons(place)}</div>`;
    out += `<h3>Buy</h3><div class="acts">${B("Buy 1 plot", "buy_land", {plots: 1}, true)}${F("Buy several", "buy_land", {}, `Buy land at ${place}`)}</div>`;
    out += `<h3>Build</h3><div class="tip">Founding a business takes four plots here and puts a building on them.</div>`
      + S.BOARD.business_types.filter(t => t.spur === spur).map(t => `<div class="row"><div class="grow"><b>${esc(t.name)}</b> <span class="dim">makes ${esc(t.makes.slice(0, 3).join(", "))}</span></div><b>${money(t.cost)}</b>${F("Found", "start_business", {type: t.name}, `Found a ${t.name}`)}</div>`).join("");
    const listed = S.BOARD.listed_land.filter(l => l.at === place && !l.mine);
    if (listed.length) out += `<h3>Offered by others</h3>` + listed.map(l => `<div class="row"><div class="grow">Plot ${esc(l.id)} <span class="dim">${esc(short(l.owner))}</span></div><b>${money2(l.price)}</b>${B("Buy", "buy_listed_land", {plot_id: l.id})}</div>`).join("");
    return out;
  }

  /* YOUR BUSINESS, AT A GLANCE (2026-10-17). The key numbers in view rather
     than behind buttons: what it is doing and how fast, how full it is, what
     each output would earn, what one more worker would add and what to offer
     one, its stock with prices you can set in place. */
  const num = (v, d = 1) => (+v || 0).toLocaleString(undefined, {maximumFractionDigits: d});
  function ownPanel(B){
    const making = B.outputs.find(o => o.making);
    const statusText = {idle: "Idle \u2014 choose what to make", stalled: `Stalled${B.stall_reason ? ": " + B.stall_reason.split(/[.;(]/)[0] : ""}`,
      working: `Making ${B.producing}`, unstaffed: `Making ${B.producing} \u2014 nobody on shift`}[B.status];
    const pct = B.storage.cap ? Math.min(100, 100 * B.storage.used / B.storage.cap) : 0;
    let out = `<div class="kpis">
      <div class="kpi-t wide ${B.status}"><span>Status</span><b>${esc(statusText)}</b></div>
      <div class="kpi-t"><span>Rate</span><b>${B.rate_now ? num(B.rate_now) + "/h" : "\u2014"}</b></div>
      <div class="kpi-t"><span>Storage</span><b>${B.storage.used}/${B.storage.cap}</b><i class="meter"><i style="width:${pct}%" class="${pct > 90 ? "full" : ""}"></i></i></div>
      <div class="kpi-t" title="Money you deposited for others to run it. Sales go to your own coins."><span>Purse</span><b>${money2(B.cash)}</b></div>
      <div class="kpi-t"><span>Staff</span><b>${B.staff.length}/${B.places}</b></div>
      <div class="kpi-t"><span>Profit 24h</span><b class="${B.books.profit > 0 ? "good" : B.books.profit < 0 ? "warn" : ""}">${B.books.profit > 0 ? "+" : ""}${money2(B.books.profit)}</b></div>
    </div>`;
    // WHAT IT IS MAKING, IN PLAIN TERMS (2026-10-18): how often a unit lands
    // at the game's current speed, and how many are in the yard now.
    const pace = S.ST && S.ST.pace ? S.ST.pace : 12;
    if (making && B.rate_now > 0){
      const realSecs = 3600 / B.rate_now / pace;
      const inYard = ((B.stock || []).find(x => x.item === making.item) || {}).qty || 0;
      out += `<div class="note prodline">One <b>${esc(making.item)}</b> every <b>${realSecs < 60 ? realSecs.toFixed(1) + " s" : (realSecs / 60).toFixed(1) + " min"}</b> at this speed (${num(B.rate_now)} a game hour). In the yard now: <b>${inYard}</b>${S.ST && S.ST.paused ? " \u2014 <span class=\"warn\">the game is paused</span>" : ""}.</div>`;
    } else if (making){
      out += `<div class="note">Nothing is being made: put someone on shift here (you or your family).</div>`;
    }
    // MONEY: wages come from this business's purse, then your own coins.
    const pocket = S.ST ? S.ST.you.denari : 0;
    const need = Math.max(B.owed || 0, B.payroll_per_hour * 4 - B.cash - pocket, B.payroll_per_hour, 0);
    if (B.insolvent || (B.payroll_per_hour > 0 && B.cash + pocket < B.payroll_per_hour)){
      out += `<div class="alarm"><b>${B.insolvent ? "Can't pay wages: unpaid workers have left" : "Can't pay the next hour of wages"}</b>`
        + `<span>Wages come from this business's purse (${money2(B.cash)}), then your coins (${money2(pocket)}). Payroll is ${money2(B.payroll_per_hour)}/h.`
        + `${B.closes_in_hours != null ? ` <b>It closes in ${num(B.closes_in_hours)}h</b> unless you deposit at least ${money2(Math.max(B.owed, 1))}.` : ""}</span>`
        + `<div class="acts">${B_(`Deposit ${money(need || 20)}`, "deposit", {business_id: B.id, amount: Math.ceil(need || 20)}, true)}</div></div>`;
    } else if (B.payroll_per_hour > 0){
      out += `<div class="note">Your purse and coins cover <b>${num((B.cash + pocket) / B.payroll_per_hour, 1)}h</b> of wages (${money2(B.payroll_per_hour)}/h). Sales go straight to your coins.</div>`;
    }
    if (B.land && B.land.item) out += `<div class="note rich-card">Rich ground: <b>${esc(B.land.item)}</b> +${Math.round(B.land.pct * 100)}%</div>`;
    else if (B.land) out += `<div class="note">Ordinary ground.</div>`;
    else if (B.land_pending) out += `<div class="note">Ground quality shows with the first harvest.</div>`;
    // THE GROUND WEARS, THE AIR FOULS (2026-10-18). See convoy/ground.py.
    if (B.ground){
      const g = B.ground, word = g.kind === "seam" ? "Seam" : "Soil", left = Math.round(g.left * 100);
      const slow = Math.round((1 - g.pace) * 100);
      out += `<div class="wear"><div class="row"><div class="grow"><b>${word}</b> ${g.spent ? `<span class="c-bad">worked out</span>` : `${left}% left`}${slow > 0 && !g.spent ? ` <span class="c-bad">\u00b7 ${slow}% slower</span>` : ""}</div></div>`
        + `<div class="bar wearbar"><i style="width:${left}%"></i></div>`
        + `<div class="dim">${g.kind === "seam" ? "Ore runs out as it is dug and never comes back. Timbered shafts make it last; a Deeper shaft reaches fresh ore." : "Soil tires as it is farmed and recovers while the field rests. Crop rotation and manure pits keep it in heart."}</div></div>`;
    }
    if (B.air && (B.air.foul >= 0.03 || B.air.smoke >= 1)){
      const foul = Math.round(B.air.foul * 100), slow = Math.round((1 - B.air.pace) * 100);
      out += `<div class="wear"><div class="row"><div class="grow"><b>Air</b> ${foul}% foul${slow > 0 ? ` <span class="c-bad">\u00b7 work ${slow}% slower</span>` : ""}</div><span class="dim">your smoke ${B.air.smoke.toFixed(1)}</span></div>`
        + `<div class="bar airbar"><i style="width:${foul}%"></i></div>`
        + `<div class="dim">Refineries foul the air most, and anything run fast smokes more. It slows crops most, then miners and refinery hands, within about 600 m. A Tall chimney carries smoke off; Hedgerows shelter a farm.</div></div>`;
    }
    // What to make.
    out += `<h3>What to make</h3><table class="grid"><tr><th>Good</th><th>Rate</th><th>Price</th><th>Worth /h</th><th></th></tr>`
      + B.outputs.map(o => `<tr class="${o.making ? "on" : ""}"><td><b>${esc(o.item)}</b>${o.land_bonus ? ` <span class="rich">+${Math.round(o.land_bonus * 100)}%</span>` : ""}`
        + `${Object.keys(o.inputs).length ? `<small>needs ${esc(Object.entries(o.inputs).map(([i, q]) => `${q} ${i}`).join(" + "))}</small>` : ""}</td>`
        + `<td>${num(o.rate)}/h</td><td>${money2(o.price)}</td><td class="${o.value_per_hour > 0 ? "good" : "warn"}">${num(o.value_per_hour, 0)}</td>`
        + `<td>${o.making ? '<span class="good">making</span>' : B_("Make", "set_production", {business_id: B.id, output: o.item})}</td></tr>`).join("")
      + `</table><div class="tip">Rates are for ${Math.max(1, B.staff.length)} worker${B.staff.length > 1 ? "s" : ""} on shift; worth is price less inputs.</div>`;
    // Workers.
    const ref = making || B.outputs.reduce((a, o) => (o.value_per_hour > a.value_per_hour ? o : a), B.outputs[0]);
    out += `<h3>Workers</h3>`;
    out += B.staff.length ? B.staff.map(st => `<div class="row"><span class="dot ${st.on_shift ? "on" : ""}"></span><div class="grow">${st.id === G.you ? "<b>You</b>" : esc(short(st.name))} <span class="dim">${esc(st.role)}</span></div>`
      + `<span class="dim">${st.id === G.you ? "owner" : st.family ? "family, unpaid" : money2(st.wage) + "/h"}</span><span class="dim">${st.on_shift ? "on shift" : "off"}</span></div>`).join("")
      : `<div class="empty">Nobody works here yet.</div>`;
    // Your family, from right here: the cheapest workers you have.
    const fam = B.family || [];
    if (fam.length){
      const roleWord = m => m.role === "partner" ? "your partner" : m.role === "in-law" ? "married in" : `your ${m.role}`;
      out += `<div class="famwork">` + fam.map(m => `<div class="row"><span class="avatar">${m.sex === "f" ? "\u{1F469}" : "\u{1F468}"}</span><div class="grow"><b>${esc(m.name)}</b> <span class="dim">${esc(roleWord(m))} \u00b7 ${m.works_here ? "works here" : m.works_at ? "works at another of yours" : "at home"}</span></div>`
        + (m.works_here ? B_("Send home", "assign_family", {member_id: m.id, business_id: ""})
           : B.places_free > 0 ? B_("Put to work here", "assign_family", {member_id: m.id, business_id: B.id}, true)
           : `<span class="dim">no room</span>`) + `</div>`).join("") + `</div>`;
    }
    const meOn = B.staff.some(st => st.id === G.you && st.on_shift);
    out += `<div class="acts">` + (meOn ? `<span class="good">You are on shift here.</span>` + B_("Stop work", "end_shift")
      : `<button class="btn go" id="work-me">${B.you_work_here ? "Start a 4h shift" : "Work here myself (4h)"}</button>`) + `</div>`;
    if (ref){
      const r0 = B.roles[0] || {role: "", suggested: 0, floor: 0};
      out += `<div class="hire">
        <div class="gain">+${num(ref.extra_worker_rate)}/h ${esc(ref.item)} <span>\u2248 +${num(ref.extra_worker_value, 0)}/h of goods for ${B.staff.length ? "one more worker" : "a first worker"}</span></div>`;
      if (B.places_free <= 0) out += `<div class="tip warn">No room for another worker: every place is taken. Buy and build on a plot to add one.</div>`;
      else {
        const shift = r0.suggested * 4;
        if (B.cash + pocket < shift) out += `<div class="tip warn">A worker at ${money2(r0.suggested)}/h costs ${money(shift)} for a 4h shift, paid from this business's purse (${money2(B.cash)}) and then your coins (${money2(pocket)}) -- not enough: they would leave unpaid.</div>`;
        else out += `<div class="tip">A worker at ${money2(r0.suggested)}/h costs ${money(shift)} for a 4h shift, paid from the purse and then your coins. Or use family: free.</div>`;
        out += `<div class="hire-row">
          <select id="h-role">${B.roles.map(r => `<option value="${esc(r.role)}" data-s="${r.suggested}">${esc(r.role)}</option>`).join("")}</select>
          <input id="h-wage" type="number" min="${r0.floor}" step="0.5" value="${r0.suggested.toFixed(2)}"><span class="unit">/h</span>
          <button class="btn go" id="h-post">Advertise</button>
          <select id="h-who"><option value="">offer to\u2026</option>${(S.BOARD ? S.BOARD.agents : []).map(a => `<option value="${esc(a.id)}">${esc(short(a.name))}</option>`).join("")}</select>
          <button class="btn" id="h-offer">Offer</button>
        </div>
        <div class="tip" id="h-why">${wageWhy(r0)}</div>`;
      }
      out += `</div>`;
    }
    // PROJECTS (2026-10-18): one at a time, sooner with a crew and material.
    out += `<h3>Build</h3>`;
    if (B.project){
      const P = B.project;
      out += `<div class="proj"><div><b>${esc(P.kind)}</b> \u2014 ready in <b>${dur(P.eta)}</b></div><div class="bar"><i style="width:${Math.round(P.pct * 100)}%"></i></div>`
        + `<div class="tip">${num(P.rate, 1)} work an hour from the crew on shift${P.material_have ? `, plus ${esc(P.material)} from the yard (${P.material_have} left)` : ` \u2014 put ${esc(P.material)} in the yard to speed it up`}. One more on shift: ${dur(P.with_one_more)}.</div></div>`;
    } else {
      out += B.projects.map(p => `<div class="row"><div class="grow"><b>${esc(p.kind)}</b>${p.level ? ` <span class="dim">level ${p.level}</span>` : ""}<br><span class="dim">${esc(p.does)} About ${num(p.work, 0)} work; ${esc(p.material)} speeds it.</span></div>`
        + (p.level >= p.max ? `<span class="dim">done</span>` : B_(`Build \u00b7 ${money(p.cost)}`, "start_project", {business_id: B.id, project: p.kind}, true)) + `</div>`).join("");
    }
    for (const pst of B.postings){
      out += `<div class="row"><div class="grow">Advert: <b>${esc(pst.role)}</b> at ${money2(pst.wage)}/h <span class="dim">${pst.applicants.length ? pst.applicants.length + " applied" : "no applicants yet"}</span></div>`
        + pst.applicants.map(a => B_(`Hire ${short(a.name)}`, "hire_applicant", {posting_id: pst.id, applicant_id: a.id}, true)).join("")
        + B_("Take down", "close_job", {posting_id: pst.id}) + `</div>`;
    }
    // Stock and prices.
    out += `<h3>Stock & prices</h3>` + (B.stock.length ? `<table class="grid"><tr><th>Good</th><th>Have</th><th>Worth</th><th>Your price</th><th></th></tr>`
      + B.stock.map(st => `<tr><td><b>${esc(st.item)}</b></td><td>${st.qty}</td><td>${money2(st.value)}</td>`
        + `<td><input class="price" data-item="${esc(st.item)}" type="number" min="0" step="0.1" placeholder="${money2(st.market)}" value="${st.retail != null ? st.retail : ""}"></td>`
        + `<td><button class="btn" data-setprice="${esc(st.item)}">Set</button> ${B_("Take out", "collect_business_inventory", {business_id: B.id, item: st.item, qty: st.qty})}</td></tr>`).join("") + `</table>`
      : `<div class="empty">Nothing in stock.</div>`);
    // Money and supplies.
    out += `<h3>Money</h3><div class="hire-row"><input id="m-amt" type="number" min="0" step="1" placeholder="amount">`
      + `<button class="btn" id="m-dep">Deposit</button><button class="btn" id="m-wd">Withdraw</button>`
      + F("Order supplies", "order_from_business", {my_business_id: B.id}, "Order supplies") + F("Hire a courier", "post_delivery_job", {business_id: B.id}, "Hire a courier") + `</div>`;
    return out;
  }
  const B_ = (label, action, args, go) => B(label, action, args, go);
  function wageWhy(r){
    const bits = [`floor ${money2(r.floor)}`];
    if (r.typical != null) bits.push(`recently hired at ${money2(r.typical)}`);
    if (r.best_advert != null) bits.push(`best rival advert ${money2(r.best_advert)}`);
    return `Suggested pitch ${money2(r.suggested)}/h \u2014 ${bits.join(" \u00b7 ")}.`;
  }
  function wireOwn(B){
    const work = $("work-me");
    // The server starts the shift too (Game.act); one call either way.
    if (work) work.onclick = () => act("apply_for_job", {business_id: B.id});
    const canPay = w => B.cash >= w * 1 || confirm(`This business holds ${B.cash.toFixed(0)}, less than one hour at ${w}/h. A worker who is not paid leaves. Hire anyway? (Deposit first to keep them.)`);
    const role = $("h-role"), wage = $("h-wage");
    if (role){
      role.onchange = () => {
        const r = B.roles.find(x => x.role === role.value);
        if (r){ wage.value = r.suggested.toFixed(2); $("h-why").textContent = wageWhy(r); }
      };
      $("h-post").onclick = () => { if (canPay(+wage.value)) act("post_job", {business_id: B.id, role: role.value, wage: +wage.value}); };
      $("h-offer").onclick = () => {
        const who = $("h-who").value;
        if (!who){ toast("Choose who to offer the job to.", "bad"); return; }
        if (!canPay(+wage.value)) return;
        act("offer_job", {business_id: B.id, agent_id: who, wage: +wage.value, role: role.value});
      };
    }
    $("pbody").querySelectorAll("[data-setprice]").forEach(b => b.onclick = () => {
      const inp = $("pbody").querySelector(`input.price[data-item="${CSS.escape(b.dataset.setprice)}"]`);
      if (!inp || inp.value === ""){ toast("Type a price first.", "bad"); return; }
      act("set_retail_price", {business_id: B.id, item: b.dataset.setprice, price: +inp.value});
    });
    const amt = () => +($("m-amt").value || 0);
    $("m-dep").onclick = () => amt() > 0 ? act("deposit", {business_id: B.id, amount: amt()}) : toast("Type an amount.", "bad");
    $("m-wd").onclick = () => amt() > 0 ? act("withdraw", {business_id: B.id, amount: amt()}) : toast("Type an amount.", "bad");
  }

  /* THE MARKET (2026-10-17): what is for sale and where, your goods with a
     price box each, and what everything is fetching. A good is for sale when a
     business holds it at a price; finished goods are bought over the counter
     in person, feedstock is ordered and delivered to a business that uses it. */
  let mkTab = "buy", mkItem = "", mkCity = "";
  const mkDraft = {};                           // prices you typed but have not posted, by business|item
  function marketPanel(M){
    const hauls = (S.BOARD.hauls || []).filter(h => h.mine_to_receive || h.mine_to_carry);
    const seg = ["buy", "sell", "deliveries", "prices"].map(t => `<button class="seg-b${mkTab === t ? " on" : ""}" data-mk="${t}">${{buy: "Buy", sell: "Sell", deliveries: `Deliveries${hauls.length ? ` (${hauls.length})` : ""}`, prices: "Prices"}[t]}</button>`).join("");
    let out = `<div class="seg">${seg}</div>`;
    const suggest = g => g.avg != null ? g.avg : g.cheapest != null ? Math.max(g.floor, g.cheapest - 0.1) : g.book;
    if (mkTab === "buy"){
      out += `<div class="howto"><b>How buying works.</b> Find the good below and press its button. <b>Feedstock</b> (Wheat, ore, hides&hellip;) is paid for now and waits at the seller's: you walk over, it loads, and you carry it to your business &mdash; or pay a courier. <b>Shop goods</b> (Meals, tools, weapons) are bought at the counter: the button walks you there and buys on arrival.</div>`;
      out += bidForm(M);
      const items = [...new Set(M.listings.map(l => l.item))].sort();
      out += `<div class="hire-row"><select id="mk-item"><option value="">Every good</option>${items.map(i => `<option${i === mkItem ? " selected" : ""}>${esc(i)}</option>`).join("")}</select>`
        + `<select id="mk-city"><option value="">Every city</option><option value="${esc(M.city)}"${mkCity ? " selected" : ""}>My city only</option></select></div>`;
      // Your own listings show too, marked, so you can see what you have up.
      const rows = M.listings.filter(l => (!mkItem || l.item === mkItem) && (!mkCity || l.city === mkCity));
      const room = S.BOARD.carry_room || 5;
      const groups = {};
      rows.forEach(l => (groups[l.item] = groups[l.item] || []).push(l));
      out += `<h3>For sale now</h3>` + (rows.length ? Object.keys(groups).sort().map(item => {
        const ls = groups[item].sort((x, y) => x.price - y.price);
        return `<div class="mk-good"><div class="mk-h"><b>${esc(item)}</b><span>${ls.length} seller${ls.length > 1 ? "s" : ""} \u00b7 from ${money2(ls[0].price)} each \u00b7 ${ls[0].kind === "order" ? "feedstock" : "shop good"}</span></div>`
          + ls.map(l => {
            const k = M.listings.indexOf(l);
            const who = `<div class="mk-who">${l.state ? "As many as you want" : `<b>${l.qty}</b>`} at <b>${money2(l.price)}</b> \u2014 ${l.state ? "the state's" : l.mine ? "your" : esc(short(l.seller)) + "'s"} ${esc(l.type.split(" /")[0])}, ${esc(l.place)}${l.city !== M.city ? ` <span class="dim">(${esc(l.city.charAt(0).toUpperCase() + l.city.slice(1))})</span>` : ""}`
              + (l.kind === "counter" && !l.open ? ` <span class="warn">nobody serving right now</span>` : "") + `</div>`;
            let actn;
            if (l.mine){
              actn = `<span class="good">your listing</span>`;
            } else if (l.kind === "order" && !l.receivers.length){
              actn = `<span class="dim">Only a business that uses ${esc(item)} can buy it, and none of yours does.</span>`;
            } else {
              const q = l.kind === "order" ? Math.max(1, Math.min(l.qty, room)) : 1;
              const label = l.kind === "order" ? "Buy &amp; fetch" : (l.here && l.open ? "Buy" : "Walk there &amp; buy");
              actn = `<input class="price qty" id="mkq-${k}" data-price="${l.price}" data-k="${k}" type="number" min="1" max="${l.qty}" step="1" value="${q}">`
                + `<button class="btn go" data-buy="${k}">${label} \u00b7 <span id="mkt-${k}">${money2(q * l.price)}</span></button>`
                + (l.kind === "order" ? F("or pay a courier", "order_from_business", {my_business_id: l.receivers[0].id, seller_business_id: l.business, item: l.item}, `Order ${l.item}, delivered by a courier`) : "");
            }
            return `<div class="mk-row">${who}<div class="mk-act">${actn}</div></div>`;
          }).join("") + `</div>`;
      }).join("") : `<div class="empty">Nothing is for sale${mkItem ? ` in ${esc(mkItem)}` : ""} right now. Post a buy order above and sellers will see it.</div>`);
    } else if (mkTab === "deliveries"){
      out += `<div class="tip">Goods you ordered, and loads you are carrying. Walk into the seller's place and it loads; walk into yours and it is handed over. On foot you carry ${S.ST && S.ST.vehicle ? "what your vehicle holds" : "5"}; a bigger order takes more trips.</div>`;
      const busy = hauls.some(h => h.mine_to_carry);      // one load at a time
      out += hauls.length ? `<table class="grid"><tr><th>Load</th><th>From</th><th>To</th><th></th></tr>` + hauls.map(h => {
        let what, btn = "";
        if (h.carrying){ what = `<span class="good">on your back</span>`; btn = `<button class="btn go" data-walk="${esc(h.to)}">Walk to ${esc(h.to)}</button>`; }
        else if (h.mine_to_carry){ what = "yours to pick up"; btn = `<button class="btn go" data-walk="${esc(h.from)}">Walk to ${esc(h.from)}</button>`; }
        else if (h.status === "claimed"){ what = "a courier is on it"; }
        else { what = h.fee > 0 ? `courier wanted (${money2(h.fee)})` : "waiting for you";
               btn = busy ? `<span class="dim">next trip</span>` : `<button class="btn go" data-fetchc="${esc(h.id)}">Fetch it myself</button>`; }
        return `<tr><td><b>${h.qty} ${esc(h.item)}</b><small>${what}</small></td><td>${esc(h.from)}<small>${esc(short(h.seller))}</small></td>`
          + `<td>${esc(h.to)}<small>${h.mine_to_receive ? `your ${esc(h.to_business)}` : esc(h.to_business)}</small></td><td>${btn}</td></tr>`;
      }).join("") + `</table>` : `<div class="empty">Nothing on the road. Feedstock you buy in the Buy list shows up here until it arrives.</div>`;
    } else if (mkTab === "sell"){
      out += `<div class="howto"><b>How selling works.</b> Two ways. <b>Sell to a buyer now:</b> someone posted the price they will pay &mdash; press Sell and you are paid at once. <b>Put it on sale:</b> set your own price on what your businesses hold, and anyone can buy it from you.</div>`;
      // YOUR DELIVERY UNDER WAY, with what to do next.
      const cur = S.ST && S.ST.delivery;
      if (cur){
        out += `<div class="proj"><b>Your delivery:</b> ${cur.qty} ${esc(cur.item)} \u2014 ${cur.loaded
          ? `loaded. Follow the compass to the yellow circle; the buyer lights up when you are close.`
          : `<span class="warn">not loaded yet.</span> Go to your business; it loads the moment you are there with the goods.`}`
          + `<div class="acts">${cur.loaded ? "" : `<button class="btn go" data-dl="load">Load now</button>`}<button class="btn" data-dl="drop">Drop it</button></div></div>`;
      }
      // DELIVER IT YOURSELF (2026-10-18): buyers who pay more at their door.
      const dl = (M.deliveries || []).filter(o => o.have > 0);
      out += `<h3>Deliver it yourself \u2014 pays more</h3>` + (dl.length ? dl.map(o => {
        const n = Math.min(o.have, o.qty, M.delivery_room);
        const btn = n > 0 ? `<button class="btn go" data-deliver='${esc(JSON.stringify({business_id: o.from, buyer_business_id: o.buyer, item: o.item, qty: n}))}'>Take the job \u00b7 ${money2(n * o.unit)}</button>` : `<span class="dim">your donkey is full</span>`;
        return `<div class="mk-row"><div class="mk-who"><b>${n} ${esc(o.item)}</b> to a ${esc(o.type.split(" /")[0])} in <b>${esc(o.city_name)}</b> \u2014 <b>${money2(o.unit)}</b> each`
          + `<small>${o.state ? "the state's" : "a citizen's"} \u00b7 the gate pays ${money2(o.gate)} \u00b7 you find the exact place when you get close</small></div><div class="mk-act">${btn}</div></div>`;
      }).join("") : `<div class="empty">Nothing to deliver yet: make some goods first.</div>`);
      // WHO WOULD BUY (2026-10-18): businesses in every town bidding for what
      // you hold or make, best price first. Raw goods go to refineries.
      const goodsHeld = {};
      M.goods.forEach(g => { if (!goodsHeld[g.item] || g.qty > goodsHeld[g.item].qty) goodsHeld[g.item] = g; });
      const bidItems = Object.keys(M.bids || {});
      out += `<h3>Who would buy</h3>` + (bidItems.length ? bidItems.map(item => {
        const g = goodsHeld[item];
        return `<div class="mk-good"><div class="mk-h"><b>${esc(item)}</b><span>${g ? `you have ${g.qty} at your ${esc(g.type.split(" /")[0])}` : "you have none yet"}</span></div>`
          + M.bids[item].map(b => {
            const n = g ? Math.min(g.qty, b.qty) : 0;
            const convoy = b.state && S.ST && S.ST.you.outposts;
            const btn = n > 0 ? `<button class="btn go" data-act="sell_to_bidder" data-args='${esc(JSON.stringify({business_id: g.business, buyer_business_id: b.business, item, qty: n}))}'>${convoy ? `State's convoy: ${n} for ${money2(n * b.price)}` : `Sell ${n} \u00b7 ${money2(n * b.price)}`}</button>` : `<span class="dim">make some first</span>`;
            return `<div class="mk-row"><div class="mk-who"><b>${money2(b.price)}</b> each \u2014 ${b.state ? "the state's" : esc(short(b.owner)) + "'s"} ${esc(b.type.split(" /")[0])}, ${esc(b.place)} <span class="dim">(${esc(b.city)})</span>`
              + `<small>${convoy ? "half what it sold for between people today; its convoy comes to your yard, free, and pays when it collects" : b.state ? "fixed low price; its cart collects at once" : `wants ${b.qty}; pays now, sends a courier to fetch it`}</small></div><div class="mk-act">${btn}</div></div>`;
          }).join("") + `</div>`;
      }).join("") : `<div class="empty">Found a farm or a mine and the refineries bidding for its goods appear here, best price first.</div>`);
      out += `<h3>Buyers waiting</h3>` + (M.wanted.length ? M.wanted.map(o => {
        const f = o.fill_from[0], n = f ? Math.min(f.have, o.qty) : 0;
        const btn = f ? `<button class="btn go" data-act="fill_buy_order" data-args='${esc(JSON.stringify({order_id: o.id, business_id: f.id}))}'>Sell ${n} \u00b7 ${money2(n * o.price)}</button>`
                      : `<span class="dim">you hold no ${esc(o.item)}</span>`;
        return `<div class="mk-row"><div class="mk-who"><b>${esc(short(o.buyer))}</b> wants <b>${o.qty} ${esc(o.item)}</b> at <b>${money2(o.price)}</b> each \u2014 their ${esc(o.type.split(" /")[0])}, ${esc(o.place)}. <span class="dim">${o.fee > 0 ? `They pay ${money2(o.fee)} to have it carried.` : "They fetch it from you."}</span></div><div class="mk-act">${btn}</div></div>`;
      }).join("") : `<div class="empty">Nobody has posted a buy order yet.</div>`);
      out += `<h3>What you have to sell</h3>` + (M.goods.length ? M.goods.map((g, i) => {
        const key = g.business + "|" + g.item, val = mkDraft[key] != null ? mkDraft[key] : g.price != null ? g.price : suggest(g).toFixed(2);
        return `<div class="mk-row"><div class="mk-who"><b>${g.qty} ${esc(g.item)}</b> at your ${esc(g.type.split(" /")[0])}, ${esc(g.place)}`
          + (g.price != null ? ` \u2014 <span class="good">on sale at ${money2(g.price)}</span>` : ` \u2014 <span class="dim">not on sale</span>`)
          + `<small>${g.avg != null ? `sells for ~${money2(g.avg)}` : "no sales yet"}${g.cheapest != null ? ` \u00b7 cheapest rival ${money2(g.cheapest)}` : ""} \u00b7 lowest allowed ${money2(g.floor)}</small></div>`
          + `<div class="mk-act">Price each <input class="price" id="mkp-${i}" type="number" min="${g.floor}" step="0.1" data-key="${esc(key)}" value="${val}">`
          + `<button class="btn ${g.price != null ? "" : "go"}" data-list="${i}">${g.price != null ? "Change price" : "Put on sale"}</button></div></div>`;
      }).join("") : `<div class="empty">Your businesses hold nothing yet. What they make turns up here.</div>`);
      if (M.carried.length){
        out += `<h3>What you carry</h3>` + M.carried.map((g, i) =>
          `<div class="mk-row"><div class="mk-who"><b>${g.qty} ${esc(g.item)}</b> on you<small>${g.avg != null ? `sells for ~${money2(g.avg)}` : `worth about ${money2(g.book)}`}</small></div><div class="mk-act">`
          + (g.list_at.length ? `Price each <input class="price" id="mkc-${i}" type="number" min="${g.floor}" step="0.1" data-key="${esc("carry|" + g.item)}" value="${mkDraft["carry|" + g.item] != null ? mkDraft["carry|" + g.item] : suggest(g).toFixed(2)}"><button class="btn go" data-carry="${i}">Put on sale at my ${esc(g.list_at[0].type.split(" /")[0])}</button>`
             : `<span class="dim">Walk to one of your businesses to put it on sale there.</span>`)
          + `</div></div>`).join("");
      }
    } else {
      out += M.prices.length ? `<table class="grid"><tr><th>Good</th><th>Sold today</th><th>Avg price</th><th>Cheapest rival</th><th>Book</th></tr>` + M.prices.map(g =>
        `<tr><td><b>${esc(g.item)}</b></td><td>${g.sold}</td><td>${g.avg != null ? money2(g.avg) : "\u2014"}</td><td>${g.cheapest != null ? money2(g.cheapest) : "\u2014"}</td><td class="dim">${money2(g.book)}</td></tr>`).join("") + `</table>`
        : `<div class="empty">Nothing has traded yet.</div>`;
    }
    return out;
  }
  let bidOpen = false;
  function bidForm(M){
    let out = "";
    if (M.my_orders.length){
      out += `<h3>Your buy orders</h3><table class="grid"><tr><th>Wanted</th><th>Price</th><th>Filled</th><th></th></tr>` + M.my_orders.map(o =>
        `<tr><td><b>${esc(o.item)}</b><small>for your ${esc(o.type.split(" /")[0])}</small></td><td>${money2(o.price)}</td>`
        + `<td>${o.posted - o.qty} of ${o.posted}${o.status === "open" ? "" : ` <span class="dim">\u00b7 ${esc(o.status)}</span>`}</td>`
        + `<td>${o.status === "open" ? B("Cancel", "cancel_buy_order", {order_id: o.id}) : ""}</td></tr>`).join("") + `</table>`;
    }
    if (!M.can_ask.length){
      return out + (M.my_orders.length ? "" : `<div class="tip">Own a business that uses feedstock (a refinery, a tavern, a smithy) and you can post what you will pay for it here, for anyone to fill.</div>`);
    }
    if (!bidOpen) return out + `<div class="mk-row bidcta"><div class="mk-who"><b>Not listed, or too dear?</b> Say what you will pay and how many, and sellers come to you.</div><div class="mk-act"><button class="btn go" id="bid-open">Post a buy order</button></div></div>`;
    const opts = M.can_ask.flatMap(b => b.items.map(i => `<option value="${esc(b.id + "|" + i.item)}">${esc(i.item)} \u2014 for your ${esc(b.type.split(" /")[0])}</option>`)).join("");
    return out + `<div class="bidform"><h3>Post a buy order</h3>
      <div class="hire-row"><select id="bid-what">${opts}</select></div>
      <div class="hire-row"><label>How many <input class="price" id="bid-qty" type="number" min="1" max="500" step="1" value="10"></label>
        <label>Price each <input class="price" id="bid-price" type="number" min="0.1" step="0.1"></label>
        <label>Courier fee <input class="price" id="bid-fee" type="number" min="0" step="0.5" value="0"></label></div>
      <div class="tip" id="bid-note"></div>
      <div class="acts"><button class="btn go" id="bid-post">Post it</button><button class="btn" id="bid-cancel">Never mind</button></div></div>`;
  }
  function wireBid(M){
    const op = $("bid-open"); if (op) op.onclick = () => { bidOpen = true; renderView(true); };
    const what = $("bid-what"); if (!what) return;
    const find = () => { const [bid, item] = what.value.split("|"); const b = M.can_ask.find(x => x.id === bid); return {b, i: b.items.find(x => x.item === item)}; };
    const fill = () => {
      const {i} = find(), pr = $("bid-price");
      pr.value = (i.cheapest != null ? i.cheapest : i.avg != null ? i.avg : i.book).toFixed(2);
      note();
    };
    const note = () => {
      const {i} = find(), q = +$("bid-qty").value || 0, pr = +$("bid-price").value || 0, fee = +$("bid-fee").value || 0;
      const total = q * pr + fee;
      $("bid-note").innerHTML = `Holds <b>${money2(total)}</b> until it is filled or you cancel: your business's cash first, then your pocket (${money2(M.cash)}). `
        + (i.cheapest != null ? `Cheapest on sale now: ${money2(i.cheapest)}. ` : "Nobody is selling it right now. ")
        + (fee > 0 ? "A courier is paid to bring it." : "Fee 0: it waits at the seller's for you to fetch.");
    };
    what.onchange = fill; ["bid-qty", "bid-price", "bid-fee"].forEach(id => $(id).addEventListener("input", note));
    fill();
    $("bid-cancel").onclick = () => { bidOpen = false; renderView(true); };
    $("bid-post").onclick = async () => {
      const {b, i} = find(), qty = Math.floor(+$("bid-qty").value), price = +$("bid-price").value, fee = +$("bid-fee").value || 0;
      if (!(qty > 0 && price > 0)){ toast("Say how many and the price.", "bad"); return; }
      const r = await act("post_buy_order", {business_id: b.id, item: i.item, qty, price, courier_fee: fee});
      if (r.ok) bidOpen = false;
      renderView(true);
    };
  }
  function wireMarket(M){
    wireBid(M);
    $("pbody").querySelectorAll("[data-mk]").forEach(b => b.onclick = () => { mkTab = b.dataset.mk; renderView(true); });
    const it = $("mk-item"), ct = $("mk-city");
    if (it) it.onchange = () => { mkItem = it.value; renderView(true); };
    if (ct) ct.onchange = () => { mkCity = ct.value; renderView(true); };
    $("pbody").querySelectorAll("input.price[data-key]").forEach(x => x.addEventListener("input", () => { mkDraft[x.dataset.key] = x.value; }));
    $("pbody").querySelectorAll("input.qty[data-k]").forEach(x => x.addEventListener("input", () => {
      const t = $(`mkt-${x.dataset.k}`); if (t) t.textContent = money2((Math.floor(+x.value) || 0) * +x.dataset.price);
    }));
    $("pbody").querySelectorAll("[data-buy]").forEach(b => b.onclick = () => {
      const l = M.listings[+b.dataset.buy], q = Math.floor(+$(`mkq-${b.dataset.buy}`).value);
      if (!(q > 0)){ toast("How many?", "bad"); return; }
      if (l.kind === "order"){
        fetchIt({my_business_id: l.receivers[0].id, seller_business_id: l.business, item: l.item, qty: q});
        return;
      }
      const buy = () => act("buy_from_business", {business_id: l.business, item: l.item, qty: q});
      if (l.here){ buy(); return; }
      // Shop goods are bought in person: the compass points you there, you
      // ride, and it is bought as you walk in (2026-10-18: no auto-walking).
      close();
      S.errand = {business: l.business, place: l.place, item: l.item, qty: q, buy};
      toast(`Ride to ${l.place} to buy ${q} ${l.item}: follow the compass. It is bought when you walk in.`);
    });
    $("pbody").querySelectorAll("[data-fetchc]").forEach(b => b.onclick = () => fetchIt({consignment_id: b.dataset.fetchc}));
    $("pbody").querySelectorAll("[data-dl]").forEach(b => b.onclick = async () => {
      const r = await api.post("/api/delivery", {action: b.dataset.dl});
      toast(r.ok ? r.message : `Can't: ${r.message}`, r.ok ? "" : "bad");
      refreshSoon(); setTimeout(() => renderView(true), 400);
    });
    $("pbody").querySelectorAll("[data-deliver]").forEach(b => b.onclick = async () => {
      const r = await api.post("/api/delivery", JSON.parse(b.dataset.deliver));
      toast(r.ok ? r.message : `Can't: ${r.message}`, r.ok ? "milestone" : "bad");
      if (r.ok){ close(); refreshSoon(); if (ctx.onDelivery) ctx.onDelivery(); }
    });
    $("pbody").querySelectorAll("[data-list]").forEach(b => b.onclick = () => {
      const g = M.goods[+b.dataset.list], v = +$(`mkp-${b.dataset.list}`).value;
      if (!(v > 0)){ toast("Type a price first.", "bad"); return; }
      act("set_retail_price", {business_id: g.business, item: g.item, price: v}).then(r => { if (r.ok) delete mkDraft[g.business + "|" + g.item]; renderView(true); });
    });
    $("pbody").querySelectorAll("[data-carry]").forEach(b => b.onclick = async () => {
      const g = M.carried[+b.dataset.carry], v = +$(`mkc-${b.dataset.carry}`).value, at = g.list_at[0].id;
      const r = await act("stock_business_inventory", {business_id: at, item: g.item, qty: g.qty});
      if (r.ok && (await act("set_retail_price", {business_id: at, item: g.item, price: v})).ok) delete mkDraft["carry|" + g.item];
      renderView(true);
    });
  }

  /* MISSIONS (2026-10-18): three state jobs in a chain, each teaching a
     system and paying a bonus. */
  async function missionAct(action, id){
    const r = await api.post("/api/mission", {action, id});
    toast(r.ok ? r.message : `Can't: ${r.message}`, !r.ok ? "bad" : r.won === false ? "rival" : "milestone");
    refreshSoon();
    if (r.ok && action === "start"){ close(); if (ctx.onDelivery) ctx.onDelivery(); }
    else if (view && view.ref === "missions") renderView(true);
  }
  function missionsPanel(Ms){
    const icon = {harvest: "\u{1F33E}", bounty: "\u{1F3F9}", citizen: "\u{1F91D}"};
    let out = `<div class="howto">Three goals, one after another. Each teaches a part of the game and pays a bonus on top of anything you earn doing it. Achievements complete by themselves; the bandit camp you start when you are ready.</div>`;
    out += Ms.board.map(m => {
      let act = "";
      if (m.status === "open") act = `<button class="btn go" data-mission="start" data-id="${esc(m.id)}">Start \u00b7 +${money(m.reward)}</button>`;
      else if (m.status === "needs") act = `<span class="dim">found a farm or a mine first</span>`;
      else if (m.status === "active" && m.auto) act = `<span class="good">completes by itself</span> <button class="btn" data-tab="market">Delivery jobs</button>`;
      else if (m.status === "active"){
        act = (m.id === "bounty" ? `<span class="good">${Ms.at_camp ? "walk up to the tents to fight" : "ride to the camp: follow the compass"}</span>` : `<span class="good">under way</span>`)
          + ` <button class="btn" data-mission="abandon">Give up</button>`;
      } else if (m.status === "done") act = `<span class="good">\u2713 done</span>`;
      else act = `<span class="dim">finish the one before</span>`;
      const where = m.status === "active" && m.id === "bounty" && Ms.active ? `<small>The camp is at <b>${esc(Ms.active.place)}</b>; your odds now ${Math.round(Ms.odds * 100)}%. The compass points the way.</small>` : "";
      return `<div class="mk-row mission ${m.status}"><div class="mk-who"><span class="avatar">${icon[m.id] || "\u2B50"}</span><b>${esc(m.title)}</b> <span class="dim">+${money(m.reward)}</span><small>${esc(m.does)}</small>${where}</div><div class="mk-act">${act}</div></div>`;
    }).join("");
    return out;
  }

  /* THE GUIDE (2026-10-18): what the game is and what to do first, a step at
     a time, each with a button that takes you there. Opens itself the first
     time you play a game; "?" in the top bar brings it back. */
  const OB = [
    {icon: "\u{1F3E0}", title: "Welcome to your house", body: h => S.ST && S.ST.you.outposts
      ? `You head <b>${esc(h.house)}</b>. There are no towns yet: everyone lives at an outpost of their own around the state's trading posts, which feed, hire and buy. Choose your land, build out from it, and settle near others when it pays. Your goal is the richest, largest house in the valley.`
      : `You head <b>${esc(h.house)}</b>. Your home stands in your town's square, and the gold squares around it are your border. Next door, two towns full of citizens are already trading. Your goal is the richest, largest house in the valley.`},
    {icon: "\u{1F46A}", title: "Your family is your first workforce", body: h => `Your partner works any business you own for nothing, always on shift. Your son and daughter come of age in a day or two; then they can work too, or marry into another house. A couple has a child every game month; feeding a child a Meal brings it a day sooner.`, tab: "house", label: "See your house"},
    {icon: "\u26CF", title: "Found a farm or a mine", body: () => `Pick <b>Farm</b> or <b>Mine</b> in the Build menu on the left and place it on a spur road. Then send your partner to work it from your house page, and choose what it makes. Rich ground shows itself at the first harvest.`},
    {icon: "\u{1F4DC}", title: "Deliver your first harvest", body: () => `Once your farm has made something, carry it to a refinery yourself: Market, Sell, <b>Deliver it yourself</b>. Your donkey carries ten, and your first delivery earns a bonus. The <b>Missions</b> page has what comes next: a bandit camp to clear, then a delivery to a citizen.`, tab: "missions", label: "Open Missions"},
    {icon: "\u{1F4B0}", title: "Sell to the best bidder", body: () => `Open the <b>Market</b> and the <b>Sell</b> tab. Refineries in every town bid for raw goods: the state's always pays a low fixed price, citizens' pay more when they need it. Pick the best price and you are paid at once.`, tab: "market", label: "Open the Market"},
    {icon: "\u{1F4A1}", title: "Learn something", body: () => `<b>Know-how</b> makes you better at something for good. Your first study lands in six game hours; the ones after take longer and pay more.`, tab: "knowhow", label: "Open Know-how"},
    {icon: "\u{1F48D}", title: "Marry for allies", body: () => `When a child comes of age, propose a match with another house's son or daughter. Accepted, the houses are allies -- and two allied houses can found a <b>clan</b>.`, tab: "house", label: "Your house"},
    {icon: "\u23F3", title: "Watch the countdowns", body: () => `<b>Coming up</b>, on the left, lists everything you have running: studies, projects, children growing up. There is always something about to land. Grow by building more, hiring citizens or slower NPC hands, and marrying well.`},
  ];
  let obStep = 0;
  async function openGuide(step){
    const h = await api.get("/api/household").catch(() => ({house: "your house"}));
    obStep = step || 0;
    const draw = () => {
      const s = OB[obStep];
      $("ob-body").innerHTML = `<div class="ob-ic">${s.icon}</div><h2>${esc(s.title)}</h2><p>${s.body(h)}</p>`
        + (s.tab ? `<button class="btn go" id="ob-go">${esc(s.label)}</button>` : "");
      $("ob-dots").innerHTML = OB.map((_, i) => `<i class="${i === obStep ? "on" : ""}"></i>`).join("");
      $("ob-back").disabled = obStep === 0;
      $("ob-next").textContent = obStep === OB.length - 1 ? "Start playing" : "Next";
      const go = $("ob-go"); if (go) go.onclick = () => { $("onboard").classList.remove("open"); view = null; openTab(s.tab); };
    };
    $("ob-back").onclick = () => { if (obStep > 0){ obStep--; draw(); } };
    $("ob-next").onclick = () => { if (obStep < OB.length - 1){ obStep++; draw(); } else $("onboard").classList.remove("open"); };
    $("ob-close").onclick = () => $("onboard").classList.remove("open");
    draw();
    $("onboard").classList.add("open");
  }
  $("t-guide").onclick = () => openGuide(0);

  /* KNOW-HOW (2026-10-18): your tech tree, by tier, with what each is worth
     to you now. One study at a time; it lands on its own. */
  function knowhowPanel(K){
    let out = `<div class="howto">Learn one thing at a time; it lands on its own and makes you better at something <b>for good</b>. Tier one takes ${K.nodes.find(n => n.tier === 1).eta}h; the last, Steam, takes two days.</div>`;
    if (K.studying) out += `<div class="kh-now"><div><b>Studying ${esc(K.studying.name)}</b> \u2014 learned in ${dur(K.studying.eta)}</div><div class="bar"><i style="width:${Math.round(K.studying.pct * 100)}%"></i></div></div>`;
    else out += `<div class="kh-now idle"><b>You are not studying anything.</b> Pick one below.</div>`;
    const tiers = [...new Set(K.nodes.map(n => n.tier))].sort();
    out += `<div class="kh-tree">` + tiers.map(t => `<div class="kh-tier"><div class="kh-th">${t === 4 ? "Milestone" : "Tier " + t}</div>` + K.nodes.filter(n => n.tier === t).map(n => {
      const btn = n.status === "open" ? B(K.studying ? `Study instead \u00b7 ${n.eta}h` : `Study \u00b7 ${n.eta}h`, "research", {tech: n.id}, !K.studying)
        : n.status === "studying" ? `<span class="good">studying</span>` : n.status === "known" ? `<span class="good">\u2713 known</span>` : `<span class="dim">${esc(n.why)}</span>`;
      return `<div class="kh-node ${n.status}"><b>${esc(n.name)}</b><div>${esc(n.does)}</div>${n.worth ? `<div class="kh-worth">${esc(n.worth)}</div>` : ""}<div class="kh-act">${btn}</div></div>`;
    }).join("") + `</div>`).join("") + `</div>`;
    return out;
  }

  /* YOUR HOUSE (2026-10-18): the household -- your first workers -- and how
     it grows: children only to the married, marriages only by agreement
     between houses, which then become allies. */
  function housePanel(H){
    const time = h => h == null ? "" : dur(h);
    let out = `<div class="howto"><b>${esc(H.house)}</b> \u2014 ${H.members.length} of ${H.cap} in the household. Grown members work your businesses for nothing and never go off shift. Children come of age on their own; new children come only to a <b>married couple</b>, and you marry by agreement with another house, which then becomes your <b>ally</b>. A grown member is your heir if you die.</div>`;
    if (H.offers_in.length) out += `<h3>Proposals to your house</h3>` + H.offers_in.map(o => `<div class="mk-row"><div class="mk-who"><b>${esc(o.house)}</b> proposes their <b>${esc(o.their)}</b> for your <b>${esc(o.mine)}</b>, with a dowry of <b>${money(o.dowry)}</b>.<small>Accept and ${esc(o.mine)} joins their household; your houses become allies.</small></div><div class="mk-act">${B("Accept", "accept_marriage", {offer_id: o.id}, true)}${B("Decline", "decline_marriage", {offer_id: o.id})}</div></div>`).join("");
    const icon = m => m.adult ? (m.sex === "f" ? "\u{1F469}" : "\u{1F468}") : (m.sex === "f" ? "\u{1F467}" : "\u{1F466}");
    const roleName = m => m.partner ? "your partner" : m.role === "in-law" ? `married in${m.from_house ? " from " + esc(m.from_house) : ""}` : m.role || "";
    out += `<h3>Household</h3><div class="mk-row person me"><div class="mk-who"><span class="avatar">${H.you.sex === "f" ? "\u{1F469}" : "\u{1F468}"}</span><b>You</b> <span class="chip calling">${esc(H.you.calling)}</span><small>head of ${esc(H.house)}</small></div></div>`
      + H.members.map(m => {
      let what = m.adult ? `${roleName(m)}${!m.partner && m.spouse ? ` \u00b7 married to ${esc(m.spouse)}` : !m.partner ? " \u00b7 unmarried" : ""}`
        : `${esc(m.role || "child")} \u00b7 old enough to work in <b>${time(m.grows_in)}</b>`;
      if (m.next_child_in != null) what += ` \u00b7 next child in <b>${time(m.next_child_in)}</b>`;
      const grow = m.pct_grown == null ? "" : `<div class="bar"><i style="width:${Math.round(m.pct_grown * 100)}%"></i></div>`;
      const work = !m.adult ? (H.meals ? B("Feed a Meal \u00b7 a day sooner", "feed_family", {member_id: m.id}, true) : `<span class="dim">carry a Meal to feed them</span>`)
        : `<select data-assign="${esc(m.id)}"><option value="">at home</option>${H.businesses.map(b => `<option value="${esc(b.id)}"${b.id === m.works_at ? " selected" : ""}>works at your ${esc(b.type.split(" /")[0])}</option>`).join("")}</select>`;
      return `<div class="mk-row"><div class="mk-who"><span class="avatar">${icon(m)}</span><b>${esc(m.name)}</b> <span class="chip calling">${esc(m.calling)}</span><small>${what}</small>${grow}</div><div class="mk-act">${work}</div></div>`;
    }).join("")
      + `<div class="tip">A married couple has a child every game month; a child is old enough to work after a month, a day sooner for every Meal you feed them (you carry ${H.meals}). Hired NPC hands work at 60% of a person's pace.</div>`;
    if (!H.businesses.length && H.members.some(m => m.adult)) out += `<div class="tip">Found a business and your family can work it from day one.</div>`;
    if (H.allies.length) out += `<h3>Allies</h3><div class="tip">${H.allies.map(a => esc(a.house)).join(", ")}</div>`;
    const mine = H.members.filter(m => m.adult && !m.spouse);
    out += `<h3>Houses to marry into</h3>`;
    if (!mine.length) out += `<div class="tip">Nobody in your house is grown and unmarried right now${H.members.some(m => !m.adult) ? " \u2014 wait for a child to come of age" : ""}.</div>`;
    const open = H.houses.filter(h => h.free.length);
    out += open.length ? open.slice(0, 30).map(h => `<div class="mk-row"><div class="mk-who"><b>${esc(h.house)}</b> ${h.ally ? `<span class="chip">ally</span>` : ""} <span class="dim">${esc(short(h.name))} \u00b7 ${esc(h.city)}</span>`
        + `<small>${h.free.map(m => `${esc(m.name)} (${esc(m.calling)})`).join(", ")}</small></div>`
        + (mine.length ? `<div class="mk-act"><select data-mine="${esc(h.agent)}">${mine.map(m => `<option value="${esc(m.id)}">your ${esc(m.name)}</option>`).join("")}</select>`
          + `<select data-theirs="${esc(h.agent)}">${h.free.map(m => `<option value="${esc(m.id)}">their ${esc(m.name)}</option>`).join("")}</select>`
          + `<input class="price" type="number" min="0" step="5" value="25" data-dowry="${esc(h.agent)}" title="Dowry"><button class="btn go" data-propose="${esc(h.agent)}">Propose</button></div>` : "") + `</div>`).join("")
      : `<div class="empty">No other house has anyone grown and unmarried right now.</div>`;
    if (H.offers_out.length) out += `<h3>Your proposals</h3>` + H.offers_out.map(o => `<div class="row"><div class="grow">To ${esc(o.house)} \u00b7 dowry ${money(o.dowry)}</div><span class="dim">${esc(o.status)}</span></div>`).join("");
    return out;
  }
  function wireHouse(H){
    $("pbody").querySelectorAll("[data-assign]").forEach(sel => sel.onchange = () =>
      act("assign_family", {member_id: sel.dataset.assign, business_id: sel.value}).then(() => renderView(true)));
    $("pbody").querySelectorAll("[data-propose]").forEach(b => b.onclick = () => {
      const a = b.dataset.propose, q = s => $("pbody").querySelector(`[data-${s}="${a}"]`);
      act("propose_marriage", {agent_id: a, member_id: q("mine").value, their_member_id: q("theirs").value,
                               dowry: +q("dowry").value || 0}).then(() => renderView(true));
    });
  }

  /* PEOPLE (designer request, 2026-10-18): everyone in your town -- what they
     own, where they work, their character and what they are good at -- with a
     job offer and a private thread a click away. Other towns cost a report. */
  let pplCity = "", pplFilter = "";
  function peoplePanel(P){
    const myBiz = (S.OBS.you.businesses || []);
    const tabs = [{key: P.your_city, name: "My town"}].concat(P.cities.map(c => ({key: c.key, name: c.name})));
    let out = `<div class="seg">${tabs.map(t => `<button class="seg-b${(P.city === t.key) ? " on" : ""}" data-city="${esc(t.key)}">${esc(t.name)}</button>`).join("")}</div>`;
    if (P.locked){
      return out + `<div class="howto"><b>${esc(P.name)}</b> has ${P.population} citizens. You know nothing else about them. A report tells you who lives there, what they own, where they work and what they are good at -- as of the hour you buy it.</div>`
        + `<div class="acts"><button class="btn go" id="buy-report"${P.cash < P.report_cost ? " disabled" : ""}>Buy a report on ${esc(P.name)} \u00b7 ${money(P.report_cost)}</button></div>`;
    }
    out += `<div class="howto">${P.live ? "" : `Report from hour ${P.hour} \u2014 <a href="#" id="buy-report">buy a fresh one (${money(P.report_cost)})</a>. `}`
      + `<b>${P.population}</b> citizens. `
      + (P.state_sites.length ? `State sites: ${P.state_sites.map(t => esc(t.split(" /")[0])).join(", ")}. ` : "")
      + (P.buildings.length ? `Citizens own: ${P.buildings.map(b => `${b.count} ${esc(b.type.split(" /")[0])}`).join(", ")}.` : "Citizens own no businesses yet.")
      + `<br><span class="dim">Wages are private: to hire someone good, offer a job and talk it over.</span></div>`;
    // CLANS (2026-10-18): across towns; a secret one is seen only from inside.
    out += `<h3>Clans</h3>` + (P.clans.length ? P.clans.map(c => `<div class="row"><div class="grow"><b>${esc(c.name)}</b>${c.secret ? ` <span class="chip">secret</span>` : ""}${c.mine ? ` <span class="good">yours</span>` : ""} <span class="dim">${c.members} members \u00b7 ${esc(c.towns.join(", "))}</span>${c.names.length && c.mine ? `<br><span class="dim">${c.names.map(n => esc(short(n))).join(", ")}</span>` : ""}</div><b>${money(c.worth)}</b></div>`).join("") : `<div class="empty">No clans yet.</div>`)
      + (P.my_clan ? `<div class="acts">${B("Leave your clan", "leave_guild", {})}</div>`
        : `<div class="tip">A clan needs two allied houses: marry one of your family into another house first.</div><div class="hire-row"><input id="clan-name" placeholder="Name a clan" maxlength="40"><label><input type="checkbox" id="clan-secret"> secret</label><button class="btn go" id="clan-make">Found it</button></div><div class="tip">A clan spans towns. A secret one is invisible to outsiders: you can belong to one while living in another town, and trade for it quietly.</div>`);
    out += `<div class="hire-row"><input id="ppl-find" placeholder="Find a name, a skill (Miner) or a character (Hauler)" value="${esc(pplFilter)}" style="flex:1"></div>`;
    const f = pplFilter.toLowerCase();
    const rows = P.people.filter(p => !f || [p.name, p.calling, ...p.skills.map(s => s.role + " " + s.level), ...p.owns.map(o => o.type)].join(" ").toLowerCase().includes(f));
    out += rows.map(p => {
      const skills = p.skills.length ? p.skills.slice(0, 4).map(s => `<span class="chip">${esc(s.role)} \u00b7 ${esc(s.level)} <i>${s.hours}h</i></span>`).join("") : `<span class="dim">no work experience yet</span>`;
      const owns = p.owns.length ? p.owns.map(o => esc(o.type.split(" /")[0])).join(", ") : "nothing";
      const job = p.job ? `${esc(p.job.role)} at ${p.job.employer === "themself" ? "their own " + esc(p.job.type.split(" /")[0]) : esc(p.job.employer === "the state" ? "the state's" : short(p.job.employer) + "'s") + " " + esc(p.job.type.split(" /")[0])}` : "no job";
      const acts = p.you ? `<span class="good">you</span>`
        : `<button class="btn go" data-msg="${esc(p.id)}">Message</button>`
          + (myBiz.length ? F("Offer a job", "offer_job", {agent_id: p.id, business_id: myBiz[0].id}, `Offer ${short(p.name)} a job`) : "")
          + (P.my_clan ? B("Invite to clan", "invite_to_guild", {target_id: p.id}) : "");
      return `<div class="mk-row person${p.you ? " me" : ""}"><div class="mk-who"><b>${esc(short(p.name))}</b> ${p.house ? `<span class="dim">of ${esc(p.house)}</span>` : ""} ${p.calling ? `<span class="chip calling">${esc(p.calling)}</span>` : ""}${p.ally ? ` <span class="chip">ally</span>` : ""} <span class="dim">worth ${money(p.worth)}</span>`
        + `<small>Owns: ${owns} \u00b7 ${job}</small><div class="skills">${skills}</div></div><div class="mk-act">${acts}</div></div>`;
    }).join("") || `<div class="empty">Nobody matches.</div>`;
    return out;
  }
  function wirePeople(P){
    $("pbody").querySelectorAll("[data-city]").forEach(b => b.onclick = () => { pplCity = b.dataset.city; renderView(true); });
    const find = $("ppl-find");
    if (find) find.oninput = () => { pplFilter = find.value; const at = find.selectionStart; renderView(true).then(() => { const x = $("ppl-find"); if (x){ x.focus(); x.setSelectionRange(at, at); } }); };
    const mk = $("clan-make");
    if (mk) mk.onclick = () => { const n = $("clan-name").value.trim(); if (!n){ toast("Name it first.", "bad"); return; }
      act("create_guild", {name: n, secret: $("clan-secret").checked}).then(() => renderView(true)); };
    const buy = $("buy-report");
    if (buy) buy.onclick = async e => {
      e.preventDefault();
      const r = await api.post("/api/report", {city: P.city});
      toast(r.ok ? r.message : `Can't: ${r.message}`, r.ok ? "" : "bad");
      refreshSoon(); renderView(true);
    };
  }

  /* A PRIVATE THREAD with one person, like a phone's messages: theirs on the
     left, yours on the right, a box to type in. Stays open beside the map. */
  let THREAD = null, threadTimer = null;
  async function loadThread(){
    if (!THREAD) return;
    const r = await api.get(`/api/thread?with=${encodeURIComponent(THREAD)}`);
    if (!r.ok || !THREAD) return;
    $("th-name").textContent = short(r.with.name);
    $("th-sub").textContent = [r.with.calling, r.with.city].filter(Boolean).join(" \u00b7 ");
    const box = $("th-msgs"), atEnd = box.scrollTop + box.clientHeight >= box.scrollHeight - 30;
    box.innerHTML = r.messages.length ? r.messages.map(m => `<div class="bub ${m.from_me ? "me" : "them"}">${esc(m.text)}<i>${clock(m.hour)}</i></div>`).join("")
      : `<div class="dim" style="text-align:center;margin-top:30px">No messages yet. Say hello, pitch a job, or name a price.</div>`;
    if (atEnd) box.scrollTop = box.scrollHeight;
  }
  function openThread(id){
    THREAD = id;
    $("thread").classList.add("open");
    $("th-text").value = ""; $("th-text").focus();
    loadThread().then(() => { $("th-msgs").scrollTop = $("th-msgs").scrollHeight; });
    clearInterval(threadTimer); threadTimer = setInterval(loadThread, 3000);
  }
  function closeThread(){ THREAD = null; clearInterval(threadTimer); $("thread").classList.remove("open"); }
  async function sendThread(){
    const text = $("th-text").value.trim(); if (!text || !THREAD) return;
    $("th-text").value = "";
    const r = await api.post("/api/act", {action: "send_direct_message", args: {target_id: THREAD, text, why: ""}});
    if (!r.ok) toast(`Can't: ${r.message || r.error}`, "bad");
    loadThread().then(() => { $("th-msgs").scrollTop = $("th-msgs").scrollHeight; });
  }
  $("th-close").onclick = closeThread;
  $("th-send").onclick = sendThread;
  $("th-text").addEventListener("keydown", e => { e.stopPropagation(); if (e.key === "Enter"){ e.preventDefault(); sendThread(); } });
  $("th-offer").onclick = () => {
    const myBiz = (S.OBS.you.businesses || []);
    if (!myBiz.length){ toast("Found a business first: an offer is a job at one of yours.", "bad"); return; }
    openForm("offer_job", {agent_id: THREAD, business_id: myBiz[0].id}, "Offer a job");
  };

  function personPanel(id, c){
    if (!c) return `<div class="empty">Nothing is known about them yet.</div>`;
    const mineBiz = S.OBS.you.businesses || [];
    let out = `<div class="card"><div class="t">${esc(short(c.name))} <span class="dim">${esc(id)}</span></div>
      <div class="m">${esc(c.doing || "")}${c.at ? ` at ${esc(c.at)}` : ""}</div>
      <div class="m">Worth ${money(c.net_worth)}${c.rank ? ` · rank ${c.rank} of ${c.of}` : ""}</div></div>`;
    if ((c.businesses || []).length) out += `<h3>Owns</h3>` + c.businesses.map(b => `<div class="row"><div class="grow">${esc(b.type)} <span class="dim">${esc(b.place)}</span></div><button class="btn" data-building="${esc(b.id)}">Look</button></div>`).join("");
    if ((c.employed_by || []).length) out += `<h3>Works</h3>` + c.employed_by.map(e => `<div class="tip">${esc(e.role)} at ${esc(short(e.business))}, ${money2(e.wage)}/hr</div>`).join("");
    out += `<h3>Deal with them</h3><div class="acts"><button class="btn go" data-msg="${esc(id)}">Message</button>${F("Pay", "pay", {agent_id: id}, `Pay ${short(c.name)}`)}`
      + (mineBiz.length ? F("Offer a job", "offer_job", {agent_id: id, business_id: mineBiz[0].id}, `Offer ${short(c.name)} a job`) : "")
      + `</div>`;
    return out;
  }

  function manageCard(b, inline){
    const stock = Object.entries(b.stock || {}).map(([k, v]) => `${v} ${k}`).join(", ") || "empty";
    const id = {business_id: b.id};
    const stalled = /STALLED|FULL|nothing|not set/i.test(b.production || "");
    return `<div class="card">${inline ? "" : `<div class="t">${esc(b.type)} <span class="dim">${esc(b.id)} · ${esc(b.location)}</span> <button class="btn go" data-building="${esc(b.id)}">Manage</button></div>`}
      <div class="m">Purse <b>${money2(b.cash)}</b> <span class="dim">(sales go to your coins)</span> · staff ${esc(b.workers)}/${esc(b.employee_places)} · storage ${esc(b.storage_used)}/${esc(b.storage_capacity)}</div>
      ${b.production ? `<div class="${stalled ? "warn" : "good"}">${esc(b.production)}</div>` : ""}
      <div class="m">Stock: ${esc(stock)}</div>
      <div class="acts">${B("Work here myself (4h)", "apply_for_job", id, true)}${F("Set production", "set_production", id)}${F("Set a price", "set_retail_price", id)}${F("Order supplies", "order_from_business", {my_business_id: b.id}, "Order supplies")}</div>
      <div class="acts">${F("Deposit", "deposit", id)}${F("Withdraw", "withdraw", id)}${F("Advertise a job", "post_job", id)}${F("Offer a job", "offer_job", id)}${F("Take stock out", "collect_business_inventory", id)}${F("Hire a courier", "post_delivery_job", id)}${inline ? "" : `<button class="btn" data-gobiz="${esc(b.id)}">Go there</button>`}</div></div>`;
  }

  const TABS = {
    here(){
      const o = S.OBS, y = o.you, here = o.here || {}, p = placeOf(y.location);
      let out = `<div class="card"><div class="t">${esc(y.location)} <span class="dim">${esc(p.cityName || "")} · ${esc(kindOf(y.location))}</span></div><div class="m">${esc(S.ST.activity)}</div></div>`;
      const biz = here.businesses || [];
      out += `<h3>Buildings here</h3>` + (biz.length ? biz.map(b => {
        const sells = Object.entries(b.sells || {});
        return `<div class="row"><div class="grow"><b>${esc(b.type)}</b>${b.owner === y.id ? ' <span class="yours">yours</span>' : ` <span class="dim">${esc(ownerLabel(b.owner))}</span>`}<br>`
          + `<span class="${/CLOSED|EMPTY/.test(b.status || "") ? "warn" : "dim"}">${esc((b.status || "").split(" -- ")[0])}</span>`
          + (sells.length ? ` · ${sells.map(([i, v]) => `${esc(i)} ${money2(v.price)}`).join(", ")}` : "") + `</div>`
          + (sells.some(([i]) => i === "Meal") ? B("Eat", "buy_meal", {business_id: b.id}, true) : "")
          + `<button class="btn" data-building="${esc(b.id)}">Open</button></div>`;
      }).join("") : `<div class="empty">No businesses stand here.</div>`);
      const people = here.agents || [];
      if (people.length) out += `<h3>People here</h3>` + people.map(a => `<div class="row"><div class="grow">${esc(short(a.name))}</div><button class="btn" data-person="${esc(a.id)}">Talk</button></div>`).join("");
      // Your kit: what you carry, to wield; what you own, to ride.
      const carry = Object.entries(y.carrying || {});
      const vehicles = (S.ST.vehicles || []);
      out += `<h3>Your kit</h3><div class="tip">Wielding ${esc(y.weapon)} · ${esc(y.vehicle)}</div>`;
      out += carry.length ? carry.map(([i, n]) => `<div class="row"><div class="grow">${n} × ${esc(i)}</div>${F("Sell", "sell_to_business", {item: i}, `Sell ${i}`)}${B("Equip", "equip", {item: i})}</div>`).join("") : `<div class="empty">You carry nothing.</div>`;
      out += vehicles.map(v => `<div class="row"><div class="grow">${esc(v.type)} <span class="dim">at ${esc(v.location)}</span></div>`
        + (v.mounted ? B("Get down", "dismount") : B("Ride", "mount", {vehicle_id: v.id}, true)) + `</div>`).join("");
      const tips = (o.you_can || []).filter(t => !/^Carrying/.test(t));
      if (tips.length) out += `<h3>Good to know</h3>` + tips.map(t => `<div class="tip">• ${esc(t)}</div>`).join("");
      return out;
    },
    travel(){
      const st = S.ST, mine = st.city, me = S.player ? S.player.root.position : null;
      const groups = {};
      for (const p of S.BOARD.places) (groups[p.city] = groups[p.city] || {name: p.city_name, rows: []}).rows.push(p);
      let out = `<div class="tip">Walk anywhere with the arrow keys or by clicking the ground or the minimap. Fast travel takes the timed road: the screen waits while the clock runs.${st.vehicle ? ` You are riding a ${esc(st.vehicle)}: ${st.speed}× walking pace.` : ""}</div>`;
      const keys = Object.keys(groups).sort((a, b) => (a === mine ? -1 : b === mine ? 1 : 0));
      for (const k of keys){
        const g = groups[k], market = S.BOARD.places.find(p => p.city === k && S.DATA.cities.find(c => c.key === k && c.market === p.name));
        out += `<h3>${esc(g.name)}${k === mine ? " — home" : ""}</h3>`;
        if (k !== mine && market) out += `<div class="acts" style="margin-bottom:6px"><button class="btn go" data-fast="${esc(market.name)}">Fast travel to ${esc(g.name)}</button></div>`;
        for (const p of g.rows.sort((a, b) => (a.minutes ?? 1e9) - (b.minutes ?? 1e9))){
          const pl = placeOf(p.name);
          const here = p.name === S.OBS.you.location;
          const walk = me && pl.c ? Math.round(Math.hypot(me.x - pl.c.x, me.z - pl.c.z) / 4.6 / (st.speed || 1)) : null;
          out += `<div class="row"><div class="grow"><b>${esc(p.name)}</b> <span class="dim">${esc(kindOf(p.name))}${walk != null && !here ? ` · ${walk < 90 ? walk + " s" : Math.round(walk / 60) + " min"} on foot` : ""}</span></div>`
            + (here ? `<span class="good">you are here</span>` : `<button class="btn" data-walk="${esc(p.name)}">Walk</button><button class="btn" data-fast="${esc(p.name)}">Fast travel</button>`)
            + `</div>`;
        }
      }
      return out;
    },
    business(){
      const o = S.OBS, list = o.you.businesses || [], here = o.you.location, P = S.BOARD.places.find(p => p.name === here) || {};
      let out = list.length ? list.map(b => manageCard(b, false)).join("") : `<div class="empty">You own no business yet.</div>`;
      out += `<h3>Found a business at ${esc(here)}</h3>`;
      const spur = placeOf(here).kind === "spur";
      out += `<div class="tip">You found it where you stand. ${spur ? "This is a spur road: farms and mines belong here." : "This is the main road: shops, taverns and workshops belong here; farms and mines need a spur road."} You have ${money2(o.you.denari)}.</div>`;
      out += S.BOARD.business_types.map(t => {
        const fits = t.spur === spur;
        return `<div class="row"><div class="grow"><b>${esc(t.name)}</b> <span class="dim">${t.spur ? "spur" : "main road"} · makes ${esc(t.makes.slice(0, 4).join(", "))}${t.makes.length > 4 ? "…" : ""}</span></div><b>${money(t.cost)}</b>`
          + (fits ? F("Found", "start_business", {type: t.name}, `Found a ${t.name}`) : `<span class="dim">not here</span>`) + `</div>`;
      }).join("");
      out += `<h3>Land</h3><div class="tip">Unsold ground sells at ${money(S.BOARD.land_price)} a plot. Each plot past a business's own four seats one more worker once built on.</div>`;
      out += `<div class="row"><div class="grow"><b>${esc(here)}</b> <span class="dim">${P.plots_free ?? "?"} of ${P.plots_total ?? "?"} plots unsold</span></div>${F("Buy land here", "buy_land", {plots: 1}, `Buy land at ${here}`)}</div>`;
      const listed = S.BOARD.listed_land.filter(l => !l.mine);
      if (listed.length) out += listed.map(l => `<div class="row"><div class="grow">Plot ${esc(l.id)} at <b>${esc(l.at)}</b> <span class="dim">${esc(short(l.owner))}${l.developed ? ", built on" : ""}</span></div><b>${money2(l.price)}</b>${B("Buy", "buy_listed_land", {plot_id: l.id})}</div>`).join("");
      const mineLand = S.BOARD.my_land;
      if (mineLand.length) out += `<h3>Your land</h3>` + mineLand.map(l => `<div class="row"><div class="grow">${esc(l.id)} at ${esc(l.at)} <span class="dim">${l.developed ? "built on" : "raw"}${l.business ? ", " + esc(l.business) : ""}${l.for_sale_at != null ? `, for sale at ${money2(l.for_sale_at)}` : ""}</span></div>${F("Sell", "list_land", {plot_id: l.id}, "Put land up for sale")}</div>`).join("");
      out += `<h3>Other places</h3>` + S.BOARD.places.filter(p => p.city === S.ST.city && p.name !== here).map(p =>
        `<div class="row"><div class="grow"><b>${esc(p.name)}</b> <span class="dim">${esc(kindOf(p.name))} · ${p.plots_free} of ${p.plots_total} plots unsold</span></div><button class="btn" data-walk="${esc(p.name)}">Walk</button></div>`).join("");
      return out;
    },
    jobs(){
      const y = S.OBS.you;
      let out = "";
      if (y.job){
        out += `<div class="card"><div class="t">You work as ${esc(y.job.role)}</div><div class="m">${esc(short(y.job.business))} · ${money2(y.job.wage_per_hour)}/hr</div>`
          + `<div class="acts">${B("Work 4 hours", "start_shift", {hours: 4}, true)}${B("Work 8 hours", "start_shift", {hours: 8})}${B("Stop work", "end_shift")}${B("Quit", "quit_job")}</div></div>`;
      } else out += `<div class="card"><div class="t">You have no job.</div><div class="m">Answer an advert, take an offer, or work your own business.</div></div>`;
      const J = S.BOARD.jobs;
      const offers = J.filter(j => j.to_me);
      out += `<h3>Offers to you</h3>` + (offers.length ? offers.map(j => `<div class="row"><div class="grow"><b>${esc(j.role)}</b> at ${esc(short(j.business))} <span class="dim">${esc(j.at)}</span></div><b>${money2(j.wage)}/hr</b>${B("Accept", "accept_job_offer", {posting_id: j.id}, true)}</div>`).join("") : `<div class="empty">Nobody has offered you a job.</div>`);
      const board = J.filter(j => !j.to_me && !j.mine).sort((a, b) => b.wage - a.wage);
      out += `<h3>Job board</h3>` + (board.length ? board.map(j => `<div class="row"><div class="grow"><b>${esc(j.role)}</b> at ${esc(short(j.business))} <span class="dim">${esc(j.at)}</span></div><b>${money2(j.wage)}/hr</b>`
        + (j.applied ? `<span class="dim">applied</span>` : B("Apply", "apply_to_job", {posting_id: j.id})) + `</div>`).join("") : `<div class="empty">No adverts are up.</div>`);
      const mine = J.filter(j => j.mine);
      if (mine.length || (y.businesses || []).length){
        out += `<h3>Your adverts</h3>` + mine.map(j => `<div class="card"><div class="t">${esc(j.role)} at ${money2(j.wage)}/hr</div>`
          + (Array.isArray(j.applicants) && j.applicants.length ? j.applicants.map(a => `<div class="row"><div class="grow">${esc(short(a.name))} applied</div>${B("Hire", "hire_applicant", {posting_id: j.id, applicant_id: a.id}, true)}</div>`).join("") : `<div class="dim">No applicants yet.</div>`)
          + `<div class="acts">${B("Take it down", "close_job", {posting_id: j.id})}</div></div>`).join("");
        if ((y.businesses || []).length) out += `<div class="acts">${F("Advertise a job", "post_job", {business_id: y.businesses[0].id})}${F("Offer someone a job", "offer_job", {business_id: y.businesses[0].id})}</div>`;
      }
      return out;
    },
    chat(){
      return `<div class="chatlog" id="chatlog"></div><div class="compose"><select id="say-to"></select><input id="say" placeholder="Say something…" maxlength="400"><button class="btn go" id="say-send">Send</button></div>`;
    },
    news(){
      return `<div class="feed">` + (FEED.slice().reverse().map(f => `<div class="${esc(f.kind)}"><span class="dim">${clock(f.hour)}</span> — ${esc(f.text)}</div>`).join("") || `<div class="empty">Nothing has happened to you yet.</div>`) + `</div>`;
    },
    ranks(){
      const st = S.ST;
      let out = "";
      if (st.cities && st.cities.length > 1) out += `<h3>The cities</h3>` + st.cities.slice().sort((a, b) => b.total - a.total).map((c, i) => `<div class="row"><div class="grow">${i + 1}. <b>${esc(c.name)}</b>${c.key === st.city ? " (yours)" : ""}</div><b>${money(c.total)}</b></div>`).join("");
      out += `<h3>Richest citizens</h3><div class="dim">Tap anyone to see what they own.</div>` + st.leaders.map((a, i) => `<div class="row click" data-assets="${esc(a.id)}"${a.you ? ' style="background:#c9a24a22"' : ""}><div class="grow">${i + 1}. ${a.you ? "<b>You</b>" : esc(short(a.name))}</div><b>${money(a.worth)}</b></div>`).join("")
        + (st.your_rank > st.leaders.length ? `<div class="row" style="background:#c9a24a22"><div class="grow">${st.your_rank}. <b>You</b></div><b>${money(st.you.net_worth)}</b></div>` : "");
      const ww = S.OBS.whats_working || [];
      if (ww.length) out += `<h3>What's working</h3><pre>${esc(ww.join("\n"))}</pre>`;
      return out;
    },
    menu(){
      const names = Object.keys(TOOLS).sort();
      return `<h3>Any action</h3><div class="tip">Everything an agent can do, by name. The buttons elsewhere fill these in for you.</div>
        <select id="pick"><option value="">Choose an action…</option>${names.map(n => `<option value="${esc(n)}">${esc(n.replace(/_/g, " "))}</option>`).join("")}</select>
        <h3>The rules</h3><button class="btn" id="m-rules">Show the briefing every agent is given</button><pre id="m-rules-t" style="display:none"></pre>
        <h3>What your agent sees</h3><button class="btn" id="m-obs">Show everything, as a model would see it</button><pre id="m-obs-t" style="display:none"></pre>
        <h3>Game</h3><div class="acts"><button class="btn" id="m-budget">Raise the spending cap by $5</button><a class="btn" href="/map" style="text-decoration:none">2D map &amp; boards</a><button class="btn go" id="m-quit">Save &amp; quit</button></div>`;
    },
  };

  function wireMenu(){
    $("pick").onchange = () => { if ($("pick").value) openForm($("pick").value, {}, $("pick").value.replace(/_/g, " ")); };
    $("m-rules").onclick = async () => { const r = await api.get("/api/briefing"); $("m-rules-t").textContent = r.text; $("m-rules-t").style.display = "block"; };
    $("m-obs").onclick = () => { $("m-obs-t").textContent = S.OBS_TEXT || ""; $("m-obs-t").style.display = "block"; };
    $("m-budget").onclick = async () => { await api.post("/api/control", {budget: (S.ST ? S.ST.budget : 10) + 5}); pollStatus(); toast("Spending cap raised by $5"); };
    $("m-quit").onclick = async () => {
      if (!confirm("Save this game and go back to the start screen? You can resume it later.")) return;
      $("m-quit").disabled = true; $("m-quit").textContent = "Saving…";
      await api.post("/api/end"); location.reload();
    };
  }

  function updateChat(){
    const log = $("chatlog"); if (!log || !S.OBS) return;
    const lines = S.OBS.chat || [];
    const atBottom = log.scrollHeight - log.scrollTop - log.clientHeight < 40;
    log.innerHTML = lines.slice(-60).map(l => {
      const m = l.match(/^(\d+:\d+) \[([^\]]+)\] ([^:]+?)(?: \(([A-Z]\d+)\))?: ([\s\S]*)$/);
      if (!m) return `<div>${esc(l)}</div>`;
      const [, t, ch, who, , text] = m;
      return `<div><span class="dim">${esc(t)}</span> <b>${esc(short(who))}</b>${ch !== "world" ? ` <span class="dim">(${esc(ch)})</span>` : ""}: ${esc(text)}</div>`;
    }).join("") || `<div class="empty">Nobody has said anything yet.</div>`;
    if (atBottom) log.scrollTop = 1e6;
    seen.chat = lines.length; badges();
  }
  function wireChat(){
    const to = $("say-to");
    to.innerHTML = `<option value="">Everyone</option>` + S.BOARD.agents.map(a => `<option value="${esc(a.id)}">${esc(short(a.name))}</option>`).join("");
    updateChat(); $("chatlog").scrollTop = 1e6;
    const send = async () => {
      const text = $("say").value.trim(); if (!text) return;
      const r = to.value ? await act("send_direct_message", {target_id: to.value, text}) : await act("post_world_chat", {text});
      if (r.ok) $("say").value = "";
    };
    $("say-send").onclick = send;
    $("say").addEventListener("keydown", e => { if (e.key === "Enter") send(); });
    $("say").focus();
  }

  /* ---------------------------------------------------------- forms, from each action's schema */
  function businessesList(){
    const out = [], seenIds = new Set();
    const add = (id, label) => { if (id && !seenIds.has(id)){ seenIds.add(id); out.push([id, label]); } };
    for (const b of S.OBS.you.businesses || []) add(b.id, `${b.type} (yours, ${b.location})`);
    for (const b of (S.OBS.here || {}).businesses || []) add(b.id, `${b.type} here (${short(nameOf(b.owner))})`);
    for (const v of S.buildings.values()) add(v.b.id, `${v.b.type}, ${v.b.place} (${v.b.owner === G.you ? "yours" : short(nameOf(v.b.owner))})`);
    return out;
  }
  const people = () => S.BOARD.agents.map(a => [a.id, short(a.name)]);
  const LISTS = {
    business_id: businessesList, seller_business_id: businessesList, to_business_id: businessesList,
    my_business_id: () => (S.OBS.you.businesses || []).map(b => [b.id, `${b.type} (${b.location})`]),
    agent_id: people, target_id: people, applicant_id: people,
    destination: () => S.BOARD.places.map(p => [p.name, `${p.name} (${p.city_name})`]),
    item: () => S.BOARD.items.map(i => [i, i]), output: () => S.BOARD.items.map(i => [i, i]),
    type: () => S.BOARD.business_types.map(t => [t.name, `${t.name} — ${t.cost}`]),
    vehicle_type: () => VEHICLES.map(v => [v, v]),
    vehicle_id: () => (S.ST.vehicles || []).map(v => [v.id, `${v.type} at ${v.location}`]),
    consignment_id: () => S.BOARD.hauls.map(c => [c.id, `${c.qty} ${c.item}: ${c.from} → ${c.to}`]),
    posting_id: () => S.BOARD.jobs.map(j => [j.id, `${j.role} at ${short(j.business)}, ${j.wage}/hr`]),
    plot_id: () => [...S.BOARD.my_land.map(l => [l.id, `${l.id} at ${l.at} (yours)`]), ...S.BOARD.listed_land.map(l => [l.id, `${l.id} at ${l.at}, ${l.price}`])],
    segment: () => S.BOARD.segments.map(s => [s, s]),
  };
  /* Which goods make sense in this form, from the business it is about:
     what it makes, takes in, holds, or has for sale -- or what you carry.
     null means no narrowing. */
  function itemsFor(action, param, pre){
    if (param !== "item" && param !== "output") return null;
    const BI = (S.BOARD && S.BOARD.biz_items) || {};
    const of = id => BI[id] || {makes: [], uses: [], holds: [], priced: []};
    const carried = Object.keys((S.OBS && S.OBS.you && S.OBS.you.carrying) || {});
    const biz = pre.business_id || pre.my_business_id;
    if (action === "set_production") return biz ? of(biz).makes : null;
    if (action === "order_from_business"){
      if (pre.seller_business_id && biz) return of(biz).uses.filter(i => of(pre.seller_business_id).holds.includes(i));
      return biz ? of(biz).uses : null;
    }
    if (action === "post_buy_order") return biz ? of(biz).uses : null;
    if (action === "buy_from_business") return biz ? of(biz).priced : null;
    if (action === "set_retail_price") return biz ? [...new Set([...of(biz).makes, ...of(biz).holds])] : null;
    if (["collect_business_inventory", "post_delivery_job"].includes(action)) return biz ? of(biz).holds : null;
    if (["stock_business_inventory", "sell_to_business", "offer_trade", "stash_in_safehouse"].includes(action)) return carried;
    return null;
  }
  function openForm(action, prefill, title){
    const t = TOOLS[action];
    if (!t){ toast(`No such action: ${action}`, "bad"); return; }
    const back = view;
    view = {kind: "form", ref: action, back};
    const props = t.parameters.properties || {}, req = new Set(t.parameters.required || []);
    let html = `<button class="back" id="f-back">← Back</button><form class="form" id="f" autocomplete="off"><div class="desc">${esc(t.description || "")}</div>`;
    for (const [k, p] of Object.entries(props)){
      if (k === "why") continue;
      const v = prefill[k] !== undefined ? prefill[k] : "";
      const label = k.replace(/_id$/, "").replace(/_/g, " ") + (req.has(k) ? "" : " (optional)");
      let opts = p.enum ? p.enum.map(x => [x, x]) : LISTS[k] ? LISTS[k]() : null;
      const only = itemsFor(action, k, prefill);
      if (opts && only) opts = opts.filter(([val]) => only.includes(val));
      if (p.type === "boolean"){
        html += `<label><input type="checkbox" name="${esc(k)}" data-type="boolean" style="width:auto"${v ? " checked" : ""}> ${esc(label)}</label>`;
      } else if (opts && opts.length){
        const has = opts.some(([val]) => String(val) === String(v));
        html += `<label>${esc(label)}</label><select name="${esc(k)}" data-type="${esc(p.type)}">`
          + (req.has(k) && has ? "" : `<option value="">${req.has(k) ? "choose…" : "—"}</option>`)
          + (v !== "" && !has ? `<option value="${esc(v)}" selected>${esc(v)}</option>` : "")
          + opts.map(([val, lab]) => `<option value="${esc(val)}"${String(val) === String(v) ? " selected" : ""}>${esc(lab)}</option>`).join("") + `</select>`;
      } else {
        const num = p.type === "number" || p.type === "integer";
        html += `<label>${esc(label)}</label><input name="${esc(k)}" data-type="${esc(p.type)}" ${num ? `type="number" step="${p.type === "integer" ? 1 : "any"}" min="0"` : ""} value="${esc(v)}">`;
      }
    }
    html += `<div class="acts" style="margin-top:12px"><button class="btn go" type="submit">Do it</button></div></form>`;
    $("p-title").textContent = title ? title.charAt(0).toUpperCase() + title.slice(1) : action.replace(/_/g, " ");
    $("pbody").innerHTML = html;
    $("panel").classList.add("open");
    const goBack = () => { view = back; if (view) renderView(true); else close(); };
    $("f-back").onclick = goBack;
    $("f").onsubmit = async e => {
      e.preventDefault();
      const args = {};
      for (const el of $("f").querySelectorAll("[name]")){
        const ty = el.dataset.type;
        if (ty === "boolean"){ if (el.checked) args[el.name] = true; continue; }
        if (el.value === "") continue;
        args[el.name] = ty === "integer" ? parseInt(el.value, 10) : ty === "number" ? parseFloat(el.value) : el.value;
      }
      const r = await act(action, args);
      if (r.ok) goBack();
    };
    const first = [...$("f").querySelectorAll("input,select")].find(i => !i.value && i.type !== "checkbox");
    if (first) first.focus();
  }

  /* ---------------------------------------------------------- the advisors */
  let lastReportDay = null;
  function moveButton(m, i){
    return `<button class="btn go" data-move="${i}">${esc(m.button.label)}</button>`;
  }
  function runMove(m){
    const b = m.button;
    if (b.kind === "act") act(b.action, b.args);
    else if (b.kind === "form") openForm(b.action, b.args || {}, m.text);
    else if (b.kind === "walk"){ walkToPlace(b.place); toast(`Walking to ${b.place}`); }
    else if (b.kind === "building"){
      const v = S.buildings.get(b.id);
      if (v && atPlace(v.b.place)) openBuilding(b.id);
      else { walkToBuilding(b.id, () => openBuilding(b.id)); toast("On your way"); }
    }
    else if (b.kind === "tab") openTab(b.tab);
    else if (b.kind === "place") ctx.startPlacing(b.type);
    else if (b.kind === "me") openMe();
    else if (b.kind === "fetch") fetchIt({consignment_id: b.consignment_id});
    else if (b.kind === "mission") missionAct(b.mission_action, b.mission_id);
  }
  function renderAdvisor(){
    const A = S.ADV; if (!A || !A.advice || !A.goals) return;   // no game loaded, or a server error
    $("nm-body").innerHTML = A.advice.map((m, i) => `<div class="move"><div class="t">${esc(short(m.text))}</div><div class="w">${esc(m.why)}</div>${moveButton(m, i)}</div>`).join("");
    $("nm-body").querySelectorAll("[data-move]").forEach(b => b.onclick = () => runMove(A.advice[+b.dataset.move]));
    const done = A.goals.filter(g => g.done).length, next = A.goals.findIndex(g => !g.done);
    $("g-count").textContent = `${done} of ${A.goals.length}`;
    $("goals").style.display = done === A.goals.length ? "none" : "";
    // The goal to do now, with how; the two after it; nothing already done.
    const shown = A.goals.map((g, i) => [g, i]).filter(([g, i]) => !g.done && i >= next && i < next + 3);
    $("g-body").innerHTML = shown.map(([g, i]) => `<div class="goal${i === next ? " next" : ""}"><i></i><span>${esc(g.goal)}${i === next ? `<span class="how">${esc(g.how)}</span>` : ""}</span></div>`).join("");
    // The top bar's arrows: what moved in the last hour.
    const k = A.kpi, d = (v, el, rank) => {
      const box = $(el); if (!box) return;
      let span = box.parentElement.querySelector(".delta");
      if (!span){ span = document.createElement("span"); span.className = "delta"; box.after(span); }
      if (v == null || Math.abs(v) < (rank ? 1 : 0.5)){ span.textContent = ""; return; }
      const up = v > 0;
      span.className = `delta ${up ? "up" : "down"}`;
      span.textContent = rank ? `${up ? "\u25b2" : "\u25bc"}${Math.abs(v)}` : `${up ? "+" : ""}${money(v)}${el === "t-worth" ? "/h" : ""}`;
    };
    d(k.cash_change_1h, "t-cash");
    d(k.worth_per_hour, "t-worth");
    d(k.rank_change_1h, "t-rank", true);
    // A new day: the report opens by itself, once.
    if (A.report && A.report.day !== lastReportDay){
      const first = lastReportDay === null;
      lastReportDay = A.report.day;
      if (!first && !view){ view = {kind: "report", ref: A.report}; renderView(true); }
    }
  }
  async function pollAdvisor(){
    try { S.ADV = await api.get("/api/advisor"); } catch (e) { return; }
    renderAdvisor();
    renderBoard();
  }
  /* THE RACE, always in view: the top five, you wherever you are, and the
     person directly above you -- the one to catch. */
  const CITY_COLOUR = ["#e9d18c", "#7ab6e8", "#8fcf6a"];
  function renderBoard(){
    const L = S.ADV && S.ADV.leaders; if (!L) return;
    const mv = r => r.moved ? `<span class="mv ${r.moved > 0 ? "c-good" : "c-bad"}">${r.moved > 0 ? "\u25b2" : "\u25bc"}${Math.abs(r.moved)}</span>`
      : `<span class="mv"></span>`;
    const T = (S.ADV && S.ADV.titles) || {};
    const ttl = r => (T[r.id] || []).length ? `<span class="ttl" title="${esc(T[r.id].join(", "))}">\u265B${T[r.id].length > 1 ? T[r.id].length : ""}</span>` : "";
    const line = r => `<div class="lb-row${r.you ? " you" : ""}" data-assets="${esc(r.id)}" title="See what they own"><span class="r">${r.rank}</span><span class="n">${r.you ? "You" : esc(short(r.name))}${ttl(r)}</span><span class="w">${money(r.worth)}</span>${mv(r)}</div>`;
    let rows = L.top.map(line).join("");
    if (!L.top.some(r => r.you)) rows += `<div class="lb-gap">\u22ee</div>` + line(L.you);
    $("lb-rows").innerHTML = rows;
    $("lb-sub").textContent = `you #${L.you.rank} of ${L.population}`;
    $("lb-chase").innerHTML = L.chasing
      ? `Next to catch: <b>${esc(short(L.chasing.name))}</b>, ${money(L.chasing.gap)} ahead`
      : L.chased_by ? `<span class="c-good">You lead.</span> <b>${esc(short(L.chased_by.name))}</b> is ${money(L.chased_by.gap)} behind` : "";
    if (L.cities.length > 1){
      const total = L.cities.reduce((a, c) => a + Math.max(1, c.total), 0);
      $("lb-cities").innerHTML = L.cities.map((c, i) => `<span style="width:${100 * Math.max(1, c.total) / total}%;background:${CITY_COLOUR[i % 3]}" title="${esc(c.name)}: ${money(c.total)}">${esc(c.name)}</span>`).join("");
      $("lb-cities").style.display = "flex";
    } else $("lb-cities").style.display = "none";
  }
  $("lboard").onclick = e => {
    const row = e.target.closest("[data-assets]");
    if (row) openAssets(row.dataset.assets); else openTab("ranks");
  };
  $("portrait").onclick = () => openMe();
  $("t-foodbox").onclick = () => openMe();
  $("t-foodbox").title = "Food: where to eat (taverns), and eat what you carry";
  $("portrait").title = "You: health, food, eat";
  $("nm-hide").onclick = () => $("nextmove").classList.toggle("collapsed");
  $("g-hide").onclick = () => $("goals").classList.toggle("collapsed");

  /* ---------------------------------------------------------- start */
  async function boot(){
    const t = await api.get("/api/tools");
    for (const tool of t.tools) TOOLS[tool.name] = tool;
    await Promise.all([pollStatus(), pollBoard(), pollState()]);
    await pollFeed();
    seen.news = FEED.length; seen.chat = (S.OBS && S.OBS.chat || []).length; badges();
    setInterval(pollStatus, 1500);
    setInterval(pollState, 3000);
    setInterval(pollBoard, 5000);
    setInterval(pollFeed, 2000);
    await pollAdvisor();
    setInterval(pollAdvisor, 3000);
    // The guide opens itself the first time you play each game.
    const key = `convoy.guided.${(S.ST && S.ST.game) || ""}`;
    let seenGuide = false;
    try { seenGuide = !!localStorage.getItem(key); localStorage.setItem(key, "1"); } catch (e) {}
    if (!seenGuide) setTimeout(() => openGuide(0), 1200);
  }

  /* ---------------------------------------------------------- the build menu */
  /* Every kind of business, its cost and where it goes; click one and place
     its hologram on the map (main.js). Greyed when you cannot afford it. */
  const BUILD_ICON = {"Farm": "\u{1F33E}", "Mining Operation": "\u26CF\uFE0F", "Refinery": "\u{1F3ED}", "Tavern / Inn": "\u{1F372}",
    "Vehicle Dealer / Stable": "\u{1F40E}", "Weaponsmith / Armory": "\u2694\uFE0F", "Home Improvement Store": "\u{1F528}",
    "Mining/Farming Equipment Store": "\u{1F527}", "Private Security Contractor": "\u{1F4BC}",
    "Guard post": "\u{1F6E1}\uFE0F", "Catapult": "\u{1FAA8}", "Land claim": "\u{1F6A9}"};
  let placingType = null;
  function renderBuildBar(){
    if (!S.BOARD) return;
    const cash = S.ST ? S.ST.you.denari : 0;
    const owned = {};
    for (const v of S.buildings.values()) if (v.b.owner === G.you) owned[v.b.type] = (owned[v.b.type] || 0) + 1;
    for (const o of (S.cellOwner ? S.cellOwner.values() : [])) if (o.structure && o.owner === G.you) owned[o.structure] = (owned[o.structure] || 0) + 1;
    const html = S.BOARD.business_types.map(t => {
      const can = cash >= t.cost;
      const tip = t.defense ? `${t.name}: one square, anywhere. ${t.does}` : t.claim ? `${t.name}: ${t.does}`
        : `${t.name}: makes ${t.makes.slice(0, 5).join(", ")}. ${S.ST && S.ST.you.outposts ? "On open land you claim as you build: the land is extra, priced on the map." : t.spur ? "Spur land (farms and mines)." : "Main road."}`;
      return `<button class="bb${can ? "" : " poor"}${placingType === t.name ? " on" : ""}${t.defense ? " def" : ""}" data-build="${esc(t.name)}"
        title="${esc(tip)}">
        <span class="ic">${BUILD_ICON[t.name] || "\u{1F3E0}"}</span>
        <span class="nm">${esc(t.name.split(" /")[0].replace("Mining/Farming Equipment Store", "Equipment").replace("Private Security Contractor", "Security firm").replace("Home Improvement Store", "Builder").replace("Mining Operation", "Mine"))}</span>
        <span class="cost">${t.from ? "from " : ""}${money(t.cost)}</span>${owned[t.name] ? `<i class="own">${owned[t.name]}</i>` : ""}
      </button>`;
    }).join("");
    const box = $("bb-items");
    if (box.dataset.html === html) return;
    box.dataset.html = html; box.innerHTML = html;
    box.querySelectorAll("[data-build]").forEach(b => b.onclick = () => {
      if (placingType === b.dataset.build){ ctx.stopPlacing(); return; }
      ctx.startPlacing(b.dataset.build);
    });
  }
  setInterval(renderBuildBar, 1000);
  function placingChanged(type){ placingType = type; $("bb-items").dataset.html = ""; renderBuildBar(); }

  /* ---------------------------------------------------------- picked squares */
  function selectionChanged(sel){
    const bar = $("selbar");
    if (!sel){ bar.style.display = "none"; return; }
    const n = sel.cells.length, place = S.places[sel.place] || {}, spur = place.kind === "spur";
    const price = S.BOARD ? S.BOARD.land_price : 100;
    let html = `<div class="sel-h"><b>${n} square${n > 1 ? "s" : ""}</b> at ${esc(sel.place)}`
      + `<span class="dim"> \u00b7 ${spur ? "farm & mine land" : "main road: shops & workshops"}</span></div><div class="acts">`;
    if (sel.block){
      const types = (S.BOARD ? S.BOARD.business_types : []).filter(t => t.spur === spur);
      html += types.map(t => `<button class="btn go" data-found="${esc(t.name)}">Build ${esc(t.name.split(" /")[0])} \u00b7 ${money(t.cost)}</button>`).join("");
    } else if (n < 4){
      html += `<span class="tip">Pick ${4 - n} more in a square to build a business here.</span>`;
    } else {
      html += `<span class="tip">A business needs four squares in a 2\u00d72 block.</span>`;
    }
    html += `<button class="btn" data-buyland="1">Buy ${n === 1 ? "this plot" : `these ${n} plots`} \u00b7 ${money(price * n)}</button>`
      + `<button class="btn ghost" data-clearsel="1">Clear</button></div>`;
    bar.innerHTML = html; bar.style.display = "block";
    bar.querySelectorAll("[data-found]").forEach(b => b.onclick = () => ctx.foundOn(sel.place, sel.cells, b.dataset.found));
    bar.querySelector("[data-buyland]").onclick = () => ctx.buyOn(sel.place, sel.cells);
    bar.querySelector("[data-clearsel]").onclick = () => ctx.clearSelection();
  }

  const api3 = {boot, act, toast, openTab, openBuilding, openPerson, openLand, openForm, close, refreshSoon,
    cameraChanged: () => renderUnit(), selectionChanged, placingChanged};
  window.convoyUI = api3;
  return api3;
}
