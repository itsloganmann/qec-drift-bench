// Page wiring: task content, the leaderboard, the task card and table, the instance viewer, the
// result charts and the shortcut checks. Every number comes from data/results.json. The 3D chip
// loads last and on its own, so the page still works when WebGL or the CDN does not.

import { drawReadout, drawPulse, drawFlux, drawQec } from './views.js'
import { forestPlot, compositeBars, timeScatter } from './charts.js'

const ORDER = ['readout', 'pulse', 'flux', 'qec']
const ENV = { readout: 'readout_drift', pulse: 'pulse_wrong_model', flux: 'flux_distortion', qec: 'qec_drift_d3' }
const PENDING = ['GPT-5.6 Sol', 'Gemini 3.8 Flash']
const MODELS = [{ id: 'claude-opus-5-5', name: 'Claude Opus 5.5' }, { id: 'claude-sonnet-5-5', name: 'Claude Sonnet 5.5' }]
const ARXIV = (id) => `https://arxiv.org/abs/${id}`

const TASKS = {
  readout: {
    name: 'Readout drift', short: 'Readout', part: 'Readout resonators and feedline',
    q: 'A qubit was read out and calibrated this morning. Has the IQ signal drifted since, and how? Refit the discriminator only if something really changed.',
    gets: '4,000 labelled calibration shots, and a few hundred new unlabelled shots from 8 runs, as points in the IQ plane.',
    returns: 'A discriminator for each run, a changed call, the drift families and their sizes.',
    sources: [['Blais 2021', '2005.12667'], ['Krantz 2019', '1904.06560'], ['Google Quantum AI 2024', '2408.13687'], ['Klimov 2018', '1809.01043']],
    changes: 'Phase rotation, phase ramp, gain drop, resonator shift, noise growth, T1 drop, and a change the device model does not describe.',
  },
  pulse: {
    name: 'Pulse under a wrong model', short: 'Pulse', part: 'XY drive line',
    q: 'Ship a 6 ns X gate for a transmon. Is the design model still right, or has the drive line or the qubit moved since the pulse was designed?',
    gets: 'The design model and its DRAG pulse, a Rabi sweep, a Ramsey trace and an amplified-error check.',
    returns: 'Twelve complex pulse samples and a diagnosis: drive scale, frequency shift, compression, or something else.',
    sources: [['Koch 2007', 'cond-mat/0703002'], ['Motzoi 2009', '0901.0534'], ['McKay 2017', '1612.00858'], ['Lazar 2023', '2212.01077']],
    changes: 'Drive gain, qubit frequency by tens of kHz, a drive line that compresses at high amplitude, and a change outside the model.',
  },
  flux: {
    name: 'Flux line distortion', short: 'Flux', part: 'Flux bias line and SQUID',
    q: 'The flux line smears every pulse with slow tails. From one step-response measurement, has the line drifted, which part, and what predistortion fixes it?',
    gets: 'The nominal four-stage line model and the measured step response, 1 ns to 20 us, with its noise.',
    returns: 'New predistortion stages, an optional FIR filter, and which stage changed or which new tail appeared.',
    sources: [['Rol 2020', '1907.04818'], ['Hellings 2025', '2503.04610'], ['Venkateswaran 2026', '2604.15895']],
    changes: 'One stage changes, a new tail appears, both, or a change no stage can describe.',
  },
  qec: {
    name: 'QEC decoder drift', short: 'QEC', part: 'Surface-code lattice, 17 qubits',
    q: 'A distance-3 surface code decodes with a nominal noise model. From syndromes alone: did the device change, what changed, and what is the right model now?',
    gets: 'The Stim circuit, 50,000 labelled shots from before and 50,000 unlabelled shots from now.',
    returns: 'A detector error model that PyMatching decodes, and a diagnosis: kind, qubit, factor, onset.',
    sources: [['Bhardwaj 2025', '2511.09491'], ['Takou 2026', '2606.11496'], ['Burnett 2019', '1901.04417'], ['McEwen 2024', '2402.15644']],
    changes: 'A hot qubit, a hot coupler, a decaying burst, a switching TLS, and a change outside the listed kinds.',
  },
}
const LABEL = {
  none: 'no change (control)', control: 'no change (control)', hot: 'hot qubit', onset: 'hot qubit that switches on during the batch', coupler: 'hot coupler', burst: 'burst', tls: 'TLS switching',
  freq: 'qubit frequency moved', compress: 'drive compression', scale: 'drive gain changed', scale_compress: 'drive gain and compression',
  tail_changed: 'one stage changed', new_tail: 'new tail', both: 'stage changed and new tail',
}
const truthText = (f, t) => (f === 'readout'
  ? (t.length ? t.map(([k, s]) => `${k.replace('_', ' ')}${s === 'near' ? ' (just above the floor)' : ''}`).join(' + ') : 'no change (control)')
  : LABEL[t] ?? t)
