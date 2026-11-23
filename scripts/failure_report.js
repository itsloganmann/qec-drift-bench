"use strict";

const $ = id => document.getElementById(id);
const data = JSON.parse($("report-data").textContent);
const compare = (a, b) => String(a).localeCompare(String(b), undefined, {numeric: true});
const format = n => n.toLocaleString("en-US");
const pct = (n, total) => total ? (100 * n / total).toFixed(1) + "%" : "N/A";
const modes = new Map(data.codebook.map(leaf => [leaf.label, leaf]));
const labelName = key => modes.get(key)?.l3 ?? ({invalid_run: "External interruption or eligibility", passed: "Passed"}[key] || key);

function node(tag, text, className) {
  const element = document.createElement(tag);
  if (text !== undefined) element.textContent = text;
  if (className) element.className = className;
  return element;
}

function addOptions(id, entries, placeholder, keep = true) {
  const select = $(id);
  const previous = keep ? select.value : "";
  const options = [...new Map(entries)].sort((a, b) => compare(a[1], b[1]));
  select.replaceChildren(new Option(placeholder, ""), ...options.map(([key, name]) => new Option(name, key)));
  if (options.some(([key]) => key === previous)) select.value = previous;
}

function asOptions(items) {
  return [...new Set(items)].map(item => [item, item]);
}

function total(rows, predicate = () => true) {
  return rows.reduce((sum, row) => sum + (predicate(row) ? row.n : 0), 0);
}

function buildHierarchy(labels) {
  const areas = new Map();
  for (const leaf of data.codebook) {
    if (!areas.has(leaf.l1)) areas.set(leaf.l1, {name: leaf.l1, level: 1, id: "area-" + areas.size, classes: new Map(), count: 0});
    const area = areas.get(leaf.l1);
    if (!area.classes.has(leaf.l2)) {
      area.classes.set(leaf.l2, {name: leaf.l2, level: 2, id: area.id + "-class-" + area.classes.size, leaves: [], count: 0});
    }
    const group = area.classes.get(leaf.l2);
    const count = labels.get(leaf.label) || 0;
    area.count += count;
    group.count += count;
    group.leaves.push({name: leaf.l3, label: leaf.label, level: 3, id: leaf.label, count, definition: leaf.definition});
  }
  return [...areas.values()];
}

let currentLevel = 3;
let chartEntries = [];
let activeRun = "";
let activeCheck = "";
let linkedLens = "";
const expanded = new Set();

function branch(row, children, denominator) {
  const detail = node("details", undefined, "branch");
  detail.id = row.id;
  detail.open = expanded.has(row.id);
  detail.addEventListener("toggle", () => {
    if (detail.open) expanded.add(row.id);
    else expanded.delete(row.id);
  });
  const summary = node("summary", row.name);
  summary.append(node("span", pct(row.count, denominator)));
  detail.append(summary, ...children);
  return detail;
}

function drawBars() {
  const bars = $("bars");
  const rows = chartEntries.filter(row => row.level === currentLevel && (row.count || $("show-zero").checked));
  rows.sort((a, b) => b.count - a.count || compare(a.name, b.name));
  const max = Math.max(1, ...rows.map(row => row.count));
  bars.replaceChildren();
  if (!rows.length) bars.append(node("p", "No failures match these filters.", "small"));
  for (const row of rows) {
    const button = node("button", undefined, "bar");
    button.type = "button";
    button.setAttribute("aria-label", row.name + ", " + format(row.count) + " failures");
    const track = node("span", undefined, "track");
    const fill = node("span", undefined, "fill");
    fill.style.setProperty("--width", (100 * row.count / max) + "%");
    track.append(fill);
    button.append(node("span", row.name), track, node("b", format(row.count)));
    button.addEventListener("click", () => {
      const target = $(row.id);
      for (let part = target; part && part !== $("tree"); part = part.parentElement) {
        if (part.tagName === "DETAILS") part.open = true;
      }
      for (const element of $("tree").querySelectorAll(".highlight")) element.classList.remove("highlight");
      target.classList.add("highlight");
      target.scrollIntoView({block: "nearest"});
      (target.querySelector(":scope > summary") || target).focus({preventScroll: true});
    });
    bars.append(button);
  }
  for (const button of $("levels").querySelectorAll("button")) {
    button.setAttribute("aria-pressed", String(Number(button.dataset.level) === currentLevel));
  }
}

