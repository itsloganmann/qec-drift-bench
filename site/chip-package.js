// The package round the die: wire bonds, the gold-plated carrier board with its coplanar traces
// and via fences, the copper base it is screwed to, and the soft shadow on the sheet.

import * as THREE from 'three'
import { mergeGeometries } from 'three/addons/utils/BufferGeometryUtils.js'
import { Flat, frame } from './chip-geom.js'
import { K, FAMILIES } from './chip-layout.js'
import { shadowOf } from './chip-look.js'

export const BOARD = { half: 7.2, round: 0.7, cavity: 5.25, top: -0.03, thick: 0.5, base: 0.85, screw: 6.35, via: 6.5 }
const TRACE = { c: 0.3, g: 0.07, pad: 0.2, anti: 0.27 }
const H = K.die / 2
const SIDES = [
  { at: (p) => [p, -H], a: [0, 1] }, { at: (p) => [p, H], a: [0, -1] }, { at: (p) => [-H, p], a: [1, 0] }, { at: (p) => [H, p], a: [-1, 0] },
]
const PORTS = [-3, -2, -1, 0, 1, 2, 3].map((k) => k * K.ports)

// A small repeatable random source, so the hand-bonded look is the same on every load.
function seeded(seed) {
  let a = seed
  return () => { a |= 0; a = (a + 0x6d2b79f5) | 0; let t = Math.imul(a ^ (a >>> 15), 1 | a); t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t; return ((t ^ (t >>> 14)) >>> 0) / 4294967296 }
}

// One aluminium wedge bond from a to b: it leaves the first bond steeply, peaks early and comes
// down at a shallow angle, with a flattened foot at each end.
function bond(a, b, h, r) {
  const d = new THREE.Vector3().subVectors(b, a)
  const L = Math.hypot(d.x, d.z)
  const dir = new THREE.Vector3(d.x / L, 0, d.z / L)
  const up = new THREE.Vector3(0, 1, 0)
  const p1 = a.clone().addScaledVector(dir, 0.1 * L).addScaledVector(up, 1.25 * h)
  const p2 = b.clone().addScaledVector(dir, -0.5 * L).addScaledVector(up, 0.85 * h)
  const tube = new THREE.TubeGeometry(new THREE.CubicBezierCurve3(a, p1, p2, b), 20, r, 6, false)
  const yaw = -Math.atan2(dir.z, dir.x)
  const foot = (p, back) => new THREE.SphereGeometry(1, 8, 6).scale(r * 2.6, r * 0.55, r * 1.5).rotateY(yaw).translate(p.x + dir.x * back, p.y + r * 0.3, p.z + dir.z * back)
  return [tube, foot(a, -r * 1.6), foot(b, r * 1.6)]
}

export function buildBonds(dev, M) {
  const rnd = seeded(17)
  const jit = (s) => (rnd() - 0.5) * 2 * s
  const groups = Object.fromEntries(FAMILIES.map((f) => [f, []]))
  const ground = []
  const R = 0.017
  const gap = BOARD.cavity - K.die / 2
  const at = (q, y) => new THREE.Vector3(q[0], y, q[1])
  for (const l of dev.launches) {
    const f = frame(l.o, l.a)
    for (const v of [-0.088, 0, 0.088]) {
      const a = f(K.padInset + K.padGap + K.padLen * 0.5 + jit(0.03), v + jit(0.008))
      const b = f(-gap - 0.32 + jit(0.04), v * 1.15 + jit(0.012))
      groups[l.family].push(...bond(at(a, 0.004), at(b, BOARD.top), 0.3 + jit(0.03), R))
    }
  }
  // Ground bonds stitch the die's ground plane to the board's between every pair of ports.
  const spots = []
  for (let k = -3; k < 3; k++) spots.push((k + 0.5) * K.ports - 0.13, (k + 0.5) * K.ports + 0.13)
  spots.push(-4.68, -4.44, 4.44, 4.68)
  for (const side of SIDES) {
    for (const p of spots) {
      const f = frame(side.at(p), side.a)
      ground.push(...bond(at(f(0.27 + jit(0.03), jit(0.02)), 0.002), at(f(-gap - 0.24 + jit(0.04), jit(0.03)), BOARD.top), 0.22 + jit(0.03), R))
    }
  }
  // The shadow map is far too coarse for a 30 micron wire, so each set of wires carries its own
  // shadow: one copy flattened onto the die and one onto the board.
  const group = (list) => {
    const wires = new THREE.Mesh(mergeGeometries(list), M.al)
    return new THREE.Group().add(wires, shadowOf(wires, 0.009, M.castDie), shadowOf(wires, BOARD.top + 0.006, M.castBoard))
  }
  return { signal: Object.fromEntries(FAMILIES.filter((f) => groups[f].length).map((f) => [f, group(groups[f])])), ground: group(ground) }
}

