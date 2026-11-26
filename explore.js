import { environments } from "./environments.js?v=scored-pilot";

const byId = id => document.getElementById(id);
const viewport = byId("viewport");
const canvas = byId("quantum-canvas");
const fallback = byId("system-fallback");
const tooltip = byId("part-tooltip");
const modelLabels = byId("model-labels");
const animationLabels = byId("animation-labels");
const moduleActions = byId("module-actions");
const systemNote = byId("system-note");
const stepper = byId("stepper");
const stepCopy = byId("step-copy");
const systemButton = byId("show-system");
const playback = byId("playback");
const motion = matchMedia("(prefers-reduced-motion: reduce)");

let selected = "control";
let view = "system";
let scene;
let playing = !motion.matches;
let activePhase = -1;
let labelSize = "";
let hovered = null;
let restoreFocus = false;

function link(label, href) {
  const anchor = document.createElement("a");
  anchor.href = href;
  anchor.textContent = label + " ↗";
  return anchor;
}

function updateTask() {
  const task = environments[selected];
  byId("task-panel").dataset.active = selected;
  byId("task-status").textContent = task.status;
  byId("task-title").textContent = task.title;
  byId("task-summary").textContent = task.summary;
  byId("task-given").textContent = task.given;
  byId("task-return").textContent = task.response;
  byId("task-score").textContent = task.score;
  byId("task-links").replaceChildren(...task.links.map(([label, href]) => link(label, href)));
  for (const button of fallback.children) {
    button.setAttribute("aria-pressed", String(button.dataset.part === selected));
  }
}

function setPlaying(next) {
  playing = next;
  scene?.play(playing);
  playback.textContent = playing ? "Pause" : "Play";
  stepCopy.setAttribute("aria-live", playing ? "off" : "polite");
}

function updateFrame(phase, moving) {
  const frameView = moving ? "zooming" : view;
  if (viewport.dataset.scene !== frameView) {
    viewport.dataset.scene = frameView;
    modelLabels.hidden = frameView !== "system";
    animationLabels.hidden = stepper.hidden = frameView !== "animation";
    labelSize = "";
  }
  if (moving) return;

  if (view === "system" && scene) {
    const size = viewport.clientWidth + "x" + viewport.clientHeight;
    if (size === labelSize) return;
    labelSize = size;
    for (const label of modelLabels.children) {
      const [x, y] = scene.label(label.dataset.part);
      const left = Math.max(label.offsetWidth / 2 + 3, Math.min(viewport.clientWidth - label.offsetWidth / 2 - 3, x));
      label.style.transform = "translate(" + (left - label.offsetWidth / 2) + "px," + Math.max(7, y - label.offsetHeight) + "px)";
    }
    if (restoreFocus) {
      modelLabels.querySelector(`[data-part="${selected}"]`).focus({ preventScroll: true });
      restoreFocus = false;
    }
  }

  if (view === "animation" && phase !== activePhase) {
    activePhase = phase;
    byId("step-title").textContent = environments[selected].phases[phase];
    byId("step-note").textContent = environments[selected].explanations[phase];
  }
}

function clearHover() {
  if (hovered !== null) scene?.highlight(null);
  hovered = null;
  tooltip.hidden = true;
  canvas.style.cursor = "";
}

function setView(next) {
  view = next;
  viewport.dataset.scene = "";
  activePhase = -1;
  labelSize = "";
  const task = environments[selected];
  const taskView = view === "animation";
  clearHover();
  moduleActions.hidden = !taskView;
  systemNote.hidden = taskView;
  if (taskView) {
    moduleActions.setAttribute("aria-label", task.module);
    animationLabels.dataset.environment = selected;
    animationLabels.replaceChildren(...task.labels.map(label => {
      const chip = document.createElement("span");
      chip.textContent = label;
      return chip;
    }));
  }

  scene.show(view, selected, playing, motion.matches);
}

function select(environment) {
  selected = environment;
  updateTask();
  if (scene) setView("animation");
}

function moveStep(offset) {
  const count = environments[selected].phases.length;
  setPlaying(false);
  scene.step((activePhase + offset + count) % count);
}

systemButton.addEventListener("click", event => {
  restoreFocus = event.detail === 0;
  setView("system");
});
playback.addEventListener("click", () => setPlaying(!playing));
byId("previous-step").addEventListener("click", () => moveStep(-1));
byId("next-step").addEventListener("click", () => moveStep(1));

motion.addEventListener("change", () => setPlaying(!motion.matches));

canvas.addEventListener("pointermove", event => {
  if (!scene || view !== "system" || event.pointerType === "touch") return;
  const hit = scene.hit(event.clientX, event.clientY);
  if (!hit) {
    clearHover();
    return;
  }
  if (hit !== hovered) {
    hovered = hit;
    scene.highlight(hit);
    tooltip.textContent = environments[hit].tooltip;
    tooltip.hidden = false;
    canvas.style.cursor = "pointer";
  }
  const bounds = viewport.getBoundingClientRect();
  const x = Math.max(4, Math.min(bounds.width - tooltip.offsetWidth - 5, event.clientX - bounds.left + 12));
  const y = Math.max(4, Math.min(bounds.height - tooltip.offsetHeight - 5, event.clientY - bounds.top + 14));
  tooltip.style.transform = "translate(" + x + "px," + y + "px)";
});

canvas.addEventListener("pointerleave", clearHover);
canvas.addEventListener("click", event => {
  const hit = scene?.hit(event.clientX, event.clientY);
  if (hit) select(hit);
});
for (const group of [modelLabels, fallback]) {
  group.addEventListener("click", event => {
    const part = event.target.closest("[data-part]");
    if (!part) return;
    select(part.dataset.part);
    if (scene && event.detail === 0) systemButton.focus({ preventScroll: true });
  });
}

updateTask();

import("./system-scene.js?v=animated-cutaway").then(({ createScene }) => {
  scene = createScene(canvas, viewport, updateFrame);
  viewport.dataset.ready = "true";
  restoreFocus = fallback.contains(document.activeElement);
  fallback.hidden = true;
  setPlaying(playing);
  setView(view);
}).catch(() => {
  systemNote.textContent = "Choose a module to see its benchmark task.";
});
