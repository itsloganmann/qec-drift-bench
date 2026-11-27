// The task map: a superconducting chip in its package, drawn in three.js. Each task family owns
// one kind of structure on the die (readout resonators, XY drive lines, flux lines, the
// surface-code lattice). Hover a structure to light it, click it or its numbered balloon to fly
// the camera there. The device itself is described in chip-layout.js.

import * as THREE from 'three'
import { OrbitControls } from 'three/addons/controls/OrbitControls.js'
import { device, FAMILIES, VIEWS, CALLOUT, K } from './chip-layout.js'
import { buildDie } from './chip-die.js'
import { buildBonds, buildCarrier } from './chip-package.js'
import { makeMaterials, paint, studio, KEY, TONE } from './chip-look.js'

const SPEED = 3.1 // signal speed along a line, mm per second of animation
const ease = (t) => (t < 0.5 ? 4 * t * t * t : 1 - Math.pow(-2 * t + 2, 3) / 2)

function unavailable(host) {
  const p = document.createElement('p')
  p.textContent = 'The 3D chip needs WebGL, which this browser has switched off. The parts list below has the same four tasks.'
  p.style.cssText = 'position:absolute;inset:0;margin:auto;height:max-content;max-width:34ch;padding:0 24px;text-align:center;color:var(--ink-2)'
  host.appendChild(p)
  return { select() {}, home() {}, setVisible() {} }
}

