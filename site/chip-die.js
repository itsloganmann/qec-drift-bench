// Builds the patterned film on the die from the layout: etched gaps, conductors, junctions,
// airbridges, the travelling-signal overlays and the invisible shapes used for picking.

import * as THREE from 'three'
import { mergeGeometries } from 'three/addons/utils/BufferGeometryUtils.js'
import { RoundedBoxGeometry } from 'three/addons/geometries/RoundedBoxGeometry.js'
import { Flat, frame, slice, pathLength, pointAt, stamp } from './chip-geom.js'
import { K, FAMILIES, launchOutline } from './chip-layout.js'
import { shadowOf } from './chip-look.js'

// Heights of the film layers above the die face. They are microns apart: enough to sort them,
// far too little to see.
export const Y = { film: 0.001, keep: 0.002, gap: 0.003, cond: 0.004, lead: 0.005, jj: 0.006, glow: 0.007 }

const cross = (q, L, w) => {
  const h = w / 2
  return [[-L, -h], [-h, -h], [-h, -L], [h, -L], [h, -h], [L, -h], [L, h], [h, h], [h, L], [-h, L], [-h, h], [-L, h]].map(([x, z]) => [q.x + x, q.z + z])
}

function bridgeGeometry() {
  const span = 0.105
  const top = 0.062
  const h = 0.034
  const t = 0.007
  const w = 0.032
  const sh = new THREE.Shape()
  sh.moveTo(-span, 0); sh.lineTo(-top, h); sh.lineTo(top, h); sh.lineTo(span, 0)
  sh.lineTo(span - 0.02, 0); sh.lineTo(top - 0.006, h - t); sh.lineTo(-top + 0.006, h - t); sh.lineTo(-span + 0.02, 0)
  const arch = new THREE.ExtrudeGeometry(sh, { depth: w, bevelEnabled: false }).translate(0, 0, -w / 2)
  const foot = (x) => new THREE.BoxGeometry(0.044, 0.006, 0.046).translate(x, 0.003, 0).toNonIndexed()
  return mergeGeometries([arch, foot(-span + 0.012), foot(span - 0.012)])
}

