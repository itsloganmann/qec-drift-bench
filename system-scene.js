import * as THREE from "https://cdn.jsdelivr.net/npm/three@0.180.0/build/three.module.js";

const copper = 0xe1a060;
const mint = 0x88f4ca;
const violet = 0xbcb2ff;
const amber = 0xffc27c;
const fault = 0xff8a71;
const vector = (x, y, z) => new THREE.Vector3(x, y, z);
const modules = {
  control: { x: -5.25, color: amber, frame: [4.05, 1.58, 3], scale: [.27, .27, .27],
    target: [0, 1.08, 0], offset: [2, 7.6, 18.8], width: 5, height: 2.75 },
  qec: { x: 0, color: mint, frame: [3.9, 3.4, 3.1], scale: [.35, .81, .46],
    target: [0, 1.85, 0], offset: [3.1, 5.5, 18.8], width: 4.8, height: 3.9 },
  readout: { x: 5.25, color: violet, frame: [4.05, 1.55, 3.3], scale: [.35, .56, .46],
    target: [0, .82, 0], offset: [1.2, 14.5, 15.7], width: 5, height: 3.15 },
};

function fadeGroup(group) {
  const copies = new Map();
  group.traverse(object => {
    if (!object.material) return;
    const original = object.material;
    if (!copies.has(original)) copies.set(original, original.clone());
    object.material = copies.get(original);
  });
  let previous;
  return opacity => {
    if (previous === opacity) return;
    previous = opacity;
    group.visible = opacity > .001;
    for (const [original, material] of copies) {
      material.opacity = original.opacity * opacity;
      material.transparent = original.transparent || opacity < .999;
      material.depthWrite = original.depthWrite && opacity > .985;
    }
  };
}

function standard(color, metalness = .18, roughness = .38) {
  return new THREE.MeshStandardMaterial({ color, metalness, roughness });
}

function luminous(color) {
  return new THREE.MeshBasicMaterial({ color });
}

function mesh(parent, geometry, material, x = 0, y = 0, z = 0) {
  const object = new THREE.Mesh(geometry, material);
  object.position.set(x, y, z);
  parent.add(object);
  return object;
}

function box(parent, size, point, material) {
  return mesh(parent, new THREE.BoxGeometry(...size), material, ...point);
}

function sphere(parent, radius, point, material) {
  return mesh(parent, new THREE.SphereGeometry(radius, 16, 10), material, ...point);
}

function cylinder(parent, radius, height, point, material) {
  return mesh(parent, new THREE.CylinderGeometry(radius, radius, height, 40), material, ...point);
}

function wire(parent, points, color, thickness = .035) {
  const path = new THREE.CatmullRomCurve3(points.map(point => vector(...point)));
  const tube = mesh(parent, new THREE.TubeGeometry(path, 48, thickness, 8, false), standard(color, .45));
  return { path, tube };
}

function trace(parent, points, color, opacity = 1) {
  const geometry = new THREE.BufferGeometry().setFromPoints(points.map(point => vector(...point)));
  const material = new THREE.LineBasicMaterial({ color, opacity, transparent: opacity < 1 });
  const line = new THREE.Line(geometry, material);
  parent.add(line);
  return line;
}

function drawGrid(parent, width, depth, spacing, y, color, centerX = 0) {
  for (let i = -width / 2; i <= width / 2 + .001; i += spacing) {
    trace(parent, [[centerX + i, y, -depth / 2], [centerX + i, y, depth / 2]], color);
  }
  for (let i = -depth / 2; i <= depth / 2 + .001; i += spacing) {
    trace(parent, [[centerX - width / 2, y, i], [centerX + width / 2, y, i]], color);
  }
}

const steel = standard(0x7f9e92, .46);
const darkSteel = standard(0x3e5a55, .35);
const black = standard(0x122724, .1, .62);
const gold = standard(copper, .53);
const board = standard(0x376955, .12, .53);

function pad(parent, x, width = 3.8) {
  box(parent, [width, .22, 3.65], [x, .14, 0], darkSteel);
  box(parent, [width - .13, .08, 3.5], [x, .29, 0], black);
}

