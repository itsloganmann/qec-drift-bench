// The device drawn on the die, as plain data. Millimetres on the die's top face, x to the right
// and z toward the viewer in the top view.
//
// It is a 17-qubit distance-3 surface-code patch of Xmon transmons (Barends et al. 2013, PRL 111
// 080502) on a square lattice: data and measure qubits alternate, and each neighbouring pair
// shares a capacitive coupler. Measure qubits are flux-tunable (a SQUID), data qubits have a
// single junction. Quarter-wave readout resonators hang off two feedlines, shorted at the
// feedline end and clawed round a qubit arm at the open end. XY drive lines stop short of an arm
// tip; flux lines end in a short to ground beside a SQUID.
//
// What is not to scale: qubits are drawn about 2x and line widths about 5x so they read at this
// size, and only qubits with a free arm on the outside of the patch are wired. A planar chip
// would reach the five inner qubits with crossovers; those lines are left out for clarity.

import { rot180, fillet, pathLength, frame } from './chip-geom.js'

export const FAMILIES = ['readout', 'pulse', 'flux', 'qec']

export const K = {
  die: 10, film: 4.9, thick: 0.5, pitch: 1,
  arm: 0.3, armW: 0.08, pocket: 0.05, // Xmon: centre to arm tip, arm width, gap to ground
  feed: { c: 0.06, g: 0.035 }, res: { c: 0.05, g: 0.0275 }, ctl: { c: 0.05, g: 0.03 }, bus: { c: 0.03, g: 0.025 },
  keep: 0.05, // hole-free margin of ground round every etched feature
  pad: 0.3, padLen: 0.3, padGap: 0.13, taper: 0.4, padInset: 0.18, // launch pad
  feedZ: 3.75, turn: 0.1, amp: 0.36, // feedline offset from centre, meander bend radius and half width
  claw: { c: 0.035, g: 0.03, wrap: 0.1 },
  tee: { c: 0.035, half: 0.075 }, // coupler end bar
  squidAt: 0.22, ports: 1.3, // SQUID position along its arm; pitch of the board's ports
  cycle: 9, // millimetres of travel per animation loop
}
const LAUNCH = K.padInset + K.padGap + K.padLen + K.taper

const SITES = [[0, -2], [1, -2], [-2, -1], [-1, -1], [0, -1], [1, -1], [-2, 0], [-1, 0], [0, 0], [1, 0], [2, 0], [-1, 1], [0, 1], [1, 1], [2, 1], [-1, 2], [0, 2]]
const EDGE = {
  L: (p) => ({ o: [-K.die / 2, p], a: [1, 0] }), R: (p) => ({ o: [K.die / 2, p], a: [-1, 0] }),
  T: (p) => ({ o: [p, -K.die / 2], a: [0, 1] }), B: (p) => ({ o: [p, K.die / 2], a: [0, -1] }),
}
const FLIP = { L: 'R', R: 'L', T: 'B', B: 'T' }
const launchAt = (edge, pos) => { const { o, a } = EDGE[edge](pos); return [o[0] + a[0] * LAUNCH, o[1] + a[1] * LAUNCH] }

// A hanger resonator under the top feedline, centred on column x, ending at an arm tip that
// points up at (x, zTip). n meander runs; the half width is solved so the total length is `total`.
function hanger(x, zTip, n, total) {
  const zc = -(K.feedZ - K.feed.c / 2 - K.feed.g - 0.03 - K.res.g - K.res.c / 2)
  const zEnd = zTip - K.claw.g - K.claw.c / 2
  const P = 2 * K.turn
  const build = (A) => {
    const pts = [[x + A, zc]]
    let side = -1
    for (let k = 0; k < n; k++) {
      pts.push([x + side * A, zc + k * P], [x + side * A, zc + (k + 1) * P])
      side = -side
    }
    pts.push([x, zc + n * P], [x, zEnd])
    return pts
  }
  const l0 = pathLength(fillet(build(K.amp), K.turn))
  const l1 = pathLength(fillet(build(K.amp + 0.02), K.turn))
  const A = K.amp + 0.02 * (total - l0) / (l1 - l0)
  return { pts: build(A), A, zc }
}

