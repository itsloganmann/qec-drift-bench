// Plots for the page: the instance viewers (what an agent sees, drawn from real public
// instances) and the results forest plot. Plain canvas 2D and SVG, coloured from the page
// tokens so both themes work.

const css = (n) => getComputedStyle(document.documentElement).getPropertyValue(n).trim()
const FONT = '11px "IBM Plex Mono", ui-monospace, monospace'

function setup(canvas) {
  const dpr = Math.min(window.devicePixelRatio || 1, 2)
  const w = canvas.clientWidth
  const h = canvas.clientHeight
  canvas.width = Math.round(w * dpr)
  canvas.height = Math.round(h * dpr)
  const g = canvas.getContext('2d')
  g.setTransform(dpr, 0, 0, dpr, 0, 0)
  g.clearRect(0, 0, w, h)
  g.font = FONT
  return { g, w, h }
}

function mix(hex, t, base) {
  const p = (c) => [1, 3, 5].map((i) => parseInt(c.slice(i, i + 2), 16))
  const a = p(hex)
  const b = p(base)
  return `rgb(${a.map((v, i) => Math.round(v * t + b[i] * (1 - t))).join(',')})`
}

// A framed plot area with linear or log x, linear y, ticks and axis titles.
function frame(g, box, sx, sy, o) {
  const ink = css('--ink-2')
  g.strokeStyle = css('--rule')
  g.lineWidth = 1
  g.strokeRect(box.x + 0.5, box.y + 0.5, box.w, box.h)
  g.fillStyle = ink
  g.textAlign = 'center'
  g.textBaseline = 'top'
  for (const t of o.xt) {
    const x = sx(t)
    g.fillRect(x, box.y + box.h, 1, 4)
    g.fillText(o.xf ? o.xf(t) : String(t), x, box.y + box.h + 6)
  }
  g.textAlign = 'right'
  g.textBaseline = 'middle'
  for (const t of o.yt) {
    const y = sy(t)
    g.fillRect(box.x - 4, y, 4, 1)
    g.fillText(o.yf ? o.yf(t) : String(t), box.x - 7, y)
  }
  g.textAlign = 'left'
  g.textBaseline = 'bottom'
  g.fillText(o.title, box.x, box.y - 6)
  g.textAlign = 'right'
  g.textBaseline = 'top'
  g.fillText(o.xlabel, box.x + box.w, box.y + box.h + 20)
  if (o.ylabel) {
    g.save()
    g.translate(box.x - (o.ygap ?? 34), box.y + box.h / 2)
    if (o.ylabel.length > 2) g.rotate(-Math.PI / 2)
    g.textAlign = 'center'
    g.textBaseline = 'middle'
    g.fillText(o.ylabel, 0, 0)
    g.restore()
  }
}

export function drawReadout(canvas, inst) {
  const { g, w, h } = setup(canvas)
  const all = inst.calib.concat(inst.shots)
  const lim = Math.max(...all.map((p) => Math.max(Math.abs(p[0]), Math.abs(p[1])))) * 1.05
  const narrow = w < 600
  const size = narrow ? Math.min(w - 64, (h - 126) / 2) : Math.min(w / 2 - 50, h - 74)
  const runs = new Set(inst.shots.map((s) => s[2])).size
  const panels = [
    { x: 48, y: 26, title: `Before: ${inst.calib.length} of ${inst.calib_n.toLocaleString('en-US')} labelled shots`, pts: inst.calib, calib: true },
    { x: narrow ? 48 : 48 + size + 50, y: narrow ? 26 + size + 52 : 26, title: `Now: ${inst.shots.length} unlabelled shots, ${runs} runs`, pts: inst.shots, calib: false },
  ]
  const lay = css('--l-readout')
  const bg = css('--sheet')
  for (const p of panels) {
    const box = { x: p.x, y: p.y, w: size, h: size }
    const sx = (v) => box.x + ((v + lim) / (2 * lim)) * box.w
    const sy = (v) => box.y + box.h - ((v + lim) / (2 * lim)) * box.h
    const r = Math.floor(lim)
    const ticks = r >= 1 ? [-r, 0, r] : [0]
    frame(g, box, sx, sy, { xt: ticks, yt: ticks, title: p.title, xlabel: 'I', ylabel: 'Q', ygap: 26 })
    for (const s of p.pts) {
      g.fillStyle = p.calib ? (s[2] ? lay : css('--muted')) : mix(lay, 0.45 + 0.55 * (s[2] / Math.max(1, runs - 1)), bg)
      g.globalAlpha = p.calib ? 0.55 : 0.9
      g.fillRect(sx(s[0]) - 1.5, sy(s[1]) - 1.5, 3, 3)
    }
    g.globalAlpha = 1
  }
  g.fillStyle = css('--ink-2')
  g.textAlign = 'left'
  g.textBaseline = 'top'
  const runText = `new shots: run 1 pale to run ${runs} dark`
  g.fillText(narrow ? 'grey: prepared |0>, colour: prepared |1>' : `grey: prepared |0>, colour: prepared |1>; ${runText}`, 48, panels[1].y + size + 38)
  if (narrow) g.fillText(runText, 48, panels[1].y + size + 54)
}

