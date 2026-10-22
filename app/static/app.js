// Frontend for the Power Systems Assistant. No framework; all model/user text is
// inserted with textContent (never innerHTML) so answers cannot inject markup.
"use strict";

const $ = (sel) => document.querySelector(sel);
const el = (tag, attrs = {}, ...children) => {
  const node = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) {
    if (k === "class") node.className = v;
    else if (k === "text") node.textContent = v;
    else if (k.startsWith("on")) node.addEventListener(k.slice(2), v);
    else node.setAttribute(k, v);
  }
  for (const c of children) if (c != null) node.append(c);
  return node;
};

const state = { docs: [], tools: [], selected: new Set(), busy: false, adminToken: "" };
try { state.adminToken = sessionStorage.getItem("adminToken") || ""; } catch { /* storage unavailable */ }

async function api(path, opts = {}) {
  const headers = { ...(opts.headers || {}) };
  if (state.adminToken) headers.Authorization = `Bearer ${state.adminToken}`;
  let res;
  try {
    res = await fetch(path, { ...opts, headers });
  } catch {
    throw new Error("Network error: the server could not be reached.");
  }
  const isJson = (res.headers.get("content-type") || "").includes("application/json");
  const body = isJson ? await res.json() : await res.text();
  if (!res.ok) {
    const err = new Error(errorText(body, res.status));
    err.status = res.status;
    err.body = body;
    throw err;
  }
  return body;
}

function errorText(body, status) {
  const d = body && body.detail;
  if (typeof d === "string") return d;
  if (d && d.message) return d.message;
  if (Array.isArray(d)) return d.map((e) => `${(e.loc || []).slice(1).join(".")}: ${e.msg}`).join("; ");
  return `Request failed (HTTP ${status})`;
}

// ------------------------------------------------------------------ status
async function loadHealth() {
  try {
    const h = await api("/api/health");
    if (h.max_upload_mb) $("#max-mb").textContent = h.max_upload_mb;
    const s = $("#status");
    s.textContent = "";
    s.append(
      el("span", { text: h.mode === "llm" ? `LLM: ${h.llm_model}` : "Offline extractive mode" }),
      el("span", { class: "pill", text: `${h.chunks_indexed} chunks` }),
      el("span", { class: "pill", text: `v${h.version}` }),
    );
  } catch (e) {
    $("#status").textContent = "API unavailable";
  }
}

// ------------------------------------------------------------------ documents
async function loadDocs() {
  try {
    state.docs = await api("/api/documents");
  } catch (e) {
    state.docs = [];
    $("#upload-msg").textContent = e.message;
  }
  const list = $("#doc-list");
  list.textContent = "";
  if (!state.docs.length) list.append(el("li", { class: "hint", text: "No documents indexed yet." }));
  for (const d of state.docs) {
    const id = `doc-${d.doc_id}`;
    const cb = el("input", { type: "checkbox", id });
    cb.checked = state.selected.has(d.doc_id);
    cb.addEventListener("change", () => (cb.checked ? state.selected.add(d.doc_id) : state.selected.delete(d.doc_id)));
    const del = el("button", { class: "del", title: `Remove ${d.title}`, "aria-label": `Remove ${d.title}`, text: "✕" });
    del.addEventListener("click", () => deleteDoc(d));
    list.append(el("li", {}, cb, el("label", { for: id }, d.title, el("small", { text: `${d.pages} pages · ${d.chunks} chunks` })), del));
  }
}

async function deleteDoc(d) {
  if (!window.confirm(`Remove "${d.title}" from the index?`)) return;
  try {
    await api(`/api/documents/${d.doc_id}`, { method: "DELETE" });
    state.selected.delete(d.doc_id);
    setMsg(`Removed ${d.title}`, "ok");
  } catch (e) {
    if (e.status === 401 && askToken()) return deleteDoc(d);
    setMsg(e.message, "err");
  }
  loadDocs(); loadHealth();
}

function setMsg(text, kind) {
  const m = $("#upload-msg");
  m.textContent = text;
  m.className = `msg ${kind || ""}`;
}

function askToken() {
  const t = window.prompt("This server protects document changes. Enter the admin token:");
  if (!t) return false;
  state.adminToken = t.trim();
  try { sessionStorage.setItem("adminToken", state.adminToken); } catch { /* ignore */ }
  return true;
}

