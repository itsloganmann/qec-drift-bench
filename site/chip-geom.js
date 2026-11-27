// Flat-geometry helpers for the chip. Everything patterned on the die and the board is a thin
// film, so it is drawn as coplanar layers (ground, hole-free margin, etched gap, conductor)
// stacked a few microns apart instead of as raised bars. Paths are [x, z] pairs in millimetres.

import * as THREE from 'three'

export const rot180 = ([x, z]) => [-x, -z]
const sub = (a, b) => [a[0] - b[0], a[1] - b[1]]
const len = (a) => Math.hypot(a[0], a[1])
const unit = (a) => { const l = len(a) || 1; return [a[0] / l, a[1] / l] }

// Round every interior corner of a polyline with radius r, clamped to half the shorter leg, so
// two successive right angles a diameter apart become one clean semicircle (a meander turn).
export function fillet(pts, r, step = 0.03) {
  if (!r || pts.length < 3) return pts.map((p) => [...p])
  const out = [[...pts[0]]]
  for (let i = 1; i < pts.length - 1; i++) {
    const p = pts[i]
    const va = sub(pts[i - 1], p)
    const vb = sub(pts[i + 1], p)
    const a = unit(va)
    const b = unit(vb)
    const ang = Math.acos(Math.max(-1, Math.min(1, a[0] * b[0] + a[1] * b[1])))
    if (ang > Math.PI - 1e-3 || ang < 1e-3) { out.push([...p]); continue }
    const t = Math.min(r / Math.tan(ang / 2), len(va) / 2, len(vb) / 2)
    const rr = t * Math.tan(ang / 2)
    const bis = unit([a[0] + b[0], a[1] + b[1]])
    const c = [p[0] + bis[0] * rr / Math.sin(ang / 2), p[1] + bis[1] * rr / Math.sin(ang / 2)]
    const a0 = Math.atan2(p[1] + a[1] * t - c[1], p[0] + a[0] * t - c[0])
    let d = Math.atan2(p[1] + b[1] * t - c[1], p[0] + b[0] * t - c[0]) - a0
    while (d > Math.PI) d -= 2 * Math.PI
    while (d < -Math.PI) d += 2 * Math.PI
    const n = Math.max(3, Math.ceil(Math.abs(d) * rr / step))
    for (let k = 0; k <= n; k++) out.push([c[0] + rr * Math.cos(a0 + d * k / n), c[1] + rr * Math.sin(a0 + d * k / n)])
  }
  out.push([...pts[pts.length - 1]])
  // Back-to-back arcs share an end point; drop the repeat so no segment has zero length.
  return out.filter((q, i) => i === 0 || Math.hypot(q[0] - out[i - 1][0], q[1] - out[i - 1][1]) > 1e-6)
}

export function pathLength(poly) {
  let L = 0
  for (let i = 1; i < poly.length; i++) L += len(sub(poly[i], poly[i - 1]))
  return L
}

// Point and unit tangent at arc length s along a polyline.
export function pointAt(poly, s) {
  for (let i = 1; i < poly.length; i++) {
    const v = sub(poly[i], poly[i - 1])
    const l = len(v)
    if (s <= l || i === poly.length - 1) {
      const t = l ? Math.max(0, Math.min(1, s / l)) : 0
      return { p: [poly[i - 1][0] + v[0] * t, poly[i - 1][1] + v[1] * t], t: unit(v) }
    }
    s -= l
  }
  return { p: [...poly[0]], t: [1, 0] }
}

// The part of a polyline between arc lengths s0 and s1.
export function slice(poly, s0, s1) {
  const out = [pointAt(poly, s0).p]
  let acc = 0
  for (let i = 1; i < poly.length; i++) {
    acc += len(sub(poly[i], poly[i - 1]))
    if (acc > s0 + 1e-6 && acc < s1 - 1e-6) out.push([...poly[i]])
  }
  out.push(pointAt(poly, s1).p)
  return out
}

// Collects flat triangles at chosen heights and turns them into one BufferGeometry. The `s`
// attribute carries arc length along ribbons so a signal can be animated down a line.
export class Flat {
  constructor() { this.p = []; this.i = []; this.s = [] }