export function drawPulse(canvas, inst) {
  const { g, w, h } = setup(canvas)
  const lay = css('--l-pulse')
  const narrow = w < 600
  const pw = narrow ? w - 64 : (w - 120) / 2
  const ph = narrow ? (h - 120) / 2 : h - 70
  const A = { x: 48, y: 26, w: pw, h: ph }
  const B = narrow ? { x: 48, y: 26 + ph + 64, w: pw, h: ph } : { x: 48 + pw + 60, y: 26, w: pw, h: ph }
  const sxa = (v) => A.x + v * A.w
  const sya = (v) => A.y + A.h - v * A.h
  frame(g, A, sxa, sya, { xt: [0, 0.5, 1], yt: [0, 0.5, 1], title: 'Rabi sweep, 100 shots per point', xlabel: 'drive amplitude', ylabel: 'P(excited)', ygap: 32 })
  const tmax = inst.ram_t[inst.ram_t.length - 1]
  const sxb = (v) => B.x + (v / tmax) * B.w
  const syb = (v) => B.y + B.h - v * B.h
  frame(g, B, sxb, syb, { xt: [0, 5000, 10000], xf: (t) => `${t / 1000}`, yt: [0, 0.5, 1], title: 'Ramsey, 1 MHz offset', xlabel: 'delay (us)', ylabel: 'P(1)', ygap: 32 })
  const series = (xs, ys, sx, sy) => {
    g.strokeStyle = lay
    g.globalAlpha = 0.35
    g.beginPath()
    xs.forEach((x, i) => (i ? g.lineTo(sx(x), sy(ys[i])) : g.moveTo(sx(x), sy(ys[i]))))
    g.stroke()
    g.globalAlpha = 1
    g.fillStyle = lay
    xs.forEach((x, i) => { g.beginPath(); g.arc(sx(x), sy(ys[i]), 1.8, 0, 7); g.fill() })
  }
  series(inst.rabi_amps, inst.rabi, sxa, sya)
  series(inst.ram_t, inst.ram, sxb, syb)
}

export function drawFlux(canvas, inst) {
  const { g, w, h } = setup(canvas)
  const lay = css('--l-flux')
  const box = { x: 66, y: 26, w: w - 86, h: h - 70 }
  const lo = Math.log10(inst.t[0])
  const hi = Math.log10(inst.t[inst.t.length - 1])
  const dev = inst.step.map((s) => (s - 1) * 1000)
  const sig = inst.sigma.map((s) => s * 1000)
  let ymin = Math.min(...dev.map((d, i) => d - sig[i]))
  let ymax = Math.max(...dev.map((d, i) => d + sig[i]))
  const pad = (ymax - ymin) * 0.1
  ymin -= pad
  ymax += pad
  const sx = (t) => box.x + ((Math.log10(t) - lo) / (hi - lo)) * box.w
  const sy = (v) => box.y + box.h - ((v - ymin) / (ymax - ymin)) * box.h
  const step = Math.pow(10, Math.floor(Math.log10((ymax - ymin) / 2)))
  const yt = []
  for (let v = Math.ceil(ymin / step) * step; v <= ymax; v += step) yt.push(Number(v.toFixed(6)))
  frame(g, box, sx, sy, {
    xt: [1, 10, 100, 1000, 10000],
    xf: (t) => (t >= 1000 ? `${t / 1000} us` : `${t} ns`),
    yt,
    yf: (v) => v.toFixed(Math.max(0, -Math.floor(Math.log10(step)))),
    title: 'Step response through the current predistortion',
    xlabel: 'time after the step',
    ylabel: 'step - 1 (parts per thousand)',
    ygap: 44,
  })
  g.fillStyle = mix(lay, 0.22, css('--sheet'))
  g.beginPath()
  inst.t.forEach((t, i) => (i ? g.lineTo(sx(t), sy(dev[i] + sig[i])) : g.moveTo(sx(t), sy(dev[i] + sig[i]))))
  for (let i = inst.t.length - 1; i >= 0; i--) g.lineTo(sx(inst.t[i]), sy(dev[i] - sig[i]))
  g.fill()
  if (ymin < 0 && ymax > 0) {
    g.strokeStyle = css('--muted')
    g.setLineDash([3, 3])
    g.beginPath(); g.moveTo(box.x, sy(0)); g.lineTo(box.x + box.w, sy(0)); g.stroke()
    g.setLineDash([])
  }
  g.strokeStyle = lay
  g.lineWidth = 1.5
  g.beginPath()
  inst.t.forEach((t, i) => (i ? g.lineTo(sx(t), sy(dev[i])) : g.moveTo(sx(t), sy(dev[i]))))
  g.stroke()
  g.lineWidth = 1
}