async function upload(file) {
  if (!file) return;
  if (!/\.pdf$/i.test(file.name)) return setMsg("Only PDF files are accepted.", "err");
  const max = Number($("#max-mb").textContent) * 1024 * 1024;
  if (file.size > max) return setMsg(`File is larger than ${$("#max-mb").textContent} MB.`, "err");
  setMsg(`Indexing ${file.name}…`);
  const fd = new FormData();
  fd.append("file", file);
  try {
    const r = await api("/api/documents", { method: "POST", body: fd });
    setMsg(r.duplicate ? `${r.title} was already indexed.` : `Indexed ${r.title}: ${r.pages} pages, ${r.chunks} chunks.`, "ok");
  } catch (e) {
    if (e.status === 401 && askToken()) return upload(file);
    setMsg(e.message, "err");
  }
  loadDocs(); loadHealth();
}

function setupUpload() {
  const input = $("#file-input");
  const dz = $("#dropzone");
  input.addEventListener("change", () => { upload(input.files[0]); input.value = ""; });
  dz.addEventListener("dragover", (e) => { e.preventDefault(); dz.classList.add("drag"); });
  dz.addEventListener("dragleave", () => dz.classList.remove("drag"));
  dz.addEventListener("drop", (e) => { e.preventDefault(); dz.classList.remove("drag"); upload(e.dataTransfer.files[0]); });
}

// ------------------------------------------------------------------ examples
async function loadExamples() {
  try {
    const ex = await api("/api/examples");
    const box = $("#examples");
    for (const x of ex) {
      box.append(el("button", { type: "button", onclick: () => { $("#question").value = x.question; ask(); } },
        el("span", { class: "cat", text: x.category }), x.question));
    }
  } catch { /* examples are optional */ }
}

// ------------------------------------------------------------------ chat
function addBubble(kind, ...children) {
  $("#empty")?.remove();
  const b = el("div", { class: `bubble ${kind}` }, ...children);
  $("#messages").append(b);
  b.scrollIntoView({ behavior: "smooth", block: "end" });
  return b;
}

const STATUS_LABEL = {
  answered: "Answer", calculation: "Calculation", abstained: "Insufficient evidence",
  needs_clarification: "Needs clarification", rejected: "Rejected", error: "Error",
};

function renderAnswerText(text, citations) {
  // Turn [S1] markers into buttons that open the source preview.
  const byId = Object.fromEntries(citations.map((c) => [c.id, c]));
  const frag = el("div", { class: "answer" });
  for (const part of text.split(/(\[S\d+\])/g)) {
    const m = part.match(/^\[(S\d+)\]$/);
    if (m && byId[m[1]]) frag.append(el("button", { class: "cite", type: "button", title: `${byId[m[1]].title}, p. ${byId[m[1]].page}`, onclick: () => showSource(byId[m[1]]), text: m[1] }));
    else if (part) frag.append(document.createTextNode(part));
  }
  return frag;
}

function pagesLabel(c) {
  return c.page_end && c.page_end !== c.page ? `pp. ${c.page}–${c.page_end}` : `p. ${c.page}`;
}

function fmtValue(v) {
  if (v && typeof v === "object" && "value" in v) return `${Number(v.value).toLocaleString(undefined, { maximumFractionDigits: 3 })} ${v.unit}`;
  if (typeof v === "boolean") return v ? "yes" : "no";
  if (typeof v === "number") return v.toLocaleString(undefined, { maximumFractionDigits: 4 });
  return String(v);
}

function calcCard(r) {
  const rows = [];
  for (const [k, v] of Object.entries(r.outputs)) {
    if (k === "loads_shed") {
      const names = v.length ? v.map((x) => `${x.name} (${x.mw} MW, P${x.priority})`).join(", ") : "none";
      rows.push(el("tr", {}, el("td", { text: "loads shed (in order)" }), el("td", { class: "v", text: names })));
      continue;
    }
    rows.push(el("tr", {}, el("td", { text: k.replaceAll("_", " ") }), el("td", { class: "v", text: fmtValue(v) })));
  }
  const det = el("details", {}, el("summary", { text: "Formula, assumptions and inputs" }));
  for (const f of r.formula) det.append(el("div", {}, el("code", { text: f })));
  for (const a of r.assumptions) det.append(el("div", { text: `• ${a}` }));
  det.append(el("div", { text: `Inputs: ${JSON.stringify(r.inputs)}` }));
  const card = el("div", { class: "calc-card" }, el("h3", { text: r.tool.replaceAll("_", " ") }), el("table", {}, ...rows), det);
  if (r.warnings?.length) card.append(el("ul", { class: "warn-list" }, ...r.warnings.map((w) => el("li", { text: w }))));
  return card;
}

