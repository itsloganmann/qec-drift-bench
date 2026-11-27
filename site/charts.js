// Result charts: the headline bars, the per-task forest plot and the time scatter. SVG drawn at
// the width of their container, so text stays the same size on a phone and a desktop.
// Marks: agents solid ink, the reference method an open diamond or outlined bar, the floor grey.

const f2 = (v) => v.toFixed(2)
const pct = (v) => `${Math.round(v * 100)}%`
const ci = (c) => `[${f2(c[0])}, ${f2(c[1])}]`
const width = (el) => Math.max(300, Math.floor(el.clientWidth || 760))
const cls = (id) => (id === 'trivial' ? 'floor' : id === 'reference' ? 'ref' : 'agent')

export function armNames(models, narrow) {
  const n = Object.fromEntries(models.map((m) => [m.id, narrow ? m.short ?? m.name : m.name]))
  n.reference = narrow ? 'Reference' : 'Reference method'
  n.trivial = narrow ? 'Floor' : 'Floor (always "no change")'
  return n
}

function point(id, x, y) {
  const c = cls(id)
  if (c === 'ref') return `<rect class="fp-pt ref" x="${x - 4}" y="${y - 4}" width="8" height="8" transform="rotate(45 ${x} ${y})"/>`
  return `<circle class="fp-pt ${c}" cx="${x}" cy="${y}" r="${c === 'floor' ? 3.5 : 4.5}"/>`
}

// One block per task: each arm's pass rate with its 95% interval, and the task selection bar.
// With o.compact (the task card) the axis title and task heading are left out.
export function forestPlot(el, results, envs, names, models, o = {}) {
  const W = width(el)
  const narrow = W < 560
  const label = armNames(models, narrow)
  const left = narrow ? 112 : 250
  const valW = narrow ? 36 : 120
  const rowH = 22
  const head = o.compact ? 22 : 44
  const lo = 0.3
  const hi = 1.0
  const sx = (v) => left + ((v - lo) / (hi - lo)) * (W - left - valW - 12)
  const arms = [...models.map((m) => m.id), 'reference', 'trivial']
  let y = head
  const parts = []
  for (const e of envs) {
    const t = results.tasks[e]
    const shipped = t.status === 'included'
    if (!o.compact) {
      parts.push(`<rect x="0" y="${y + 3}" width="10" height="10" style="fill:var(--l-${names[e].fam})"/>`)
      parts.push(`<text class="fp-task" x="16" y="${y + 12}">${names[e].short}<tspan class="fp-status ${shipped ? 'in' : 'out'}" dx="10">${shipped ? 'selected' : t.pass[t.best].ci[0] > results.threshold ? 'held back, too easy' : 'held back, close call'}</tspan></text>`)
      y += rowH
    }
    for (const a of arms) {
      const s = t.pass[a]
      parts.push(`<text class="fp-arm" x="${o.compact ? 0 : 16}" y="${y + 12}">${label[a]}</text>`)
      if (!s) parts.push(`<text class="fp-val" x="${W - 2}" y="${y + 12}" text-anchor="end">not run</text>`)
      if (s) {
        parts.push(`<line class="fp-ci ${cls(a)}" x1="${sx(Math.max(lo, s.ci[0]))}" x2="${sx(s.ci[1])}" y1="${y + 8}" y2="${y + 8}"/>`)
        parts.push(point(a, sx(s.rate), y + 8))
        parts.push(`<text class="fp-val" x="${W - 2}" y="${y + 12}" text-anchor="end">${f2(s.rate)}${narrow ? '' : ` ${ci(s.ci)}`}</text>`)
      }
      y += rowH
    }
    y += o.compact ? 0 : 10
  }
  const H = y + 6
  const top = head - 6
  const threshold = results.threshold
  const grid = (narrow ? [...new Set([lo, 0.5, threshold, hi])].sort((a, b) => a - b) : [0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9, 1.0])
    .map((v) => `<line class="fp-grid" x1="${sx(v)}" x2="${sx(v)}" y1="${top}" y2="${H - 4}"/><text class="fp-tick" x="${sx(v)}" y="${top - 5}" text-anchor="middle">${v === threshold ? f2(v) : v.toFixed(1)}</text>`)
    .join('')
  const bar = `<rect class="fp-easy" x="${sx(threshold)}" y="${top}" width="${sx(hi) - sx(threshold)}" height="${H - 4 - top}"/>
    <line class="fp-bar" x1="${sx(threshold)}" x2="${sx(threshold)}" y1="${top}" y2="${H - 4}"/>`
  const titles = o.compact ? '' : `<text class="fp-axis" x="${sx(lo)}" y="12">pass rate</text>
    <text class="fp-axis" x="${sx(threshold) + 5}" y="12">${pct(threshold)} bar${narrow ? '' : ', too easy to ship above it'}</text>
    <text class="fp-axis" x="${W - 2}" y="${narrow ? 12 : top - 5}" text-anchor="end">${narrow ? '' : 'rate [95% interval]'}</text>`
  el.innerHTML = `<svg viewBox="0 0 ${W} ${H}" width="${W}" height="${H}" role="img" aria-label="Pass rate with 95% intervals per task and agent">${grid}${bar}${titles}${parts.join('')}</svg>`
}

