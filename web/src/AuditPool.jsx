import React, { useMemo, useState } from 'react'
import { ExternalLink, Loader2, Search, ShieldAlert, X } from 'lucide-react'

/**
 * The pool: records the audit held out of the catalog (never audited, thin, duplicate,
 * or hazard-capped). It is deliberately reachable but clearly marked — a reader looking
 * for inspiration should not mistake it for vetted work, and a reader looking for leads
 * should be able to see exactly what is missing (docs/AUDIT_PROTOCOL.md, A1/A8).
 */
export default function AuditPool({ open, pool, stats, onClose }) {
  const [q, setQ] = useState('')
  const [kind, setKind] = useState('all')

  const rows = useMemo(() => {
    let base = pool?.records || []
    if (kind !== 'all') {
      base = base.filter((r) => (r.why_not_promoted || []).some((w) => w.startsWith(kind)))
    }
    const terms = q.toLowerCase().split(/\s+/).filter((t) => t.length > 2)
    if (terms.length) {
      base = base.filter((r) => {
        const hay = `${r.name} ${r.summary} ${(r.moves || []).join(' ')} ${r.domain}`.toLowerCase()
        return terms.every((t) => hay.includes(t))
      })
    }
    return base.slice(0, 120)
  }, [pool, q, kind])

  const kinds = useMemo(() => {
    const c = { all: (pool?.records || []).length }
    for (const r of pool?.records || []) {
      for (const w of r.why_not_promoted || []) {
        const key = String(w).split(':')[0]
        if (key === 'not_audited' || key === 'verdict' || key === 'duplicate_of' || key === 'hazard') {
          const label = key === 'verdict' ? `verdict:${(r.audit || {}).verdict || '?'}` : key
          c[label] = (c[label] || 0) + 1
        }
      }
    }
    return c
  }, [pool])

  if (!open) return null

  return (
    <div className="fixed inset-0 z-40 flex justify-end bg-bone-950/45" onMouseDown={onClose}>
      <section onMouseDown={(e) => e.stopPropagation()}
        className="rise-in h-full w-full max-w-2xl overflow-y-auto border-l border-bone-300 bg-bone-100">
        <div className="sticky top-0 z-10 border-b border-bone-300 bg-bone-100/95 px-5 py-3 backdrop-blur">
          <div className="flex items-start gap-3">
            <ShieldAlert className="mt-1 h-4 w-4 shrink-0 text-signal-700" />
            <div className="min-w-0 flex-1">
              <p className="accession">holding area · not part of the catalog</p>
              <h2 className="font-display text-[22px] font-medium leading-tight tracking-[-0.015em]">
                The unaudited pool
              </h2>
            </div>
            <button onClick={onClose} className="btn-quiet !px-2"><X className="h-4 w-4" /></button>
          </div>
          <p className="mt-2 text-[12.5px] leading-snug text-bone-700">
            {(stats?.pool_records ?? pool?.count ?? 0)} records that the audit has <b>not</b> cleared for the
            catalog. Nothing was deleted — these are leads for a future audit, not examples to cite. Each row
            states why it is here and what would settle it.
          </p>
          <div className="mt-2 flex items-center gap-1.5">
            <div className="relative flex-1">
              <Search className="pointer-events-none absolute left-2.5 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-bone-500" />
              <input value={q} onChange={(e) => setQ(e.target.value)}
                placeholder="filter the pool by text…"
                className="w-full rounded border border-bone-300 bg-bone-50 py-1.5 pl-8 pr-3 font-mono text-[12px] placeholder:text-bone-500 focus:border-bone-400" />
            </div>
            {Object.entries(kinds).slice(0, 5).map(([k, n]) => (
              <button key={k} onClick={() => setKind(k)}
                className={`pill shrink-0 !py-0.5 ${kind === k ? 'pill-active' : ''}`}>
                {k.replace('verdict:', '')}<span className="text-bone-500">{n}</span>
              </button>
            ))}
          </div>
        </div>

        {!pool && (
          <p className="flex items-center gap-2 px-5 py-6 text-[12px] text-bone-600">
            <Loader2 className="h-3.5 w-3.5 animate-spin" /> loading the pool…
          </p>
        )}
        {pool && !rows.length && (
          <p className="px-5 py-6 text-[12.5px] text-bone-700">
            Nothing in the pool matches — the pool holds {(pool.records || []).length} records.
          </p>
        )}

        <ul className="divide-y divide-bone-300">
          {rows.map((r) => (
            <li key={r.id} className="px-5 py-3">
              <div className="flex items-baseline gap-2">
                {/* a pool record has no deep sheet or audit to inspect, so the name
                    links out to the source rather than opening the catalog inspector */}
                <a className="font-display text-[16px] leading-tight hover:text-signal-700"
                  href={r.url} target="_blank" rel="noreferrer noopener">
                  {r.name || r.id}
                </a>
                <span className="leader" />
                <span className="font-mono text-[10px] text-bone-600">{Number(r.coolness || 0).toFixed(2)}</span>
                <a href={r.url} target="_blank" rel="noreferrer noopener" title="original submission"
                  className="text-bone-500 hover:text-signal-700"><ExternalLink className="h-3 w-3" /></a>
              </div>
              <p className="micro mt-0.5 text-bone-600">{r.domain} · {r.event || 'unattributed'}</p>
              {r.summary && <p className="mt-1 text-[12.5px] leading-snug text-bone-800">{r.summary}</p>}
              <div className="mt-1.5 flex flex-wrap gap-1">
                {(r.why_not_promoted || []).map((w) => (
                  <span key={w} className="stamp !text-[9.5px] border-signal-500/50 text-signal-700"
                    title="why this record is not in the catalog">
                    {w.length > 74 ? `${w.slice(0, 74)}…` : w}
                  </span>
                ))}
              </div>
              {!!r.would_settle_it?.length && (
                <p className="mt-1 font-mono text-[10.5px] leading-snug text-bone-600">
                  settles it: {r.would_settle_it.join(' · ')}
                </p>
              )}
            </li>
          ))}
        </ul>

        <div className="border-t border-bone-300 px-5 py-4">
          <p className="font-mono text-[10.5px] uppercase leading-relaxed tracking-label text-bone-600">
            machine-readable: <a className="text-signal-700 hover:underline" href="data/pool.json">data/pool.json</a> ·
            {' '}<a className="text-signal-700 hover:underline" href="data/pool.csv">data/pool.csv</a> ·
            work list <a className="text-signal-700 hover:underline" href="data/promotion-queue.json">data/promotion-queue.json</a> ·
            rules <a className="text-signal-700 hover:underline" href="data/audit-rubric.json">data/audit-rubric.json</a>
          </p>
        </div>
      </section>
    </div>
  )
}