function drawTaxonomy() {
  const cohort = $("cohort").value;
  const pool = data.groups.filter(row => !cohort || row.cohort === cohort);
  addOptions("configuration", asOptions(pool.map(row => row.configuration)), "All configurations");
  addOptions("family", asOptions(pool.map(row => row.family)), "All task families");
  const chosen = pool.filter(row =>
    (!$("configuration").value || row.configuration === $("configuration").value) &&
    (!$("family").value || row.family === $("family").value)
  );
  const selected = chosen.filter(row => row.selected && row.rule !== "invalid_run");
  const eligible = total(selected);
  const passed = total(selected, row => row.rule === "passed");
  const diagnosis = total(selected, row => row.diagnosis === true);
  const measuredCorrect = total(selected, row => row.diagnosis === true && row.repair_met !== null);
  const short = total(selected, row => row.diagnosis === true && row.repair_met === false);
  const diagnosisMeasured = total(selected, row => row.diagnosis !== null);
  $("metrics").replaceChildren(...[
    ["Joint pass rate", pct(passed, eligible)],
    ["Correct diagnosis", pct(diagnosis, diagnosisMeasured)],
    ["Repair fell short after correct diagnosis", pct(short, measuredCorrect)],
    ["Scores included", format(eligible)],
  ].map(([name, value]) => {
    const card = node("div");
    card.append(node("strong", value), node("span", name, "small"));
    return card;
  }));
  const lens = $("lens").value;
  const labels = new Map();
  for (const row of selected) labels.set(row[lens], (labels.get(row[lens]) || 0) + row.n);
  const external = total(chosen) - eligible;
  const reviewExclusions = lens === "review" ? labels.get("invalid_run") || 0 : 0;
  $("matches").textContent = format(eligible) + " scored episodes · " + format(external) + " external interruptions or exclusions" +
    (reviewExclusions ? " · " + format(reviewExclusions) + " additional review-coded exclusions" : "");
  const hierarchy = buildHierarchy(labels);
  chartEntries = hierarchy.flatMap(area => [
    area, ...[...area.classes.values()].flatMap(group => [group, ...group.leaves]),
  ]);
  const failures = hierarchy.reduce((sum, area) => sum + area.count, 0);
  $("chart-base").textContent = format(failures) + " primary failure labels. Select a bar to open its branch.";
  $("tree").replaceChildren(...hierarchy.map(area => branch(area,
    [...area.classes.values()].map(group => branch(group, group.leaves.map(leaf => {
      const item = node("div", undefined, "leaf");
      item.id = leaf.id;
      item.tabIndex = -1;
      item.append(node("strong", leaf.name + " · " + pct(leaf.count, eligible)), node("p", leaf.definition, "small"));
      if (data.private && leaf.count) {
        const link = node("a", "Open traces", "small");
        const params = new URLSearchParams({
          mode: leaf.label, lens, cohort, configuration: $("configuration").value, family: $("family").value,
        });
        link.href = "#traces?" + params;
        item.append(link);
      }
      return item;
    }), eligible)),
  eligible)));
  drawBars();
}

function listButton(title, subtitle, current, action) {
  const button = node("button", title);
  button.type = "button";
  button.setAttribute("aria-pressed", String(current));
  if (subtitle) button.append(node("small", subtitle));
  button.addEventListener("click", action);
  return button;
}

function drawTrail(run, index) {
  const selected = run?.checks[index];
  const trail = $("trail");
  trail.replaceChildren();
  if (!selected) {
    trail.append(node("p", "Select a trajectory and a failed check.", "small"));
    return;
  }
  const reviewLabel = labelName(run.review);
  const titles = [];
  if (run.source_note) titles.push(node("p", run.source_note, "small"));
  if (run.source_url?.startsWith("file:///")) {
    const source = node("a", "Open archived source");
    source.href = run.source_url;
    titles.push(source);
  }
  trail.append(...titles);
  const timeline = node("ol");
  const excerpts = run.trace?.[selected.kind] || [];
  if (!excerpts.length) trail.append(node("p", "No check-specific excerpt was located in the saved view.", "small"));
  for (const entry of excerpts) {
    const item = node("li");
    const info = [entry.evidence, entry.role, entry.position ? "line " + entry.position : ""].filter(Boolean);
    item.append(node("p", info.join(" · "), "small"), node("pre", entry.text));
    timeline.append(item);
  }
  if (run.cause) {
    const item = node("li");
    item.append(node("strong", "Recorded trajectory review"), node("p", reviewLabel + " · " + run.cause));
    timeline.append(item);
  }
  const verdict = node("li");
  verdict.append(node("strong", "Recorded verdict"), node("p", selected.title), node("p", selected.result));
  timeline.append(verdict);
  trail.append(timeline);
}

