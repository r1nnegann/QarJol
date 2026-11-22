/* QarJol web interface.
 *
 * This file only draws. Every number comes from the Python package qarjol
 * (qarjol/web_api.py), through one of two engines:
 *   server   python app.py answers /api/... on this machine (no internet needed)
 *   pyodide  the online page loads Python in the browser and imports the same files
 */
"use strict";

const PYODIDE_VERSION = "0.29.5";
const PYODIDE_LOCAL = "pyodide/";
const PYODIDE_CDN = `https://cdn.jsdelivr.net/pyodide/v${PYODIDE_VERSION}/full/`;
const PY_FILES = ["__init__.py", "bayes.py", "campus.py", "search.py", "mdp.py", "agent.py", "web_api.py"];

const $ = (sel, root = document) => root.querySelector(sel);
const $$ = (sel, root = document) => Array.from(root.querySelectorAll(sel));
const SVG_NS = "http://www.w3.org/2000/svg";
const f2 = (x) => Number(x).toFixed(2);
const f3 = (x) => Number(x).toFixed(3);
const f4 = (x) => Number(x).toFixed(4);
const cellText = (c) => `(${c[0]},${c[1]})`;
const esc = (s) => String(s).replace(/[&<>"]/g, (ch) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[ch]));

function svg(tag, attrs = {}, parent) {
  const el = document.createElementNS(SVG_NS, tag);
  for (const [k, v] of Object.entries(attrs)) if (v !== undefined && v !== null) el.setAttribute(k, v);
  if (parent) parent.appendChild(el);
  return el;
}
function svgText(parent, x, y, text, attrs = {}) {
  const t = svg("text", { x, y, ...attrs }, parent);
  t.textContent = text;
  return t;
}
function cssVar(name) { return getComputedStyle(document.documentElement).getPropertyValue(name).trim(); }

/* ------------------------------------------------------------------ engine */

const Engine = {
  mode: null,
  py: null,
  info: "",

  async init() {
    const forced = new URLSearchParams(location.search).get("engine");
    const local = ["localhost", "127.0.0.1", "[::1]", "::1"].includes(location.hostname);
    if (forced !== "pyodide" && (local || forced === "server")) {
      try {
        const r = await fetch("api/health", { cache: "no-store" });
        if (r.ok) {
          const j = await r.json();
          if (j.ok) {
            this.mode = "server";
            this.info = `Python ${j.python} · local server`;
            return;
          }
        }
      } catch (e) { /* no local server: fall back to Pyodide */ }
    }
    await this.initPyodide();
  },

  async initPyodide() {
    setEngine("loading", "Loading Python in the browser…");
    let base = PYODIDE_LOCAL;
    try { await loadScript(base + "pyodide.js"); }
    catch (e) { base = PYODIDE_CDN; await loadScript(base + "pyodide.js"); }
    this.py = await globalThis.loadPyodide({ indexURL: new URL(base, location.href).href });
    const fs = this.py.FS;
    fs.mkdirTree("/home/pyodide/qarjol");
    for (const name of PY_FILES) {
      const r = await fetch(`qarjol/${name}`, { cache: "no-cache" });
      if (!r.ok) throw new Error(`Could not load qarjol/${name}`);
      fs.writeFile(`/home/pyodide/qarjol/${name}`, await r.text());
    }
    this.py.runPython([
      "import sys, json",
      "sys.path.insert(0, '/home/pyodide')",
      "import qarjol.web_api as W",
    ].join("\n"));
    const ver = this.py.runPython("sys.version.split()[0]");
    this.mode = "pyodide";
    this.info = `Python ${ver} · in this browser (Pyodide)`;
  },

  async call(fn, args) {
    if (this.mode === "server") {
      const endpoint = { scenario: "scenario", evaluate: "evaluate", random_morning: "random" }[fn];
      const q = new URLSearchParams();
      for (const [k, v] of Object.entries(args)) {
        if (v === null || v === undefined) continue;
        q.set(k, Array.isArray(v) ? v.join(",") : String(v));
      }
      const r = await fetch(`api/${endpoint}?${q}`, { cache: "no-store" });
      const j = await r.json();
      if (!r.ok) throw new Error(j.error || `HTTP ${r.status}`);
      return j;
    }
    this.py.globals.set("ARGS", JSON.stringify(args));
    const out = this.py.runPython(`json.dumps(W.${fn}(**json.loads(ARGS)))`);
    return JSON.parse(out);
  },
};

function loadScript(src) {
  return new Promise((resolve, reject) => {
    const s = document.createElement("script");
    s.src = src;
    s.onload = resolve;
    s.onerror = () => { s.remove(); reject(new Error(`Could not load ${src}`)); };
    document.head.appendChild(s);
  });
}

function setEngine(state, text) {
  const pill = $("#engine");
  pill.dataset.state = state;
  $("#engine-text").textContent = text;
  $("#engine-footer").textContent = state === "ready" ? `Engine: ${text}` : "";
}

function toast(msg) {
  const t = $("#toast");
  t.textContent = msg;
  t.hidden = false;
  clearTimeout(toast.timer);
  toast.timer = setTimeout(() => { t.hidden = true; }, 5000);
}

/* ------------------------------------------------------------------- state */

const state = {
  prior: 0.30,
  plow: 0.50,
  readings: ["SNOW", "CLEAR"],
  view: "route",
  data: null,
  bayesMinute: 0,
  astarStep: null,
  random: null,
  evalData: null,
};

function readHash() {
  const h = new URLSearchParams(location.hash.slice(1));
  const p = parseFloat(h.get("prior"));
  const w = parseFloat(h.get("plow"));
  if (p >= 0 && p <= 1) state.prior = p;
  if (w >= 0 && w <= 1) state.plow = w;
  if (h.has("r")) state.readings = h.get("r").split(",").filter((x) => x === "SNOW" || x === "CLEAR").slice(0, 20);
}
function writeHash() {
  const h = new URLSearchParams({ prior: f2(state.prior), plow: f2(state.plow), r: state.readings.join(",") });
  history.replaceState(null, "", `#${h}`);
}

let refreshTimer = null;
let refreshSeq = 0;
function scheduleRefresh(delay = 90) {
  clearTimeout(refreshTimer);
  refreshTimer = setTimeout(refresh, delay);
}
async function refresh() {
  if (!Engine.mode) return;
  const seq = ++refreshSeq;
  writeHash();
  syncControls();
  try {
    const data = await Engine.call("scenario", { prior: state.prior, plow: state.plow, readings: state.readings });
    if (seq !== refreshSeq) return;
    state.data = data;
    const n = data.minutes.length;
    if (state.bayesMinute >= n) state.bayesMinute = Math.max(0, n - 1);
    if (state.astarStep === null) state.astarStep = data.search.shortcut.trace.length;
    renderAll();
  } catch (e) {
    toast(`Could not compute: ${e.message}`);
  }
}

/* ---------------------------------------------------------------- controls */

function syncControls() {
  $("#prior").value = state.prior;
  $("#plow").value = state.plow;
  $("#prior-out").textContent = f2(state.prior);
  $("#plow-out").textContent = f2(state.plow);
  for (const b of $$(".preset")) {
    const same = Math.abs(+b.dataset.prior - state.prior) < 1e-9 && Math.abs(+b.dataset.plow - state.plow) < 1e-9
      && b.dataset.readings === state.readings.join(",");
    b.setAttribute("aria-pressed", same ? "true" : "false");
  }
}

function renderChips() {
  const box = $("#chips");
  box.innerHTML = "";
  const used = state.data ? state.data.inputs.readings_used : state.readings.length;
  if (!state.readings.length) {
    box.innerHTML = '<span class="chip-empty">No readings yet. Add the first one.</span>';
    return;
  }
  state.readings.forEach((r, i) => {
    const c = document.createElement("span");
    c.className = `chip ${r.toLowerCase()}${i >= used ? " unused" : ""}`;
    c.innerHTML = `<span class="m">m${i}</span>${r}`;
    if (i >= used) c.title = "Not used: the robot had already decided to Move";
    box.appendChild(c);
  });
}

function addReading(r) {
  if (state.readings.length >= 20) { toast("At most 20 readings."); return; }
  state.readings.push(r);
  scheduleRefresh(0);
}

function bindControls() {
  $("#prior").addEventListener("input", (e) => { state.prior = +e.target.value; $("#prior-out").textContent = f2(state.prior); scheduleRefresh(); });
  $("#plow").addEventListener("input", (e) => { state.plow = +e.target.value; $("#plow-out").textContent = f2(state.plow); scheduleRefresh(); });
  for (const b of $$(".preset")) {
    b.addEventListener("click", () => {
      state.prior = +b.dataset.prior;
      state.plow = +b.dataset.plow;
      state.readings = b.dataset.readings.split(",");
      state.bayesMinute = 0;
      setView("route");
      scheduleRefresh(0);
    });
  }
  for (const b of $$("[data-add]")) b.addEventListener("click", () => addReading(b.dataset.add));
  $("#undo").addEventListener("click", () => { state.readings.pop(); scheduleRefresh(0); });
  $("#reset").addEventListener("click", () => { state.readings = []; state.bayesMinute = 0; scheduleRefresh(0); });
  $("#random-btn").addEventListener("click", playRandomMorning);
  for (const t of $$(".tabs [data-view]")) t.addEventListener("click", () => setView(t.dataset.view));
  $("#astar-step").addEventListener("input", (e) => { stopAstar(); state.astarStep = +e.target.value; renderMap(); });
  $("#astar-play").addEventListener("click", toggleAstar);
  $("#eval-btn").addEventListener("click", runEvaluation);
  $("#theme-toggle").addEventListener("click", toggleTheme);

  document.addEventListener("keydown", (e) => {
    if (e.ctrlKey || e.metaKey || e.altKey) return;
    const tag = (e.target.tagName || "").toLowerCase();
    if (tag === "select" || tag === "textarea" || (tag === "input" && e.target.type !== "range")) return;
    if (e.key === "s" || e.key === "S") addReading("SNOW");
    else if (e.key === "c" || e.key === "C") addReading("CLEAR");
    else if (e.key === "Backspace" && state.readings.length) { e.preventDefault(); state.readings.pop(); scheduleRefresh(0); }
  });
}

function toggleTheme() {
  const root = document.documentElement;
  const dark = root.dataset.theme ? root.dataset.theme === "dark" : matchMedia("(prefers-color-scheme: dark)").matches;
  root.dataset.theme = dark ? "light" : "dark";
  try { localStorage.setItem("qarjol-theme", root.dataset.theme); } catch (e) { /* ignore */ }
  renderAll();
  if (state.evalData) renderEvaluation();
}
function restoreTheme() {
  try {
    const t = localStorage.getItem("qarjol-theme");
    if (t === "light" || t === "dark") document.documentElement.dataset.theme = t;
  } catch (e) { /* ignore */ }
}

function setView(view) {
  if (view === "random" && !state.random) return;
  state.view = view;
  for (const t of $$(".tabs [data-view]")) t.setAttribute("aria-selected", t.dataset.view === view ? "true" : "false");
  $("#astar-player").hidden = view !== "astar";
  if (view !== "astar") stopAstar();
  stopRobot();
  renderMap();
}

/* --------------------------------------------------------------------- map */

const CELL = 70;
const PAD = 26;
let robotTimer = null;
let astarTimer = null;

function cellXY(c) { return [PAD + c[1] * CELL + CELL / 2, PAD + c[0] * CELL + CELL / 2]; }

function drawCampus(root, campus) {
  const g = svg("g", {}, root);
  for (let c = 0; c < campus.width; c++) svgText(g, PAD + c * CELL + CELL / 2, 16, c, { "text-anchor": "middle", "font-size": 11, fill: cssVar("--muted") });
  for (let r = 0; r < campus.height; r++) svgText(g, 12, PAD + r * CELL + CELL / 2 + 4, r, { "text-anchor": "middle", "font-size": 11, fill: cssVar("--muted") });
  for (let r = 0; r < campus.height; r++) {
    for (let c = 0; c < campus.width; c++) {
      if ("LMC".includes(campus.rows[r][c])) continue;
      svg("rect", { x: PAD + c * CELL + 3, y: PAD + r * CELL + 3, width: CELL - 6, height: CELL - 6, rx: 10,
        fill: cssVar("--walk"), stroke: cssVar("--walk-line"), "data-cell": `${r},${c}` }, g);
    }
  }
  for (const b of campus.buildings) {
    const rs = b.cells.map((x) => x[0]); const cs = b.cells.map((x) => x[1]);
    const r0 = Math.min(...rs), r1 = Math.max(...rs), c0 = Math.min(...cs), c1 = Math.max(...cs);
    const x = PAD + c0 * CELL + 3, y = PAD + r0 * CELL + 3;
    const w = (c1 - c0 + 1) * CELL - 6, h = (r1 - r0 + 1) * CELL - 6;
    svg("rect", { x, y, width: w, height: h, rx: 10, fill: cssVar("--bldg") }, g);
    for (let i = 0; i < 3; i++) svg("rect", { x: x + 8 + i * 12, y: y + 8, width: 7, height: 7, rx: 1.5, fill: cssVar("--bldg-ink"), opacity: 0.25 }, g);
    svgText(g, x + w / 2, y + h / 2 + 4, b.name, { "text-anchor": "middle", "font-size": w < 80 ? 11 : 13, "font-weight": 600, fill: cssVar("--bldg-ink") });
  }
  const special = [
    [campus.start, "S", "Dorm"], [campus.goal, "G", "AI Lab"], [campus.passage, "P", "Courtyard"],
  ];
  for (const [cell, sym, name] of special) {
    const [cx, cy] = cellXY(cell);
    if (sym === "P") {
      svg("rect", { x: cx - CELL / 2 + 3, y: cy - CELL / 2 + 3, width: CELL - 6, height: CELL - 6, rx: 10,
        fill: cssVar("--snow"), stroke: cssVar("--blocked"), "stroke-dasharray": "4 3", "stroke-width": 1.5 }, g);
      snowflake(g, cx, cy - 6, 9, cssVar("--blocked"));
    } else {
      svg("circle", { cx, cy: cy - 6, r: 13, fill: sym === "G" ? cssVar("--good") : cssVar("--text-2") }, g);
      svgText(g, cx, cy - 1.5, sym, { "text-anchor": "middle", "font-size": 13, "font-weight": 800, fill: cssVar("--surface") });
    }
    svgText(g, cx, cy + 23, name, { "text-anchor": "middle", "font-size": 10.5, "font-weight": 600, fill: cssVar("--text-2"),
      stroke: cssVar("--walk"), "stroke-width": 3, "paint-order": "stroke", "stroke-linejoin": "round" });
  }
}

function snowflake(g, cx, cy, r, color) {
  for (let i = 0; i < 3; i++) {
    const a = (Math.PI / 3) * i;
    svg("line", { x1: cx - r * Math.cos(a), y1: cy - r * Math.sin(a), x2: cx + r * Math.cos(a), y2: cy + r * Math.sin(a),
      stroke: color, "stroke-width": 2, "stroke-linecap": "round" }, g);
  }
}

function drawPath(root, path, color, opts = {}) {
  if (!path || path.length < 2) return null;
  const pts = path.map(cellXY).map(([x, y]) => `${x},${y}`).join(" ");
  if (opts.halo !== false) svg("polyline", { points: pts, fill: "none", stroke: cssVar("--surface"), "stroke-width": (opts.width || 5) + 4, "stroke-linecap": "round", "stroke-linejoin": "round", opacity: 0.9 }, root);
  return svg("polyline", { points: pts, fill: "none", stroke: color, "stroke-width": opts.width || 5,
    "stroke-linecap": "round", "stroke-linejoin": "round", "stroke-dasharray": opts.dash || null, opacity: opts.opacity || 1 }, root);
}

function drawRobot(root, cell) {
  const [x, y] = cellXY(cell);
  const g = svg("g", { class: "robot", transform: `translate(${x},${y})` }, root);
  svg("rect", { x: -14, y: -13, width: 28, height: 22, rx: 7, fill: cssVar("--accent"), stroke: cssVar("--surface"), "stroke-width": 2 }, g);
  svg("circle", { cx: -5, cy: -3, r: 3, fill: "#fff" }, g);
  svg("circle", { cx: 5, cy: -3, r: 3, fill: "#fff" }, g);
  svg("rect", { x: -9, y: 9, width: 18, height: 4, rx: 2, fill: cssVar("--text-2") }, g);
  svg("line", { x1: 0, y1: -13, x2: 0, y2: -19, stroke: cssVar("--accent"), "stroke-width": 2 }, g);
  svg("circle", { cx: 0, cy: -20, r: 2.5, fill: cssVar("--wait") }, g);
  return g;
}

function drawBlockedMark(root, cell) {
  const [x, y] = cellXY(cell);
  const g = svg("g", {}, root);
  svg("circle", { cx: x, cy: y - 6, r: 15, fill: cssVar("--bad") }, g);
  svg("path", { d: `M${x - 6} ${y - 12}l12 12M${x + 6} ${y - 12}l-12 12`, stroke: "#fff", "stroke-width": 3, "stroke-linecap": "round" }, g);
  return g;
}

function legendHtml(items) {
  return items.map(([kind, color, label, dash]) => kind === "line"
    ? `<span><i class="swatch" style="background:${dash ? `repeating-linear-gradient(90deg,${color} 0 6px,transparent 6px 10px)` : color}"></i>${label}</span>`
    : `<span><i class="swatch box" style="background:${color}"></i>${label}</span>`).join("");
}

function renderMap() {
  const d = state.data;
  if (!d) return;
  const campus = d.campus, s = d.search;
  const root = $("#map");
  root.innerHTML = "";
  const size = PAD + campus.width * CELL + 6;
  root.setAttribute("viewBox", `0 0 ${size} ${PAD + campus.height * CELL + 6}`);
  drawCampus(root, campus);
  const overlay = svg("g", {}, root);
  const cap = $("#map-caption");
  const legend = $("#map-legend");

  if (state.view === "astar") {
    const trace = s.shortcut.trace;
    const k = Math.min(state.astarStep ?? trace.length, trace.length);
    $("#astar-step").max = trace.length;
    $("#astar-step").value = k;
    const ramp = ["--seq-1", "--seq-2", "--seq-3", "--seq-4", "--seq-5", "--seq-6"].map(cssVar);
    trace.slice(0, k).forEach((t, i) => {
      const [cx, cy] = cellXY(t.node);
      const shade = ramp[Math.min(ramp.length - 1, Math.floor((i / Math.max(1, trace.length - 1)) * (ramp.length - 1)))];
      svg("rect", { x: cx - CELL / 2 + 6, y: cy - CELL / 2 + 6, width: CELL - 12, height: CELL - 12, rx: 8, fill: shade, opacity: 0.85 }, overlay);
      const dark = ramp.indexOf(shade) >= 3;
      const ink = dark ? "#fff" : cssVar("--text");
      svgText(overlay, cx, cy - 8, `#${i + 1}`, { "text-anchor": "middle", "font-size": 11, "font-weight": 700, fill: ink });
      svgText(overlay, cx, cy + 7, `g${t.g}+h${t.h}`, { "text-anchor": "middle", "font-size": 10, fill: ink, style: "font-family:var(--mono)" });
      svgText(overlay, cx, cy + 20, `f=${t.f}`, { "text-anchor": "middle", "font-size": 10.5, "font-weight": 700, fill: ink });
      if (i === k - 1) svg("rect", { x: cx - CELL / 2 + 4, y: cy - CELL / 2 + 4, width: CELL - 8, height: CELL - 8, rx: 10, fill: "none", stroke: cssVar("--wait"), "stroke-width": 3 }, overlay);
    });
    if (k >= trace.length) drawPath(overlay, s.shortcut.path, cssVar("--move"), { width: 3, opacity: 0.9 });
    const cur = trace[k - 1];
    $("#astar-text").textContent = k === 0 ? "Press play to expand nodes" : `#${k}/${trace.length} ${cellText(cur.node)} g=${cur.g} h=${cur.h} f=${cur.f}`;
    cap.innerHTML = `A* expanded <b>${s.shortcut.expanded}</b> cells to find the <b>${s.shortcut.cost}-step</b> shortcut. Uniform-cost search (h = 0) expands <b>${s.ucs.expanded}</b> for the same length: the Manhattan heuristic skips useless cells.`;
    legend.innerHTML = legendHtml([["box", ramp[1], "expanded early"], ["box", ramp[5], "expanded late"], ["line", cssVar("--move"), "shortest route"]]);
    syncAstarTable(k);
    return;
  }

  if (state.view === "random" && state.random) {
    const rm = state.random;
    drawPath(overlay, rm.path, rm.stuck ? cssVar("--wait") : cssVar("--move"), { width: 4, opacity: 0.35, halo: false });
    const robot = drawRobot(overlay, campus.start);
    const revealed = rm.revealed;
    cap.innerHTML = revealed
      ? randomCaption(rm)
      : `The robot waited <b>${rm.wait_minutes}</b> min, then left. Driving…`;
    legend.innerHTML = legendHtml([["line", cssVar("--move"), "shortcut"], ["line", cssVar("--wait"), "fallback after a blocked courtyard"], ["box", cssVar("--bad"), "blocked P (revealed)"]]);
    if (revealed) {
      const end = rm.path[rm.path.length - 1];
      const [x, y] = cellXY(end);
      robot.setAttribute("transform", `translate(${x},${y})`);
      drawPath(overlay, rm.path, rm.stuck ? cssVar("--wait") : cssVar("--move"), { width: 4 });
      overlay.appendChild(robot);
      if (rm.stuck) drawBlockedMark(overlay, campus.passage);
    } else {
      animateRobot(overlay, robot, rm.path, rm.stuck ? rm.replan_from : null, () => {
        rm.revealed = true;
        renderMap();
      });
    }
    return;
  }

  // Route plan
  const status = d.result.status;
  drawPath(overlay, s.stuck_path, cssVar("--wait"), { width: 4, dash: "2 9", opacity: 0.9 });
  drawPath(overlay, s.shortcut.path, cssVar("--move"), { width: 5 });
  const [tx, ty] = cellXY(s.replan_from);
  svg("circle", { cx: tx, cy: ty, r: 6, fill: cssVar("--surface"), stroke: cssVar("--wait"), "stroke-width": 2.5 }, overlay);
  const robot = drawRobot(overlay, campus.start);
  legend.innerHTML = legendHtml([
    ["line", cssVar("--move"), `shortcut via P, ${s.shortcut.cost} steps`],
    ["line", cssVar("--wait"), `fallback if P is blocked, ${s.stuck_steps} steps`, true],
  ]);
  if (status === "move") {
    cap.innerHTML = `Plan: take the <b>${s.shortcut.cost}-step shortcut</b> through the courtyard. If P is blocked on arrival, the robot sees it at ${cellText(s.replan_from)} after ${s.steps_to_turn_back} steps and A* re-plans without P: <b>${s.stuck_steps} steps</b> in total. <button type="button" class="btn ghost" id="drive-btn">Drive the shortcut</button>`;
    $("#drive-btn").addEventListener("click", () => { stopRobot(); animateRobot(overlay, robot, s.shortcut.path, null, null); });
  } else if (status === "waiting") {
    cap.innerHTML = `The robot is <b>waiting at the dorm</b>. Add another sensor reading to continue the morning.`;
  } else {
    cap.innerHTML = `Add a sensor reading to start the morning. Both routes are already planned by A*.`;
  }
}

function randomCaption(rm) {
  const first = rm.steps[0];
  const truth = rm.state_on_departure === "Blocked" ? "<b style='color:var(--bad)'>blocked</b>" : "<b style='color:var(--good)'>clear</b>";
  const outcome = rm.stuck
    ? `It met the drift, turned back at ${cellText(rm.replan_from)} and took the fallback: <b>${rm.travel_steps} steps</b>.`
    : `It used the shortcut: <b>${rm.travel_steps} steps</b>.`;
  return `Revealed: the courtyard was ${truth} when the robot left (it started ${first.true_state.toLowerCase()}). ${outcome} Total ${rm.total_minutes} min, reward <b>${rm.reward.toFixed(0)}</b>. Seed ${rm.seed}.`;
}

function animateRobot(layer, robot, path, stopCell, done) {
  stopRobot();
  let i = 0;
  const reduce = matchMedia("(prefers-reduced-motion: reduce)").matches;
  const stepMs = reduce ? 0 : 260;
  let markShown = false;
  const tick = () => {
    const [x, y] = cellXY(path[i]);
    robot.style.transition = reduce ? "none" : `transform ${stepMs}ms ease-in-out`;
    robot.setAttribute("transform", `translate(${x},${y})`);
    let pause = 0;
    if (stopCell && !markShown && path[i][0] === stopCell[0] && path[i][1] === stopCell[1]) {
      markShown = true;
      pause = reduce ? 0 : 700;
      drawBlockedMark(layer, state.data.campus.passage);
      layer.appendChild(robot);
    }
    i++;
    if (i < path.length) robotTimer = setTimeout(tick, stepMs + pause);
    else if (done) robotTimer = setTimeout(done, 350);
  };
  tick();
}
function stopRobot() { clearTimeout(robotTimer); robotTimer = null; }

function toggleAstar() {
  if (astarTimer) { stopAstar(); return; }
  const n = state.data.search.shortcut.trace.length;
  if ((state.astarStep ?? n) >= n) state.astarStep = 0;
  $("#astar-play").innerHTML = '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M7 5h4v14H7zM13 5h4v14h-4z"/></svg>';
  $("#astar-play").setAttribute("aria-label", "Pause");
  const step = () => {
    state.astarStep++;
    renderMap();
    if (state.astarStep >= n) stopAstar();
    else astarTimer = setTimeout(step, 520);
  };
  renderMap();
  astarTimer = setTimeout(step, 300);
}
function stopAstar() {
  clearTimeout(astarTimer); astarTimer = null;
  const b = $("#astar-play");
  b.innerHTML = '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M8 5v14l11-7z"/></svg>';
  b.setAttribute("aria-label", "Play A* expansion");
}

/* ---------------------------------------------------------------- decision */

function renderDecision() {
  const d = state.data;
  const box = $("#decision");
  const m = d.minutes;
  const last = m[m.length - 1];
  const s = d.search;
  box.className = "decision";
  if (!m.length) {
    box.innerHTML = `<div class="verdict"><span class="pill none">NO DATA</span></div><p>Add a sensor reading. The robot needs at least one reading to decide.</p>`;
    $("#decision-minute").textContent = "";
  } else if (d.result.status === "move") {
    box.classList.add("move");
    const after = d.result.waited === 0 ? "right away" : `after waiting ${d.result.waited} min`;
    box.innerHTML = `<div class="verdict"><span class="pill move">MOVE</span><span class="headline">Leave ${after}</span></div>
      <p>P(Blocked) is <b>${f4(last.belief)}</b>, so Move scores higher (${f3(last.scores.Move)} vs ${f3(last.scores.Wait)}). Plan: ${s.shortcut.cost}-step shortcut; ${s.stuck_steps} steps if P turns out blocked.</p>`;
    $("#decision-minute").textContent = `decided at minute ${last.minute}`;
  } else {
    box.classList.add("wait");
    box.innerHTML = `<div class="verdict"><span class="pill wait">WAIT</span><span class="headline">Wait for the snowplow</span></div>
      <p>P(Blocked) is <b>${f4(last.belief)}</b>, so Wait scores higher (${f3(last.scores.Wait)} vs ${f3(last.scores.Move)}). Before the next reading the belief becomes <b>${f4(last.next_prior)}</b>. Add another reading.</p>`;
    $("#decision-minute").textContent = `minute ${last.minute}`;
  }
  for (const b of $$("[data-add]")) b.classList.toggle("attention", d.result.status !== "move");

  // Belief meter
  const meter = $("#belief-meter");
  const th = d.mdp.threshold;
  let html = '<div class="track">';
  if (th === null) html += '<div class="zone-all"></div>';
  else html += `<div class="zone-move" style="flex-basis:${th * 100}%"></div><div class="zone-wait"></div>`;
  html += "</div>";
  if (th !== null) {
    html += `<div class="tick" style="left:${th * 100}%"></div><div class="tick-label" style="left:${th * 100}%">b* ${f3(th)}</div>`;
    if (th > 0.12) html += `<div class="zone-text" style="left:${th * 50}%;color:var(--move)">Move</div>`;
    if (th < 0.88) html += `<div class="zone-text" style="left:${(th + 1) * 50}%;color:var(--wait)">Wait</div>`;
  } else {
    const best = d.mdp.qb_at_0.Move >= d.mdp.qb_at_0.Wait ? "Move" : "Wait";
    html += `<div class="zone-text" style="left:50%;color:var(--move)">${best} for every belief</div>`;
  }
  html += '<div class="axis" style="left:0">0</div><div class="axis" style="right:0">1</div>';
  for (const e of m) html += `<div class="mark ${e.action.toLowerCase()}" style="left:${e.belief * 100}%" title="minute ${e.minute}: ${f4(e.belief)} → ${e.action}">${e.minute}</div>`;
  meter.innerHTML = html;
  $("#threshold-text").textContent = th === null ? "no crossover" : "below b*: Move · above: Wait";

  // Scores of the last minute
  const sc = $("#scores");
  if (last) {
    const vals = [last.scores.Move, last.scores.Wait];
    const max = Math.max(...vals.map(Math.abs), 1);
    sc.innerHTML = ["Move", "Wait"].map((a) => {
      const v = last.scores[a];
      const best = a === last.action;
      return `<div class="score-row${best ? " best" : ""}"><span>${a}</span><div class="bar-bg"><div class="bar" style="width:${Math.max(0, v) / max * 100}%;background:var(--${a.toLowerCase()})"></div></div><span class="val">${f3(v)}</span></div>`;
    }).join("") + `<span class="muted small">Q<sub>b</sub> scores at minute ${last.minute}${last.action ? `; the larger wins` : ""}</span>`;
  } else sc.innerHTML = "";

  // Timeline
  const ol = $("#minutes");
  if (!m.length) { ol.innerHTML = '<li class="empty">No readings yet.</li>'; return; }
  ol.innerHTML = m.map((e) => `<li><span class="no ${e.action.toLowerCase()}">${e.minute}</span><div class="body">
      Reading <b>${e.reading}</b>: P(Blocked) ${f4(e.prior)} → <b>${f4(e.belief)}</b> ⇒ <b>${e.action}</b>
      ${e.next_prior !== undefined ? `<div class="predict">waits 1 min, prior for next reading ${f4(e.next_prior)}</div>` : ""}
    </div></li>`).join("")
    + (d.result.status === "waiting" ? '<li><span class="no wait">…</span><div class="body muted">Still waiting: add another reading.</div></li>' : "");
}

/* ------------------------------------------------------------- algorithms */

function renderAstarCard() {
  const d = state.data, s = d.search, c = d.campus;
  $("#astar-input").innerHTML = `6×6 grid, 4-directional moves, cost 1 per step. Start S ${cellText(c.start)}, goal G ${cellText(c.goal)}, snow-prone courtyard P ${cellText(c.passage)}. Heuristic: Manhattan distance.`;
  $("#astar-stats").innerHTML = `
    <div class="stat"><div class="v" style="color:var(--move)">${s.shortcut.cost}</div><div class="k">steps, shortcut via P</div></div>
    <div class="stat"><div class="v" style="color:var(--wait)">${s.stuck_steps}</div><div class="k">steps if P is blocked (${s.steps_to_turn_back} + ${s.replan.cost})</div></div>
    <div class="stat"><div class="v">${s.shortcut.expanded}<span class="muted" style="font-size:.9rem"> / ${s.ucs.expanded}</span></div><div class="k">cells expanded, A* / UCS</div></div>`;
  const rows = s.shortcut.trace.map((t, i) => `<tr data-i="${i + 1}"><td>${i + 1}</td><td>${cellText(t.node)}</td><td>${t.g}</td><td>${t.h}</td><td>${t.f}</td><td>${t.frontier}</td></tr>`).join("");
  $("#astar-table").innerHTML = `<thead><tr><th>#</th><th>cell</th><th>g</th><th>h</th><th>f</th><th>frontier</th></tr></thead><tbody>${rows}</tbody>`;
  $("#astar-output").innerHTML = `shortcut ${s.shortcut.path.map(cellText).join(" → ")} (${s.shortcut.cost} steps). Fallback: ${s.steps_to_turn_back} steps to ${cellText(s.replan_from)}, then an ${s.replan.cost}-step re-plan without P, ${s.stuck_steps} in total.`;
  syncAstarTable(state.view === "astar" ? state.astarStep : 0);
}
function syncAstarTable(k) {
  for (const tr of $$("#astar-table tbody tr")) tr.classList.toggle("hl", +tr.dataset.i === k);
}

function renderBayesCard() {
  const d = state.data;
  const m = d.minutes;
  const tabs = $("#bayes-tabs");
  if (!m.length) {
    tabs.innerHTML = "";
    $("#bayes-input").textContent = "Add a sensor reading to see the update.";
    $("#bayes-steps").textContent = "";
    $("#bayes-bars").innerHTML = "";
    $("#bayes-output").textContent = "no reading yet";
    return;
  }
  tabs.innerHTML = m.map((e, i) => `<button type="button" role="tab" aria-selected="${i === state.bayesMinute}" data-i="${i}">minute ${e.minute} · ${e.reading}</button>`).join("");
  for (const b of $$("button", tabs)) b.addEventListener("click", () => { state.bayesMinute = +b.dataset.i; renderBayesCard(); });
  const e = m[state.bayesMinute];
  const u = e.bayes, sensor = d.bayes.sensor, r = u.reading;
  const prev = state.bayesMinute > 0 ? m[state.bayesMinute - 1] : null;
  const tr = d.mdp.wait_transition;
  const priorSource = prev
    ? `after waiting: ${f4(prev.belief)}×${f2(tr.Blocked.Blocked)} + ${f4(1 - prev.belief)}×${f2(tr.Clear.Blocked)} = <b>${f4(e.prior)}</b>`
    : `forecast prior <b>${f2(e.prior)}</b>`;
  $("#bayes-input").innerHTML = `Prior P(Blocked): ${priorSource}. Sensor: P(SNOW|Blocked) = ${f2(sensor.Blocked.SNOW)}, P(SNOW|Clear) = ${f2(sensor.Clear.SNOW)}. Reading: <b>${r}</b>.`;
  $("#bayes-steps").innerHTML = [
    `P(${r}|Blocked)·P(Blocked) = ${f2(u.likelihood_blocked)} × ${f4(u.prior_blocked)} = ${f4(u.joint_blocked)}`,
    `P(${r}|Clear)·P(Clear)     = ${f2(u.likelihood_clear)} × ${f4(1 - u.prior_blocked)} = ${f4(u.joint_clear)}`,
    `P(${r}) = ${f4(u.joint_blocked)} + ${f4(u.joint_clear)} = ${f4(u.evidence)}`,
  ].map(esc).join("<br>");
  const bar = (label, p) => `<div class="prob-row"><span>${label}</span><div class="prob-track">
      <div class="b" style="flex-basis:${p * 100}%" title="Blocked ${f4(p)}">${p >= 0.12 ? `Blocked ${f3(p)}` : ""}</div>
      <div class="c" style="flex-basis:${(1 - p) * 100}%" title="Clear ${f4(1 - p)}">${1 - p >= 0.12 ? `Clear ${f3(1 - p)}` : ""}</div></div></div>`;
  $("#bayes-bars").innerHTML = bar("Before", u.prior_blocked) + bar(`After ${r}`, u.posterior_blocked);
  $("#bayes-output").innerHTML = `P(Blocked | ${r}) = ${f4(u.joint_blocked)} / ${f4(u.evidence)} = <b>${f4(u.posterior_blocked)}</b>. This belief goes to the MDP step, which chooses <b>${e.action}</b>.`;
}

function renderMdpCard() {
  const d = state.data, p = d.mdp.params, R = d.mdp.rewards, T = d.mdp.wait_transition, Q = d.mdp.q;
  $("#gamma").textContent = `γ = ${p.gamma}`;
  const s = d.search;
  $("#reward-table").innerHTML = `<thead><tr><th>Reward R(s,a)</th><th>Move</th><th>Wait</th></tr></thead><tbody>
    <tr><td class="txt">Clear</td><td>${p.delivery_reward} − ${s.shortcut.cost} = ${R.Clear.Move.toFixed(0)}</td><td>${R.Clear.Wait.toFixed(0)}</td></tr>
    <tr><td class="txt">Blocked</td><td>${p.delivery_reward} − ${s.stuck_steps} − ${p.stuck_penalty} = ${R.Blocked.Move.toFixed(0)}</td><td>${R.Blocked.Wait.toFixed(0)}</td></tr></tbody>`;
  $("#transition-table").innerHTML = `<thead><tr><th>Wait: T(s → s′)</th><th>→ Clear</th><th>→ Blocked</th></tr></thead><tbody>
    <tr><td class="txt">Clear</td><td>${f2(T.Clear.Clear)}</td><td>${f2(T.Clear.Blocked)} <span class="muted">new drift</span></td></tr>
    <tr><td class="txt">Blocked</td><td>${f2(T.Blocked.Clear)} <span class="muted">snowplow</span></td><td>${f2(T.Blocked.Blocked)}</td></tr></tbody>`;
  const best = (st) => d.mdp.policy[st];
  $("#q-table").innerHTML = `<thead><tr><th>Q(s,a)</th><th>Move</th><th>Wait</th><th>best</th></tr></thead><tbody>
    ${["Clear", "Blocked"].map((st) => `<tr><td class="txt">${st}</td><td class="${best(st) === "Move" ? "best" : ""}">${f4(Q[st].Move)}</td><td class="${best(st) === "Wait" ? "best" : ""}">${f4(Q[st].Wait)}</td><td class="txt">${best(st)}</td></tr>`).join("")}</tbody>`;
  $("#vi-caption").textContent = `V(s) after each sweep; converged after ${d.mdp.iterations} sweeps`;
  const th = d.mdp.threshold;
  $("#mdp-output").innerHTML = (th === null
    ? `with these settings one action wins for every belief: <b>${d.mdp.qb_at_0.Move >= d.mdp.qb_at_0.Wait ? "Move" : "Wait"}</b>.`
    : `if the state were known: Clear → ${best("Clear")}, Blocked → ${best("Blocked")}. With belief b the scores cross at <b>b* ≈ ${f4(th)}</b>: below it Move, above it Wait (exact ties go to Move).`);
  chartValueIteration();
  chartBeliefScores();
}

/* ------------------------------------------------------------------ charts */

const Tip = {
  show(evt, html) {
    const t = $("#tooltip");
    t.innerHTML = html;
    t.hidden = false;
    const pad = 14;
    const w = t.offsetWidth, h = t.offsetHeight;
    let x = evt.clientX + pad, y = evt.clientY + pad;
    if (x + w > innerWidth - 8) x = evt.clientX - w - pad;
    if (y + h > innerHeight - 8) y = evt.clientY - h - pad;
    t.style.left = `${x}px`; t.style.top = `${y}px`;
  },
  hide() { $("#tooltip").hidden = true; },
};
const tipRow = (color, name, value) => `<div class="r"><span><i style="background:${color}"></i> ${name}</span><b>${value}</b></div>`;

function niceTicks(min, max, count = 5) {
  const span = max - min || 1;
  const step0 = span / count;
  const mag = 10 ** Math.floor(Math.log10(step0));
  const step = [1, 2, 2.5, 5, 10].map((m) => m * mag).find((s) => span / s <= count) || 10 * mag;
  const out = [];
  const lo = Math.floor(min / step + 1e-9) * step, hi = Math.ceil(max / step - 1e-9) * step;
  for (let v = lo; v <= hi + 1e-9; v += step) out.push(+v.toFixed(10));
  return { ticks: out, step };
}

function chartFrame(el, W, H, M, xd, yd, xTicks, yTicks, xFmt, yFmt, xLabel, yLabel) {
  el.innerHTML = "";
  const root = svg("svg", { viewBox: `0 0 ${W} ${H}`, role: "img" }, el);
  const x = (v) => M.l + ((v - xd[0]) / (xd[1] - xd[0])) * (W - M.l - M.r);
  const y = (v) => H - M.b - ((v - yd[0]) / (yd[1] - yd[0])) * (H - M.t - M.b);
  const grid = svg("g", { class: "grid" }, root);
  for (const t of yTicks) {
    svg("line", { x1: M.l, x2: W - M.r, y1: y(t), y2: y(t) }, grid);
    svgText(root, M.l - 6, y(t) + 3.5, yFmt(t), { "text-anchor": "end" });
  }
  for (const t of xTicks) svgText(root, x(t), H - M.b + 15, xFmt(t), { "text-anchor": "middle" });
  svg("line", { class: "axis-line", x1: M.l, x2: W - M.r, y1: H - M.b, y2: H - M.b }, root);
  if (xLabel) svgText(root, (M.l + W - M.r) / 2, H - 4, xLabel, { "text-anchor": "middle" });
  if (yLabel) svgText(root, 12, M.t + (H - M.t - M.b) / 2, yLabel, { "text-anchor": "middle", transform: `rotate(-90 12 ${M.t + (H - M.t - M.b) / 2})` });
  return { root, x, y };
}

function addHover(root, W, H, M, onMove) {
  const cross = svg("line", { y1: M.t, y2: H - M.b, stroke: cssVar("--border-strong"), "stroke-width": 1, visibility: "hidden" }, root);
  const dots = svg("g", { visibility: "hidden" }, root);
  const hit = svg("rect", { x: M.l, y: M.t, width: W - M.l - M.r, height: H - M.t - M.b, fill: "transparent", style: "cursor:crosshair" }, root);
  const toLocal = (evt) => {
    const pt = root.createSVGPoint();
    pt.x = evt.clientX; pt.y = evt.clientY;
    return pt.matrixTransform(root.getScreenCTM().inverse());
  };
  hit.addEventListener("pointermove", (evt) => {
    const p = toLocal(evt);
    const res = onMove(p.x);
    if (!res) return;
    cross.setAttribute("x1", res.x); cross.setAttribute("x2", res.x);
    cross.setAttribute("visibility", "visible");
    dots.innerHTML = "";
    for (const [cy, color] of res.points) svg("circle", { cx: res.x, cy, r: 4.5, fill: color, stroke: cssVar("--surface"), "stroke-width": 2 }, dots);
    dots.setAttribute("visibility", "visible");
    Tip.show(evt, res.html);
  });
  hit.addEventListener("pointerleave", () => { cross.setAttribute("visibility", "hidden"); dots.setAttribute("visibility", "hidden"); Tip.hide(); });
}

function line(root, pts, color, width = 2, dash) {
  return svg("polyline", { points: pts.map(([a, b]) => `${a},${b}`).join(" "), fill: "none", stroke: color, "stroke-width": width,
    "stroke-linejoin": "round", "stroke-linecap": "round", "stroke-dasharray": dash || null }, root);
}

function chartValueIteration() {
  const d = state.data, sw = d.mdp.sweeps;
  const W = 420, H = 260, M = { l: 40, r: 78, t: 12, b: 36 };
  const n = sw[sw.length - 1].iteration;
  const ymax = Math.max(...sw.map((s) => Math.max(s.Clear, s.Blocked)), 1);
  const yt = niceTicks(Math.min(0, ...sw.map((s) => Math.min(s.Clear, s.Blocked))), ymax, 5);
  const xt = niceTicks(0, n, 6);
  const { root, x, y } = chartFrame($("#chart-vi"), W, H, M, [0, n], [yt.ticks[0], yt.ticks[yt.ticks.length - 1]], xt.ticks.filter((t) => t <= n), yt.ticks, (v) => v, (v) => v, "sweep", "V(s)");
  const series = [["Clear", cssVar("--clear"), "V(Clear)"], ["Blocked", cssVar("--blocked"), "V(Blocked)"]];
  for (const [k, color, name] of series) {
    const pts = sw.map((s) => [x(s.iteration), y(s[k])]);
    line(root, pts, color);
    const lastPt = pts[pts.length - 1];
    svgText(root, lastPt[0] + 6, lastPt[1] + 4, `${name} ${f2(sw[sw.length - 1][k])}`, { class: "lbl" });
  }
  addHover(root, W, H, M, (px) => {
    const i = Math.max(0, Math.min(n, Math.round(((px - M.l) / (W - M.l - M.r)) * n)));
    const s = sw[i];
    return { x: x(i), points: series.map(([k, c]) => [y(s[k]), c]),
      html: `<div class="t">sweep ${i}</div>${series.map(([k, c, name]) => tipRow(c, name, f4(s[k]))).join("")}` };
  });
}

function chartBeliefScores() {
  const d = state.data, q0 = d.mdp.qb_at_0, q1 = d.mdp.qb_at_1, th = d.mdp.threshold;
  const W = 460, H = 260, M = { l: 40, r: 74, t: 12, b: 36 };
  const vals = [q0.Move, q0.Wait, q1.Move, q1.Wait];
  const yt = niceTicks(Math.min(0, ...vals), Math.max(...vals), 5);
  const xt = niceTicks(0, 1, 5);
  const { root, x, y } = chartFrame($("#chart-qb"), W, H, M, [0, 1], [yt.ticks[0], yt.ticks[yt.ticks.length - 1]], xt.ticks, yt.ticks, (v) => v.toFixed(1), (v) => v, "belief b = P(Blocked)", "score");
  const qb = (a, b) => (1 - b) * q0[a] + b * q1[a];
  if (th !== null) {
    svg("rect", { x: x(0), y: M.t, width: x(th) - x(0), height: H - M.t - M.b, fill: cssVar("--move"), opacity: 0.06 }, root);
    svg("rect", { x: x(th), y: M.t, width: x(1) - x(th), height: H - M.t - M.b, fill: cssVar("--wait"), opacity: 0.06 }, root);
    line(root, [[x(th), M.t], [x(th), H - M.b]], cssVar("--text-2"), 1.5, "4 4");
    svgText(root, x(th) + 5, M.t + 12, `b* = ${f3(th)}`, { class: "lbl" });
  }
  const acts = [["Move", cssVar("--move")], ["Wait", cssVar("--wait")]];
  for (const [a, color] of acts) {
    line(root, [[x(0), y(q0[a])], [x(1), y(q1[a])]], color);
    svgText(root, x(1) + 6, y(q1[a]) + 4, `${a} ${f2(q1[a])}`, { class: "lbl" });
  }
  for (const e of d.minutes) {
    const yy = y(e.scores[e.action]);
    svg("circle", { cx: x(e.belief), cy: yy, r: 6, fill: cssVar(`--${e.action.toLowerCase()}`), stroke: cssVar("--surface"), "stroke-width": 2 }, root);
    svgText(root, x(e.belief), yy - 10, `m${e.minute}`, { "text-anchor": "middle", class: "lbl" });
  }
  addHover(root, W, H, M, (px) => {
    const b = Math.max(0, Math.min(1, (px - M.l) / (W - M.l - M.r)));
    const br = Math.round(b * 100) / 100;
    const mv = qb("Move", br), wt = qb("Wait", br);
    return { x: x(br), points: [[y(mv), cssVar("--move")], [y(wt), cssVar("--wait")]],
      html: `<div class="t">b = ${br.toFixed(2)} → ${mv >= wt ? "Move" : "Wait"}</div>${tipRow(cssVar("--move"), "Move", f3(mv))}${tipRow(cssVar("--wait"), "Wait", f3(wt))}` };
  });
}

/* ------------------------------------------------------------ random morning */

async function playRandomMorning() {
  const btn = $("#random-btn");
  btn.disabled = true;
  try {
    const rm = await Engine.call("random_morning", { prior: state.prior, plow: state.plow, seed: null });
    rm.revealed = false;
    state.random = rm;
    $("#tab-random").disabled = false;
    // Show the readings the robot saw in the main panels too.
    state.readings = rm.steps.map((s) => s.reading);
    state.bayesMinute = 0;
    await refresh();
    setView("random");
    document.getElementById("demo").scrollIntoView({ behavior: "smooth", block: "start" });
  } catch (e) {
    toast(`Random morning failed: ${e.message}`);
  } finally {
    btn.disabled = false;
  }
}

/* -------------------------------------------------------------- evaluation */

async function runEvaluation() {
  const btn = $("#eval-btn");
  const status = $("#eval-status");
  btn.disabled = true;
  status.textContent = Engine.mode === "pyodide" ? "Simulating in the browser…" : "Simulating…";
  await new Promise((r) => setTimeout(r, 30));
  const t0 = performance.now();
  try {
    state.evalData = await Engine.call("evaluate", { mornings: +$("#mornings").value, prior: state.prior, plow: state.plow });
    status.textContent = `${state.evalData.mornings.toLocaleString("en-US")} mornings per policy and scenario, seed ${state.evalData.seed}, ${((performance.now() - t0) / 1000).toFixed(1)} s`;
    renderEvaluation();
  } catch (e) {
    status.textContent = "";
    toast(`Evaluation failed: ${e.message}`);
  } finally {
    btn.disabled = false;
  }
}

const POLICY_STYLE = { agent: "--move", always_move: "--wait", trust_sensor: "--third" };

function renderEvaluation() {
  const ev = state.evalData;
  if (!ev) return;
  const el = $("#chart-eval");
  const W = 820, H = 320, M = { l: 46, r: 16, t: 48, b: 44 };
  const all = ev.scenarios.flatMap((s) => s.results.map((r) => r.avg_reward));
  const yt = niceTicks(Math.min(0, ...all), Math.max(...all) * 1.04, 5);
  const ymax = yt.ticks[yt.ticks.length - 1];
  el.innerHTML = "";
  const root = svg("svg", { viewBox: `0 0 ${W} ${H}`, role: "img", "aria-label": "Average reward per policy and scenario" }, el);
  const y = (v) => H - M.b - (v / ymax) * (H - M.t - M.b);
  const grid = svg("g", { class: "grid" }, root);
  for (const t of yt.ticks) { svg("line", { x1: M.l, x2: W - M.r, y1: y(t), y2: y(t) }, grid); svgText(root, M.l - 6, y(t) + 3.5, t, { "text-anchor": "end" }); }
  svgText(root, 12, M.t + (H - M.t - M.b) / 2, "avg reward", { "text-anchor": "middle", transform: `rotate(-90 12 ${M.t + (H - M.t - M.b) / 2})` });
  const groups = ev.scenarios.length;
  const gw = (W - M.l - M.r) / groups;
  const bw = Math.min(46, (gw - 40) / 3);
  // legend
  let lx = M.l;
  for (const p of ev.policies) {
    svg("rect", { x: lx, y: 6, width: 12, height: 12, rx: 3, fill: cssVar(POLICY_STYLE[p]) }, root);
    svgText(root, lx + 17, 16, p, { class: "lbl" });
    lx += 17 + p.length * 7.2 + 22;
  }
  svgText(root, lx + 6, 16, "★ best reward in the scenario", {});
  ev.scenarios.forEach((s, gi) => {
    const gx = M.l + gi * gw + gw / 2;
    svgText(root, gx, H - M.b + 17, s.name, { "text-anchor": "middle", class: "lbl" });
    svgText(root, gx, H - M.b + 31, `prior ${f2(s.prior)}, plow ${f2(s.plow)}`, { "text-anchor": "middle" });
    const bestReward = Math.max(...s.results.map((r) => r.avg_reward));
    s.results.forEach((r, i) => {
      const x0 = gx + (i - 1.5) * (bw + 2) + 1;
      const top = y(Math.max(0, r.avg_reward)), base = y(0);
      const h = base - top, rad = Math.min(4, h);
      const path = `M${x0},${base}V${top + rad}Q${x0},${top} ${x0 + rad},${top}H${x0 + bw - rad}Q${x0 + bw},${top} ${x0 + bw},${top + rad}V${base}Z`;
      const bar = svg("path", { d: path, fill: cssVar(POLICY_STYLE[r.policy]) }, root);
      if (Math.abs(r.avg_reward - bestReward) < 5e-4) svgText(root, x0 + bw / 2, top - 5, "★", { "text-anchor": "middle", class: "lbl" });
      const hit = svg("rect", { x: x0 - 1, y: M.t, width: bw + 2, height: base - M.t, fill: "transparent" }, root);
      hit.addEventListener("pointermove", (evt) => {
        bar.setAttribute("opacity", 0.8);
        Tip.show(evt, `<div class="t">${s.name} · ${r.policy}</div>${tipRow(cssVar(POLICY_STYLE[r.policy]), "avg reward", f3(r.avg_reward))}<div class="r"><span>avg minutes</span><b>${f3(r.avg_minutes)}</b></div><div class="r"><span>stuck rate</span><b>${f3(r.stuck_rate)}</b></div>`);
      });
      hit.addEventListener("pointerleave", () => { bar.removeAttribute("opacity"); Tip.hide(); });
    });
  });
  svg("line", { class: "axis-line", x1: M.l, x2: W - M.r, y1: y(0), y2: y(0) }, root);

  const rows = ev.scenarios.flatMap((s) => {
    const best = Math.max(...s.results.map((r) => r.avg_reward));
    return s.results.map((r, i) => `<tr><td class="txt">${i === 0 ? `<b>${s.name}</b>` : ""}</td><td class="txt">${r.policy}</td><td>${f3(r.avg_minutes)}</td><td class="${Math.abs(r.avg_reward - best) < 5e-4 ? "best" : ""}">${f3(r.avg_reward)}</td><td>${f3(r.stuck_rate)}</td></tr>`);
  }).join("");
  $("#eval-table").innerHTML = `<thead><tr><th>Scenario</th><th>Policy</th><th>Avg minutes</th><th>Avg reward</th><th>Stuck rate</th></tr></thead><tbody>${rows}</tbody>`;
}

/* -------------------------------------------------------------------- main */

function renderAll() {
  if (!state.data) return;
  renderChips();
  renderMap();
  renderDecision();
  renderAstarCard();
  renderBayesCard();
  renderMdpCard();
}

async function main() {
  restoreTheme();
  readHash();
  bindControls();
  syncControls();
  try {
    await Engine.init();
    setEngine("ready", Engine.info);
  } catch (e) {
    setEngine("error", "Python engine failed to load");
    toast(`Python could not start: ${e.message}. Run "python app.py" locally instead.`);
    return;
  }
  await refresh();
  let resizeTimer = null;
  addEventListener("resize", () => { clearTimeout(resizeTimer); resizeTimer = setTimeout(() => { if (state.evalData) renderEvaluation(); }, 150); });
}

main();