function instrument(parent, x, color, readout) {
  const accent = luminous(color);
  pad(parent, x);
  for (let level = 0; level < 3; level++) {
    const y = .62 + .46 * level;
    box(parent, [3.1, .43, 2.52], [x, y, -.2], darkSteel);
    box(parent, [3.03, .35, .045], [x, y, 1.07], steel);
    box(parent, [.93, .225, .025], [x - .7, y, 1.1], black);
    trace(parent, Array.from({ length: 19 }, (_, n) => [
      x - 1.1 + n * .044,
      y + (readout ? (n % 4 < 2 ? -.047 : .047) : Math.sin(n * 1.1) * Math.sin(n * Math.PI / 18) * .072),
      1.122,
    ]), color);
    for (let k = 0; k < 3; k++) {
      const dial = cylinder(parent, .073, .08, [x + .16 + k * .27, y, 1.12], black);
      dial.rotation.x = Math.PI / 2;
      sphere(parent, .024, [x + 1.25, y, 1.115], accent);
    }
  }
  if (readout) {
    box(parent, [2.65, .08, 1.48], [x, 1.8, -.28], board);
    for (let i = 0; i < 4; i++) {
      box(parent, [.4, .15, .38], [x - .84 + i * .54, 1.9, -.44], steel);
      trace(parent, [[x - .84 + i * .54, 1.85, -.1], [x - .84 + i * .54, 1.85, .4]], copper);
    }
  }
}

function cryostat(parent) {
  pad(parent, 0, 4.4);
  box(parent, [3.2, .27, 2.75], [0, 4.27, -.15], steel);
  for (const x of [-1.55, 1.55]) {
    for (const z of [-1.31, 1.03]) {
      box(parent, [.11, 3.8, .11], [x, 2.28, z], darkSteel);
    }
  }
  cylinder(parent, 1.4, .36, [0, 3.88, -.15], steel);
  for (let level = 0; level < 5; level++) {
    const y = 3.44 - .51 * level;
    cylinder(parent, 1.29 - .13 * level, .14, [0, y, -.15], level % 2 ? steel : gold);
    for (let k = 0; k < 8; k++) {
      const angle = k * Math.PI / 4;
      const radius = 1.11 - .13 * level;
      const x = Math.cos(angle) * radius;
      const z = -.15 + Math.sin(angle) * radius;
      cylinder(parent, .052, .47, [x, y + .22, z], gold);
      if (level === 0) cylinder(parent, .079, .15, [x, y + .15, z], darkSteel);
    }
  }
  box(parent, [1.21, .08, 1.06], [0, 1.12, -.15], board);
  box(parent, [.53, .08, .53], [0, 1.19, -.15], luminous(mint));
  box(parent, [.35, .065, .35], [0, 1.25, -.15], black);
  for (let i = -1; i <= 1; i++) {
    box(parent, [1.04, .01, .027], [0, 1.17, -.15 + .16 * i], gold);
  }
}

function makeOverview(group) {
  const targets = [];
  const markers = {};
  const focus = {};
  const shells = {};
  drawGrid(group, 18, 8, .5, 0, 0x294239);

  for (const [id, { x, color }] of Object.entries(modules)) {
    const center = id === "qec";
    const shell = new THREE.Group();
    shell.position.x = x;
    group.add(shell);
    if (center) cryostat(shell);
    else instrument(shell, 0, color, id === "readout");
    shells[id] = fadeGroup(shell);
    const target = box(group, [center ? 4.4 : 3.8, center ? 4.33 : 2.04, 3.5],
      [x, center ? 2.22 : 1.02, 0], new THREE.MeshBasicMaterial({ visible: false }));
    target.userData.part = id;
    targets.push(target);
    markers[id] = vector(x, center ? 4.65 : 2.25, .35);
    focus[id] = box(group, [center ? 4.55 : 3.95, .024, 3.8], [x, .014, 0], luminous(color));
    focus[id].visible = false;
  }

  const { path: inbound } = wire(group, [[-3.65, .75, .65], [-2.68, .51, .65], [-2.28, .51, .2], [-1.5, 1.46, -.28], [-.49, 1.5, -.28]], copper, .068);
  const { path: outbound } = wire(group, [[.49, 1.5, -.28], [1.5, 1.46, -.28], [2.42, .51, .24], [2.85, .51, .69], [3.7, .75, .69]], 0x8988d0, .068);
  const pulses = [sphere(group, .12, [0, 0, 0], luminous(amber)), sphere(group, .12, [0, 0, 0], luminous(violet))];

  return {
    targets, markers, shells,
    highlight(id) {
      for (const [part, edge] of Object.entries(focus)) edge.visible = id === part;
    },
    update(time) {
      pulses[0].position.copy(inbound.getPointAt((time * .38) % 1));
      pulses[1].position.copy(outbound.getPointAt((time * .38 + .48) % 1));
    },
  };
}

function axes(group, x, depth = 5.6) {
  box(group, [x, .065, depth], [0, -.08, 0], black);
  drawGrid(group, x, depth, .4, 0, 0x304d42);
}