export function createChip(host, overlay, { onSelect = () => {}, onHover = () => {} } = {}) {
  const still = window.matchMedia('(prefers-reduced-motion: reduce)')
  let renderer
  try {
    renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true, stencil: true, powerPreference: 'high-performance' })
  } catch {
    return unavailable(host)
  }
  renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 2))
  renderer.toneMapping = TONE
  renderer.shadowMap.enabled = true
  renderer.shadowMap.type = THREE.VSMShadowMap
  renderer.localClippingEnabled = true
  renderer.shadowMap.autoUpdate = false // nothing that casts a shadow ever moves
  host.prepend(renderer.domElement)

  const scene = new THREE.Scene()
  const camera = new THREE.PerspectiveCamera(24, 1, 0.5, 300)
  const controls = new OrbitControls(camera, renderer.domElement)
  controls.enableDamping = true
  controls.dampingFactor = 0.09
  controls.rotateSpeed = 0.7
  controls.enableZoom = false
  controls.enablePan = false
  controls.minPolarAngle = 0.12
  controls.maxPolarAngle = 1.32

  const pmrem = new THREE.PMREMGenerator(renderer)
  const envs = {}
  const key = new THREE.DirectionalLight(0xffffff, 1.3)
  key.position.set(...KEY)
  key.castShadow = true
  key.shadow.mapSize.set(2048, 2048)
  Object.assign(key.shadow.camera, { left: -11, right: 11, top: 11, bottom: -11, near: 2, far: 40 })
  key.shadow.radius = 3.5
  key.shadow.blurSamples = 12
  key.shadow.bias = -0.0004
  scene.add(key)

  const M = makeMaterials(renderer)
  const dev = device()
  const die = buildDie(dev, M)
  const bonds = buildBonds(dev, M)
  scene.add(die.root, bonds.ground, buildCarrier(M))
  for (const f of FAMILIES) if (bonds.signal[f]) die.fam[f].add(bonds.signal[f])

  // State. `level` holds the eased emphasis of each family; `want` is where it is heading.
  let selected = null
  let hovered = null
  let focused = false
  let zoom = 0 // eased 0 to 1 as the camera goes from the whole package to one family
  let dark = false
  const shown = Object.fromEntries(FAMILIES.map((f) => [f, true]))
  const level = Object.fromEntries(FAMILIES.map((f) => [f, { tint: 1, lift: 0, glow: 0 }]))
  const tones = { metal: new THREE.Color(), fam: Object.fromEntries(FAMILIES.map((f) => [f, new THREE.Color()])) }
  function want(f) {
    const hot = f === hovered
    const on = f === selected
    // Zoomed in, only the current family keeps its colour. From afar, pointing at one family
    // pales the others so that its parts read as one group.
    const tint = on || hot ? 1 : focused ? 0.1 : hovered ? 0.4 : 1
    return { tint, lift: hot ? 0.5 : on ? 0.16 : 0, glow: on && !still.matches ? 1 : 0 }
  }
  const mixed = new THREE.Color()
  function applyLevels() {
    for (const f of FAMILIES) {
      const { tint, lift, glow } = level[f]
      const m = M.fam[f]
      m.color.copy(tones.metal).lerp(tones.fam[f], tint)
      m.metalness = 1 - 0.88 * tint
      m.roughness = 0.3 + 0.3 * tint
      m.envMapIntensity = 1 - 0.45 * tint
      m.emissive.copy(tones.fam[f])
      m.emissiveIntensity = (0.06 + lift) * tint
      M.glow[f].uniforms.uGain.value = glow
      M.glow[f].uniforms.uColor.value.copy(mixed.copy(tones.fam[f]).lerp(M.white, dark ? 0.5 : 0.68))
      M.glow[f].visible = glow > 0.01
    }
  }
  function easeLevels(dt) {
    const k = 1 - Math.exp(-dt / 0.11)
    let moving = false
    for (const f of FAMILIES) {
      const to = want(f)
      for (const p of ['tint', 'lift', 'glow']) {
        const d = to[p] - level[f][p]
        if (Math.abs(d) > 0.004) { level[f][p] += d * k; moving = true } else level[f][p] = to[p]
      }
    }
    applyLevels()
    return moving
  }
  function repaint() {
    dark = paint(M, tones, renderer)
    scene.environment = envs[dark] ??= pmrem.fromScene(studio(dark), 0.03).texture
    key.intensity = dark ? 1.0 : 1.3
    renderer.shadowMap.needsUpdate = true
    applyLevels()
    request()
  }

  // If a panel (.layers) lies over the top left of the stage, views and balloons keep clear of it.
  const panelEl = overlay.root.querySelector('.layers')
  let panel = null
  function measure() {
    if (!panelEl) return
    const r = panelEl.getBoundingClientRect()
    const o = host.getBoundingClientRect()
    panel = { l: r.left - o.left, t: r.top - o.top, r: r.right - o.left, b: r.bottom - o.top }
  }

  // Camera. A view is a box on the die plus a direction; fit() finds the camera that frames it
  // in the stage as it is now, clear of the panel and hint that overlay it.
  const scratch = camera.clone()
  const corner = new THREE.Vector3()
  function fit(name) {
    const w = host.clientWidth
    const h = host.clientHeight
    const v = VIEWS[name === 'home' && w < 560 ? 'die' : name]
    const [x0, z0, x1, z1] = v.box
    const [y0, y1] = v.y || [0, 0.3]
    const pad = name === 'home' ? { l: 14, r: 14, t: 16, b: w < 560 ? 40 : 26 } : { l: 26, r: 26, t: 30, b: 44 }
    // On a narrow stage the layers panel takes a real share of the width: frame the view below it.
    if (panel && panel.r - panel.l > 0.35 * w) pad.t = Math.max(pad.t, panel.b + 8)
    const ax = 1 - (pad.l + pad.r) / w
    const ay = 1 - (pad.t + pad.b) / h
    const dir = new THREE.Vector3(Math.sin(v.pol) * Math.sin(v.az), Math.cos(v.pol), Math.sin(v.pol) * Math.cos(v.az))
    const target = new THREE.Vector3((x0 + x1) / 2, 0, (z0 + z1) / 2)
    scratch.copy(camera)
    let dist = 40
    for (let it = 0; it < 7; it++) {
      scratch.position.copy(target).addScaledVector(dir, dist)
      scratch.lookAt(target)
      scratch.updateMatrixWorld()
      let lo = [Infinity, Infinity]
      let hi = [-Infinity, -Infinity]
      for (const x of [x0, x1]) for (const y of [y0, y1]) for (const z of [z0, z1]) {
        corner.set(x, y, z).project(scratch)
        lo = [Math.min(lo[0], corner.x), Math.min(lo[1], corner.y)]
        hi = [Math.max(hi[0], corner.x), Math.max(hi[1], corner.y)]
      }
      const halfH = dist * Math.tan(THREE.MathUtils.degToRad(camera.fov / 2))
      const right = new THREE.Vector3().setFromMatrixColumn(scratch.matrixWorld, 0)
      const up = new THREE.Vector3().setFromMatrixColumn(scratch.matrixWorld, 1)
      target.addScaledVector(right, ((lo[0] + hi[0]) / 2 - (pad.l - pad.r) / w) * halfH * camera.aspect)
      target.addScaledVector(up, ((lo[1] + hi[1]) / 2 - (pad.b - pad.t) / h) * halfH)
      dist *= Math.max((hi[0] - lo[0]) / (2 * ax), (hi[1] - lo[1]) / (2 * ay))
    }
    return { pos: target.clone().addScaledVector(dir, dist), target }
  }
  let view = 'home'
  let flight = null
  let roamed = false
  const sph0 = new THREE.Spherical()
  const sph1 = new THREE.Spherical()
  const off = new THREE.Vector3()
  function go(name, glide = true) {
    view = name
    focused = name !== 'home'
    roamed = false
    const to = fit(name)
    if (!glide || still.matches) {
      camera.position.copy(to.pos)
      controls.target.copy(to.target)
      flight = null
    } else {
      sph0.setFromVector3(off.subVectors(camera.position, controls.target))
      sph1.setFromVector3(off.subVectors(to.pos, to.target))
      let dTheta = sph1.theta - sph0.theta
      dTheta -= Math.round(dTheta / (2 * Math.PI)) * 2 * Math.PI
      flight = { t: 0, t0: controls.target.clone(), t1: to.target, dTheta, span: 0.95 + 0.25 * Math.min(1, to.target.distanceTo(controls.target) / 6) }
    }
    home.hidden = name === 'home'
    if (hint) hint.style.visibility = name === 'home' ? '' : 'hidden'
    request()
  }
  function fly(dt) {
    flight.t = Math.min(1, flight.t + dt / flight.span)
    const e = ease(flight.t)
    controls.target.lerpVectors(flight.t0, flight.t1, e)
    off.setFromSphericalCoords(sph0.radius + (sph1.radius - sph0.radius) * e, sph0.phi + (sph1.phi - sph0.phi) * e, sph0.theta + flight.dTheta * e)
    camera.position.copy(controls.target).add(off)
    if (flight.t >= 1) flight = null
  }
  controls.addEventListener('start', () => { flight = null; roamed = true; renderer.domElement.style.cursor = 'grabbing' })
  controls.addEventListener('end', () => { renderer.domElement.style.cursor = hovered ? 'pointer' : 'grab' })

  // Picking uses generous invisible shapes over each structure, not the hairline geometry.
  const ray = new THREE.Raycaster()
  const ndc = new THREE.Vector2()
  function pick(ev) {
    const r = renderer.domElement.getBoundingClientRect()
    ndc.set(((ev.clientX - r.left) / r.width) * 2 - 1, -((ev.clientY - r.top) / r.height) * 2 + 1)
    ray.setFromCamera(ndc, camera)
    // Where shapes overlap, the finer structure wins: a control line over the lattice it feeds.
    const hits = ray.intersectObjects(die.pickers.filter((m) => shown[m.userData.family]), false).map((h) => h.object.userData.family)
    return ['flux', 'pulse', 'readout', 'qec'].find((f) => hits.includes(f)) ?? null
  }
  function hover(f) {
    if (f === hovered) return
    hovered = f
    renderer.domElement.style.cursor = f ? 'pointer' : 'grab'
    for (const g of FAMILIES) balloons[g].b.classList.toggle('hot', g === f)
    onHover(f)
    request()
  }
  let downAt = null
  const el = renderer.domElement
  el.style.cursor = 'grab'
  el.addEventListener('pointerdown', (e) => { downAt = [e.clientX, e.clientY] })
  el.addEventListener('pointerup', (e) => {
    if (!downAt || Math.hypot(e.clientX - downAt[0], e.clientY - downAt[1]) > 5) return
    const f = pick(e)
    if (f) onSelect(f)
  })
  el.addEventListener('pointermove', (e) => { if (!e.buttons) hover(pick(e)) })
  el.addEventListener('pointerleave', () => hover(null))
  el.addEventListener('dblclick', (e) => { if (!pick(e)) go('home') })
  host.addEventListener('keydown', (e) => { if (e.key === 'Escape' && view !== 'home') go('home') })

  // Balloons: numbered callouts with leader lines, as on an engineering drawing.
  const svgNS = 'http://www.w3.org/2000/svg'
  const balloons = {}
  for (const [i, f] of FAMILIES.entries()) {
    const line = document.createElementNS(svgNS, 'line')
    line.setAttribute('class', 'leader')
    const dot = document.createElementNS(svgNS, 'circle')
    dot.setAttribute('r', '2.5')
    dot.setAttribute('class', 'leader-dot')
    overlay.svg.append(line, dot)
    const b = document.createElement('button')
    b.className = 'balloon'
    b.dataset.family = f
    b.type = 'button'
    b.textContent = String(i + 1)
    b.setAttribute('aria-label', `Item ${i + 1}: open the ${overlay.names?.[f] ?? f} task`)
    b.addEventListener('click', () => onSelect(f))
    b.addEventListener('pointerenter', () => hover(f))
    b.addEventListener('pointerleave', () => hover(null))
    b.addEventListener('focus', () => hover(f))
    b.addEventListener('blur', () => hover(null))
    overlay.root.appendChild(b)
    const { at, tag } = CALLOUT[f]
    balloons[f] = { line, dot, b, at: new THREE.Vector3(at[0], 0, at[1]), tag: new THREE.Vector3(tag[0], 0, tag[1]) }
  }
  const home = document.createElement('button')
  home.type = 'button'
  home.className = 'btn chip-home'
  home.textContent = 'Show the whole chip'
  home.hidden = true
  home.style.cssText = 'position:absolute;right:12px;bottom:10px;z-index:2;background:var(--sheet)'
  home.addEventListener('click', () => go('home'))
  overlay.root.appendChild(home)

  const hint = overlay.root.querySelector('.hint')
  const centre = new THREE.Vector3()
  const p = new THREE.Vector3()
  function placeBalloons() {
    const w = host.clientWidth
    const h = host.clientHeight
    centre.set(0, 0, 0).project(camera)
    const cx = (centre.x * 0.5 + 0.5) * w
    const cy = (-centre.y * 0.5 + 0.5) * h
    const under = (px, py) => panel && px > panel.l - 20 && px < panel.r + 20 && py > panel.t - 20 && py < panel.b + 20
    const placed = []
    for (const f of FAMILIES) {
      const { line, dot, b, at, tag } = balloons[f]
      p.copy(at).project(camera)
      const x = (p.x * 0.5 + 0.5) * w
      const y = (-p.y * 0.5 + 0.5) * h
      const show = shown[f] && p.z < 1 && x > 8 && x < w - 8 && y > 8 && y < h - 8
      b.style.visibility = line.style.visibility = dot.style.visibility = show ? 'visible' : 'hidden'
      if (!show) continue
      // From afar, push the balloon outward from the chip centre so it sits clear of the die.
      let dx = x - cx
      let dy = y - cy
      const d = Math.hypot(dx, dy)
      const mid = d < 40
      if (mid) { dx = 0.88; dy = -0.47 } else { dx /= d; dy /= d }
      const reach = Math.max(46, Math.min(84, w * 0.1)) * (mid ? 2.9 : 1)
      let bx = x + dx * reach
      let by = y + dy * reach
      // Up close, move it to its own patch of bare ground beside the structure. A neighbouring
      // family's balloon is dropped if that patch is off the stage or under the panel.
      if (zoom > 0.001) {
        p.copy(tag).project(camera)
        let tx = (p.x * 0.5 + 0.5) * w - x
        let ty = (-p.y * 0.5 + 0.5) * h - y
        const short = 40 / (Math.hypot(tx, ty) || 1)
        if (short > 1) { tx *= short; ty *= short }
        const fits = x + tx > 24 && x + tx < w - 24 && y + ty > 24 && y + ty < h - 24 && !under(x + tx, y + ty)
        if (zoom > 0.5 && f !== selected && !fits) {
          b.style.visibility = line.style.visibility = dot.style.visibility = 'hidden'
          continue
        }
        bx += (x + tx - bx) * zoom
        by += (y + ty - by) * zoom
      }
      bx = Math.min(w - 20, Math.max(20, bx))
      by = Math.min(h - 20, Math.max(20, by))
      if (under(bx, by)) {
        if (x > panel.r) bx = panel.r + 22
        else by = panel.b + 22
      }
      if (!home.hidden && bx > w - 200 && by > h - 62) by = h - 62
      for (const q of placed) {
        if (Math.hypot(bx - q[0], by - q[1]) < 36) { bx += dy * 38; by -= dx * 38 }
      }
      placed.push([bx, by])
      line.setAttribute('x1', x); line.setAttribute('y1', y)
      line.setAttribute('x2', bx); line.setAttribute('y2', by)
      dot.setAttribute('cx', x); dot.setAttribute('cy', y)
      b.style.transform = `translate(${bx - 15}px, ${by - 15}px)`
      b.classList.toggle('on', f === selected)
    }
  }

  // Render only while something is moving, and not at all while the stage is off screen.
  let raf = 0
  let last = 0
  let onScreen = true
  let phase = 0
  function frame(now) {
    raf = 0
    const dt = Math.min(Math.max((now - last) / 1000, 0), 0.05)
    last = now
    let busy = false
    if (flight) { fly(dt); busy = true }
    busy = controls.update() || busy
    busy = easeLevels(dt) || busy
    const z1 = focused ? 1 : 0
    if (still.matches || Math.abs(z1 - zoom) < 0.004) zoom = z1
    else { zoom += (z1 - zoom) * (1 - Math.exp(-dt / 0.22)); busy = true }
    if (selected && shown[selected] && !still.matches) {
      phase = (phase + dt * SPEED) % K.cycle
      for (const f of FAMILIES) M.glow[f].uniforms.uHead.value = phase
      busy = true
    }
    renderer.render(scene, camera)
    placeBalloons()
    if (busy && onScreen && !document.hidden) request()
  }
  function request() { if (!raf) raf = requestAnimationFrame(frame) }
  controls.addEventListener('change', request)
  new IntersectionObserver(([e]) => { onScreen = e.isIntersecting; if (onScreen) request() }).observe(host)
  document.addEventListener('visibilitychange', request)

  function resize() {
    const w = host.clientWidth
    const h = host.clientHeight
    if (!w || !h) return
    measure()
    renderer.setSize(w, h, false)
    camera.aspect = w / h
    camera.updateProjectionMatrix()
    overlay.svg.setAttribute('viewBox', `0 0 ${w} ${h}`)
    // Keep the framing through a resize. If the camera is in flight (picking a task can change
    // the stage's height), carry on gliding to the corrected spot instead of jumping there.
    if (!roamed) go(view, flight !== null)
    request()
  }
  const sizes = new ResizeObserver(resize)
  sizes.observe(host)
  if (panelEl) sizes.observe(panelEl)
  resize()

  window.matchMedia('(prefers-color-scheme: dark)').addEventListener('change', repaint)
  new MutationObserver(repaint).observe(document.documentElement, { attributes: true, attributeFilter: ['data-theme', 'class', 'style'] })
  still.addEventListener('change', request)
  repaint()

  return {
    // Mark a family as the current one; with move, fly the camera to it.
    select(f, move = true) {
      selected = FAMILIES.includes(f) ? f : null
      if (move && selected) go(selected)
      request()
    },
    // Back to the whole package. The current family stays marked.
    home() { go('home') },
    setVisible(f, on) {
      if (!(f in shown)) return
      shown[f] = !!on
      die.fam[f].visible = shown[f]
      if (!on && hovered === f) hover(null)
      request()
    },
  }
}