function renderResponse(r) {
  const meta = el("div", { class: "meta" },
    el("span", { class: `badge ${r.status}`, text: STATUS_LABEL[r.status] || r.status }),
    el("span", { text: `${Math.round(r.latency_ms)} ms` }),
    el("span", { text: r.mode === "llm" ? "LLM" : "extractive" }));
  if (r.grounding && r.grounding.total_sentences) meta.append(el("span", { text: `grounding ${Math.round(r.grounding.score * 100)}%` }));
  if (r.usage?.cost_usd) meta.append(el("span", { text: `$${r.usage.cost_usd.toFixed(5)}` }));
  const parts = [meta, renderAnswerText(r.answer, r.citations || [])];
  if (r.calculation) parts.push(calcCard(r.calculation));
  if (r.citations?.length) {
    const label = r.status === "calculation" ? "Background references" : "Sources";
    parts.push(el("div", { class: "sources" }, el("span", { class: "hint", text: `${label}:` }),
      ...r.citations.map((c) => el("button", { type: "button", class: `source-chip${c.flagged ? " flag" : ""}`, onclick: () => showSource(c),
        text: `${c.id} · ${c.title} · ${pagesLabel(c)}` }))));
    showSource(r.citations[0]);
  }
  if (r.warnings?.length) parts.push(el("ul", { class: "warn-list" }, ...r.warnings.map((w) => el("li", { text: w }))));
  return parts;
}