export function buildDie(dev, M) {
  const root = new THREE.Group()
  const fam = Object.fromEntries(FAMILIES.map((f) => [f, new THREE.Group()]))
  const flats = {}
  const lay = (f, k) => (flats[`${f}:${k}`] ??= new Flat())
  const bridges = Object.fromEntries(FAMILIES.map((f) => [f, []]))
  const pick = Object.fromEntries(FAMILIES.map((f) => [f, new Flat()]))

  // The die: a silicon slab, with the metal film stopping short of the diced edge.
  const slab = new THREE.Mesh(new RoundedBoxGeometry(K.die, K.thick, K.die, 3, 0.03), M.si)
  slab.position.y = -K.thick / 2
  slab.castShadow = slab.receiveShadow = true
  root.add(slab)
  const film = new THREE.Mesh(new THREE.PlaneGeometry(2 * K.film, 2 * K.film).rotateX(-Math.PI / 2), M.film)
  film.position.y = Y.film
  film.receiveShadow = true
  root.add(film)

  // Qubits: a cross-shaped island floating in a cross-shaped pocket.
  const { arm: L, armW: S, pocket: W, keep } = K
  for (const q of dev.qubits) {
    lay('qec', 'keep').poly(cross(q, L + W + keep, S + 2 * W + 2 * keep), Y.keep)
    lay('qec', 'gap').poly(cross(q, L + W, S + 2 * W), Y.gap)
    lay('qec', 'cond').poly(cross(q, L, S), Y.cond)
    if (q.anc) lay('qec', 'glow').poly(cross(q, L, S), Y.glow, 6.3)
    // Josephson junctions bridge the pocket on one flank of an arm: two for a SQUID, one otherwise.
    const f = (a, b) => [q.x + q.jj.dir[0] * a, q.z + q.jj.side * b]
    const b0 = S / 2 - 0.008
    const b1 = S / 2 + W + 0.008
    for (const da of q.anc ? [-0.032, 0.032] : [0]) {
      const a = K.squidAt + da
      lay('qec', 'lead').poly([f(a - 0.007, b0), f(a + 0.007, b0), f(a + 0.007, b1), f(a - 0.007, b1)], Y.lead)
      const m = S / 2 + W / 2
      lay('qec', 'jj').poly([f(a - 0.013, m - 0.012), f(a + 0.013, m - 0.012), f(a + 0.013, m + 0.012), f(a - 0.013, m + 0.012)], Y.jj)
    }
  }
  for (let v = -2; v <= 2; v++) {
    const us = dev.qubits.filter((q) => q.v === v).map((q) => q.u)
    pick.qec.rect(Math.min(...us) - 0.46, v - 0.5, Math.max(...us) + 0.46, v + 0.5, 0)
  }

  // Couplers: a short floating strip with a bar at each end, facing the two arm tips.
  for (const c of dev.couplers) {
    const f = frame([c.x, c.z], c.dir)
    const a0 = L + W + K.tee.c / 2
    const a1 = K.pitch - a0
    const sVal = 0.9 + c.step * 1.2
    for (const a of [a0, a1]) {
      const bar = [f(a, -K.tee.half), f(a, K.tee.half)]
      lay('qec', 'keep').ribbon(bar, K.tee.c + 2 * (K.bus.g + keep), Y.keep, { ext0: K.bus.g + keep, ext1: K.bus.g + keep })
      lay('qec', 'gap').ribbon(bar, K.tee.c + 2 * K.bus.g, Y.gap, { ext0: K.bus.g, ext1: K.bus.g })
      lay('qec', 'cond').ribbon(bar, K.tee.c, Y.cond)
      lay('qec', 'glow').ribbon(bar, K.tee.c, Y.glow, { s0: sVal, still: true })
    }
    const strip = [f(a0, 0), f(a1, 0)]
    lay('qec', 'keep').ribbon(strip, K.bus.c + 2 * (K.bus.g + keep), Y.keep)
    lay('qec', 'gap').ribbon(strip, K.bus.c + 2 * K.bus.g, Y.gap)
    lay('qec', 'cond').ribbon(strip, K.bus.c, Y.cond)
    lay('qec', 'glow').ribbon(strip, K.bus.c * 1.6, Y.glow, { s0: sVal, still: true })
    bridges.qec.push({ p: f(K.pitch / 2, 0), t: c.dir, k: 0.8 })
  }

  // Coplanar-waveguide lines: a hole-free margin, the etched gap, then the centre conductor.
  for (const ln of dev.lines) {
    const f = ln.family
    const w = ln.c + 2 * ln.g
    const total = pathLength(ln.poly)
    const gapEnd = ln.short ? slice(ln.poly, 0, total - 0.075) : ln.poly
    lay(f, 'keep').ribbon(ln.poly, w + 2 * keep, Y.keep, { ext1: ln.open ? ln.g + keep : 0 })
    lay(f, 'gap').ribbon(gapEnd, w, Y.gap, { ext1: ln.open ? ln.g : 0 })
    lay(f, 'cond').ribbon(ln.poly, ln.c, Y.cond)
    lay(f, 'glow').ribbon(ln.poly, ln.c * 1.5, Y.glow, { s0: ln.delay })
    pick[f].ribbon(ln.poly, ln.kind === 'feed' ? 0.5 : ln.kind === 'res' ? 0.42 : 0.5, 0)

    if (ln.short) {
      // The flux line ends by merging into the ground on one side; its return current then
      // runs along the edge next to the SQUID. One gap closes early, the other wraps the tip.
      const end = pointAt(ln.poly, total)
      const e = frame(end.p, end.t)
      const o = ln.short * (ln.c / 2 + ln.g / 2)
      lay(f, 'gap').ribbon([e(-0.09, o), e(ln.g, o)], ln.g, Y.gap)
      lay(f, 'gap').ribbon([e(ln.g / 2, o + ln.short * ln.g / 2), e(ln.g / 2, -ln.short * ln.c / 2)], ln.g, Y.gap)
    }
    if (ln.claw) {
      // The open end of a resonator forks round the qubit's arm tip.
      const { q, dir } = ln.claw
      const c = frame([q.x, q.z], dir)
      const base = L + K.claw.g + K.claw.c / 2
      const off = S / 2 + K.claw.g + K.claw.c / 2
      const u = [c(L - K.claw.wrap, off), c(base, off), c(base, -off), c(L - K.claw.wrap, -off)]
      const cw = K.claw.c + 2 * K.claw.g
      lay(f, 'keep').ribbon(u, cw + 2 * keep, Y.keep, { ext0: K.claw.g + keep, ext1: K.claw.g + keep })
      lay(f, 'gap').ribbon(u, cw, Y.gap, { ext0: K.claw.g, ext1: K.claw.g })
      lay(f, 'cond').ribbon(u, K.claw.c, Y.cond)
      pick[f].rect(q.x - 0.2, q.z + dir[1] * 0.42 - 0.2, q.x + 0.2, q.z + dir[1] * 0.42 + 0.2, 0)
    }

    // Airbridges tie the two ground planes together across the line: on every straight run,
    // but not where a resonator runs alongside its feedline.
    let acc = 0
    for (let i = 1; i < ln.poly.length; i++) {
      const a = ln.poly[i - 1]
      const b = ln.poly[i]
      const l = Math.hypot(b[0] - a[0], b[1] - a[1])
      const first = acc < 1e-6
      acc += l
      if (l < 0.3 || (first && ln.skipFirst)) continue
      const n = Math.max(1, Math.round(l / 0.55))
      for (let j = 0; j < n; j++) {
        const u = (j + 0.5) / n
        const p = [a[0] + (b[0] - a[0]) * u, a[1] + (b[1] - a[1]) * u]
        if ((ln.clear || []).some(([x0, z0, x1, z1]) => p[0] > x0 && p[0] < x1 && p[1] > z0 && p[1] < z1)) continue
        bridges[f].push({ p, t: [(b[0] - a[0]) / l, (b[1] - a[1]) / l], k: ln.kind === 'feed' ? 1.25 : 1 })
      }
    }
  }

  // Launch pads: the line widens to a pad big enough to wire-bond, keeping its proportions.
  for (const l of dev.launches) {
    lay(l.family, 'keep').poly(launchOutline(l, K.padGap + keep), Y.keep)
    lay(l.family, 'gap').poly(launchOutline(l, K.padGap), Y.gap)
    lay(l.family, 'cond').poly(launchOutline(l), Y.cond)
    const c = frame(l.o, l.a)
    pick[l.family].poly([c(0.1, -0.4), c(0.1, 0.4), c(1.05, 0.4), c(1.05, -0.4)], 0)
  }

  // Alignment crosses in the corners and the die label, etched like everything else.
  for (const [sx, sz] of [[1, 1], [1, -1], [-1, 1], [-1, -1]]) {
    lay('die', 'gap').poly(cross({ x: sx * 4.5, z: sz * 4.5 }, 0.12, 0.028), Y.gap)
    lay('die', 'keep').rect(sx * 4.5 - 0.17, sz * 4.5 - 0.17, sx * 4.5 + 0.17, sz * 4.5 + 0.17, Y.keep)
  }
  const wLabel = stamp(lay('die', 'gap'), 'QAB-17 D3 R0.1', -1.75, 4.24, 0.19, Y.gap)
  lay('die', 'keep').rect(-1.82, 4.17, -1.75 + wLabel + 0.04, 4.5, Y.keep)

  const matFor = (f, k) => ({ keep: M.plain, gap: M.gap, cond: M.fam[f], lead: M.lead, jj: M.jj, glow: M.glow[f] })[k]
  for (const [id, flat] of Object.entries(flats)) {
    const [f, k] = id.split(':')
    const mesh = new THREE.Mesh(flat.geometry(), matFor(f, k))
    mesh.receiveShadow = k !== 'glow'
    mesh.renderOrder = Object.keys(Y).indexOf(k)
    ;(fam[f] || root).add(mesh)
  }

  // One instanced mesh of bridges per family, so a layer can be switched off whole.
  const bg = bridgeGeometry()
  const m4 = new THREE.Matrix4()
  const sc = new THREE.Matrix4()
  for (const f of FAMILIES) {
    const list = bridges[f]
    if (!list.length) continue
    const inst = new THREE.InstancedMesh(bg, M.al, list.length)
    list.forEach((b, i) => {
      m4.makeBasis(new THREE.Vector3(-b.t[1], 0, b.t[0]), new THREE.Vector3(0, 1, 0), new THREE.Vector3(-b.t[0], 0, -b.t[1]))
      m4.setPosition(b.p[0], Y.cond, b.p[1])
      inst.setMatrixAt(i, m4.multiply(sc.makeScale(b.k, 1, 1)))
    })
    inst.receiveShadow = true
    fam[f].add(inst, shadowOf(inst, Y.glow + 0.002, M.castDie))
  }

  const pickers = FAMILIES.map((f) => {
    const m = new THREE.Mesh(pick[f].geometry())
    m.userData.family = f
    return m
  })
  for (const f of FAMILIES) root.add(fam[f])
  return { root, fam, pickers }
}