const CAPTION = {
  readout: (i) => `Before: ${i.calib.length} of the ${i.calib_n.toLocaleString('en-US')} labelled calibration shots, drawn at random. Now: every new shot the agent gets.`,
  pulse: () => 'The two measurements an agent gets on the qubit as it is now, with shot noise.',
  flux: () => 'The measured step response through the predistortion in use now. The band is the stated noise.',
  qec: () => 'The lattice map shows how much more or less often each stabiliser fires now than before. The trace shows the firing rate across the new batch, in 25 windows.',
}

const $ = (s) => document.querySelector(s)
const f2 = (v) => v.toFixed(2)
const pct = (v) => `${Math.round(v * 100)}%`
const day = (d) => new Date(`${d}T12:00:00Z`).toLocaleDateString('en-GB', { day: 'numeric', month: 'short', year: 'numeric', timeZone: 'UTC' })
let results = null
let instances = null
let chip = null
let current = 'readout'
let inst = 0

const shippedEnvs = () => ORDER.filter((f) => results.tasks[ENV[f]].status === 'included')
const names = () => Object.fromEntries(ORDER.map((f) => [ENV[f], { short: TASKS[f].short, fam: f }]))

// Rank as on arena leaderboards: 1 plus the number of agents whose interval sits wholly above.
function ranks(ids, arms) {
  return Object.fromEntries(ids.map((a) => [a, 1 + ids.filter((b) => arms[b].ci[0] > arms[a].ci[1]).length]))
}

function renderLeaderboard() {
  const comp = results.composite.arms
  const shipped = shippedEnvs()
  const held = ORDER.filter((f) => !shipped.includes(f))
  const cols = [...shipped, ...held]
  $('#lb thead').innerHTML = `<tr><th>Rank</th><th>Agent</th><th>Pass rate</th>${cols.map((f) => `<th class="${shipped.includes(f) ? '' : 'heldh'}">${TASKS[f].short}${shipped.includes(f) ? '' : '<span class="tag">held back</span>'}</th>`).join('')}</tr>`
  const cell = (s) => (s ? `<span class="mono">${f2(s.rate)}</span><span class="iv">[${f2(s.ci[0])}, ${f2(s.ci[1])}]</span>` : '<span class="mono">-</span>')
  const tasks = (id) => cols.map((f) => `<td class="${shipped.includes(f) ? '' : 'heldc'}">${cell(results.tasks[ENV[f]].pass[id])}</td>`).join('')
  const ids = MODELS.map((m) => m.id).sort((a, b) => comp[b].mean - comp[a].mean)
  const rk = ranks(ids, comp)
  const name = Object.fromEntries(MODELS.map((m) => [m.id, m.name]))
  const rows = ids.map((id) => `<tr><td class="rank">${rk[id]}</td><td>${name[id]}</td><td class="score">${cell({ rate: comp[id].mean, ci: comp[id].ci })}</td>${tasks(id)}</tr>`)
  rows.push(`<tr class="pending"><td class="rank">-</td><td colspan="${2 + cols.length}">${PENDING.join(', ')}<span class="tag">pending</span> Not scored yet. They will run under the same rule and harness before the first release.</td></tr>`)
  for (const [id, label] of [['reference', 'Reference method'], ['trivial', 'Floor: always answer "no change"']]) {
    rows.push(`<tr class="base"><td class="rank"></td><td>${label}</td><td class="score">${cell({ rate: comp[id].mean, ci: comp[id].ci })}</td>${tasks(id)}</tr>`)
  }
  $('#lb tbody').innerHTML = rows.join('')

  // The sentences round the table, written from the same numbers.
  const best = ids[0]
  const ref = comp.reference
  const agents = ids.map((id) => `${f2(comp[id].mean)} for ${name[id]}`).join(' and ')
  const changed = shipped.flatMap((f) => MODELS.map((m) => results.tasks[ENV[f]].pass[m.id].split.changed.rate))
  const beat = comp[best].mean > ref.mean
  $('#lead').textContent = `${beat ? `${name[best]} leads the scripted reference method` : 'No agent beats the scripted reference method yet'}: its pass rate on the shipped tasks is ${f2(ref.mean)}, against ${agents}, and the intervals overlap. On devices that really changed, the agents pass only ${pct(Math.min(...changed))} to ${pct(Math.max(...changed))} of instances.`
  const walls = ORDER.flatMap((f) => MODELS.flatMap((m) => results.tasks[ENV[f]].pass[m.id].wall_min ?? []))
  const [d0, d1] = results.scored
  $('#lbnote').innerHTML = `Pass rate: the mean over ${shipped.map((f) => TASKS[f].short).join(' and ')} of the share of instances that pass the <a href="#defs">pass rule</a>. Interval: approximate 95%, from a bootstrap over the ${results.composite.clusters} seed clusters and the instances in each. Rank: 1 plus the number of agents whose interval sits wholly above. ${held.map((f) => TASKS[f].short).join(' and ')} are held back and do not count: their best agent is just above the 75% bar, but its interval crosses it. Both agents ran in Claude Code, headless, with no network and the grader out of reach, on ${d0 === d1 ? day(d0) : `${day(d0)} to ${day(d1)}`}; episodes took ${Math.round(Math.min(...walls))} to ${Math.round(Math.max(...walls))} minutes. Pending models also appear on the <a href="https://www.kaggle.com/benchmarks/loganmann24/quantum-bench/leaderboard">Kaggle leaderboard</a>, scored there with each task's own rubric, not this pass rule.`
  $('#stamp-date').textContent = `Scored ${day(d1)}`
  $('#stamp-tasks').textContent = `${shipped.length} of ${ORDER.length} tasks shipped`
}

