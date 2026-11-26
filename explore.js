import { environments } from "./environments.js";

const byId = id => document.getElementById(id);
const viewport = byId("viewport");
const canvas = byId("quantum-canvas");
const fallback = byId("system-fallback");
const tooltip = byId("part-tooltip");
const modelLabels = byId("model-labels");
const animationLabels = byId("animation-labels");
const phaseList = byId("phases");
const systemButton = byId("show-system");
const animationButton = byId("show-animation");
const playback = byId("playback");
const buttons = [...document.querySelectorAll("[data-environment]")];
const motion = matchMedia("(prefers-reduced-motion: reduce)");

let selected = "control";
let view = "system";
let scene;
let failed = false;
let playing = !motion.matches;
let activePhase = -1;
let labelSize = "";
let hovered = null;

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
  for (const button of buttons) {
    button.setAttribute("aria-pressed", String(button.dataset.environment === selected));
  }
}

function updatePlayback() {
  playback.hidden = !scene || view !== "animation";
  playback.textContent = playing ? "Pause" : "Play";
}

function updateFrame(phase) {
  if (view === "system" && scene) {
    const size = viewport.clientWidth + "x" + viewport.clientHeight;
    if (size === labelSize) return;
    labelSize = size;
    for (const label of modelLabels.children) {
      const [x, y] = scene.label(label.dataset.part);
      const left = Math.max(label.offsetWidth / 2 + 3, Math.min(viewport.clientWidth - label.offsetWidth / 2 - 3, x));
      label.style.transform = "translate(" + (left - label.offsetWidth / 2) + "px," + Math.max(7, y - label.offsetHeight) + "px)";
    }
  }

  if (view === "animation" && phase !== activePhase) {
    activePhase = phase;
    byId("model-note").textContent = environments[selected].explanations[phase];
    for (const [index, button] of [...phaseList.children].entries()) {
      button.setAttribute("aria-pressed", String(index === phase));
    }
  }
}

function clearHover() {
  if (hovered !== null) scene?.highlight(null);
  hovered = null;
  tooltip.hidden = true;
  canvas.style.cursor = "";
}

function setView(next) {
  view = failed ? "system" : next;
  activePhase = -1;
  labelSize = "";
  const task = environments[selected];
  const taskView = view === "animation";
  clearHover();
  systemButton.setAttribute("aria-pressed", String(!taskView));
  animationButton.setAttribute("aria-pressed", String(taskView));
  if (taskView) {
    modelLabels.hidden = true;
    animationLabels.dataset.environment = selected;
    animationLabels.replaceChildren(...task.labels.map(label => {
      const chip = document.createElement("span");
      chip.textContent = label;
      return chip;
    }));
    phaseList.replaceChildren(...task.phases.map((label, index) => {
      const button = document.createElement("button");
      button.type = "button";
      button.textContent = label;
      button.addEventListener("click", () => {
        playing = false;
        scene?.play(false);
        scene?.step(index);
        updatePlayback();
      });
      return button;
    }));
  } else {
    modelLabels.hidden = false;
  }

  animationLabels.hidden = !scene || !taskView;
  phaseList.hidden = !scene || !taskView;
  byId("model-note").textContent = failed
    ? "3D unavailable on this device. Explore the task details below."
    : taskView ? task.explanations[0] : "Hover for details. Select a component to see its task.";
  byId("model-key").textContent = taskView ? "Illustrative animation" : "Illustrative system";
  scene?.show(view, selected, playing);
  updatePlayback();
}

function select(environment) {
  selected = environment;
  updateTask();
  setView("animation");
}

for (const button of buttons) {
  button.addEventListener("click", () => select(button.dataset.environment));
}

systemButton.addEventListener("click", () => setView("system"));
animationButton.addEventListener("click", () => setView("animation"));
playback.addEventListener("click", () => {
  playing = !playing;
  scene?.play(playing);
  updatePlayback();
});

motion.addEventListener("change", () => {
  playing = !motion.matches;
  scene?.play(playing);
  updatePlayback();
});

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

updateTask();

import("./system-scene.js").then(({ createScene }) => {
  scene = createScene(canvas, viewport, updateFrame);
  viewport.dataset.ready = "true";
  fallback.hidden = true;
  setView(view);
}).catch(() => {
  failed = true;
  animationButton.disabled = true;
  setView("system");
});
