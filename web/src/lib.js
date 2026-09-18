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