  // A strip of width w centred on a polyline, mitred at corners. ext0/ext1 lengthen the ends;
  // `still` keeps s constant instead of counting arc length.
  ribbon(poly, w, y, { ext0 = 0, ext1 = 0, s0 = 0, still = false } = {}) {
    const P = poly.map((q) => [...q])
    const n = P.length
    if (n < 2) return this
    const d0 = unit(sub(P[1], P[0]))
    const d1 = unit(sub(P[n - 1], P[n - 2]))
    P[0] = [P[0][0] - d0[0] * ext0, P[0][1] - d0[1] * ext0]
    P[n - 1] = [P[n - 1][0] + d1[0] * ext1, P[n - 1][1] + d1[1] * ext1]
    const base = this.p.length / 3
    let s = still ? s0 : s0 - ext0
    for (let i = 0; i < n; i++) {
      const dp = i > 0 ? unit(sub(P[i], P[i - 1])) : unit(sub(P[1], P[0]))
      const dn = i < n - 1 ? unit(sub(P[i + 1], P[i])) : dp
      const m = unit([-(dp[1] + dn[1]), dp[0] + dn[0]])
      const k = (w / 2) / Math.max(0.35, m[0] * -dp[1] + m[1] * dp[0])
      if (i > 0 && !still) s += len(sub(P[i], P[i - 1]))
      this.p.push(P[i][0] + m[0] * k, y, P[i][1] + m[1] * k, P[i][0] - m[0] * k, y, P[i][1] - m[1] * k)
      this.s.push(s, s)
      if (i > 0) {
        const a = base + 2 * (i - 1)
        this.i.push(a, a + 2, a + 1, a + 1, a + 2, a + 3)
      }
    }
    return this
  }

  // A filled simple polygon (it may be concave).
  poly(pts, y, s = 0) {
    const base = this.p.length / 3
    const v2 = pts.map((q) => new THREE.Vector2(q[0], q[1]))
    for (const q of pts) { this.p.push(q[0], y, q[1]); this.s.push(s) }
    for (const [a, b, c] of THREE.ShapeUtils.triangulateShape(v2, [])) {
      const up = (pts[b][1] - pts[a][1]) * (pts[c][0] - pts[a][0]) - (pts[b][0] - pts[a][0]) * (pts[c][1] - pts[a][1])
      if (up > 0) this.i.push(base + a, base + b, base + c)
      else this.i.push(base + a, base + c, base + b)
    }
    return this
  }

  rect(x0, z0, x1, z1, y, s = 0) { return this.poly([[x0, z0], [x1, z0], [x1, z1], [x0, z1]], y, s) }

  disc(cx, cz, r, y, n = 20) {
    const pts = []
    for (let k = 0; k < n; k++) pts.push([cx + r * Math.cos(2 * Math.PI * k / n), cz + r * Math.sin(2 * Math.PI * k / n)])
    return this.poly(pts, y)
  }

  geometry() {
    const g = new THREE.BufferGeometry()
    const nrm = new Float32Array(this.p.length)
    for (let k = 1; k < nrm.length; k += 3) nrm[k] = 1
    g.setAttribute('position', new THREE.Float32BufferAttribute(this.p, 3))
    g.setAttribute('normal', new THREE.BufferAttribute(nrm, 3))
    g.setAttribute('s', new THREE.Float32BufferAttribute(this.s, 1))
    g.setIndex(this.i)
    return g
  }
}

// A local frame at point o with axis a: maps (along, across) to die coordinates.
export const frame = (o, a) => (u, v) => [o[0] + a[0] * u - a[1] * v, o[1] + a[1] * u + a[0] * v]

// A tiny 5x7 block font for etched labels, the kind a mask-layout tool stamps on a die.
const GLYPH = {
  0: '0e11131519110e', 1: '040c040404040e', 2: '0e11010204081f', 3: '1f02040201110e', 4: '02060a121f0202', 5: '1f101e0101110e',
  6: '0608101e11110e', 7: '1f010204080808', 8: '0e11110e11110e', 9: '0e11110f01020c', A: '0e11111f111111', B: '1e11111e11111e',
  D: '1e11111111111e', E: '1f10101e10101f', Q: '0e11111115120d', R: '1e11111e141211', S: '0f10100e01011e', V: '11111111110a04',
  '-': '0000001f000000', '.': '00000000000c0c',
}

// Stamp text as little squares into a Flat. (x, z) is the top-left corner, h the cap height;
// `along` and `down` are unit vectors, so labels can be turned to face any edge.
export function stamp(flat, text, x, z, h, y, along = [1, 0], down = [0, 1]) {
  const px = h / 7
  let col = 0
  for (const ch of text) {
    const g = GLYPH[ch]
    if (g) {
      for (let r = 0; r < 7; r++) {
        const bits = parseInt(g.slice(r * 2, r * 2 + 2), 16)
        for (let c = 0; c < 5; c++) {
          if (!(bits & (16 >> c))) continue
          const u = (col + c) * px
          const v = r * px
          const q = (du, dv) => [x + along[0] * (u + du) + down[0] * (v + dv), z + along[1] * (u + du) + down[1] * (v + dv)]
          flat.poly([q(0, 0), q(px, 0), q(px, px), q(0, px)], y)
        }
      }
    }
    col += 6
  }
  return col * px
}
