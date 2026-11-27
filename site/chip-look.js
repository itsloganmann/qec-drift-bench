// How the chip looks: materials, the studio it reflects, tone mapping, and the colours it takes
// from the page's CSS tokens so that it follows the light and dark themes.

import * as THREE from 'three'
import { FAMILIES, K } from './chip-layout.js'

// The key light's position, and how far it throws a shadow per millimetre of height.
export const KEY = [-9, 16, -4]
const THROW = [-KEY[0] / KEY[1], -KEY[2] / KEY[1]]

// The shadow of a mesh on the plane y = y0: the same geometry, flattened along the key light.
// Used for bond wires and airbridges, which are too fine for the shadow map.
export function shadowOf(mesh, y0, mat) {
  const s = mesh.isInstancedMesh ? new THREE.InstancedMesh(mesh.geometry, mat, mesh.count) : new THREE.Mesh(mesh.geometry, mat)
  if (mesh.isInstancedMesh) s.instanceMatrix = mesh.instanceMatrix
  s.matrixAutoUpdate = false
  s.matrix.set(1, THROW[0], 0, -y0 * THROW[0], 0, 0, 0, y0, 0, THROW[1], 1, -y0 * THROW[1], 0, 0, 0, 1)
  s.frustumCulled = false
  s.renderOrder = 8
  return s
}

// Token fallbacks, [light, dark], used when the page does not define one.
const FALLBACK = {
  '--chip-si': ['#8d95a1', '#2a3039'], '--chip-metal': ['#d3d8de', '#5a626d'], '--chip-pad': ['#eceef1', '#7c848f'],
  '--chip-gap': ['#434b57', '#0e1217'], '--chip-jj': ['#d22b2f', '#ff5c5f'], '--chip-gold': ['#d9c590', '#a39672'],
  '--chip-board': ['#3d4a44', '#1b2320'], '--l-readout': ['#00807f', '#33c2c0'], '--l-pulse': ['#b0266f', '#ee64ad'],
  '--l-flux': ['#a8660a', '#e8a53e'], '--l-qec': ['#2c50c0', '#7495ff'], '--sheet': ['#f7f8f9', '#151a21'],
}

// Khronos PBR Neutral tone mapping: it leaves colours below the highlights alone, so the layer
// colours on the die match the swatches in the legend. three 0.160 predates the built-in, so
// there it is supplied as the custom tone-mapping function.
export const TONE = THREE.NeutralToneMapping ?? THREE.CustomToneMapping
if (!THREE.NeutralToneMapping) THREE.ShaderChunk.tonemapping_pars_fragment = THREE.ShaderChunk.tonemapping_pars_fragment.replace(
  'vec3 CustomToneMapping( vec3 color ) { return color; }',
  `vec3 CustomToneMapping( vec3 color ) {
    color *= toneMappingExposure;
    float x = min( color.r, min( color.g, color.b ) );
    float offset = x < 0.08 ? x - 6.25 * x * x : 0.04;
    color -= offset;
    float peak = max( color.r, max( color.g, color.b ) );
    if ( peak < 0.76 ) return color;
    float newPeak = 1.0 - 0.0576 / ( peak + 0.24 - 0.76 );
    color *= newPeak / peak;
    float g = 1.0 - 1.0 / ( 0.15 * ( peak - newPeak ) + 1.0 );
    return mix( color, vec3( newPeak ), g );
  }`,
)