function renderCard(f) {
  const t = TASKS[f]
  const r = results.tasks[ENV[f]]
  const shipped = r.status === 'included'
  const best = r.pass[r.best]
  const who = MODELS.find((m) => m.id === r.best)?.name ?? r.best
  const card = $('#card')
  card.style.setProperty('--c', `var(--l-${f})`)
  card.innerHTML = `
    <div class="tabs" role="group" aria-label="Choose a task">${ORDER.map((g) => `<button type="button" data-f="${g}" aria-pressed="${g === f}" style="--c:var(--l-${g})">${TASKS[g].short}</button>`).join('')}</div>
    <div class="card-head"><span class="num">${ORDER.indexOf(f) + 1}</span><h2>${t.name}</h2>
      <span class="chipstat ${shipped ? 'in' : 'out'}">${shipped ? 'Shipped' : 'Held back'}</span></div>
    <p class="q">${t.q}</p>
    <dl>
      <div><dt>Agent gets</dt><dd>${t.gets}</dd></div>
      <div><dt>Agent returns</dt><dd>${t.returns}</dd></div>
      <div><dt>What can change</dt><dd>${t.changes}</dd></div>
      <div><dt>Best agent</dt><dd>${who} passes <span class="mono">${f2(best.rate)} [${f2(best.ci[0])}, ${f2(best.ci[1])}]</span>${shipped ? '.' : '. That is above the 75% bar, but the interval crosses it, so the task is held back as a close call.'}</dd></div>
    </dl>
    <div><div class="label">Pass rate on this task</div><div id="cardplot" class="mini"></div></div>
    <p class="src">Physics: ${t.sources.map(([n, id]) => `<a href="${ARXIV(id)}">${n}</a>`).join(', ')}. Full citations in the task's TASK.md.</p>
    <p class="src"><a href="#data">See the data an agent gets</a> <span aria-hidden="true">/</span> <a href="#${f}">Link to this task</a></p>`
  forestPlot($('#cardplot'), results, [ENV[f]], names(), MODELS, { compact: true })
  card.querySelectorAll('.tabs button').forEach((b) => b.addEventListener('click', () => select(b.dataset.f, true, true)))
}