// Headline: mean pass rate over the shipped tasks, one bar per arm, each task's own pass rate as
// a coloured tick on the bar so the mean never hides the parts.
export function compositeBars(el, comp, models, fams, taskNames) {
  const W = width(el)
  const narrow = W < 560
  const label = armNames(models, narrow)
  const left = narrow ? 112 : 250
  const valW = narrow ? 36 : 120
  const rowH = 34
  const sx = (v) => left + v * (W - left - valW - 12)
  const ids = [...models.map((m) => m.id), 'reference', 'trivial'].filter((a) => comp.arms[a])
  ids.sort((a, b) => comp.arms[b].mean - comp.arms[a].mean)
  const H = 28 + ids.length * rowH + 24
  const out = []
  for (const v of [0, 0.25, 0.5, 0.75, 1]) {
    out.push(`<line class="fp-grid" x1="${sx(v)}" x2="${sx(v)}" y1="20" y2="${H - 26}"/><text class="fp-tick" x="${sx(v)}" y="14" text-anchor="middle">${v}</text>`)
  }
  ids.forEach((a, i) => {
    const s = comp.arms[a]
    const y = 28 + i * rowH
    out.push(`<text class="fp-arm" x="0" y="${y + 15}">${label[a]}</text>`)
    out.push(`<rect class="cb-bar ${cls(a)}" x="${sx(0)}" y="${y + 3}" width="${sx(s.mean) - sx(0)}" height="16"/>`)
    out.push(`<line class="cb-ci" x1="${sx(s.ci[0])}" x2="${sx(s.ci[1])}" y1="${y + 11}" y2="${y + 11}"/>`)
    for (const x of s.ci) out.push(`<line class="cb-ci" x1="${sx(x)}" x2="${sx(x)}" y1="${y + 6}" y2="${y + 16}"/>`)
    s.per.forEach((p, k) => out.push(`<rect x="${sx(p) - 1.5}" y="${y}" width="3" height="22" style="fill:var(--l-${fams[k]})"/>`))
    out.push(`<text class="cb-val" x="${W - 2}" y="${y + 15}" text-anchor="end">${f2(s.mean)}${narrow ? '' : ` ${ci(s.ci)}`}</text>`)
  })
  out.push(`<text class="fp-axis" x="${sx(1)}" y="${H - 6}" text-anchor="end">mean pass rate over ${taskNames.join(' and ')}</text>`)
  const key = fams.map((f, k) => `<span><i style="background:var(--l-${f})"></i>${taskNames[k]} pass rate</span>`).join('')
  el.innerHTML = `<svg viewBox="0 0 ${W} ${H}" width="${W}" height="${H}" role="img" aria-label="Mean pass rate over the selected tasks per agent">${out.join('')}</svg>
    <div class="legend"><span><i class="k-bar"></i>agent</span><span><i class="k-ref"></i>reference method</span><span><i class="k-floor"></i>floor</span><span><i class="k-ci"></i>95% interval</span>${key}</div>`
}