// A plain photo studio for the metal to reflect: a graded dome, one big softbox overhead and
// two strips low down that put a glint on the bond wires and the die's edge. Below the horizon
// is the sheet the package sits on, so it is pale on the light theme and dark on the dark one.
export function studio(dark) {
  const floor = dark ? 0.14 : 0.66
  const s = new THREE.Scene()
  const dome = new THREE.SphereGeometry(60, 48, 24)
  const c = new THREE.Color()
  const col = []
  const pos = dome.attributes.position
  for (let i = 0; i < pos.count; i++) {
    const t = pos.getY(i) / 60
    c.setScalar(t > 0 ? 0.5 + 0.28 * Math.pow(t, 0.8) : 0.5 + (floor - 0.5) * Math.pow(-t, 0.5))
    col.push(c.r, c.g, c.b)
  }
  dome.setAttribute('color', new THREE.Float32BufferAttribute(col, 3))
  s.add(new THREE.Mesh(dome, new THREE.MeshBasicMaterial({ side: THREE.BackSide, vertexColors: true })))
  const panel = (w, h, at, power) => {
    const m = new THREE.Mesh(new THREE.PlaneGeometry(w, h), new THREE.MeshBasicMaterial({ side: THREE.DoubleSide }))
    m.material.color.setScalar(power)
    m.position.set(...at)
    m.lookAt(0, 0, 0)
    s.add(m)
  }
  panel(40, 26, [-26, 40, -30], 1.3)
  panel(70, 4, [14, 8, 54], 2.2)
  panel(4, 40, [-56, 12, 10], 1.5)
  return s
}

function holeTexture(bg, fg, srgb) {
  const n = 64
  const cv = document.createElement('canvas')
  cv.width = cv.height = n
  const g = cv.getContext('2d')
  g.fillStyle = bg
  g.fillRect(0, 0, n, n)
  g.fillStyle = fg
  g.fillRect(n * 0.34, n * 0.34, n * 0.32, n * 0.32)
  const t = new THREE.CanvasTexture(cv)
  t.wrapS = t.wrapT = THREE.RepeatWrapping
  t.repeat.set(2 * K.film / 0.05, 2 * K.film / 0.05)
  if (srgb) t.colorSpace = THREE.SRGBColorSpace
  return t
}

export function makeMaterials(renderer) {
  const std = (o) => new THREE.MeshStandardMaterial(o)
  // Coplanar film layers are also nudged apart in depth so they never fight.
  const layer = (m, n) => Object.assign(m, { polygonOffset: true, polygonOffsetFactor: -n, polygonOffsetUnits: -2 * n })
  // Flattened shadows: the stencil test keeps overlapping pieces from darkening twice, and the
  // clipping planes keep the die's shadows on the die and the board's off the trench.
  const cast = (planes, both) => layer(new THREE.MeshBasicMaterial({
    color: 0x000000, transparent: true, depthWrite: false, toneMapped: false, clippingPlanes: planes, clipIntersection: both,
    stencilWrite: true, stencilRef: 1, stencilFunc: THREE.NotEqualStencilFunc, stencilZPass: THREE.ReplaceStencilOp,
  }), 8)
  const walls = (d, sign) => [[1, 0], [-1, 0], [0, 1], [0, -1]].map(([x, z]) => new THREE.Plane(new THREE.Vector3(sign * x, 0, sign * z), sign * d))
  const M = {
    white: new THREE.Color(1, 1, 1),
    castDie: cast(walls(K.die / 2 - 0.01, 1), false),
    castBoard: cast(walls(K.die / 2 + 0.26, -1), true),
    si: std({ metalness: 0.4, roughness: 0.4 }),
    film: layer(std({ metalness: 1, roughness: 0.3 }), 1),
    plain: layer(std({ metalness: 1, roughness: 0.3 }), 2),
    gap: layer(std({ metalness: 0.35, roughness: 0.3 }), 3),
    lead: layer(std({ metalness: 1, roughness: 0.25 }), 5),
    jj: layer(std({ metalness: 0.2, roughness: 0.5 }), 6),
    al: std({ metalness: 1, roughness: 0.28 }),
    pit: new THREE.MeshBasicMaterial({ color: 0x000000, transparent: true, depthWrite: false, toneMapped: false }),
    gold: std({ metalness: 1, roughness: 0.36 }),
    cu: layer(std({ metalness: 1, roughness: 0.36 }), 2),
    goldDim: layer(std({ metalness: 1, roughness: 0.5 }), 1),
    lam: layer(std({ metalness: 0, roughness: 0.7 }), 1),
    board: std({ metalness: 0, roughness: 0.7 }),
    base: std({ metalness: 1, roughness: 0.34 }),
    steel: std({ metalness: 1, roughness: 0.3 }),
    dark: layer(std({ color: 0x08090b, metalness: 0, roughness: 0.9 }), 3),
    contact: new THREE.MeshBasicMaterial({ color: 0x000000, transparent: true, depthWrite: false, toneMapped: false }),
    shadow: new THREE.ShadowMaterial({ opacity: 0.2 }),
    fam: {},
    glow: {},
  }
  // Flux-trapping holes: a regular grid of small squares etched through the ground plane.
  M.film.map = holeTexture('#ffffff', '#555555', true)
  M.film.metalnessMap = holeTexture('#0000ff', '#000050', false)
  for (const t of [M.film.map, M.film.metalnessMap]) t.anisotropy = Math.min(8, renderer.capabilities.getMaxAnisotropy())
  for (const f of FAMILIES) {
    M.fam[f] = layer(std({}), 4)
    // A bright packet travelling along the family's lines: s is distance along the line.
    M.glow[f] = layer(new THREE.ShaderMaterial({
      transparent: true,
      depthWrite: false,
      uniforms: { uHead: { value: 0 }, uSpan: { value: K.cycle }, uWidth: { value: 0.42 }, uGain: { value: 0 }, uColor: { value: new THREE.Color() } },
      vertexShader: 'attribute float s; varying float vS; void main() { vS = s; gl_Position = projectionMatrix * modelViewMatrix * vec4( position, 1.0 ); }',
      fragmentShader: `uniform float uHead; uniform float uSpan; uniform float uWidth; uniform float uGain; uniform vec3 uColor; varying float vS;
        void main() {
          float d = mod( vS - uHead + 0.5 * uSpan, uSpan ) - 0.5 * uSpan;
          gl_FragColor = vec4( uColor, exp( - d * d / ( uWidth * uWidth ) ) * uGain );
          #include <tonemapping_fragment>
          #include <colorspace_fragment>
        }`,
    }), 7)
  }
  return M
}

