import { environments } from "./environments.js?v=task-details";

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
const tourStages = ["control", "qec", "readout"];

let selected = "control";
let view = "system";
let scene;
let playing = !motion.matches;
let activePhase = -1;
let labelSize = "";
let hovered = null;
let restoreFocus = false;
let tourStage = -1;
let tourComplete = false;

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
  byId("task-faults").textContent = task.faults;
  byId("task-given").textContent = task.given;
  byId("task-return").textContent = task.response;
  byId("task-score").textContent = task.score;
  byId("task-links").replaceChildren(...task.links.map(([label, href]) => link(label, href)));
  for (const button of fallback.children) {
    button.setAttribute("aria-pressed", String(button.dataset.part === selected));
  }
}

function updatePlayback() {
  const inModule = view === "animation";
  const label = inModule && playing ? "Pause" : !inModule && tourComplete ? "Replay" : "Play";
  const subject = inModule && tourStage < 0 ? "simulation" : "walkthrough";
  playback.textContent = label;
  playback.setAttribute("aria-label", `${label} ${subject}`);
  stepCopy.setAttribute("aria-live", playing ? "off" : "polite");
}

function setPlaying(next) {
  playing = next;
  scene?.play(playing);
  updatePlayback();
}

function updateFrame(phase, moving, finished) {
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

  if (finished && playing && tourStage >= 0) {
    const next = tourStages[++tourStage];
    if (next) select(next);
    else returnToSystem(true);
  }
}

function clearHover() {
  if (hovered !== null) scene?.highlight(null);
  hovered = null;
  tooltip.hidden = true;
  canvas.style.cursor = "";
}

function setView(next) {
  clearHover();
  view = next;
  viewport.dataset.scene = "";
  activePhase = -1;
  labelSize = "";
  const task = environments[selected];
  const taskView = view === "animation";
  systemButton.hidden = !taskView;
  systemNote.hidden = taskView;
  moduleActions.setAttribute("aria-label", taskView ? task.module : "Simulation controls");
  systemNote.textContent = tourComplete ? "Walkthrough complete. Select a module to explore it." : "Play the walkthrough or select a module.";
  if (taskView) {
    animationLabels.dataset.environment = selected;
    animationLabels.replaceChildren(...task.labels.map(label => {
      const chip = document.createElement("span");
      chip.textContent = label;
      return chip;
    }));
  }

  updatePlayback();
  scene.show(view, selected, { play: playing, reduceMotion: motion.matches, playOnce: tourStage >= 0 });
}

function select(environment) {
  selected = environment;
  tourComplete = false;
  updateTask();
  if (scene) setView("animation");
}

function returnToSystem(completed = false) {
  if (tourStage >= 0) playing = !motion.matches;
  tourStage = -1;
  tourComplete = completed;
  setView("system");
}

function moveStep(offset) {
  const count = environments[selected].phases.length;
  setPlaying(false);
  scene.step((activePhase + offset + count) % count);
}

systemButton.addEventListener("click", event => {
  restoreFocus = event.detail === 0;
  returnToSystem();
});
playback.addEventListener("click", () => {
  if (view === "animation") {
    setPlaying(!playing);
    return;
  }
  tourStage = 0;
  playing = true;
  select(tourStages[tourStage]);
});
byId("previous-step").addEventListener("click", () => moveStep(-1));
byId("next-step").addEventListener("click", () => moveStep(1));

motion.addEventListener("change", () => {
  if (tourStage < 0) setPlaying(!motion.matches);
});

function showHover(part, clientX, clientY) {
  if (part !== hovered) {
    hovered = part;
    scene.highlight(part);
    tooltip.textContent = environments[part].tooltip;
    tooltip.hidden = false;
    canvas.style.cursor = "pointer";
  }
  const bounds = viewport.getBoundingClientRect();
  const x = Math.max(4, Math.min(bounds.width - tooltip.offsetWidth - 5, clientX - bounds.left + 12));
  const y = Math.max(4, Math.min(bounds.height - tooltip.offsetHeight - 5, clientY - bounds.top + 14));
  tooltip.style.transform = "translate(" + x + "px," + y + "px)";
}

canvas.addEventListener("pointermove", event => {
  if (!scene || view !== "system" || event.pointerType === "touch") return;
  const hit = scene.hit(event.clientX, event.clientY);
  if (hit) showHover(hit, event.clientX, event.clientY);
  else clearHover();
});

canvas.addEventListener("pointerleave", clearHover);
for (const label of modelLabels.children) {
  const part = label.dataset.part;
  label.setAttribute("aria-description", environments[part].tooltip);
  label.addEventListener("pointerenter", event => {
    if (scene && view === "system" && event.pointerType !== "touch") {
      showHover(part, event.clientX, event.clientY);
    }
  });
  label.addEventListener("pointerleave", clearHover);
}
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

import("./system-scene.js?v=walkthrough").then(({ createScene }) => {
  scene = createScene(canvas, viewport, updateFrame);
  viewport.dataset.ready = "true";
  restoreFocus = fallback.contains(document.activeElement);
  fallback.hidden = true;
  setView(view);
  moduleActions.hidden = false;
}).catch(() => {
  systemNote.textContent = "Choose a module to see its benchmark task.";
});
