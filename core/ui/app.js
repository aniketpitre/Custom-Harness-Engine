/* Harness dashboard: a dependency-free client for the control-plane API.
 * Everything the agent produced is untrusted text: it is only ever inserted through esc() / textContent. */
(() => {
  "use strict";
  const TOKEN_KEY = "harness.token";
  const THEME_KEY = "harness.theme";
  const $ = (sel, root = document) => root.querySelector(sel);
  const view = $("#view");
  let timers = [];

  // -- utilities ------------------------------------------------------------------------------
  const esc = (v) => String(v ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  const money = (v) => (v === null || v === undefined) ? "n/a" : v === 0 ? "$0" : v < 1 ? `$${v.toFixed(4)}` : `$${v.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
  const num = (v) => (v || 0).toLocaleString();
  const ago = (iso) => {
    if (!iso) return "";
    const s = (Date.now() - new Date(iso).getTime()) / 1000;
    if (s < 60) return `${Math.max(0, Math.round(s))}s ago`;
    if (s < 3600) return `${Math.round(s / 60)}m ago`;
    if (s < 86400) return `${Math.round(s / 3600)}h ago`;
    return new Date(iso).toLocaleDateString();
  };
  const every = (fn, ms) => { fn(); timers.push(setInterval(fn, ms)); };
  const clearTimers = () => { timers.forEach(clearInterval); timers = []; };
  function toast(msg) {
    const t = document.createElement("div");
    t.className = "toast"; t.setAttribute("role", "status"); t.textContent = msg;
    document.body.appendChild(t); setTimeout(() => t.remove(), 3500);
  }

  // status -> icon + label (never colour alone)
  function statusBadge(s) {
    if (s.active || s.status === "running") return `<span class="badge live">running</span>`;
    const map = { success: "good", failure: "critical", pending: "", blocked: "warning" };
    const label = s.outcome && s.outcome !== "completed" ? s.outcome.replace(/_/g, " ") : s.status;
    const cls = s.outcome && ["budget_exhausted", "turn_limit", "time_limit"].includes(s.outcome) ? "warning" : (map[s.status] ?? "");
    return `<span class="badge ${cls}">${esc(label)}</span>`;
  }
  const tierClass = { R0: "", R1: "", R2: "warning", R3: "serious", R4: "critical" };
  const decisionBadge = (d) => `<span class="badge ${d === "DENY" ? "critical" : d === "REQUIRE_APPROVAL" ? "warning" : "good"}">${esc(d)}</span>`;

  // -- API ------------------------------------------------------------------------------------
  const token = () => sessionStorage.getItem(TOKEN_KEY) || localStorage.getItem(TOKEN_KEY) || "";
  async function api(path, opts = {}) {
    const res = await fetch(path, {
      method: opts.method || "GET",
      headers: { Authorization: `Bearer ${token()}`, ...(opts.body ? { "Content-Type": "application/json" } : {}) },
      body: opts.body ? JSON.stringify(opts.body) : undefined,
    });
    if (res.status === 401) { signOut($("#app").hidden ? "That token was not accepted." : "Your session ended or the token was revoked. Sign in again."); throw new Error("unauthorised"); }
    const data = await res.json().catch(() => ({}));
    if (!res.ok) { const e = new Error(data.detail || `${res.status}`); e.status = res.status; throw e; }
    return data;
  }

  // -- auth -----------------------------------------------------------------------------------
  function signOut(msg) {
    sessionStorage.removeItem(TOKEN_KEY); localStorage.removeItem(TOKEN_KEY);
    clearTimers();
    $("#app").hidden = true; $("#login").hidden = false;
    $("#login-error").textContent = msg || "";
    $("#token").focus();
  }
  async function signIn(tok, remember) {
    sessionStorage.setItem(TOKEN_KEY, tok);
    if (remember) localStorage.setItem(TOKEN_KEY, tok);
    try { await api("/sessions?limit=1"); }
    catch (e) { if (e.message !== "unauthorised") signOut(`Could not connect: ${e.message}`); return; }
    $("#login").hidden = true; $("#app").hidden = false;
    route();
  }
  $("#login-form").addEventListener("submit", (e) => {
    e.preventDefault(); signIn($("#token").value.trim(), $("#remember").checked);
  });
  $("#logout").addEventListener("click", () => signOut());

  // -- theme ----------------------------------------------------------------------------------
  function applyTheme(t) {
    if (t === "auto") document.documentElement.removeAttribute("data-theme");
    else document.documentElement.setAttribute("data-theme", t);
    $("#theme-toggle").textContent = `Theme: ${t}`;
  }
  let theme = (() => { try { return localStorage.getItem(THEME_KEY) || "auto"; } catch { return "auto"; } })();
  applyTheme(theme);
  $("#theme-toggle").addEventListener("click", () => {
    theme = { auto: "light", light: "dark", dark: "auto" }[theme];
    try { localStorage.setItem(THEME_KEY, theme); } catch { /* private mode */ }
    applyTheme(theme);
  });

  // -- tooltip --------------------------------------------------------------------------------
  const tip = $("#tip");
  document.addEventListener("mousemove", (e) => {
    const t = e.target.closest?.("[data-tip]");
    if (!t) { tip.hidden = true; return; }
    tip.textContent = t.getAttribute("data-tip"); tip.hidden = false;
    const x = Math.min(e.clientX + 12, window.innerWidth - tip.offsetWidth - 8);
    tip.style.left = `${x}px`; tip.style.top = `${e.clientY + 14}px`;
  });

  // -- router ---------------------------------------------------------------------------------
  const routes = { overview, sessions, session, run, approvals, usage, schedules, skills, agents, plugins };
  async function route() {
    if ($("#app").hidden || location.hash.startsWith("#token=")) return;
    clearTimers();
    const [, name = "overview", arg] = (location.hash || "#/overview").split("/");
    document.querySelectorAll("#nav a").forEach((a) => a.classList.toggle("active", a.dataset.route === name || (name === "session" && a.dataset.route === "sessions")));
    const fn = routes[name] || overview;
    view.innerHTML = `<p class="muted">Loading…</p>`;
    try { await fn(arg && decodeURIComponent(arg)); }
    catch (e) { if (e.message !== "unauthorised") view.innerHTML = `<div class="card error">${esc(e.status === 403 ? "This token lacks the scope for this page." : e.message)}</div>`; }
    view.focus({ preventScroll: true });
  }
  window.addEventListener("hashchange", route);

  // background: connection + approvals badge
  async function heartbeat() {
    if ($("#app").hidden) return;
    try {
      const pend = await api("/approvals");
      const c = $("#approval-count");
      c.hidden = !pend.length; c.textContent = pend.length;
      $("#conn").textContent = "connected";
    } catch (e) { $("#conn").textContent = e.status === 403 ? "connected" : "offline"; }
  }
  setInterval(heartbeat, 4000);

  // -- charts ---------------------------------------------------------------------------------
  // Charts are drawn at the host's real pixel width (no stretched text) and redrawn on resize.
  const charts = new Map();
  function chartHost(rows, opts) {
    const id = `c${Math.random().toString(36).slice(2)}`;
    charts.set(id, [rows, opts]);
    requestAnimationFrame(drawCharts);
    return `<div class="chart-host" id="${id}"></div>`;
  }
  function drawCharts() {
    for (const [id, [rows, opts]] of charts) {
      const el = document.getElementById(id);
      if (!el) { charts.delete(id); continue; }
      el.innerHTML = barChart(rows, { ...opts, width: Math.max(el.clientWidth, 260) });
    }
  }
  window.addEventListener("resize", () => requestAnimationFrame(drawCharts));
  function barChart(rows, { valueFmt = money, label = (r) => r.key, width = 640 } = {}) {
    if (!rows.length) return `<div class="empty">No data yet</div>`;
    const W = width, H = 220, L = 58, B = 26, T = 10, R = 8;
    const max = Math.max(...rows.map((r) => r.value)) || 1;
    const nice = (() => { const p = 10 ** Math.floor(Math.log10(max)); return Math.ceil(max / p) * p; })();
    const bw = (W - L - R) / rows.length;
    const y = (v) => T + (H - T - B) * (1 - v / nice);
    let g = "";
    for (let i = 0; i <= 4; i++) {
      const v = (nice * i) / 4, yy = y(v);
      g += `<line class="${i ? "gridline" : "baseline"}" x1="${L}" x2="${W - R}" y1="${yy}" y2="${yy}"/>`;
      g += `<text class="tick" x="${L - 6}" y="${yy + 4}" text-anchor="end">${esc(valueFmt(v))}</text>`;
    }
    const step = Math.ceil(rows.length / Math.max(2, Math.floor((W - L) / 64)));
    rows.forEach((r, i) => {
      const x = L + i * bw, w = Math.max(bw - 2, 1), top = y(r.value), h = Math.max(H - B - top, r.value > 0 ? 1 : 0);
      const rad = Math.min(4, w / 2, h);
      // rounded data-end anchored to the baseline
      const path = h > 0 ? `M${x},${H - B} V${top + rad} Q${x},${top} ${x + rad},${top} H${x + w - rad} Q${x + w},${top} ${x + w},${top + rad} V${H - B} Z` : "";
      g += `<rect class="hit" x="${x}" y="${T}" width="${bw}" height="${H - B - T}" data-tip="${esc(label(r))}: ${esc(valueFmt(r.value))}"/>`;
      if (path) g += `<path class="bar" d="${path}" pointer-events="none"/>`;
      if (i % step === 0) g += `<text class="tick" x="${x + bw / 2}" y="${H - 8}" text-anchor="middle">${esc(label(r).slice(5))}</text>`;
    });
    return `<svg class="chart" viewBox="0 0 ${W} ${H}" role="img" aria-label="bar chart">${g}</svg>`;
  }
  function hbars(rows, fmtv = money) {
    if (!rows.length) return `<div class="empty">No data yet</div>`;
    const max = Math.max(...rows.map((r) => r.value)) || 1;
    return rows.map((r) => `<div class="hbar"><span class="name" title="${esc(r.key)}">${esc(r.key)}</span>
      <span class="track" data-tip="${esc(r.key)}: ${esc(fmtv(r.value))}"><span class="fill" style="width:${(100 * r.value / max).toFixed(1)}%"></span></span>
      <span class="num mono">${esc(fmtv(r.value))}</span></div>`).join("");
  }
  function lastDays(rows, days) {
    const byDay = Object.fromEntries(rows.map((r) => [r.key, r.cost_usd]));
    const out = [];
    for (let i = days - 1; i >= 0; i--) {
      const d = new Date(Date.now() - i * 86400000).toISOString().slice(0, 10);
      out.push({ key: d, value: byDay[d] || 0 });
    }
    return out;
  }

  // -- views ----------------------------------------------------------------------------------
  function sessionsTable(rows, empty = "No sessions yet. Start one from New run.") {
    if (!rows.length) return `<div class="empty">${esc(empty)}</div>`;
    return `<div class="tw"><table><thead><tr><th>Status</th><th>Goal</th><th class="hide-sm">Agent</th><th class="num">Cost</th><th class="hide-sm">Updated</th></tr></thead><tbody>
      ${rows.map((s) => `<tr class="link" data-href="#/session/${encodeURIComponent(s.id)}"><td>${statusBadge(s)}</td>
        <td class="goal" title="${esc(s.goal)}">${esc(s.goal)}</td><td class="hide-sm">${esc(s.agent_id)}</td>
        <td class="num">${money(s.cost_usd)}</td><td class="hide-sm muted">${esc(ago(s.updated_at))}</td></tr>`).join("")}
    </tbody></table></div>`;
  }
  view.addEventListener("click", (e) => {
    const tr = e.target.closest("tr[data-href]");
    if (tr && !e.target.closest("a,button")) location.hash = tr.dataset.href;
  });

  async function overview() {
    const [recent, byDay, pend] = await Promise.all([
      api("/sessions?limit=100"), api("/usage?days=30&by=day"), api("/approvals").catch(() => []),
    ]);
    const day = Date.now() - 86400000;
    const last24 = recent.filter((s) => new Date(s.updated_at).getTime() > day);
    const done = recent.filter((s) => ["success", "failure"].includes(s.status));
    const rate = done.length ? Math.round((100 * done.filter((s) => s.status === "success").length) / done.length) : null;
    const running = recent.filter((s) => s.active || s.status === "running").length;
    view.innerHTML = `
      <div class="head"><div><h1>Overview</h1><div class="muted">Policy-gated agent runs, spend and approvals</div></div>
        <a class="button primary" href="#/run">New run</a></div>
      <div class="grid tiles">
        <div class="card tile"><div class="label">Running now</div><div class="value">${running}</div><div class="sub">${last24.length} sessions in 24h</div></div>
        <div class="card tile"><div class="label">Success rate</div><div class="value">${rate === null ? "n/a" : rate + "%"}</div><div class="sub">last ${done.length} finished runs</div></div>
        <div class="card tile"><div class="label">Spend, 30 days</div><div class="value">${money(byDay.total_cost_usd)}</div><div class="sub">${num(byDay.total_tokens)} tokens${byDay.unpriced_calls ? ` · ${byDay.unpriced_calls} unpriced` : ""}</div></div>
        <div class="card tile"><div class="label">Pending approvals</div><div class="value">${pend.length}</div><div class="sub"><a href="#/approvals">review</a></div></div>
      </div>
      <div class="grid cols">
        <div class="card"><h2>Daily spend (USD), last 30 days</h2>${chartHost(lastDays(byDay.rows, 30))}</div>
        <div class="card"><h2>Recent sessions</h2>${sessionsTable(recent.slice(0, 8))}</div>
      </div>`;
  }

  async function sessions() {
    view.innerHTML = `<div class="head"><div><h1>Sessions</h1><div class="muted">Every run is a durable, hash-chained event log</div></div></div>
      <div class="filters"><select id="f-status" aria-label="Status"><option value="">Any status</option><option>running</option><option>success</option><option>failure</option><option>pending</option></select>
      <select id="f-agent" aria-label="Agent"><option value="">Any agent</option></select>
      <label class="check"><input id="f-children" type="checkbox"> include subagents</label></div>
      <div class="card" id="s-table"></div>`;
    const agentsList = await api("/agents").catch(() => []);
    $("#f-agent").insertAdjacentHTML("beforeend", agentsList.map((a) => `<option>${esc(a.id)}</option>`).join(""));
    const load = async () => {
      const q = new URLSearchParams({ limit: "200" });
      if ($("#f-status").value) q.set("status", $("#f-status").value);
      if ($("#f-agent").value) q.set("agent_id", $("#f-agent").value);
      if ($("#f-children").checked) q.set("include_children", "true");
      $("#s-table").innerHTML = sessionsTable(await api(`/sessions?${q}`), "No sessions match these filters.");
    };
    ["#f-status", "#f-agent", "#f-children"].forEach((s) => $(s).addEventListener("change", load));
    every(load, 5000);
  }

  function renderEvent(e) {
    const p = e.payload || {}, t = e.type, time = new Date(e.created_at).toLocaleTimeString();
    const meta = (kind, extra = "") => `<div class="meta"><span class="kind">${esc(kind)}</span><span>#${e.seq}</span><span>${esc(time)}</span>${extra}</div>`;
    switch (t) {
      case "user_msg": return `<div class="ev user">${meta("user")}<div class="body">${esc(p.content)}</div></div>`;
      case "assistant_msg": {
        const calls = (p.tool_calls || []).map((c) => `<code>${esc(c.function?.name)}</code> <span class="mono small muted">${esc((c.function?.arguments || "").slice(0, 300))}</span>`).join("<br>");
        return `<div class="ev assistant">${meta("assistant")}${p.content ? `<div class="body">${esc(p.content)}</div>` : ""}${calls ? `<div class="small">${calls}</div>` : ""}</div>`;
      }
      case "action": {
        const d = p.policy_decision || {};
        return `<div class="ev action ${d.decision === "DENY" ? "denied" : ""}">${meta("action", `${decisionBadge(d.decision)} <span class="tier badge ${tierClass[d.risk_tier] || ""}">${esc(d.risk_tier)}</span>${p.approved_by ? `<span>approved by ${esc(p.approved_by)}</span>` : ""}`)}
          <div><b>${esc(p.tool)}</b> · ${esc(p.action)} <span class="muted small">${esc(d.reason)}</span></div>
          <details><summary>result</summary><pre>${esc(p.raw_result)}</pre></details></div>`;
      }
      case "tool_result": return `<div class="ev">${meta("tool result", p.is_error ? `<span class="badge critical">error</span>` : "")}<details><summary>${esc((p.content || "").slice(0, 140))}</summary><pre>${esc(p.content)}</pre></details></div>`;
      case "llm_call": return `<div class="ev">${meta("model call", `<span class="mono">${esc(p.model)}</span><span>${num(p.prompt_tokens)} in / ${num(p.completion_tokens)} out</span><span>${money(p.cost_usd)}</span>`)}</div>`;
      case "mode_change": return `<div class="ev">${meta("mode", `<span>${esc(p.from)} → <b>${esc(p.to)}</b></span><span>by ${esc(p.approved_by)}</span>`)}${p.plan ? `<details><summary>approved plan</summary><pre>${esc(p.plan)}</pre></details>` : ""}</div>`;
      case "verification": return `<div class="ev">${meta("verification", `<span class="badge ${p.passed ? "good" : "critical"}">${p.passed ? "passed" : "failed"}</span>`)}<div class="body small">${esc(p.reason || p.details || "")}</div></div>`;
      case "outcome": return `<div class="ev">${meta("outcome", `<span class="badge ${p.outcome === "completed" ? "good" : "critical"}">${esc(p.outcome)}</span>`)}${p.error ? `<div class="body small error">${esc(p.error)}</div>` : ""}</div>`;
      case "run_start": return `<div class="ev">${meta("run start", `<span class="mono">${esc(p.model)}</span><span>mode ${esc(p.mode || "default")}</span><span>${(p.tools || []).length} tools</span>`)}</div>`;
      case "compaction": return `<div class="ev">${meta("compaction")}<div class="body small muted">${p.summary ? "History summarised to fit the context window" : "Old tool outputs pruned"}</div></div>`;
      default: return `<div class="ev">${meta(t.replace(/_/g, " "))}<details><summary>payload</summary><pre>${esc(JSON.stringify(p, null, 2))}</pre></details></div>`;
    }
  }

  async function session(id) {
    let s = await api(`/sessions/${encodeURIComponent(id)}`);
    let lastSeq = 0;
    view.innerHTML = `
      <div class="head"><div><div class="small"><a href="#/sessions">← Sessions</a></div><h1 id="s-title"></h1>
        <div class="row" id="s-badges"></div></div>
        <div class="row" id="s-actions"></div></div>
      <div class="grid cols">
        <div class="card"><h2>Timeline</h2><div class="timeline" id="tl"></div></div>
        <div class="grid" style="align-content:start">
          <div class="card"><h2>Summary</h2><dl class="kv" id="s-kv"></dl></div>
          <div id="s-approvals"></div>
          <div class="card" id="s-final" hidden><h2>Final answer</h2><div class="body" id="s-final-text" style="white-space:pre-wrap"></div></div>
          <div class="card" id="s-interrupt" hidden><h2>Steer the run</h2>
            <form id="int-form" class="row"><input id="int-text" placeholder="Note for the agent (delivered next turn)" aria-label="Interrupt note">
            <button class="primary">Send</button></form></div>
        </div>
      </div>`;
    $("#s-title").textContent = s.goal.length > 90 ? s.goal.slice(0, 90) + "…" : s.goal;
    const paint = () => {
      $("#s-badges").innerHTML = `${statusBadge(s)} <span class="muted small">${esc(s.agent_id)} · mode ${esc(s.permission_mode || "default")}</span>`;
      const r = s.run_receipt || {};
      $("#s-kv").innerHTML = [
        ["Session", `<span class="mono">${esc(s.id)}</span>`], ["Outcome", esc(s.outcome || "-")],
        ["Verified", esc(s.verified ?? "n/a")],
        ["Tokens", `${num(s.prompt_tokens ?? liveUsage.in)} in / ${num(s.completion_tokens ?? liveUsage.out)} out`],
        ["Cost", money(s.cost_usd ?? (liveUsage.in ? liveUsage.cost : null))], ["Model", `<span class="mono">${esc(r.model_used || "-")}</span>`],
        ["Chain head", `<span class="mono small">${esc((r.chain_head || "").slice(0, 24))}</span>`],
        ["Created", esc(new Date(s.created_at).toLocaleString())],
        ...(s.parent_session_id ? [["Parent", `<a href="#/session/${encodeURIComponent(s.parent_session_id)}">${esc(s.parent_session_id.slice(0, 8))}</a>`]] : []),
      ].map(([k, v]) => `<dt>${k}</dt><dd>${v}</dd>`).join("");
      if (r.final_text) { $("#s-final").hidden = false; $("#s-final-text").textContent = r.final_text; }
      const live = s.active || s.status === "running";
      $("#s-interrupt").hidden = !live;
      $("#s-actions").innerHTML = `${live ? `<button id="b-cancel" class="danger">Cancel run</button>` : ""}
        ${s.status === "pending" ? `<button id="b-start" class="primary">Start</button>` : ""}
        <button id="b-verify">Verify chain</button><button id="b-fork">Fork</button>`;
      $("#b-cancel")?.addEventListener("click", async () => { await api(`/sessions/${id}/cancel`, { method: "POST" }); toast("Cancel requested"); });
      $("#b-start")?.addEventListener("click", async () => { await api(`/sessions/${id}/run`, { method: "POST" }); refresh(); });
      $("#b-verify").addEventListener("click", async () => {
        const v = await api(`/sessions/${id}/verify-chain`);
        toast(v.ok ? "Event chain intact: no event was altered" : `Chain broken at event #${v.first_bad_seq}`);
      });
      $("#b-fork").addEventListener("click", async () => {
        const f = await api(`/sessions/${id}/fork`, { method: "POST", body: {} });
        location.hash = `#/session/${encodeURIComponent(f.session_id)}`;
      });
    };
    $("#int-form").addEventListener("submit", async (e) => {
      e.preventDefault();
      const text = $("#int-text").value.trim(); if (!text) return;
      await api(`/sessions/${id}/interrupt`, { method: "POST", body: { message: text } });
      $("#int-text").value = ""; toast("Note queued for the next turn");
    });
    const tl = $("#tl");
    const liveUsage = { in: 0, out: 0, cost: 0 };
    wireApprovals($("#s-approvals"));
    const refresh = async () => {
      const evs = await api(`/sessions/${encodeURIComponent(id)}/events?after=${lastSeq}`);
      evs.filter((e) => e.type === "llm_call").forEach((e) => {
        liveUsage.in += e.payload.prompt_tokens || 0; liveUsage.out += e.payload.completion_tokens || 0; liveUsage.cost += e.payload.cost_usd || 0;
      });
      const pend = (await api("/approvals").catch(() => [])).filter((a) => a.session_id === id);
      const box = $("#s-approvals"), shown = [...box.querySelectorAll("[data-id]")].map((n) => n.dataset.id).join();
      if (shown !== pend.map((a) => a.id).join()) box.innerHTML = pend.map((a) => approvalCard(a, false)).join("");
      if (evs.length) {
        if (!lastSeq) tl.innerHTML = "";
        tl.insertAdjacentHTML("beforeend", evs.map(renderEvent).join(""));
        lastSeq = evs[evs.length - 1].seq;
      } else if (!lastSeq) tl.innerHTML = `<div class="empty">No events yet</div>`;
      s = await api(`/sessions/${encodeURIComponent(id)}`);
      paint();
    };
    paint();
    every(refresh, 2000);
  }

  async function run() {
    const agentsList = await api("/agents");
    view.innerHTML = `<div class="head"><div><h1>New run</h1><div class="muted">Start a detached run; watch it live and approve actions as they come</div></div></div>
      <form id="run-form" class="card" style="max-width:760px">
        <label for="r-agent">Agent</label><select id="r-agent">${agentsList.map((a) => `<option value="${esc(a.id)}">${esc(a.id)} · ${esc(a.domain)}</option>`).join("")}</select>
        <label for="r-goal">Goal</label><textarea id="r-goal" required placeholder="e.g. Check why the checkout pods in staging keep restarting"></textarea>
        <label for="r-mode">Permission mode</label>
        <select id="r-mode"><option value="">default: policy table (R2/R3 ask)</option><option value="plan">plan: read-only until you approve the plan</option>
          <option value="read-only">read-only: investigate and report only</option><option value="strict">strict: every change needs approval</option></select>
        <div class="row" style="margin-top:14px"><button class="primary">Start run</button><span id="r-err" class="error"></span></div>
      </form>`;
    $("#run-form").addEventListener("submit", async (e) => {
      e.preventDefault();
      try {
        const body = { agent_id: $("#r-agent").value, goal: $("#r-goal").value.trim(), run: true };
        if ($("#r-mode").value) body.permission_mode = $("#r-mode").value;
        const r = await api("/sessions", { method: "POST", body });
        location.hash = `#/session/${encodeURIComponent(r.session_id)}`;
      } catch (err) { $("#r-err").textContent = err.message; }
    });
  }

  function approvalCard(a, withLink = true) {
    return `<div class="card" data-id="${esc(a.id)}" style="margin-bottom:12px">
      <div class="row"><span class="tier badge ${tierClass[a.risk_tier] || ""}">${esc(a.risk_tier)}</span><b>${esc(a.tool)}</b>
      ${withLink && a.session_id ? `<a class="small" href="#/session/${encodeURIComponent(a.session_id)}">session ${esc(a.session_id.slice(0, 8))}</a>` : ""}</div>
      <pre>${esc(a.rendered)}</pre>
      <div class="row" style="margin-top:10px"><input class="a-note" placeholder="Note (sent to the agent on deny)" aria-label="Note">
      <select class="a-scope" aria-label="Scope"><option value="once">once</option><option value="session">this session</option>${a.risk_tier === "R3" ? "" : `<option value="always">always (these exact arguments)</option>`}</select>
      <button class="primary a-yes">Approve</button><button class="danger a-no">Deny</button></div></div>`;
  }
  function wireApprovals(root, after) {
    root.addEventListener("click", async (e) => {
      const card = e.target.closest("[data-id]"); if (!card) return;
      const approved = e.target.classList.contains("a-yes");
      if (!approved && !e.target.classList.contains("a-no")) return;
      e.target.disabled = true;
      try {
        await api(`/approvals/${encodeURIComponent(card.dataset.id)}`, { method: "POST", body: { approved, scope: $(".a-scope", card).value, note: $(".a-note", card).value || null } });
        toast(approved ? "Approved" : "Denied"); card.remove(); heartbeat(); after && after();
      } catch (err) { e.target.disabled = false; toast(err.message); }
    });
  }

  async function approvals() {
    view.innerHTML = `<div class="head"><div><h1>Approvals</h1><div class="muted">Actions waiting for a human. The first answer from any channel (here, terminal, Telegram) wins</div></div></div><div id="a-list"></div>`;
    const load = async () => {
      const pend = await api("/approvals");
      const list = $("#a-list");
      if (!list) return;
      if (!pend.length) { list.innerHTML = `<div class="card empty">Nothing is waiting for approval.</div>`; return; }
      const open = new Set([...list.querySelectorAll("[data-id]")].map((n) => n.dataset.id));
      if (pend.length === open.size && pend.every((a) => open.has(a.id))) return;   // keep typed notes
      list.innerHTML = pend.map((a) => approvalCard(a)).join("");
    };
    wireApprovals($("#a-list"), () => load());
    every(load, 2500);
  }

  async function usage() {
    view.innerHTML = `<div class="head"><div><h1>Usage &amp; cost</h1><div class="muted">From the model-call events in the log (subagents included)</div></div>
      <div class="seg" role="group" aria-label="Range">${[7, 30, 90].map((d) => `<button data-days="${d}" class="${d === 30 ? "on" : ""}">${d} days</button>`).join("")}</div></div>
      <div id="u-body"></div>`;
    const load = async (days) => {
      const [byDay, byModel, byAgent] = await Promise.all(["day", "model", "agent"].map((by) => api(`/usage?days=${days}&by=${by}`)));
      const rowsFor = (u) => u.rows.map((r) => ({ key: String(r.key), value: r.cost_usd }));
      const table = (u) => `<div class="tw"><table><thead><tr><th>${esc(u.by)}</th><th class="num">Calls</th><th class="num">Input</th><th class="num">Output</th><th class="num">Cost</th></tr></thead><tbody>
        ${u.rows.map((r) => `<tr><td class="mono">${esc(r.key)}</td><td class="num">${num(r.calls)}</td><td class="num">${num(r.prompt_tokens)}</td><td class="num">${num(r.completion_tokens)}</td><td class="num">${money(r.cost_usd)}${r.unpriced_calls ? ` <span class="muted small">+${r.unpriced_calls} unpriced</span>` : ""}</td></tr>`).join("") || `<tr><td colspan="5" class="empty">No model calls</td></tr>`}</tbody></table></div>`;
      $("#u-body").innerHTML = `
        <div class="grid tiles"><div class="card tile"><div class="label">Spend</div><div class="value">${money(byDay.total_cost_usd)}</div><div class="sub">last ${days} days</div></div>
          <div class="card tile"><div class="label">Tokens</div><div class="value">${num(byDay.total_tokens)}</div></div>
          <div class="card tile"><div class="label">Unpriced calls</div><div class="value">${num(byDay.unpriced_calls)}</div><div class="sub">set HARNESS_PRICES for these</div></div></div>
        <div class="card" style="margin-bottom:14px"><h2>Daily spend (USD)</h2>${chartHost(lastDays(byDay.rows, days))}</div>
        <div class="grid cols"><div class="card"><h2>By model</h2>${hbars(rowsFor(byModel))}<details style="margin-top:8px"><summary>table</summary>${table(byModel)}</details></div>
          <div class="card"><h2>By agent</h2>${hbars(rowsFor(byAgent))}<details style="margin-top:8px"><summary>table</summary>${table(byAgent)}</details></div></div>`;
    };
    view.querySelector(".seg").addEventListener("click", (e) => {
      const b = e.target.closest("button[data-days]"); if (!b) return;
      view.querySelectorAll(".seg button").forEach((x) => x.classList.toggle("on", x === b));
      load(Number(b.dataset.days));
    });
    await load(30);
  }

  async function schedules() {
    const [jobs, agentsList] = await Promise.all([api("/cron"), api("/agents").catch(() => [])]);
    view.innerHTML = `<div class="head"><div><h1>Schedules</h1><div class="muted">Persistent cron jobs and heartbeats</div></div></div>
      <div class="card" style="margin-bottom:14px">${jobs.length ? `<table><thead><tr><th>Job</th><th>Schedule</th><th>Agent</th><th>Goal</th><th>Next run</th><th></th></tr></thead><tbody>
        ${jobs.map((j) => `<tr data-job="${esc(j.id)}"><td class="mono small">${esc(String(j.id).slice(0, 12))}</td><td class="mono">${esc(j.cron || (j.interval_minutes ? `every ${j.interval_minutes}m` : j.trigger || ""))}</td>
          <td>${esc(j.agent_id)}</td><td class="goal" title="${esc(j.goal)}">${esc(j.goal)}</td><td class="muted">${j.paused ? `<span class="badge warning">paused</span>` : esc(j.next_run ? new Date(j.next_run).toLocaleString() : "")}</td>
          <td class="row"><button class="j-toggle">${j.paused ? "Resume" : "Pause"}</button><button class="danger j-del">Delete</button></td></tr>`).join("")}</tbody></table>` : `<div class="empty">No schedules</div>`}</div>
      <form id="cron-form" class="card" style="max-width:760px"><h2>Add a cron job</h2>
        <div class="row"><div style="flex:1"><label for="c-cron">Cron (5 fields)</label><input id="c-cron" placeholder="0 9 * * 1-5" required></div>
        <div style="flex:1"><label for="c-agent">Agent</label><select id="c-agent">${agentsList.map((a) => `<option>${esc(a.id)}</option>`).join("")}</select></div></div>
        <label for="c-goal">Goal</label><input id="c-goal" required placeholder="Summarise overnight alerts">
        <div class="row" style="margin-top:12px"><button class="primary">Schedule</button><span id="c-err" class="error"></span></div></form>`;
    view.querySelectorAll("tr[data-job]").forEach((tr) => {
      const id = encodeURIComponent(tr.dataset.job);
      $(".j-toggle", tr).addEventListener("click", async (e) => { await api(`/cron/${id}/${e.target.textContent === "Pause" ? "pause" : "resume"}`, { method: "POST" }); schedules(); });
      $(".j-del", tr).addEventListener("click", async () => { if (confirm("Delete this schedule?")) { await api(`/cron/${id}`, { method: "DELETE" }); schedules(); } });
    });
    $("#cron-form").addEventListener("submit", async (e) => {
      e.preventDefault();
      try { await api("/cron", { method: "POST", body: { cron: $("#c-cron").value.trim(), agent_id: $("#c-agent").value, goal: $("#c-goal").value.trim() } }); schedules(); }
      catch (err) { $("#c-err").textContent = err.message; }
    });
  }

  async function skills() {
    const list = await api("/skills");
    view.innerHTML = `<div class="head"><div><h1>Skills</h1><div class="muted">SKILL.md procedures the agents load on demand</div></div></div>
      <div class="card">${list.length ? `<table><thead><tr><th>Name</th><th>Description</th><th class="hide-sm">Version</th><th class="hide-sm">Author</th></tr></thead><tbody>
      ${list.map((s) => `<tr><td class="mono">${esc(s.name)}</td><td>${esc(s.description)}</td><td class="hide-sm">${esc(s.version ?? "")}</td><td class="hide-sm">${esc(s.authorship ?? "")}</td></tr>`).join("")}</tbody></table>` : `<div class="empty">No skills installed</div>`}</div>`;
  }

  async function agents() {
    const list = await api("/agents");
    view.innerHTML = `<div class="head"><div><h1>Agents</h1><div class="muted">Profiles from agents.yaml: capabilities, rules and limits</div></div></div>
      <div class="grid cols">${list.map((a) => `<div class="card"><div class="row" style="justify-content:space-between"><h2 style="margin:0">${esc(a.id)}</h2><span class="badge">${esc(a.domain)}</span></div>
        <p class="muted small">${esc(a.system_prompt)}</p>
        <dl class="kv"><dt>Capabilities</dt><dd>${(a.allowed_tools || []).map((t) => `<code>${esc(t)}</code>`).join(" ") || "-"}</dd>
        <dt>Rules</dt><dd>${(a.rules || []).map((r) => `<code>${esc(r)}</code>`).join(" ") || "-"}</dd>
        <dt>Mode</dt><dd>${esc(a.permission_mode || "default")}</dd>
        <dt>Limits</dt><dd>${esc(a.max_turns ?? "default")} turns · ${a.token_budget ? num(a.token_budget) : "default"} tokens · ${a.max_cost_usd ? money(a.max_cost_usd) : "no USD cap"}</dd>
        <dt>Model</dt><dd class="mono">${esc(a.model || "default")}</dd></dl>
        <div style="margin-top:10px"><a class="button" href="#/run">Run with this agent</a></div></div>`).join("")}</div>`;
  }

  async function plugins() {
    let list;
    try { list = await api("/admin/plugins"); }
    catch (e) { if (e.status === 403) { view.innerHTML = `<div class="card">Plugin status needs a token with the <code>admin</code> scope.</div>`; return; } throw e; }
    view.innerHTML = `<div class="head"><div><h1>Plugins</h1><div class="muted">Loaded plugins and the tools they register</div></div>
      <button id="reload">Reload agents &amp; tools</button></div>
      <div class="card"><table><thead><tr><th>Plugin</th><th>State</th><th>Tools</th></tr></thead><tbody>
      ${list.map((p) => `<tr><td class="mono">${esc(p.name)}</td><td><span class="badge ${p.error ? "critical" : p.state === "active" ? "good" : ""}">${esc(p.state)}</span>${p.error ? `<div class="error small">${esc(p.error)}</div>` : ""}</td>
        <td class="small">${(p.tools || []).map((t) => `<code>${esc(t)}</code>`).join(" ")}</td></tr>`).join("")}</tbody></table></div>`;
    $("#reload").addEventListener("click", async () => { await api("/admin/reload", { method: "POST" }); toast("Reloaded"); plugins(); });
  }

  // -- boot -----------------------------------------------------------------------------------
  // `harness dashboard` passes the token in the URL fragment, which browsers never send to a server
  function consumeFragment() {
    if (!location.hash.startsWith("#token=")) return false;
    const tok = new URLSearchParams(location.hash.slice(1)).get("token");
    history.replaceState(null, "", location.pathname + "#/overview");   // do not leave it in the address bar
    if (tok) { sessionStorage.setItem(TOKEN_KEY, tok); signIn(tok, false).then(heartbeat); }
    return true;
  }
  window.addEventListener("hashchange", consumeFragment);
  if (!consumeFragment()) {
    if (token()) signIn(token(), false).then(heartbeat);
    else signOut();
  }
})();