function pulseTask(group) {
  axes(group, 13.2);
  const left = -5.85;
  const width = 5.75;
  const center = vector(3.7, 1.78, 0);
  const radius = 1.58;
  const guides = new THREE.MeshBasicMaterial({ color: amber, wireframe: true, transparent: true, opacity: .19 });
  mesh(group, new THREE.SphereGeometry(radius, 28, 14), guides, ...center);
  trace(group, [[center.x, .08, 0], [center.x, 3.52, 0]], 0x91aaa0);
  sphere(group, .07, [center.x, center.y + radius, 0], luminous(amber));
  sphere(group, .07, [center.x, center.y - radius, 0], luminous(amber));

  const vectorLine = trace(group, [center.toArray(), [center.x, center.y + radius, 0]], amber);
  const state = sphere(group, .133, [center.x, center.y + radius, 0], luminous(amber));
  const nominal = Array.from({ length: 12 }, (_, i) => 1.85 * Math.sin(Math.PI * (i + .5) / 12) ** 2);
  const bars = nominal.map((height, i) => box(group, [.32, 1, .36], [left + (i + .5) * width / 12, height / 2 + .04, .18], standard(amber)));
  const ideal = nominal.flatMap((height, i) => [
    [left + i * width / 12, height + .04, -.18],
    [left + (i + 1) * width / 12, height + .04, -.18],
  ]);
  trace(group, ideal, 0xa8c5b7, .7);
  trace(group, [[left, 0, -.2], [left, 2.5, -.2]], 0x91aaa0);

  return (phase, t) => {
    const progress = Math.min(1, .15 + t * 1.35);
    const scale = phase === 1 ? .66 : 1;
    for (const [i, bar] of bars.entries()) {
      const height = nominal[i] * scale;
      bar.scale.y = height;
      bar.position.y = height / 2 + .04;
      bar.material.color.setHex(phase === 1 ? fault : amber);
    }
    const theta = Math.PI * scale * progress;
    state.position.set(center.x + Math.sin(theta) * radius, center.y + Math.cos(theta) * radius, 0);
    state.material.color.setHex(phase === 1 ? fault : mint);
    const position = vectorLine.geometry.attributes.position;
    position.setXYZ(1, state.position.x, state.position.y, state.position.z);
    position.needsUpdate = true;
    vectorLine.material.color.copy(state.material.color);
  };
}

function surfaceTask(group) {
  axes(group, 9.6);
  const rounds = [0.35, 1.61, 2.87];
  const dots = [];
  const endpoints = [[-1.15, -.32], [-.35, .32], [1.12, .32]];
  for (const [index, y] of rounds.entries()) {
    box(group, [5.9, .052, 3.65], [0, y, 0], new THREE.MeshBasicMaterial({ color: 0x314f43, transparent: true, opacity: .36, depthWrite: false }));
    for (let row = 0; row < 3; row++) {
      for (let col = 0; col < 5; col++) {
        const x = (col - 2) * 1.12 + (row % 2) * .28;
        const z = (row - 1) * 1.05;
        const node = box(group, [.42, .055, .42], [x, y + .07, z], standard((row + col) % 2 ? 0x447566 : 0x2f564d));
        node.rotation.y = Math.PI / 4;
      }
    }
    const [x, z] = endpoints[index];
    dots.push(sphere(group, .155, [x, y + .16, z], luminous(mint)));
    trace(group, [[-2.95, y + .035, 1.8], [2.95, y + .035, 1.8]], 0x5e8e7b);
  }
  const prior = trace(group, rounds.map(y => [-1.15, y + .16, -.32]), 0x80a897, .7);
  const { path: update, tube: connecting } = wire(group, rounds.map((y, i) => [endpoints[i][0], y + .16, endpoints[i][1]]), mint, .04);
  const marker = sphere(group, .09, [0, 0, 0], luminous(mint));

  return (phase, t) => {
    for (const [i, dot] of dots.entries()) {
      const [x, z] = endpoints[phase === 0 ? 0 : i];
      dot.position.set(x, rounds[i] + .16, z);
      dot.material.color.setHex(phase === 1 ? fault : mint);
      dot.scale.setScalar(.83 + .17 * Math.cos(2 * Math.PI * (t - i / 3)));
    }
    prior.visible = phase < 2;
    connecting.visible = phase === 2;
    marker.visible = phase === 2;
    marker.position.copy(update.getPointAt(t));
  };
}

