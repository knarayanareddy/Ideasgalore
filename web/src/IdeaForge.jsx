import React, { useEffect, useMemo, useState } from 'react'
import { Copy, Dice5, Download, Loader2, Sparkles, X } from 'lucide-react'
import { copyText, getJson } from './lib.js'

/* The Remix bench. Collisions arrive pre-generated in data/remixes.json
   (build time, zero runtime cost — ADR-13); the "collide it myself" panel runs
   the same move-intersection logic client-side for a bespoke pairing. */

export default function IdeaForge({ rows, onOpen, onJump }) {
  const [data, setData] = useState(null)
  const [openId, setOpenId] = useState(null)
  const [movesMeta, setMovesMeta] = useState({})
  const [a, setA] = useState(null)
  const [b, setB] = useState(null)
  const [err, setErr] = useState(null)

  useEffect(() => {
    let alive = true
    Promise.all([getJson('data/remixes.json'), getJson('data/moves.json')])
      .then(([r, m]) => {
        if (!alive) return
        setData(r)
        setMovesMeta(m.moves || {})
        if (r.recipes?.[0]) setOpenId(r.recipes[0].id)
      })
      .catch((e) => alive && setErr(String(e.message || e)))
    return () => { alive = false }
  }, [])

  const roll = () => {
    const pool = rows.length ? rows : []
    const i = Math.floor(Math.random() * pool.length)
    let j = Math.floor(Math.random() * pool.length)
    if (j === i) j = (j + 7) % pool.length
    setA(pool[i]?.id); setB(pool[j]?.id)
  }

  const bespoke = useMemo(() => {
    const ra = rows.find((r) => r.id === a)
    const rb = rows.find((r) => r.id === b)
    if (!ra || !rb || ra.id === rb.id) return null
    const shared = ra.moves.filter((m) => rb.moves.includes(m))
    const union = [...new Set([...ra.moves, ...rb.moves])]
    return {
      ra, rb, shared,
      transfer: shared.length
        ? shared.map((m) => ({ move: m, ...(movesMeta[m] || {}) }))
        : union.slice(0, 2).map((m) => ({ move: m, ...(movesMeta[m] || {}) })),
      stack: [...new Set([...ra.stack, ...rb.stack])].slice(0, 10),
      distance: ra.domain === rb.domain ? 'same shelf — expect a variant, not a collision' : 'different shelves — the transfer is the idea',
    }
  }, [a, b, rows, movesMeta])

  if (err) return <p className="micro">{err}</p>
  if (!data) {
    return <p className="flex items-center gap-2 text-[12px] text-bone-600"><Loader2 className="h-3.5 w-3.5 animate-spin" />loading the remix bench…</p>
  }

  const recipes = data.recipes || []
  return (
    <div className="space-y-4">
      <div className="plate p-4">
        <h2 className="font-display text-[21px] leading-tight">The Remix Bench</h2>
        <p className="mt-1 max-w-3xl text-[13px] leading-relaxed text-bone-800">
          Every brief here is a collision: two projects that solve different problems with the same
          mechanism, or the same problem with different constraints. {data.counts?.curated} are curated by
          the expert panel; {data.counts?.mined} are mined by <span className="font-mono text-[12px]">min(coolness) × sector_distance</span>.
          Treat <span className="font-mono text-[11.5px]">first_48_hours</span> as scaffolding and{' '}
          <span className="font-mono text-[11.5px]">kill_criteria</span> as a scope guard.
        </p>
      </div>

      <div className="grid grid-cols-1 gap-2.5 lg:grid-cols-2">
        {recipes.map((r) => {
          const open = openId === r.id
          return (
            <article key={r.id} className="plate flex flex-col p-3.5">
              <div className="flex items-start gap-2">
                <span className={`stamp ${r.kind === 'curated' ? 'border-signal-500 text-signal-700' : 'border-bone-400 text-bone-600'}`}>
                  {r.kind}
                </span>
                {r.move && <span className="chip !text-[9.5px]">{r.move.replace(/-/g, ' ')}</span>}
                {r.effort && <span className="ml-auto font-mono text-[10px] text-bone-500">{r.effort}</span>}
              </div>
              <button onClick={() => setOpenId(open ? null : r.id)} className="mt-1.5 text-left">
                <h3 className="font-display text-[17.5px] font-medium leading-[1.18] hover:text-signal-700">{r.title}</h3>
              </button>
              <div className="mt-2 flex flex-wrap gap-1.5">
                {(r.parents_detail || r.parents || []).map((p) => {
                  const row = typeof p === 'string' ? rows.find((x) => x.id === p) : null
                  const name = typeof p === 'string' ? row?.name : p.name
                  const id = typeof p === 'string' ? p : p.id
                  const target = row || rows.find((x) => x.id === id)
                  return (
                    <button key={id} onClick={() => target && onOpen(target)}
                      className="pill hover:!border-signal-500">
                      {name || id}<span className="text-bone-500">×</span>
                    </button>
                  )
                })}
              </div>
              {open ? (
                <div className="mt-3 space-y-2.5 border-t border-bone-300 pt-3">
                  <p className="font-mono text-[10.5px] text-bone-600">
                    {r.shared_moves?.length
                      ? <>shared moves: {r.shared_moves.map((m) => m.replace(/-/g, ' ')).join(' · ')}</>
                      : <>no shared move — this pairing works by contrast
                        {r.domain_distance ? ` (domain distance ${r.domain_distance})` : ''}</>}
                    {typeof r.score === 'number' && (
                      <span className="text-bone-500"> · collision score {r.score.toFixed(3)}
                        {r.provenance ? ` · ${r.provenance}` : ''}</span>
                    )}
                  </p>
                  <Field label="why these two" body={r.why_these_two} />
                  <Field label="the wedge" body={r.the_wedge} />
                  {!!r.starter_stack?.length && (
                    <div>
                      <p className="micro">starter stack</p>
                      <ul className="mt-1 space-y-0.5">
                        {r.starter_stack.map((s) => (
                          <li key={s} className="flex gap-2 text-[12.5px] leading-snug text-bone-800">
                            <span className="text-brass-700">—</span>{s}
                          </li>
                        ))}
                      </ul>
                    </div>
                  )}
                  {!!r.first_48_hours?.length && (
                    <div>
                      <p className="micro">first 48 hours</p>
                      <ol className="mt-1 space-y-1">
                        {r.first_48_hours.map((s, i) => (
                          <li key={s} className="flex gap-2 text-[12.5px] leading-snug text-bone-800">
                            <span className="font-mono text-[10px] text-bone-500">{String(i + 1).padStart(2, '0')}</span>{s}
                          </li>
                        ))}
                      </ol>
                    </div>
                  )}
                  {!!r.kill_criteria?.length && (
                    <div className="rounded border-l-2 border-signal-500 bg-signal-100/50 px-2.5 py-1.5">
                      <p className="micro !text-signal-700">kill criteria</p>
                      {r.kill_criteria.map((k) => <p key={k} className="mt-0.5 text-[12.5px] leading-snug text-bone-900">{k}</p>)}
                    </div>
                  )}
                  {!!r.reusable_moves?.length && (
                    <div>
                      <p className="micro">moves being carried over</p>
                      {r.reusable_moves.map((m, i) => (
                        <p key={i} className="mt-1 text-[12.5px] leading-snug text-bone-800">
                          <span className="font-mono text-[10.5px] uppercase tracking-label text-bone-600">{m.from || m.move}</span>
                          {' — '}{m.steal_this}
                        </p>
                      ))}
                    </div>
                  )}
                </div>
              ) : (
                <p className="mt-2 line-clamp-2 text-[12.5px] leading-snug text-bone-700">{r.why_these_two}</p>
              )}
              <button onClick={() => setOpenId(open ? null : r.id)} className="mt-2 self-start font-mono text-[10px] uppercase tracking-label text-signal-700 hover:underline">
                {open ? 'collapse brief' : 'open brief'}
              </button>
            </article>
          )
        })}
      </div>

      {/* bespoke collision */}
      <section className="plate p-4">
        <div className="flex flex-wrap items-center gap-2">
          <Sparkles className="h-4 w-4 text-signal-700" />
          <h2 className="font-display text-[19px]">Collide two plates yourself</h2>
          <button className="btn-quiet ml-auto" onClick={roll}><Dice5 className="h-3.5 w-3.5" />surprise me</button>
          {onJump && <button className="btn-quiet" onClick={onJump}>back to index</button>}
        </div>
        <div className="mt-3 grid grid-cols-1 gap-2 sm:grid-cols-2">
          {[['a', a, setA], ['b', b, setB]].map(([slot, val, set]) => (
            <select key={slot} value={val || ''} onChange={(e) => set(e.target.value)}
              className="rounded border border-bone-300 bg-bone-50 px-2 py-1.5 font-mono text-[11px] text-bone-800">
              <option value="">project {slot} — pick one…</option>
              {rows.map((r) => <option key={r.id} value={r.id}>{r.name} · {r.coolness.toFixed(2)}</option>)}
            </select>
          ))}
        </div>
        {bespoke ? (
          <div className="mt-3 grid grid-cols-1 gap-3 md:grid-cols-3">
            <div className="md:col-span-2">
              <p className="micro">shared moves</p>
              <p className="mt-1 text-[13px] text-bone-800">
                {bespoke.shared.length ? bespoke.shared.map((m) => `\`${m}\``).join('  ') : 'none — this is a contrast pairing, not a transfer'}
              </p>
              <p className="micro mt-3">what carries over</p>
              <ul className="mt-1 space-y-1.5">
                {bespoke.transfer.map((t) => (
                  <li key={t.move} className="text-[12.5px] leading-snug text-bone-800">
                    <span className="font-mono text-[10.5px] uppercase tracking-label text-signal-700">{t.move.replace(/-/g, ' ')}</span>
                    <br />{t.steal_this || 'no definition recorded for this move'}
                  </li>
                ))}
              </ul>
              <p className="micro mt-3">combined stack</p>
              <p className="mt-1 font-mono text-[11px] leading-relaxed text-bone-700">{bespoke.stack.join(' · ') || '—'}</p>
              <p className="mt-3 text-[11.5px] italic text-bone-600">{bespoke.distance}</p>
            </div>
            <div className="space-y-2">
              {[bespoke.ra, bespoke.rb].map((r) => (
                <button key={r.id} onClick={() => onOpen(r)} className="plate block w-full p-2 text-left hover:border-signal-500">
                  <p className="font-display text-[15px] leading-tight">{r.name}</p>
                  <p className="micro mt-0.5 truncate">{r.event || 'unattributed'}</p>
                </button>
              ))}
              <button className="btn-signal w-full justify-center" onClick={() => copyText(briefText(bespoke))}>
                <Copy className="h-3.5 w-3.5" />copy brief
              </button>
              <button className="btn-quiet w-full justify-center" onClick={() => {
                const blob = new Blob([briefText(bespoke)], { type: 'text/markdown' })
                const url = URL.createObjectURL(blob)
                const el = document.createElement('a')
                el.href = url; el.download = 'collision-brief.md'; el.click()
                setTimeout(() => URL.revokeObjectURL(url), 1500)
              }}><Download className="h-3.5 w-3.5" />download</button>
            </div>
          </div>
        ) : (
          <p className="mt-2 text-[12.5px] text-bone-600">Pick two different plates. Same-shelf pairs give you variants; cross-shelf pairs are where the theft gets interesting.</p>
        )}
      </section>
    </div>
  )
}

function Field({ label, body }) {
  if (!body) return null
  return (
    <div>
      <p className="micro">{label}</p>
      <p className="mt-0.5 text-[13px] leading-relaxed text-bone-900">{body}</p>
    </div>
  )
}

function briefText({ ra, rb, shared, transfer, stack }) {
  return [
    `# Collision brief — ${ra.name} × ${rb.name}`,
    '',
    `Generated from Ideas Galore. Sources:`,
    `- ${ra.name} — ${ra.url} (${ra.event || 'unattributed'})`,
    `- ${rb.name} — ${rb.url} (${rb.event || 'unattributed'})`,
    '',
    `## Moves in play`,
    ...(shared.length ? shared.map((m) => `- \`${m}\` (both projects)`) : ['- none shared: this pairing works by contrast']),
    '',
    ...transfer.map((t) => `**${t.move}** — ${t.steal_this || ''}`),
    '',
    `## Combined stack`,
    stack.join(' · ') || '—',
    '',
    `_Sector labels, moves and scores are derived by Ideas Galore; verify claims on the source pages before building._`,
  ].join('\n')
}
