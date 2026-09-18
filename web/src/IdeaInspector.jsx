import React, { useMemo, useState } from 'react'
import {
  BookOpen, Copy, Github, ExternalLink, Loader2, Play, Star, X,
} from 'lucide-react'
import { copyText, ideaMarkdown } from './lib.js'

const WEIGHTS = {
  engagement: [0.30, 'Devpost likes, log-scaled — community noticed it'],
  validation: [0.22, 'judge or editorial recognition'],
  event_prestige: [0.14, 'scale of the hackathon it survived'],
  recency: [0.10, '14-month half-life on the idea'],
  specificity: [0.14, 'does it state a mechanism, not a vibe'],
  signal_richness: [0.10, 'depth of what we could capture'],
  redundancy: [-0.12, 'near-duplicate of another record (browse only)'],
}

export default function IdeaInspector({ row, detail, moveMeta, sector, rows, shards, onClose, onOpen, inShelf, onShelf, flash }) {
  const [busy, setBusy] = useState(false)
  const loading = !detail && !shards[slugOf(row.domain)]

  const neighbors = useMemo(() => rows
    .filter((r) => r.id !== row.id && (r.subsystem === row.subsystem || r.moves.some((m) => row.moves.includes(m))))
    .map((r) => {
      const shared = r.moves.filter((m) => row.moves.includes(m))
      return { row: r, shared, score: shared.length * 2 + (r.subsystem === row.subsystem ? 1 : 0) + r.coolness }
    })
    .sort((a, b) => b.score - a.score)
    .slice(0, 6), [rows, row])

  const parts = detail?.coolness_parts || null
  const intel = detail?.inspiration_intel || null

  return (
    <div className="fixed inset-0 z-40 flex justify-end bg-bone-950/45" onMouseDown={onClose}>
      <section onMouseDown={(e) => e.stopPropagation()}
        className="rise-in h-full w-full max-w-2xl overflow-y-auto border-l border-bone-300 bg-bone-50">
        {/* header */}
        <div className="sticky top-0 z-10 border-b border-bone-300 bg-bone-50/95 px-5 py-3 backdrop-blur">
          <div className="flex items-start gap-3">
            <span className="mt-1.5 h-2.5 w-2.5 shrink-0 rounded-full" style={{ background: sector?.hue || '#877c63' }} />
            <div className="min-w-0 flex-1">
              <p className="accession">{row.accession} · {row.domain} · {row.subsystem}</p>
              <h2 className="font-display text-[25px] font-medium leading-tight tracking-[-0.015em]">{row.name}</h2>
              <p className="mt-0.5 font-mono text-[11px] text-bone-600">
                {row.event || 'unattributed'}{row.eventOrg ? ` · ${row.eventOrg}` : ''}
              </p>
            </div>
            <button onClick={onClose} className="btn-quiet !px-2"><X className="h-4 w-4" /></button>
          </div>
          <div className="mt-2.5 flex flex-wrap gap-1.5">
            <a className="btn-signal" href={row.url} target="_blank" rel="noreferrer noopener">
              <ExternalLink className="h-3.5 w-3.5" />open submission
            </a>
            <button className={`btn-quiet ${inShelf ? '!border-signal-500 !text-signal-700' : ''}`} onClick={onShelf}>
              <Star className={`h-3.5 w-3.5 ${inShelf ? 'fill-signal-500 text-signal-700' : ''}`} />
              {inShelf ? 'on your shelf' : 'keep for later'}
            </button>
            <button className="btn-quiet" disabled={busy} onClick={async () => {
              setBusy(true)
              const ok = await copyText(ideaMarkdown(row, detail))
              flash(ok ? 'copied — paste into your next project brief' : 'copy blocked by browser')
              setBusy(false)
            }}><Copy className="h-3.5 w-3.5" />copy as markdown</button>
          </div>
        </div>

        <div className="space-y-6 px-5 py-5">
          {/* the summary */}
          <p className="font-display text-[17px] leading-relaxed text-bone-900">{detail?.summary || row.hook}</p>

          {/* score decomposition */}
          <div className="plate p-3.5">
            <div className="flex items-baseline gap-2">
              <h3 className="micro">coolness · scoring_version 1</h3>
              <span className="font-mono text-[15px] text-signal-700">{(detail?.coolness ?? row.coolness).toFixed(3)}</span>
              <span className="ml-auto font-mono text-[10px] text-bone-500">explainable by design</span>
            </div>
            <div className="mt-2.5 space-y-1.5">
              {Object.entries(WEIGHTS).map(([key, [w, why]]) => {
                const v = parts?.[key]
                if (v === undefined) return null
                const signed = Math.min(Math.abs(v), 1)
                return (
                  <div key={key} className="flex items-center gap-2" title={why}>
                    <span className="w-[104px] shrink-0 font-mono text-[10px] uppercase tracking-label text-bone-600">{key}</span>
                    <span className="scorebar flex-1">
                      <span style={{ width: `${signed * 100}%`, opacity: w < 0 ? 0.5 : 1 }} />
                    </span>
                    <span className="w-16 shrink-0 text-right font-mono text-[10px] text-bone-700">
                      {v.toFixed(2)} <span className="text-bone-400">×{Math.abs(w)}</span>
                    </span>
                  </div>
                )
              })}
            </div>
            {!parts && <p className="micro mt-2 text-bone-500">component breakdown arrives with the deep sheet</p>}
          </div>

          {/* moves: the stealable layer */}
          {row.moves.length > 0 && (
            <div>
              <h3 className="micro mb-2">transferable moves — what you can copy</h3>
              <ul className="space-y-2">
                {row.moves.map((m) => (
                  <li key={m} className="plate p-3" style={{ borderLeft: `3px solid ${sector?.hue || '#877c63'}` }}>
                    <p className="font-mono text-[11px] uppercase tracking-label text-bone-800">{m.replace(/-/g, ' ')}</p>
                    <p className="mt-1 text-[13px] leading-snug text-bone-800">{moveMeta[m]?.definition}</p>
                    {moveMeta[m]?.steal_this && (
                      <p className="mt-1.5 border-t border-dashed border-bone-300 pt-1.5 text-[12.5px] italic leading-snug text-signal-700">
                        {moveMeta[m].steal_this}
                      </p>
                    )}
                  </li>
                ))}
              </ul>
            </div>
          )}

          {loading && (
            <p className="flex items-center gap-2 text-[12px] text-bone-600">
              <Loader2 className="h-3.5 w-3.5 animate-spin" /> loading the deep sheet…
            </p>
          )}

          {intel && (
            <div className="space-y-3">
              <h3 className="micro">the build notebook — by the team, condensed by us</h3>
              <Block label="the wedge" body={intel.the_wedge} />
              <Block label="naive version vs. this one" body={intel.naive_version_vs_this} />
              <Block label="how they built it" body={intel.how_they_built_it} />
              <Block label="hard-won lesson" body={intel.hard_won_lesson} />
              <Block label="proof points" body={intel.proof_points} />
              <Block label="what they'd do next" body={intel.next_moves} />
              {intel.reuse_surface && <Block label="transfers to" body={intel.reuse_surface} />}
            </div>
          )}

          {detail?.quote && (
            <div>
              <h3 className="micro mb-1.5">in their words <span className="normal-case">(≤220-char excerpt, Devpost-stored)</span></h3>
              <blockquote className="ink-panel !text-[12px] italic">“{detail.quote}”</blockquote>
            </div>
          )}

          {/* facts + links */}
          <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
            <div className="plate p-3">
              <h3 className="micro mb-2">event record</h3>
              <Fact k="hackathon" v={row.event} />
              <Fact k="organizer" v={row.eventOrg} />
              <Fact k="closed" v={detail?.event?.date} />
              <Fact k="registrations" v={row.eventRegistrations ? row.eventRegistrations.toLocaleString() : null} />
              <Fact k="prize pool" v={row.eventPrize ? `$${row.eventPrize.toLocaleString()}` : null} />
              <Fact k="recognition" v={detail?.award && detail.award !== 'Unknown' ? detail.award : null} />
              <Fact k="likes" v={row.likes === null ? null : String(row.likes)} note={row.likes === null ? 'not fetched — never read as zero' : undefined} />
              {!!detail?.event?.themes?.length && <Fact k="themes" v={detail.event.themes.join(' · ')} />}
            </div>
            <div className="plate p-3">
              <h3 className="micro mb-2">stack &amp; provenance</h3>
              <p className="text-[12.5px] leading-snug text-bone-800">
                {row.stack.length ? row.stack.join(' · ') : 'no technologies recovered at this depth'}
              </p>
              <p className="mt-2 text-[11.5px] leading-snug text-bone-600">
                {detail?.built_with_observed
                  ? 'The first tags are the team’s own `built with` list; the rest are lexicon matches.'
                  : 'All stack labels here are lexicon matches from the project text (derived).'}
              </p>
              <div className="mt-3 flex flex-wrap gap-1.5">
                {detail?.repo_url && <a className="chip hover:!border-signal-500" href={detail.repo_url} target="_blank" rel="noreferrer noopener"><Github className="h-3 w-3" />code</a>}
                {detail?.demo_url && <a className="chip hover:!border-signal-500" href={detail.demo_url} target="_blank" rel="noreferrer noopener"><Play className="h-3 w-3" />demo</a>}
                {detail?.video_url && <a className="chip hover:!border-signal-500" href={detail.video_url} target="_blank" rel="noreferrer noopener"><BookOpen className="h-3 w-3" />talk</a>}
              </div>
              {detail?.provenance && (
                <div className="mt-3 border-t border-bone-300 pt-2">
                  <p className="micro mb-1">field provenance</p>
                  <div className="flex flex-wrap gap-1">
                    {Object.entries(detail.provenance).map(([k, v]) => (
                      <span key={k} className={`stamp ${v === 'observed' ? 'border-brass-500 text-brass-700' : v === 'editorial' ? 'border-signal-500 text-signal-700' : 'border-bone-400 text-bone-600'}`}>
                        {k}:{v}
                      </span>
                    ))}
                  </div>
                </div>
              )}
              {typeof detail?.domain_margin === 'number' && (
                <p className="mt-2 font-mono text-[10px] text-bone-500">
                  sector confidence {detail.domain_margin.toFixed(2)} — derived label, not a team statement
                </p>
              )}
            </div>
          </div>

          {/* neighborhood */}
          {!!neighbors.length && (
            <div>
              <h3 className="micro mb-1.5">parallel invention — same move, same shelf</h3>
              <div className="flex flex-wrap gap-1.5">
                {neighbors.map(({ row: n, shared }) => (
                  <button key={n.id} onClick={() => onOpen(n)} className="pill text-left hover:!border-signal-500">
                    <span className="h-1.5 w-1.5 rounded-full" style={{ background: sector?.hue }} />
                    {n.name.length > 26 ? `${n.name.slice(0, 26)}…` : n.name}
                    <span className="text-bone-500">{n.coolness.toFixed(2)}</span>
                    {!!shared.length && <span className="text-brass-700">{shared.length} move{shared.length > 1 ? 's' : ''}</span>}
                  </button>
                ))}
              </div>
            </div>
          )}
        </div>
      </section>
    </div>
  )
}

function slugOf(name) {
  return String(name || 'unclassified').toLowerCase().replace(/&/g, 'and').replace(/[^a-z0-9]+/g, '-').replace(/^-|-$/g, '') || 'unclassified'
}

function Block({ label, body }) {
  if (!body) return null
  return (
    <div>
      <p className="micro">{label}</p>
      <p className="mt-0.5 text-[13.5px] leading-relaxed text-bone-900">{body}</p>
    </div>
  )
}

function Fact({ k, v, note }) {
  return (
    <p className="flex items-baseline gap-1 text-[12.5px] leading-6">
      <span className="font-mono text-[10px] uppercase tracking-label text-bone-600">{k}</span>
      <span className="leader" />
      <span className={v ? 'text-bone-900' : 'text-bone-400'} title={note || ''}>{v || '—'}</span>
    </p>
  )
}