function drawTraces() {
  const cohort = $("trace-cohort").value;
  const pool = data.cases.filter(run => !cohort || run.cohort === cohort);
  addOptions("trace-configuration", asOptions(pool.map(run => run.configuration)), "All configurations");
  addOptions("trace-family", asOptions(pool.map(run => run.family)), "All task families");
  const mode = $("trace-mode").value;
  const text = $("trace-search").value.trim().toLowerCase();
  const sort = $("trace-sort").value;
  const other = sort === "task" ? "configuration" : "task";
  const runs = pool.filter(run =>
    (!$("trace-configuration").value || run.configuration === $("trace-configuration").value) &&
    (!$("trace-family").value || run.family === $("trace-family").value) &&
    (!mode || (linkedLens ? run.rule !== "invalid_run" && run[linkedLens] === mode : run.review === mode || run.rule === mode)) &&
    (!text || [run.task, run.family, run.id].some(s => s.toLowerCase().includes(text)))
  ).sort((a, b) => compare(a[sort], b[sort]) || compare(a[other], b[other]));
  const current = runs.find(run => run.id === activeRun) || runs[0];
  const changed = activeRun !== current?.id;
  activeRun = current?.id || "";
  if (changed) activeCheck = "";
  const index = activeCheck === "" ? 0 : Number(activeCheck);
  $("run-count").textContent = format(runs.length) + " matching trajectories";
  $("runs").replaceChildren(...runs.map(run => listButton(
    run.task, run.configuration + " · " + labelName(run.rule), run === current,
    () => { activeRun = run.id; activeCheck = ""; drawTraces(); $("checks").querySelector("button")?.focus(); },
  )));
  $("run-selected").textContent = current ? current.configuration : "";
  $("checks").replaceChildren(...(current?.checks || []).map((value, position) => listButton(
    value.title, undefined, position === index,
    () => { activeCheck = String(position); drawTraces(); $("checks").children[position].focus(); },
  )));
  drawTrail(current, index);
}

function route() {
  const traces = location.hash.startsWith("#traces");
  $("taxonomy").hidden = traces;
  $("traces").hidden = !traces;
  for (const id of ["nav-taxonomy", "nav-traces"]) {
    if ((id === "nav-traces") === traces) $(id).setAttribute("aria-current", "page");
    else $(id).removeAttribute("aria-current");
  }
  if (traces) {
    const params = new URLSearchParams(location.hash.split("?")[1]);
    const lens = params.get("lens");
    linkedLens = lens === "rule" || lens === "review" ? lens : "";
    const mode = params.get("mode");
    if (mode && modes.has(mode)) {
      $("trace-mode").value = mode;
      const cohort = params.get("cohort") || "";
      $("trace-cohort").value = cohort;
      const pool = data.cases.filter(run => !cohort || run.cohort === cohort);
      addOptions("trace-configuration", asOptions(pool.map(run => run.configuration)), "All configurations");
      addOptions("trace-family", asOptions(pool.map(run => run.family)), "All task families");
      $("trace-configuration").value = params.get("configuration") || "";
      $("trace-family").value = params.get("family") || "";
      $("trace-search").value = "";
    }
    drawTraces();
  } else drawTaxonomy();
}

const cohortOptions = Object.entries(data.cohorts);
addOptions("cohort", cohortOptions, "All evaluations");
$("cohort").value = "fresh";
addOptions("trace-cohort", cohortOptions, "All evaluations");
addOptions("trace-mode", [...data.codebook.map(leaf => [leaf.label, leaf.l3]), ["invalid_run", labelName("invalid_run")]], "All failure modes");
$("snapshot").textContent = format(data.snapshot.scored) + " of " + format(data.snapshot.planned) +
  " replication scores verified · " + data.snapshot.checked.slice(0, 10) + " UTC";
$("trace-coverage").textContent = data.private
  ? "Filter the saved trajectories. Each failed check ends with the recorded verdict."
  : "Source-verified examples from the historical evaluation and the replication.";
for (const id of ["cohort", "configuration", "family", "lens"]) $(id).addEventListener("change", drawTaxonomy);
for (const id of ["trace-cohort", "trace-configuration", "trace-family", "trace-sort"]) $(id).addEventListener("change", drawTraces);
$("trace-mode").addEventListener("change", () => { linkedLens = ""; drawTraces(); });
$("trace-search").addEventListener("input", drawTraces);
$("filters").addEventListener("reset", () => setTimeout(() => { $("cohort").value = "fresh"; drawTaxonomy(); }, 0));
$("expand").addEventListener("click", () => $("tree").querySelectorAll("details").forEach(detail => { detail.open = true; }));
$("collapse").addEventListener("click", () => $("tree").querySelectorAll("details").forEach(detail => { detail.open = false; }));
$("show-zero").addEventListener("change", drawBars);
$("levels").addEventListener("click", event => {
  if (!event.target.dataset.level) return;
  currentLevel = Number(event.target.dataset.level);
  drawBars();
});
window.addEventListener("hashchange", route);
route();
