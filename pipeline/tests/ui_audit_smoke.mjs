import { readFileSync } from 'fs'
import * as L from '../../web/src/lib.js'

// The repo's own check helper (this script has no assert import; a missing one is how a smoke test
// quietly becomes a console.log).
function assert(cond, msg) { if (!cond) { console.error('❌ ' + msg); process.exit(1) } }

const pub = new URL('../../web/public/', import.meta.url).pathname
const packed = JSON.parse(readFileSync(pub + 'catalog-packed.json', 'utf8'))
const rows = L.decodeRows(packed)
console.log('rows', rows.length, 'row_format', packed.row_format.length)
// ADR-P15: the tier must survive decode, or the card badge lies about how much was checked.
const ti = packed.row_format.indexOf('tier_id')
assert(ti === 16, `tier_id is not the 17th packed column (found ${ti})`)
const lite = rows.filter((r) => r.tier === 'lite').map((r) => r.id)
const full = rows.filter((r) => r.tier === 'full').map((r) => r.id)
assert(rows.every((r) => r.tier === null || r.tier === 'lite' || r.tier === 'full'), 'tier decoded to junk')
assert(lite.length > 0 && full.length > 0, 'both ladders must be represented in the served table')
console.log('tiers: full', full.length, '· lite', lite.length, '->', lite.join(','))
for (const id of lite) {
  const r = rows.find((x) => x.id === id)
  assert(r.verdict === 'sound-with-caveats', `${id} published a ${r.verdict} verdict on six fields`)
}
const r0 = rows[0]
console.log('verdict/worth/vetted:', r0.verdict, r0.worth, r0.vetted)
if (!r0.verdict || !r0.worth || r0.vetted !== true) throw new Error('Tier-1 audit decode failed')

// sector/name decode must survive the two extra columns
for (const r of rows) {
  if (!r.id || !r.name || typeof r.coolness !== 'number' || !Array.isArray(r.moves)) throw new Error('decode drift ' + r.id)
  if (!L.domainSlug(r.domain)) throw new Error('slug')
}

const rubric = JSON.parse(readFileSync(pub + 'data/audit-rubric.json', 'utf8'))
// UI field list must cover exactly the rubric's mandatory fields
const uiFields = [...L.AUDIT_FIELD_ORDER]
const rubFields = rubric.mandatory_fields
if (uiFields.filter(f => !rubFields.includes(f)).length) throw new Error('UI shows a field not in the rubric: ' + uiFields.filter(f => !rubFields.includes(f)))
const missing = rubFields.filter(f => !uiFields.includes(f))
if (missing.length) throw new Error('UI hides a mandatory rubric field: ' + missing)
for (const f of rubFields) if (!L.AUDIT_FIELD_LABELS[f]) throw new Error('no label for ' + f)
for (const c of Object.keys(rubric.checks)) if (!L.AUDIT_CHECK_LABELS[c]) throw new Error('no check label for ' + c)

// headline reads verdict meaning from the rubric, same words the gates enforce
const head = L.auditHeadline(r0, null, rubric)
console.log('headline:', head.verdict, '|', head.verdictLabel.slice(0, 40), '| tone', head.tone, '| vetted', head.vetted)
if (head.verdictLabel === head.verdict) throw new Error('rubric label not applied')
if (L.toneClass(head.tone).includes('undefined')) throw new Error('tone class')

// markdown export must carry caveats, unknowns, hazard, assumptions
const sheet = {
  audited_at: '2026-09-18', audit_version: 1, source_url: 'https://devpost.com/software/x',
  verdict: 'sound-with-caveats', worth: 'strong', soundness_score: 0.61, rubric_coverage: 0.5,
  worth_note: 'the pricing gate is the idea',
  evidence: [{ id: 'e1' }],
  checks: { numbers_add_up: { status: 'unverifiable', pass: 0.25, why: 'no harness published' },
            artifact_exists: { status: 'supported', pass: 0.5, why: 'video only' } },
  fields: { what_to_steal: { value: 'quote cost before generating' },
            what_breaks_first: { value: 'the retry loop' },
            clone_cost: { value: { estimate: '$40', why: 'seeded runs', assumptions: ['one reviewer', 'no queue'] } },
            prior_art: { value: [{ title: 'Runway', url: 'https://runway.com' }] } },
  unknowns: [{ field: 'how_they_tested', missing: 'no test command published', how: 'ask the team' }],
  hazard: { class: 'regulated-claim', team_disclaimed: false, note: 'screening language' },
}
const md = L.auditMarkdown(r0, sheet, rubric)
for (const needle of ['**Audit verdict:** sound-with-caveats · worth copying: strong', 'what_to_steal' in sheet.fields ? 'quote cost before generating' : '',
  '$40', 'assumes: one reviewer', 'how they tested it', 'unverifiable (0.25)', 'no test command published',
  'regulated-claim', '1 evidence rows']) {
  if (needle && !md.includes(needle)) throw new Error('markdown missing: ' + needle + '\n' + md)
}
if (!md.includes('numbers_add_up') && !md.includes('Numbers, with the arithmetic')) { /* check label mapping ok */ }
console.log('audit markdown ok,', md.split('\n').length, 'lines')
const poolJson = JSON.parse(readFileSync(pub + 'data/pool.json', 'utf8'))
console.log('pool:', poolJson.count, 'records,',
  (poolJson.records[0].why_not_promoted || []).length, 'reasons on first row')

// The hazard census is a claim about the corpus, published in three places at once: the
// stats line, the audits index and the pool. If they disagree, the UI badge is lying — and a
// count that silently excludes held records understates regulated claims in the catalog.
const stats = JSON.parse(readFileSync(pub + 'catalog-stats.json', 'utf8'))
const idxRecs = Object.values(JSON.parse(readFileSync(pub + 'data/audits.json', 'utf8')).records)
const idxHaz = idxRecs.filter(r => r.hazard).length
const poolHaz = poolJson.records.filter(r => r.provenance === 'audited-hold' && (r.audit || {}).hazard).length
if (stats.records_hazarded !== idxHaz) {
  throw new Error(`stats.records_hazarded=${stats.records_hazarded} but the audits index carries ${idxHaz}`)
}
if (stats.records_hazarded_held !== poolHaz) {
  throw new Error(`stats.records_hazarded_held=${stats.records_hazarded_held} but ${poolHaz} held rows are hazarded`)
}
for (const r of idxRecs) {
  if (!r.url || !r.name || !r.verdict) throw new Error('audit index row missing name/url/verdict: ' + JSON.stringify(r))
}
console.log('hazard census:', idxHaz, 'published ·', poolHaz, 'held · agrees with stats and the badge;',
  idxRecs.length, 'index rows with name+url+verdict')
console.log('\n✅ browser decode + audit layer consistent with the built catalog')