function readoutTask(group) {
  axes(group, 10.4, 6.4);
  trace(group, [[-5.2, .026, 0], [5.2, .026, 0]], 0x688e7d);
  trace(group, [[0, .026, -3.2], [0, .026, 3.2]], 0x688e7d);
  const boundary = box(group, [.045, .025, 5.9], [0, .04, 0], luminous(mint));
  const old = box(group, [.035, .022, 5.9], [0, .03, 0], luminous(0x708e84));
  const colors = [violet, mint];
  let seed = 6537;
  function random() {
    seed = (1664525 * seed + 1013904223) >>> 0;
    return (seed + 1) / 4294967297;
  }
  const geometry = new THREE.SphereGeometry(.065, 8, 6);
  const points = Array.from({ length: 90 }, (_, i) => {
    const label = i < 45 ? 0 : 1;
    const angle = random() * Math.PI * 2;
    const radius = Math.min(2.15, Math.sqrt(-2 * Math.log(random())));
    const x = (label ? 1.76 : -1.76) + Math.cos(angle) * radius * .69;
    const z = Math.sin(angle) * radius * .72;
    const point = mesh(group, geometry, luminous(colors[label]));
    return { label, x, z, point };
  });

  return (phase, t) => {
    const drift = phase === 0 ? 0 : phase === 1 ? Math.min(1, .35 + 1.1 * t) : 1;
    const angle = .43 * drift;
    const cut = phase === 2 ? 1.47 * Math.min(1, .4 + t * 1.15) : 0;
    const cosine = Math.cos(angle);
    const sine = Math.sin(angle);
    for (const { label, x, z, point } of points) {
      const px = cosine * x + sine * z + 1.47 * drift;
      const pz = -sine * x + cosine * z;
      const decision = phase === 2 ? cosine * (px - cut) - sine * pz : px;
      point.position.set(px, .14, pz);
      point.material.color.setHex((decision > 0) === Boolean(label) ? colors[label] : fault);
    }
    boundary.position.x = cut;
    boundary.rotation.y = phase === 2 ? angle : 0;
    boundary.material.color.setHex(phase === 1 ? fault : mint);
    old.visible = phase === 2;
  };
}

const animationBuilders = { control: pulseTask, qec: surfaceTask, readout: readoutTask };

function makeCutaway(scene, id, build) {
  const module = modules[id];
  const [width, height, depth] = module.frame;
  const group = new THREE.Group();
  group.position.set(module.x, .34, 0);
  scene.add(group);

  const figure = new THREE.Group();
  figure.position.y = .14;
  figure.scale.set(...module.scale);
  group.add(figure);
  const update = build(figure);

  box(group, [width, .09, depth], [0, .01, 0], darkSteel);
  const frameShape = new THREE.BoxGeometry(width, height, depth);
  const outline = new THREE.LineSegments(new THREE.EdgesGeometry(frameShape),
    new THREE.LineBasicMaterial({ color: module.color, transparent: true, opacity: .38 }));
  frameShape.dispose();
  outline.position.y = height / 2;
  group.add(outline);

  for (const x of [-width / 2, width / 2]) {
    box(group, [.075, height, .075], [x, height / 2, -depth / 2], darkSteel);
    trace(group, [[x, .09, depth / 2], [x, .09, -depth / 2], [x, height, -depth / 2]], module.color, .73);
  }

  const fade = fadeGroup(group);
  fade(0);
  return { update, fade };
}

const overviewPose = { target: vector(0, 1.68, 0), offset: vector(4.2, 7.02, 18.8), width: 16.7, height: 6.4 };
const insidePoses = Object.fromEntries(Object.entries(modules).map(([id, module]) => {
  const [x, y, z] = module.target;
  return [id, { target: vector(module.x + x, y, z), offset: vector(...module.offset),
    width: module.width, height: module.height }];
}));