// Read the page tokens into the materials. Returns true when the page is in its dark theme.
export function paint(M, tones, renderer) {
  const style = getComputedStyle(document.documentElement)
  const c = new THREE.Color()
  const sheet = style.getPropertyValue('--sheet').trim() || FALLBACK['--sheet'][0]
  c.set(sheet)
  const dark = 0.2126 * c.r + 0.7152 * c.g + 0.0722 * c.b < 0.2
  const tok = (name) => style.getPropertyValue(name).trim() || FALLBACK[name][dark ? 1 : 0]
  M.si.color.set(tok('--chip-si'))
  for (const m of [M.film, M.plain]) m.color.set(tok('--chip-metal'))
  tones.metal.set(tok('--chip-metal'))
  M.gap.color.set(tok('--chip-gap'))
  M.lead.color.set(tok('--chip-pad'))
  M.al.color.set(tok('--chip-pad')).multiplyScalar(dark ? 1 : 0.74)
  M.castDie.opacity = M.castBoard.opacity = dark ? 0.34 : 0.2
  M.pit.opacity = dark ? 0.7 : 0.5
  M.jj.color.set(tok('--chip-jj'))
  M.jj.emissive.set(tok('--chip-jj'))
  M.jj.emissiveIntensity = 0.35
  for (const m of [M.gold, M.cu]) m.color.set(tok('--chip-gold'))
  M.goldDim.color.set(tok('--chip-gold')).multiplyScalar(0.7)
  M.base.color.set(tok('--chip-gold')).lerp(c.set('#c08660'), 0.4)
  for (const m of [M.lam, M.board]) m.color.set(tok('--chip-board'))
  M.steel.color.set(dark ? '#838b97' : '#c3c8d0')
  for (const f of FAMILIES) tones.fam[f].set(tok(`--l-${f}`))
  M.contact.opacity = dark ? 0.55 : 0.3
  M.shadow.opacity = dark ? 0.4 : 0.15
  renderer.toneMappingExposure = dark ? 0.9 : 1.0
  return dark
}
