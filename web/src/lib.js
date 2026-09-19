/* Shared catalog logic for the Field Museum UI.
   Deliberately mirrors the shapes in web/public/agents/schema.json so a browser
   row, an NDJSON record and an MCP tool result decode the same way. */

export async function getJson(path) {
  const base = import.meta.env.BASE_URL || './'
  const res = await fetch(base + path.replace(/^\.\//, ''), { cache: 'force-cache' })
  if (!res.ok) throw new Error(`${res.status} ${path}`)
  return res.json()
}

export function domainSlug(name) {
  return String(name || 'unclassified')
    .toLowerCase()
    .replace(/&/g, 'and')
    .replace(/[^a-z0-9]+/g, '-')
    .replace(/^-|-$/g, '') || 'unclassified'
}

/** Integer-dictionary rows -> objects. Column order = packed.row_format. */
export function decodeRows(packed) {
  const { domains = {}, subsystems = {}, moves = {}, stacks = {}, awards = {}, events = {} } = packed
  const dict = (table, i) => table[String(i)] ?? null
  return (packed.rows || []).map((r, i) => {
    const ev = events[String(r[3])] || []
    return {
      idx: i,
      id: r[0],
      name: r[1],
      hook: r[2],
      eventSlug: ev[0] || null,
      event: ev[1] || null,
      eventOrg: ev[2] || null,
      eventRegistrations: ev[3] || 0,
      eventPrize: ev[4] || 0,
      eventHue: ev[5] || '#877c63',
      likes: r[4] === -1 ? null : r[4],
      coolness: (r[5] || 0) / 1000,
      domain: dict(domains, r[6]) || 'Emerging & Cross-Domain',
      subsystem: dict(subsystems, r[7]) || 'General',
      moves: (r[8] || []).map((m) => dict(moves, m)).filter(Boolean),
      stack: (r[9] || []).map((s) => dict(stacks, s)).filter(Boolean),
      depth: r[10] ? 'deep' : 'listing',
      hasThumbnail: !!r[11],
      award: dict(awards, r[12]) || 'Unknown',
      ageDays: r[13],
      url: `https://devpost.com/software/${r[0]}`,
      accession: `ACC·${String(i + 1).padStart(4, '0')}`,
      // audit layer (row_format 15/16): dictionary ids -> verdict names. A pre-audit
      // build has 14 columns, so read them defensively: absent must mean "unaudited",
      // never "verified".
      verdict: r.length > 15 ? (packed.verdicts || {})[String(r[14])] ?? null : null,
      worth: r.length > 15 ? (packed.worth || {})[String(r[15])] ?? null : null,
      vetted: r.length > 15
        ? ['strong', 'sound-with-caveats'].includes((packed.verdicts || {})[String(r[14])])
        : false,
    }
  })
}

const STOP = new Set(['the','and','with','for','that','this','from','into','your','they','them','its','our','are','was','has','have','not','but','all','can','you','use','when','than','then','also','more','their','what'])

export function tokenize(text) {
  return String(text || '')
    .toLowerCase()
    .replace(/[^a-z0-9\s]/g, ' ')
    .split(/\s+/)
    .filter((t) => t.length > 2 && !STOP.has(t))
}

/** Tiny inverted index: built once per catalog, keeps search flat under ~5ms. */
export function buildIndex(rows) {
  const index = new Map()
  rows.forEach((row, i) => {
    const hay = [...tokenize(`${row.name} ${row.hook} ${row.domain} ${row.subsystem} ${row.event}`),
      ...row.moves, ...row.stack]
    for (const t of hay) {
      let bucket = index.get(t)
      if (!bucket) index.set(t, (bucket = new Set()))
      bucket.add(i)
    }
  })
  return index
}

export function searchRows(rows, index, query, limit = 200) {
  const terms = [...new Set(tokenize(query))]
  if (!terms.length) return rows.map((row) => ({ row, score: row.coolness }))
  const buckets = terms.map((t) => {
    const exact = index.get(t)
    if (exact) return exact
    const prefix = new Set()
    for (const [tok, set] of index) {
      if (tok.startsWith(t)) set.forEach((i) => prefix.add(i))
    }
    return prefix
  })
  const scored = []
  buckets.forEach((set, bi) => {
    for (const i of set) {
      scored[i] = (scored[i] || 0) + 1
    }
    void bi
  })
  scored.forEach((hits, i) => {
    if (hits > 0) scored[i] = hits / terms.length + rows[i].coolness
  })
  const out = []
  scored.forEach((s, i) => s > 0 && out.push({ row: rows[i], score: s }))
  out.sort((a, b) => b.score - a.score)
  return out.slice(0, limit)
}

export function scorePartsOf(row, detail) {
  return (detail && detail.coolness_parts) || null
}

export const SORTS = {
  coolness: (a, b) => b.coolness - a.coolness || a.name.localeCompare(b.name),
  specific: (a, b) => (b.specificity || b.coolness) - (a.specificity || a.coolness),
  recent: (a, b) => (a.ageDays ?? 9e3) - (b.ageDays ?? 9e3),
  likes: (a, b) => (b.likes ?? -1) - (a.likes ?? -1),
  az: (a, b) => a.name.localeCompare(b.name),
}

export function ideaMarkdown(row, detail) {
  const intel = detail?.inspiration_intel
  const lines = [
    `### ${row.name} — ${row.accession}`,
    `_${row.url}_`,
    '',
    `**Hackathon:** ${row.event || 'unattributed'}${row.eventOrg ? ` (${row.eventOrg})` : ''}`,
    `**Sector:** ${row.domain} · ${row.subsystem}`,
    `**Coolness:** ${row.coolness.toFixed(3)} (scoring_version 1) · **Depth:** ${row.depth}` +
      (row.likes === null ? '' : ` · **Likes:** ${row.likes}`),
    row.award && row.award !== 'Unknown' ? `**Recognition:** ${row.award}` : '',
    '',
    row.hook ? `> ${row.hook}` : '',
    '',
  ]
  if (row.moves.length) {
    lines.push('**Steal these moves:**')
    row.moves.forEach((m) => lines.push(`- \`${m}\`${intel?.steal_this?.length ? ` — ${intel.steal_this[row.moves.indexOf(m)] || ''}` : ''}`))
    lines.push('')
  }
  if (intel) {
    if (intel.the_wedge) lines.push(`**The wedge:** ${intel.the_wedge}`, '')
    if (intel.naive_version_vs_this) lines.push(`**Naive vs. this:** ${intel.naive_version_vs_this}`, '')
    if (intel.reuse_surface) lines.push(`**Transfers to:** ${intel.reuse_surface}`, '')
    if (detail?.quote) lines.push(`> ${detail.quote}`, '')
  }
  if (row.stack.length) lines.push(`**Stack (authors' tags + inferred):** ${row.stack.join(', ')}`, '')
  const links = [detail?.repo_url && `[code](${detail.repo_url})`, detail?.demo_url && `[demo](${detail.demo_url})`,
    detail?.video_url && `[video](${detail.video_url})`].filter(Boolean)
  if (links.length) lines.push(`**Links:** ${links.join(' · ')}`, '')
  lines.push('_Provenance: summary/links observed on Devpost; sector, moves and score are derived by Ideas Galore._')
  return lines.filter((l) => l !== '').join('\n')
}

export function shelfMarkdown(ids, rows, details) {
  const chosen = ids.map((id) => rows.find((r) => r.id === id)).filter(Boolean)
  return [
    '# Idea shelf — Ideas Galore',
    '',
    `Exported ${new Date().toISOString().slice(0, 10)} · ${chosen.length} accessioned idea(s).`,
    '',
    ...chosen.map((row) => ideaMarkdown(row, details[row.id])),
  ].join('\n\n')
}

export async function copyText(text) {
  try {
    await navigator.clipboard.writeText(text)
    return true
  } catch {
    const ta = document.createElement('textarea')
    ta.value = text
    document.body.appendChild(ta)
    ta.select()
    const ok = document.execCommand('copy')
    ta.remove()
    return ok
  }
}

export function downloadText(name, text, type = 'text/markdown') {
  const url = URL.createObjectURL(new Blob([text], { type }))
  const a = document.createElement('a')
  a.href = url
  a.download = name
  a.click()
  setTimeout(() => URL.revokeObjectURL(url), 2000)
}

/* ── audit layer ─────────────────────────────────────────────────────────
   Everything here reads the same files the gates validate and the MCP server
   serves, so "is this vetted?" has one answer in the browser and in the API. */

export const AUDIT_STATUS_TONE = {
  confirmed: 'ok', supported: 'ok', partial: 'warn', unverifiable: 'mute',
  contradicted: 'bad', duplicate: 'mute',
}

/** Check order in the inspector: can you hold it → is the build real → is it honest. */
export const AUDIT_CHECK_ORDER = [
  'artifact_exists', 'build_is_real', 'test_or_eval_evidence',
  'numbers_add_up', 'stack_consistency', 'limits_disclosed',
]

export const AUDIT_CHECK_LABELS = {
  artifact_exists: 'artifact exists',
  build_is_real: 'build is real',
  test_or_eval_evidence: 'tests / eval evidence',
  numbers_add_up: 'numbers add up',
  stack_consistency: 'stack is consistent',
  limits_disclosed: 'limits disclosed',
}

/** The 12 mandatory fields, in reading order for a builder. */
export const AUDIT_FIELD_ORDER = [
  'what_it_is', 'what_it_does', 'how_it_works', 'numbers_with_arithmetic',
  'data_and_models', 'how_they_tested', 'limits_they_disclosed', 'built_with_verified',
  'what_to_steal', 'what_breaks_first', 'clone_cost', 'prior_art',
]

export const AUDIT_FIELD_LABELS = {
  what_it_is: 'what it is',
  what_it_does: 'what it does',
  how_it_works: 'how it works',
  numbers_with_arithmetic: 'the numbers, with the arithmetic',
  data_and_models: 'data & models',
  how_they_tested: 'how they tested it',
  limits_they_disclosed: 'limits they disclosed',
  built_with_verified: 'built with (verified)',
  what_to_steal: 'what to steal',
  what_breaks_first: 'what breaks first in a rebuild',
  clone_cost: 'cost to clone it',
  prior_art: 'prior art it should credit',
}

export function toneClass(tone) {
  return {
    ok: 'border-brass-500 text-brass-700',
    warn: 'border-signal-500 text-signal-700',
    bad: 'border-signal-700 text-signal-900 bg-signal-100/50',
    mute: 'border-bone-400 text-bone-500',
  }[tone] || 'border-bone-400 text-bone-500'
}

const _jsonCache = new Map()
async function cachedJson(path) {
  if (!_jsonCache.has(path)) {
    _jsonCache.set(path, getJson(path).catch(() => null))
  }
  return _jsonCache.get(path)
}

/** The rubric, so the UI explains verdicts with the same words the gates enforce. */
export async function fetchRubric() {
  const rub = await cachedJson('data/audit-rubric.json')
  return rub && rub.verdicts ? rub : null
}

/** Full audit sheet for one record: fields + evidence + per-check reasoning. */
export async function fetchAuditSheet(row) {
  if (!row) return null
  const key = `data/audits/${domainSlug(row.domain)}.json`
  const sheet = await cachedJson(key)
  const fromSheet = sheet?.records?.[row.id]
  if (fromSheet) return fromSheet
  const index = await cachedJson('data/audits.json')     // pre-audit / small-build fallback
  return index?.records?.[row.id] || null
}

/** Records the audit held out of the catalog — leads, not vetted examples. */
export async function fetchPool() {
  const pool = await cachedJson('data/pool.json')
  return pool ? { count: pool.count || (pool.records || []).length, records: pool.records || [] } : null
}

export function verdictTone(verdict) {
  if (!verdict) return 'mute'
  return { strong: 'ok', 'sound-with-caveats': 'ok', thin: 'mute', duplicate: 'warn', unsound: 'bad' }[verdict] || 'mute'
}

export function auditHeadline(row, sheet, rubric) {
  const verdict = row?.verdict || sheet?.verdict || null
  const score = sheet?.soundness_score
  const cov = sheet?.rubric_coverage
  return {
    verdict,
    verdictLabel: verdict ? (rubric?.verdicts?.[verdict] || verdict) : 'not audited yet',
    worth: row?.worth || sheet?.worth || null,
    worthLabel: row?.worth ? (rubric?.worth?.[row.worth] || row.worth) : null,
    score: typeof score === 'number' ? score : null,
    coverage: typeof cov === 'number' ? cov : null,
    tone: verdictTone(verdict),
    vetted: verdict === 'strong' || verdict === 'sound-with-caveats',
  }
}

/** Markdown for the audit block — appended to ideaMarkdown() so an exported brief
   carries the caveats instead of leaving the reader to guess them. */
export function auditMarkdown(row, sheet, rubric) {
  const head = auditHeadline(row, sheet, rubric)
  const lines = ['', `**Audit verdict:** ${head.verdict || 'unaudited'}` +
    (head.worth ? ` · worth copying: ${head.worth}` : '') +
    (head.score !== null ? ` · soundness ${head.score.toFixed(2)} over ${Math.round((head.coverage ?? 0) * 100)}% of the rubric` : '')]
  if (sheet?.worth_note) lines.push(`> ${sheet.worth_note}`)
  const steal = sheet?.fields?.what_to_steal?.value
  if (steal) lines.push(`**What to steal:** ${steal}`)
  const breaks = sheet?.fields?.what_breaks_first?.value
  if (breaks) lines.push(`**What breaks first:** ${breaks}`)
  const cc = sheet?.fields?.clone_cost?.value
  if (cc?.estimate) {
    lines.push(`**Cost to clone:** ${cc.estimate}${cc.why ? ` — ${cc.why}` : ''}`)
    if (cc.assumptions?.length) lines.push(cc.assumptions.map((a) => `  - assumes: ${a}`).join('\n'))
  }
  const checks = sheet?.checks || {}
  const names = Object.keys(checks).length ? Object.keys(checks) : []
  if (names.length) {
    lines.push('', '**Checks:**')
    names.forEach((k) => {
      const c = checks[k] || {}
      lines.push(`- ${AUDIT_CHECK_LABELS[k] || k}: ${c.status}${typeof c.pass === 'number' ? ` (${c.pass.toFixed(2)})` : ''}${c.why ? ` — ${c.why}` : ''}`)
    })
  }
  const unknowns = sheet?.unknowns || []
  if (unknowns.length) {
    lines.push('', '**What we could not fill in (do not guess these):**')
    unknowns.forEach((u) => lines.push(`- ${AUDIT_FIELD_LABELS[u.field] || u.field}: ${u.missing || 'not filed'}` +
      (u.how ? ` → ${u.how}` : '')))
  }
  const hz = sheet?.hazard
  if (hz?.class) {
    lines.push('', `**Hazard:** ${hz.class}${hz.team_disclaimed ? ' (team disclaims it)' : ' (no disclaimer found)'} — ${hz.note || ''}`)
  }
  if (sheet?.duplicate_of) lines.push('', `**Merged into:** ${sheet.duplicate_of} — same submission, the richer record is published.`)
  if (sheet?.source_url) lines.push('', `_Audited ${sheet.audited_at || '?'} against ${sheet.source_url} · ${sheet.evidence?.length || 0} evidence rows._`)
  return lines.filter((l) => l !== '').join('\n')
}