export function createScene(canvas, view, onFrame) {
  const renderer = new THREE.WebGLRenderer({ canvas, alpha: true, antialias: true });
  renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 1.75));
  renderer.toneMapping = THREE.ACESFilmicToneMapping;
  renderer.toneMappingExposure = 1.38;
  const scene = new THREE.Scene();
  scene.add(new THREE.HemisphereLight(0xe6fff5, 0x324036, 2.25));
  const light = new THREE.DirectionalLight(0xffede0, 3.15);
  light.position.set(-7, 12, 9);
  scene.add(light);
  const fill = new THREE.DirectionalLight(0x98c8ed, 1.45);
  fill.position.set(6, 8, -9);
  scene.add(fill);
  const overview = new THREE.Group();
  scene.add(overview);
  const system = makeOverview(overview);
  const details = Object.fromEntries(Object.entries(animationBuilders).map(([id, build]) =>
    [id, makeCutaway(scene, id, build)]));
  const camera = new THREE.OrthographicCamera();
  const ray = new THREE.Raycaster();
  let mode = "system";
  let part = "control";
  let width = 1;
  let height = 1;
  let elapsed = 0;
  let last = 0;
  let playing = true;
  let onscreen = true;
  let reducedMotion = false;
  let transition;
  const pose = { ...overviewPose, target: overviewPose.target.clone(), offset: overviewPose.offset.clone() };
  const openings = Object.fromEntries(Object.keys(modules).map(id => [id, 0]));

  function placeCamera() {
    const aspect = width / height;
    const vertical = Math.max(pose.height, pose.width / aspect);
    camera.left = -vertical * aspect / 2;
    camera.right = vertical * aspect / 2;
    camera.top = vertical / 2;
    camera.bottom = -vertical / 2;
    camera.near = .1;
    camera.far = 100;
    camera.position.copy(pose.target).add(pose.offset);
    camera.lookAt(pose.target);
    camera.updateProjectionMatrix();
    camera.updateMatrixWorld();
  }

  function moveCamera(progress) {
    const { from, to, closed, opened } = transition;
    const eased = THREE.MathUtils.smoothstep(progress, 0, 1);
    pose.target.lerpVectors(from.target, to.target, eased);
    pose.offset.lerpVectors(from.offset, to.offset, eased);
    pose.width = THREE.MathUtils.lerp(from.width, to.width, eased);
    pose.height = THREE.MathUtils.lerp(from.height, to.height, eased);
    for (const id of Object.keys(modules)) {
      const opening = THREE.MathUtils.lerp(closed[id], Number(opened === id), eased);
      openings[id] = opening;
      system.shells[id](1 - THREE.MathUtils.smoothstep(opening, .34, .94));
      details[id].fade(THREE.MathUtils.smoothstep(opening, .42, 1));
    }
    if (progress === 1) transition = undefined;
    placeCamera();
  }

  function resize() {
    width = Math.max(1, view.clientWidth);
    height = Math.max(1, view.clientHeight);
    renderer.setSize(width, height, false);
    placeCamera();
    draw();
  }

  function draw() {
    let phase = 0;
    system.update(elapsed);
    if (mode === "animation") {
      const cycle = elapsed / 2.5;
      phase = Math.floor(cycle) % 3;
      details[part].update(phase, cycle % 1);
    }
    renderer.render(scene, camera);
    onFrame(phase, Boolean(transition));
  }

  function frame(now) {
    if (transition) {
      moveCamera(Math.min(1, (now - transition.start) / 1050));
      draw();
    } else if (onscreen && playing) {
      elapsed += Math.min(.08, (now - (last || now)) / 1000);
      draw();
    }
    last = now;
  }

  new ResizeObserver(resize).observe(view);
  new IntersectionObserver(([entry]) => { onscreen = entry.isIntersecting; }).observe(view);
  renderer.setAnimationLoop(frame);
  resize();

  return {
    show(viewMode, environment, play, reduce) {
      const changed = mode !== viewMode || (viewMode === "animation" && part !== environment);
      mode = viewMode;
      part = environment;
      playing = play;
      reducedMotion = reduce;
      if (changed) {
        elapsed = 0;
        transition = {
          start: performance.now(),
          from: { ...pose, target: pose.target.clone(), offset: pose.offset.clone() },
          to: mode === "system" ? overviewPose : insidePoses[part],
          closed: { ...openings },
          opened: mode === "animation" ? part : null,
        };
        moveCamera(reducedMotion ? 1 : 0);
      }
      system.highlight(null);
      draw();
    },
    play(value) { playing = value; },
    reduceMotion(value) {
      reducedMotion = value;
      if (reducedMotion && transition) {
        moveCamera(1);
        draw();
      }
    },
    step(index) { elapsed = index * 2.5 + 2.49; draw(); },
    hit(clientX, clientY) {
      if (mode !== "system" || transition) return null;
      const bounds = canvas.getBoundingClientRect();
      ray.setFromCamera(new THREE.Vector2(
        2 * (clientX - bounds.left) / bounds.width - 1,
        1 - 2 * (clientY - bounds.top) / bounds.height,
      ), camera);
      return ray.intersectObjects(system.targets, false)[0]?.object.userData.part ?? null;
    },
    highlight(id) {
      system.highlight(id);
      draw();
    },
    label(id) {
      const point = system.markers[id].clone().project(camera);
      return [(point.x + 1) * width / 2, (1 - point.y) * height / 2];
    },
  };
}