export function drawQec(canvas, inst) {
  const { g, w, h } = setup(canvas)
  const lay = css('--l-qec')
  const bg = css('--sheet')
  // Mean change in firing rate per stabiliser position, averaged over rounds.
  const acc = {}
  for (const [k, c] of Object.entries(inst.coords)) {
    const key = `${c[0]},${c[1]}`
    acc[key] ??= { x: c[0], y: c[1], d: 0, n: 0 }
    acc[key].d += inst.post[+k] - inst.pre[+k]
    acc[key].n += 1
  }
  const stabs = Object.values(acc).map((s) => ({ ...s, d: s.d / s.n }))
  const maxd = Math.max(0.004, ...stabs.map((s) => Math.abs(s.d)))
  const narrow = w < 600
  const size = narrow ? Math.min(w - 64, h / 2 - 40) : Math.min(h - 70, w * 0.42)
  const cell = size / 6
  const ox = 48
  const oy = 30
  const P = (x, y) => [ox + x * cell, oy + y * cell]
  g.fillStyle = css('--ink-2')
  g.textBaseline = 'bottom'
  g.fillText('Change in stabiliser firing rate, new batch vs labelled batch', ox, oy - 8)
  for (const s of stabs) {
    const [x, y] = P(s.x, s.y)
    const t = Math.min(1, Math.abs(s.d) / maxd)
    g.fillStyle = s.d >= 0 ? mix(lay, 0.1 + 0.9 * t, bg) : mix(css('--muted'), 0.1 + 0.9 * t, bg)
    g.beginPath()
    g.moveTo(x, y - cell * 0.95); g.lineTo(x + cell * 0.95, y); g.lineTo(x, y + cell * 0.95); g.lineTo(x - cell * 0.95, y)
    g.closePath()
    g.fill()
  }
  for (const [q, c] of Object.entries(inst.qcoords)) {
    const [x, y] = P(c[0], c[1])
    const isData = inst.data_q.includes(+q)
    g.fillStyle = isData ? css('--ink') : bg
    g.strokeStyle = css('--ink')
    g.beginPath(); g.arc(x, y, isData ? 4 : 3, 0, 7); g.fill(); g.stroke()
  }
  g.fillStyle = css('--ink-2')
  g.textBaseline = 'top'
  g.fillText(`colour: fires more, grey: fires less; full scale +-${(maxd * 100).toFixed(2)} points`, ox, oy + 6 * cell + 14)
  // Firing rate over the batch, 25 windows of 2,000 shots.
  const box = narrow ? { x: 56, y: oy + size + 80, w: w - 72, h: h - (oy + size + 80) - 44 } : { x: ox + size + 84, y: 30, w: w - (ox + size + 84) - 16, h: h - 76 }
  if (box.w < 120) return
  const pre = inst.pre.reduce((a, b) => a + b, 0) / inst.pre.length
  const series = inst.windows.map((wv) => wv.reduce((a, b) => a + b, 0) / wv.length / pre - 1)
  const m = Math.max(0.02, ...series.map(Math.abs)) * 1.15
  const sx = (i) => box.x + (i / (series.length - 1)) * box.w
  const sy = (v) => box.y + box.h / 2 - (v / m) * (box.h / 2)
  const pct = Math.round(m * 100)
  frame(g, box, sx, sy, {
    xt: [0, 12, 24], xf: (i) => `${((i + 1) * 0.2).toFixed(1)} s`,
    yt: [-m, 0, m], yf: (v) => `${v > 0 ? '+' : ''}${Math.round((v / m) * pct)}%`,
    title: 'Mean firing rate over the new batch', xlabel: 'time in batch',
    ylabel: 'change from before', ygap: 38,
  })
  g.strokeStyle = lay
  g.lineWidth = 1.5
  g.beginPath()
  series.forEach((v, i) => (i ? g.lineTo(sx(i), sy(v)) : g.moveTo(sx(i), sy(v))))
  g.stroke()
  g.lineWidth = 1
}