export function device() {
  const s = K.pitch
  const key = (u, v) => `${u},${v}`
  const qubits = SITES.map(([u, v]) => ({ u, v, x: u * s, z: v * s, anc: (u + v) % 2 !== 0, jj: { dir: [1, 0], side: -1 } }))
  const at = Object.fromEntries(qubits.map((q) => [key(q.u, q.v), q]))

  // Couplers, each tagged with its step in the syndrome cycle: a measure qubit meets its four
  // data neighbours in an order that differs between the X and Z checks.
  const couplers = []
  for (const q of qubits) {
    for (const d of [[1, 0], [0, 1]]) {
      const n = at[key(q.u + d[0], q.v + d[1])]
      if (!n) continue
      const [anc, dat] = q.anc ? [q, n] : [n, q]
      const toward = [dat.u - anc.u, dat.v - anc.v]
      const order = anc.u % 2 !== 0 ? [[0, -1], [1, 0], [-1, 0], [0, 1]] : [[0, -1], [-1, 0], [1, 0], [0, 1]]
      couplers.push({ x: q.x, z: q.z, dir: d, step: order.findIndex((o) => o[0] === toward[0] && o[1] === toward[1]) })
    }
  }

  // Half of the wiring; the other half is the same turned through 180 degrees.
  const half = []
  const zf = -K.feedZ
  half.push({ family: 'readout', kind: 'feed', ...K.feed, r: 0.22, pts: [launchAt('T', -3.9), [-3.9, zf], [2.6, zf], launchAt('T', 2.6)],
    launch: [['T', -3.9], ['T', 2.6]], delay: 0, clear: [] })
  const feed = half[0]
  const HANG = [[-2, -1, 3, 4.62], [-1, -1, 3, 4.56], [0, -2, 5, 4.5], [1, -2, 5, 4.44]]
  for (const [u, v, n, total] of HANG) {
    const q = at[key(u, v)]
    const h = hanger(q.x, q.z - K.arm, n, total)
    half.push({ family: 'readout', kind: 'res', ...K.res, r: K.turn, pts: h.pts, claw: { q, dir: [0, -1] }, skipFirst: true, delay: q.x + K.amp + 3.9 + 0.2 })
    feed.clear.push([q.x - h.A - 0.12, zf - 0.3, q.x + h.A + 0.12, zf + 0.3])
  }
  const tipX = -(K.arm + K.pocket + 0.05 + K.ctl.g) // XY line stops this far left of a qubit centre
  const XY = [[-2, -1, -1.3, 0.3], [-2, 0, 0, 0], [-1, 1, 1.3, 0.3], [-1, 2, 2.6, 0.6]]
  XY.forEach(([u, v, pad, jog], i) => {
    const q = at[key(u, v)]
    const pts = [launchAt('L', pad)]
    if (jog) pts.push([-3.75, pad], [-3.75 + jog, q.z])
    pts.push([q.x + tipX, q.z])
    half.push({ family: 'pulse', kind: 'xy', ...K.ctl, r: 0.15, pts, open: true, launch: [['L', pad]], delay: i * 2.2, q })
  })
  const Z = [[-2, -1, -2.6, -1], [-1, 2, 3.9, 1]]
  Z.forEach(([u, v, pad, side], i) => {
    const q = at[key(u, v)]
    q.jj = { dir: [-1, 0], side, squidLine: true }
    const edge = [q.x - K.squidAt, q.z + side * (K.armW / 2 + K.pocket)]
    const d = [Math.SQRT1_2, -side * Math.SQRT1_2]
    const end = [edge[0] - d[0] * 0.075, edge[1] - d[1] * 0.075]
    const run = Math.abs(end[1] - pad)
    half.push({ family: 'flux', kind: 'z', ...K.ctl, r: 0.15, pts: [launchAt('L', pad), [end[0] - run, pad], end], short: side, launch: [['L', pad]], delay: i * 4.5, q })
  })

  const lines = []
  for (const ln of half) {
    lines.push(ln)
    const q2 = (q) => q && at[key(-q.u, -q.v)]
    const twin = { ...ln, pts: ln.pts.map(rot180), launch: (ln.launch || []).map(([e, p]) => [FLIP[e], -p]), q: q2(ln.q),
      clear: (ln.clear || []).map(([a, b, c, d]) => [-c, -d, -a, -b]), delay: ln.delay + (ln.kind === 'xy' || ln.kind === 'z' ? 1.1 : 0) }
    if (ln.claw) twin.claw = { q: q2(ln.claw.q), dir: [0, 1] }
    if (ln.kind === 'z') twin.q.jj = { dir: [1, 0], side: -ln.short, squidLine: true }
    lines.push(twin)
  }
  for (const ln of lines) ln.poly = fillet(ln.pts, ln.r)

  const launches = []
  for (const ln of lines) for (const [e, p] of ln.launch || []) launches.push({ ...EDGE[e](p), edge: e, pos: p, family: ln.family, c: ln.c, g: ln.g })

  return { qubits, couplers, lines, launches, at: (u, v) => at[key(u, v)] }
}

// Outline of a launch pad and its taper down to the line, in the pad's own frame
// (u inward from the die edge, v along the edge). half(u) gives the half width at each station.
export function launchOutline(l, grow = 0) {
  const f = frame(l.o, l.a)
  const u0 = K.padInset + K.padGap - grow
  const u1 = K.padInset + K.padGap + K.padLen
  const w0 = K.pad / 2 + grow
  const w1 = l.c / 2 + (grow ? grow * (l.g / K.padGap) : 0)
  return [f(u0, -w0), f(u0, w0), f(u1, w0), f(LAUNCH, w1), f(LAUNCH, -w1), f(u1, -w0)]
}

// Where the camera goes for each family. box is [x0, z0, x1, z1] on the die; az and pol are the
// view direction in radians.
export const VIEWS = {
  home: { box: [-7.2, -7.2, 7.2, 7.2], az: 0.5, pol: 0.78, y: [-1.3, 0.3] },
  die: { box: [-5.7, -5.7, 5.7, 5.7], az: 0.5, pol: 0.78, y: [-0.5, 0.3] },
  readout: { box: [-2.7, -4.6, 1.7, -1.2], az: -0.42, pol: 0.74 },
  pulse: { box: [-5.6, -0.75, -1.55, 0.75], az: -0.25, pol: 0.86 },
  flux: { box: [1.45, 0.55, 5.6, 3.1], az: 0.62, pol: 0.82 },
  qec: { box: [-2.6, -2.6, 2.6, 2.6], az: 0.3, pol: 0.52 },
}

// Each family's numbered balloon: `at` is the point its leader ends on, and `tag` is a patch of
// bare ground nearby where the balloon sits once the camera is close enough for it to fit.
export const CALLOUT = {
  readout: { at: [-1, -3.6], tag: [-1.28, -4.3] },
  pulse: { at: [-3.25, 0], tag: [-2.95, -0.5] },
  flux: { at: [3.05, 1.92], tag: [3.4, 1.57] },
  qec: { at: [0.5, 0], tag: [0.5, -0.5] },
}