function renderTable() {
  $('#bom tbody').innerHTML = ORDER.map((f) => {
    const t = TASKS[f]
    const shipped = results.tasks[ENV[f]].status === 'included'
    return `<tr data-f="${f}" style="--c:var(--l-${f})"${f === current ? ' aria-current="true"' : ''} class="${shipped ? '' : 'held'}">
      <td><button type="button" class="fam" data-f="${f}"><span class="sw" style="--c:var(--l-${f})"></span>${t.name}</button><div class="mono env">${ENV[f]}</div></td>
      <td>${t.part}</td><td>${t.gets}</td><td>${t.returns}</td><td><span class="chipstat ${shipped ? 'in' : 'out'}">${shipped ? 'Shipped' : 'Held back'}</span></td></tr>`
  }).join('')
  $('#bom').querySelectorAll('tr[data-f]').forEach((tr) => tr.addEventListener('click', () => select(tr.dataset.f, true, true)))
}

const DRAW = { readout: drawReadout, pulse: drawPulse, flux: drawFlux, qec: drawQec }
function renderViewer() {
  const list = instances[current]
  inst = Math.min(inst, list.length - 1)
  $('#vname').textContent = TASKS[current].name
  $('#vpick').innerHTML = list.map((_, i) => `<button type="button" aria-pressed="${i === inst}" data-i="${i}" aria-label="Example ${i + 1}">${i + 1}</button>`).join('')
  $('#vpick').querySelectorAll('button').forEach((b) => b.addEventListener('click', () => { inst = +b.dataset.i; $('#vreveal').setAttribute('aria-pressed', 'false'); renderViewer() }))
  const shown = $('#vreveal').getAttribute('aria-pressed') === 'true'
  $('#vtruth').textContent = shown ? `Hidden change: ${truthText(current, list[inst].truth)}` : ''
  $('#vreveal').textContent = shown ? 'Hide the hidden change' : 'Show the hidden change'
  $('#vcap').textContent = CAPTION[current](list[inst])
  const cv = $('#vcanvas')
  const narrow = cv.clientWidth < 600
  const tall = { readout: [700, 460], pulse: [640, 340], flux: [360, 340], qec: [700, 400] }[current]
  cv.style.height = `${narrow ? tall[0] : tall[1]}px`
  cv.setAttribute('aria-label', `${TASKS[current].name}, example ${inst + 1}. ${CAPTION[current](list[inst])}`)
  DRAW[current](cv, list[inst])
}
$('#vreveal').addEventListener('click', (e) => {
  const on = e.currentTarget.getAttribute('aria-pressed') !== 'true'
  e.currentTarget.setAttribute('aria-pressed', String(on))
  renderViewer()
})

function select(f, fly, user = false) {
  current = f
  inst = 0
  $('#vreveal').setAttribute('aria-pressed', 'false')
  renderCard(f)
  $('#bom').querySelectorAll('tr[data-f]').forEach((tr) => (tr.dataset.f === f ? tr.setAttribute('aria-current', 'true') : tr.removeAttribute('aria-current')))
  if (instances) renderViewer()
  chip?.select(f, fly)
  if (user) history.replaceState(null, '', `#${f}`)
}

function renderSplit() {
  const arms = [...MODELS, { id: 'reference', name: 'Reference method' }]
  const shipped = shippedEnvs()
  $('#split thead').innerHTML = `<tr><th rowspan="2">Agent</th>${ORDER.map((f) => `<th colspan="2" class="grp${shipped.includes(f) ? '' : ' heldh'}">${TASKS[f].short}</th>`).join('')}</tr>
    <tr>${ORDER.map(() => '<th class="v">controls</th><th class="v">changed</th>').join('')}</tr>`
  const bar = (v) => `<span class="bar" style="width:${Math.round(v * 40)}px"></span>${f2(v)}`
  $('#split tbody').innerHTML = arms.map((a) => `<tr><td>${a.name}</td>${ORDER.map((f) => {
    const s = results.tasks[ENV[f]].pass[a.id].split
    return `<td class="v">${bar(s.controls.rate)}</td><td class="v">${bar(s.changed.rate)}</td>`
  }).join('')}</tr>`).join('')
  const ro = results.tasks[ENV.readout].pass
  const fa = MODELS.map((m) => 1 - ro[m.id].split.controls.rate)
  $('#splitnote').textContent = `Controls are devices with only normal wander; the right answer is "no change". The floor passes every control and no changed device. On Readout the agents raise a false alarm on ${pct(Math.min(...fa))} to ${pct(Math.max(...fa))} of controls, against ${pct(1 - ro.reference.split.controls.rate)} for the reference method.`
}