async function ask() {
  const q = $("#question").value.trim();
  if (!q || state.busy) return;
  state.busy = true;
  $("#ask-btn").disabled = true;
  addBubble("user", q);
  const pending = addBubble("bot", el("span", { class: "typing", text: "Searching documents…" }));
  $("#question").value = "";
  const body = { question: q };
  if (state.selected.size) body.doc_ids = [...state.selected];
  try {
    const r = await api("/api/chat", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
    pending.replaceChildren(...renderResponse(r));
  } catch (e) {
    pending.replaceChildren(el("div", { class: "meta" }, el("span", { class: "badge error", text: "Error" })), el("div", { text: e.message }));
  } finally {
    state.busy = false;
    $("#ask-btn").disabled = false;
    $("#question").focus();
  }
}

// ------------------------------------------------------------------ source preview
function showTab(name) {
  for (const t of document.querySelectorAll(".tab")) {
    const on = t.dataset.tab === name;
    t.classList.toggle("active", on);
    t.setAttribute("aria-selected", String(on));
  }
  $("#tab-source").hidden = name !== "source";
  $("#tab-calc").hidden = name !== "calc";
}

function showSource(c) {
  showTab("source");
  const box = $("#source-preview");
  const img = el("img", { alt: `${c.title}, page ${c.page}`, loading: "lazy", src: `/api/documents/${encodeURIComponent(c.doc_id)}/pages/${c.page}.png` });
  img.addEventListener("error", () => img.replaceWith(el("p", { class: "hint", text: "Page image unavailable." })));
  box.replaceChildren(...[
    el("div", { class: "src-title", text: `${c.id} · ${c.title}` }),
    el("div", { class: "hint", text: `${c.filename} · ${pagesLabel(c)}${c.section ? " · " + c.section : ""} · similarity ${c.score.toFixed(2)}` }),
    c.flagged ? el("div", { class: "field-err", text: "Instruction-like text in this passage was ignored." }) : null,
    el("div", { class: "snippet", text: c.snippet }),
    img,
  ].filter(Boolean));
}

// ------------------------------------------------------------------ calculators
async function loadTools() {
  try { state.tools = await api("/api/tools"); } catch { state.tools = []; }
  const sel = $("#tool-select");
  for (const t of state.tools) sel.append(el("option", { value: t.name, text: t.name.replaceAll("_", " ") }));
  sel.addEventListener("change", renderToolForm);
  renderToolForm();
}

function resolveType(prop) {
  if (prop.type) return prop.type;
  const opt = (prop.anyOf || []).find((x) => x.type && x.type !== "null");
  return opt ? opt.type : "string";
}

const LOAD_EXAMPLE = JSON.stringify([
  { name: "Fire pumps", mw: 0.3, priority: 1 }, { name: "Process line", mw: 1.3, priority: 2 },
  { name: "Compressors", mw: 0.8, priority: 3 }, { name: "Office HVAC", mw: 0.4, priority: 4 },
], null, 1);

function renderToolForm() {
  const tool = state.tools.find((t) => t.name === $("#tool-select").value);
  const form = $("#calc-form");
  form.replaceChildren();
  $("#calc-result").replaceChildren();
  if (!tool) return;
  $("#tool-desc").textContent = tool.description;
  const { properties, required = [] } = tool.schema;
  for (const [name, prop] of Object.entries(properties)) {
    const type = resolveType(prop);
    const label = `${name}${required.includes(name) ? " *" : ""}`;
    let input;
    if (type === "boolean") {
      input = el("input", { type: "checkbox", name, "data-type": type });
      form.append(el("label", { class: "row-check" }, input, label));
      continue;
    }
    if (type === "array") {
      input = el("textarea", { name, "data-type": type, placeholder: name === "loads" ? LOAD_EXAMPLE : "e.g. 50, 50, 30" });
    } else {
      input = el("input", { name, "data-type": type, type: "number", step: "any", inputmode: "decimal" });
      if (prop.default != null) input.placeholder = `default ${prop.default}`;
    }
    form.append(el("label", {}, label, input, el("span", { class: "field-err", "data-err": name })));
  }
  form.append(el("button", { class: "primary", type: "submit", text: "Calculate" }));
}

function collectArgs(form) {
  const args = {};
  for (const input of form.querySelectorAll("[name]")) {
    const t = input.dataset.type;
    if (t === "boolean") { if (input.checked) args[input.name] = true; continue; }
    const raw = input.value.trim();
    if (!raw) continue;
    if (t === "array") {
      if (raw.startsWith("[")) {
        try { args[input.name] = JSON.parse(raw); } catch { throw new Error(`${input.name}: invalid JSON`); }
      } else args[input.name] = raw.split(/[,\s]+/).filter(Boolean).map(Number);
    } else if (t === "integer") args[input.name] = parseInt(raw, 10);
    else args[input.name] = Number(raw);
  }
  return args;
}

async function calculate(e) {
  e.preventDefault();
  const form = $("#calc-form");
  for (const s of form.querySelectorAll("[data-err]")) s.textContent = "";
  const out = $("#calc-result");
  let args;
  try { args = collectArgs(form); } catch (err) { out.replaceChildren(el("p", { class: "field-err", text: err.message })); return; }
  try {
    const r = await api("/api/calculate", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ tool: $("#tool-select").value, args }) });
    out.replaceChildren(calcCard(r));
  } catch (err) {
    const errs = err.body?.detail?.errors;
    if (errs) {
      for (const x of errs) {
        const slot = form.querySelector(`[data-err="${CSS.escape(x.field.split(".")[0])}"]`);
        if (slot) slot.textContent = x.message;
      }
      const general = errs.filter((x) => !form.querySelector(`[data-err="${CSS.escape(x.field.split(".")[0])}"]`) || x.field === "");
      out.replaceChildren(el("p", { class: "field-err", text: general.length ? general.map((x) => x.message).join("; ") : "Please fix the highlighted fields." }));
    } else out.replaceChildren(el("p", { class: "field-err", text: err.message }));
  }
}

// ------------------------------------------------------------------ init
function init() {
  $("#ask-form").addEventListener("submit", (e) => { e.preventDefault(); ask(); });
  $("#question").addEventListener("keydown", (e) => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); ask(); } });
  for (const t of document.querySelectorAll(".tab")) t.addEventListener("click", () => showTab(t.dataset.tab));
  $("#calc-form").addEventListener("submit", calculate);
  setupUpload();
  loadHealth(); loadDocs(); loadExamples(); loadTools();
}
init();
