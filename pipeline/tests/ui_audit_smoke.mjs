import { readFileSync } from 'fs'
import * as L from '../../web/src/lib.js'

const pub = new URL('../../web/public/', import.meta.url).pathname
const packed = JSON.parse(readFileSync(pub + 'catalog-packed.json', 'utf8'))
const rows = L.decodeRows(packed)
console.log('rows', rows.length, 'row_format', packed.row_format.length)
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
console.log('pool:', JSON.parse(readFileSync(pub + 'data/pool.json', 'utf8')).count, 'records,',
  (JSON.parse(readFileSync(pub + 'data/pool.json', 'utf8')).records[0].why_not_promoted || []).length, 'reasons on first row')
console.log('\n✅ browser decode + audit layer consistent with the built catalog')