function renderCharts() {
  const shipped = shippedEnvs()
  for (const f of ORDER) results.tasks[ENV[f]].label = TASKS[f].short
  compositeBars($('#composite'), results.composite, MODELS, shipped, shipped.map((f) => TASKS[f].short))
  forestPlot($('#forest'), results, ORDER.map((f) => ENV[f]), names(), MODELS)
  timeScatter($('#scatter'), results, ORDER.map((f) => ENV[f]), ORDER, MODELS)
  if ($('#cardplot')) forestPlot($('#cardplot'), results, [ENV[current]], names(), MODELS, { compact: true })
}

const CHEATS = [
  ['never', 'Always answer "no change"'],
  ['always', 'Always answer "changed" and refit'],
  ['other', 'Always answer "something unlisted"'],
  ['const', 'Return one fixed answer'],
  ['swapped', 'Run the reference on another instance\'s data'],
  ['frames', 'Search the call stack for the truth'],
  ['import', 'Import the grader'],
  ['malformed', 'Return a malformed answer'],
]
function renderCheats() {
  $('#cheat thead').innerHTML = `<tr><th>Strategy</th>${ORDER.map((f) => `<th class="v">${TASKS[f].short}</th>`).join('')}</tr>`
  const bar = (v) => `<span class="bar" style="width:${Math.round(v * 60)}px"></span>${f2(v)}`
  const body = CHEATS.map(([k, lab]) => `<tr><td>${lab}</td>${ORDER.map((f) => `<td class="v">${bar(results.tasks[ENV[f]].cheats[k])}</td>`).join('')}</tr>`)
  body.push(`<tr class="ok"><td>Reference method, for scale</td>${ORDER.map((f) => `<td class="v">${bar(results.tasks[ENV[f]].native.reference[0])}</td>`).join('')}</tr>`)
  $('#cheat tbody').innerHTML = body.join('')
}

$('#copybib').addEventListener('click', async (e) => {
  const btn = e.currentTarget
  try {
    await navigator.clipboard.writeText($('#bib').textContent)
    btn.textContent = 'Copied'
  } catch {
    const range = document.createRange()
    range.selectNodeContents($('#bib'))
    getSelection().removeAllRanges()
    getSelection().addRange(range)
    btn.textContent = 'Selected, press copy'
  }
  setTimeout(() => { btn.textContent = 'Copy BibTeX' }, 1800)
})

async function loadChip() {
  try {
    const { createChip } = await import('./chip.js')
    chip = createChip($('#stage'), { root: $('#stage'), svg: $('#ov'), names: Object.fromEntries(ORDER.map((f) => [f, TASKS[f].name])) }, {
      onSelect: (f) => select(f, true, true),
      onHover: () => {},
    })
    chip.select(current, false)
  } catch (err) {
    console.warn('3D chip not shown:', err)
    $('#stage').classList.add('nochip')
    $('#stage').insertAdjacentHTML('beforeend', '<p class="nochip-msg">The 3D chip could not load in this browser. Pick a task with the buttons beside it or in the table below.</p>')
  }
}

async function main() {
  results = await (await fetch('data/results.json')).json()
  renderLeaderboard()
  renderTable()
  renderCharts()
  renderSplit()
  renderCheats()
  const fromHash = () => {
    const f = location.hash.slice(1)
    if (!ORDER.includes(f)) return false
    select(f, true)
    $('#tasks-h').scrollIntoView({ behavior: matchMedia('(prefers-reduced-motion: reduce)').matches ? 'auto' : 'smooth' })
    return true
  }
  if (!fromHash()) select('readout', false)
  window.addEventListener('hashchange', fromHash)
  loadChip()
  instances = await (await fetch('data/instances.json')).json()
  renderViewer()
  let raf = 0
  let lastW = 0
  const redraw = () => { cancelAnimationFrame(raf); raf = requestAnimationFrame(() => { renderViewer(); renderCharts() }) }
  new ResizeObserver(() => { const w = $('.wrap').clientWidth; if (w !== lastW) { lastW = w; redraw() } }).observe($('.wrap'))
  window.matchMedia('(prefers-color-scheme: dark)').addEventListener('change', redraw)
  new MutationObserver(redraw).observe(document.documentElement, { attributes: true, attributeFilter: ['data-theme'] })
}
main()