function roundedSquare(half, r) {
  const s = new THREE.Shape()
  s.moveTo(-half + r, -half)
  s.lineTo(half - r, -half); s.absarc(half - r, -half + r, r, -Math.PI / 2, 0)
  s.lineTo(half, half - r); s.absarc(half - r, half - r, r, 0, Math.PI / 2)
  s.lineTo(-half + r, half); s.absarc(-half + r, half - r, r, Math.PI / 2, Math.PI)
  s.lineTo(-half, -half + r); s.absarc(-half + r, -half + r, r, Math.PI, 1.5 * Math.PI)
  return s
}

export function buildCarrier(M) {
  const root = new THREE.Group()
  const B = BOARD

  // Board: laminate with a square pocket for the die and four screw holes, plated on top.
  const sh = roundedSquare(B.half, B.round)
  const cav = new THREE.Path()
  cav.moveTo(-B.cavity, -B.cavity); cav.lineTo(-B.cavity, B.cavity); cav.lineTo(B.cavity, B.cavity); cav.lineTo(B.cavity, -B.cavity); cav.closePath()
  sh.holes.push(cav)
  for (const [sx, sz] of [[1, 1], [1, -1], [-1, 1], [-1, -1]]) sh.holes.push(new THREE.Path().absarc(sx * B.screw, sz * B.screw, 0.3, 0, 2 * Math.PI, true))
  const bevel = 0.02
  const boardGeo = new THREE.ExtrudeGeometry(sh, { depth: B.thick - 2 * bevel, bevelEnabled: true, bevelThickness: bevel, bevelSize: bevel, bevelSegments: 2, curveSegments: 10 })
    .rotateX(-Math.PI / 2).translate(0, B.top - B.thick + bevel, 0)
  const board = new THREE.Mesh(boardGeo, [M.gold, M.board])
  board.castShadow = board.receiveShadow = true
  root.add(board)

  // Copper pattern: every port is a grounded coplanar trace from the pocket edge out to a via,
  // which would carry the signal to a connector on the back of the board.
  const lam = new Flat()
  const cu = new Flat()
  const hole = new Flat()
  const dimple = new Flat()
  const y = B.top + 0.0012
  for (const side of SIDES) {
    for (const p of PORTS) {
      const f = frame(side.at(p), side.a)
      const d0 = -(B.cavity - K.die / 2)
      const dv = -(B.via - K.die / 2)
      lam.poly([f(d0, -TRACE.c / 2 - TRACE.g), f(d0, TRACE.c / 2 + TRACE.g), f(dv, TRACE.c / 2 + TRACE.g), f(dv, -TRACE.c / 2 - TRACE.g)], y)
      lam.disc(...f(dv, 0), TRACE.anti, y, 28)
      cu.poly([f(d0 - 0.09, -TRACE.c / 2), f(d0 - 0.09, TRACE.c / 2), f(dv, TRACE.c / 2), f(dv, -TRACE.c / 2)], y + 0.0012)
      cu.disc(...f(dv, 0), TRACE.pad, y + 0.0012, 28)
      hole.disc(...f(dv, 0), 0.07, y + 0.0024, 18)
    }
    // Via fence: a row of ground vias between neighbouring traces keeps them from talking.
    for (let k = -4; k <= 3; k++) {
      const p = (k + 0.5) * K.ports
      for (let d = 0.75; d < 1.75; d += 0.3) {
        const c = frame(side.at(p), side.a)(-d, 0)
        dimple.disc(c[0], c[1], 0.05, y, 14)
        hole.disc(c[0], c[1], 0.018, y + 0.0012, 10)
      }
    }
  }
  for (const [flat, mat] of [[lam, M.lam], [cu, M.cu], [hole, M.dark], [dimple, M.goldDim]]) {
    const m = new THREE.Mesh(flat.geometry(), mat)
    m.receiveShadow = true
    root.add(m)
  }

  // Copper base under the board; it shows in the pocket round the die and at the edges.
  const baseGeo = new THREE.ExtrudeGeometry(roundedSquare(B.half, B.round), { depth: B.base - 0.06, bevelEnabled: true, bevelThickness: 0.03, bevelSize: 0.03, bevelSegments: 2, curveSegments: 10 })
    .rotateX(-Math.PI / 2).translate(0, B.top - B.thick - B.base + 0.03, 0)
  const base = new THREE.Mesh(baseGeo, M.base)
  base.castShadow = base.receiveShadow = true
  root.add(base)

  // The trench between die and board lies in the shadow of its own walls.
  const pit = new THREE.Shape()
  pit.moveTo(-B.cavity, -B.cavity); pit.lineTo(B.cavity, -B.cavity); pit.lineTo(B.cavity, B.cavity); pit.lineTo(-B.cavity, B.cavity); pit.closePath()
  const dieHole = new THREE.Path()
  dieHole.moveTo(-H, -H); dieHole.lineTo(-H, H); dieHole.lineTo(H, H); dieHole.lineTo(H, -H); dieHole.closePath()
  pit.holes.push(dieHole)
  const trench = new THREE.Mesh(new THREE.ShapeGeometry(pit).rotateX(-Math.PI / 2), M.pit)
  trench.position.y = B.top - B.thick + 0.004
  root.add(trench)

  // Screws: a chamfered head with a hex socket.
  const head = new THREE.LatheGeometry([[0.43, 0], [0.43, 0.13], [0.38, 0.18], [0, 0.18]].map(([r, h]) => new THREE.Vector2(r, h)), 40)
  const socket = new THREE.CylinderGeometry(0.17, 0.17, 0.012, 6).translate(0, 0.181, 0)
  for (const [sx, sz] of [[1, 1], [1, -1], [-1, 1], [-1, -1]]) {
    const s = new THREE.Mesh(head, M.steel)
    s.position.set(sx * B.screw, B.top, sz * B.screw)
    s.rotation.y = sx * 0.7 + sz * 0.3
    s.castShadow = s.receiveShadow = true
    s.add(new THREE.Mesh(socket, M.dark))
    root.add(s)
  }

  // The sheet under the package: a soft contact shadow plus the key light's cast shadow.
  const floorY = B.top - B.thick - B.base
  const cv = document.createElement('canvas')
  cv.width = cv.height = 256
  const g = cv.getContext('2d')
  g.shadowColor = '#000'
  g.shadowBlur = 26
  g.shadowOffsetX = 512
  g.fillStyle = '#000'
  for (let k = 0; k < 2; k++) g.fillRect(-512 + 58, 58, 140, 140)
  const ao = new THREE.Mesh(new THREE.PlaneGeometry(4 * B.half * (256 / 280), 4 * B.half * (256 / 280)).rotateX(-Math.PI / 2), M.contact)
  M.contact.map = new THREE.CanvasTexture(cv)
  ao.position.y = floorY + 0.004
  ao.renderOrder = -1
  root.add(ao)
  const floor = new THREE.Mesh(new THREE.PlaneGeometry(90, 90).rotateX(-Math.PI / 2), M.shadow)
  floor.position.y = floorY
  floor.receiveShadow = true
  floor.renderOrder = -2
  root.add(floor)
  return root
}