// One marker shape per agent, so the time scatter can show task by colour and agent by shape.
function mark(j, x, y, c) {
  const st = `fill:${c};stroke:var(--sheet);stroke-width:1.5`
  if (j % 4 === 0) return `<circle cx="${x}" cy="${y}" r="5.5" style="${st}"/>`
  if (j % 4 === 1) return `<rect x="${x - 5}" y="${y - 5}" width="10" height="10" style="${st}"/>`
  if (j % 4 === 2) return `<path d="M${x} ${y - 6.5}L${x + 6} ${y + 4.5}L${x - 6} ${y + 4.5}Z" style="${st}"/>`
  return `<path d="M${x} ${y - 6.5}L${x + 6.5} ${y}L${x} ${y + 6.5}L${x - 6.5} ${y}Z" style="${st}"/>`
}

// Pass rate against wall-clock minutes per episode: one point per model and task.
export function timeScatter(el, results, envs, fams, models) {
  const W = width(el)
  const narrow = W < 560
  const legendW = 0
  const H = narrow ? 300 : 340
  const box = { x: 52, y: 16, w: W - 52 - legendW - 12, h: H - 60 }
  const walls = envs.flatMap((e) => models.flatMap((m) => results.tasks[e].pass[m.id]?.wall_min ?? []))
  const xmax = Math.max(10, Math.ceil(Math.max(...walls) / 5) * 5)
  const sx = (m) => box.x + (m / xmax) * box.w
  const sy = (v) => box.y + box.h - ((v - 0.3) / 0.7) * box.h
  const out = []
  for (let m = 0; m <= xmax; m += narrow ? 10 : 5) out.push(`<line class="fp-grid" x1="${sx(m)}" x2="${sx(m)}" y1="${box.y}" y2="${box.y + box.h}"/><text class="fp-tick" x="${sx(m)}" y="${box.y + box.h + 16}" text-anchor="middle">${m}</text>`)
  for (const v of [0.3, 0.5, 0.7, 0.9]) out.push(`<line class="fp-grid" x1="${box.x}" x2="${box.x + box.w}" y1="${sy(v)}" y2="${sy(v)}"/><text class="fp-tick" x="${box.x - 8}" y="${sy(v) + 4}" text-anchor="end">${v.toFixed(1)}</text>`)
  const thresholdY = sy(results.threshold)
  out.push(`<line class="fp-bar" x1="${box.x}" x2="${box.x + box.w}" y1="${thresholdY}" y2="${thresholdY}"/><text class="fp-axis" x="${box.x + 6}" y="${thresholdY - 6}">${pct(results.threshold)} bar</text>`)
  out.push(`<text class="fp-axis" x="${box.x + box.w}" y="${H - 8}" text-anchor="end">median minutes per episode</text>`)
  out.push(`<text class="fp-axis" transform="translate(14 ${box.y + box.h / 2}) rotate(-90)" text-anchor="middle">pass rate</text>`)
  envs.forEach((e, k) => {
    models.forEach((m, j) => {
      const s = results.tasks[e].pass[m.id]
      const w = s?.wall_min
      if (!w?.length) return
      const median = (w[Math.floor((w.length - 1) / 2)] + w[Math.floor(w.length / 2)]) / 2
      const x = sx(median)
      const y = sy(s.rate)
      const c = `var(--l-${fams[k]})`
      out.push(`<line x1="${sx(w[0])}" x2="${sx(w[w.length - 1])}" y1="${y}" y2="${y}" style="stroke:${c};stroke-opacity:0.5"/>`)
      out.push(`<line x1="${x}" x2="${x}" y1="${sy(s.ci[0])}" y2="${sy(s.ci[1])}" style="stroke:${c};stroke-width:1.5"/>`)
      out.push(mark(j, x, y, c))
    })
  })
  el.innerHTML = `<svg viewBox="0 0 ${W} ${H}" width="${W}" height="${H}" role="img" aria-label="Pass rate against minutes per episode">${out.join('')}</svg>
    <div class="legend">${envs.map((e, k) => `<span><i class="sq" style="background:var(--l-${fams[k]})"></i>${results.tasks[e].label}</span>`).join('')}
    ${models.map((m, j) => `<span><svg width="12" height="12" viewBox="-6 -6 12 12" style="display:inline-block;vertical-align:-1px;margin-right:5px">${mark(j, 0, 0, 'var(--ink-2)')}</svg>${m.short ?? m.name}</span>`).join('')}</div>`
}
