import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import {
  Archive, Boxes, Command, Dice5, ExternalLink, Layers, LibraryBig, Loader2,
  RotateCcw, Search, Sparkles, Star, X,
} from 'lucide-react'
import {
  auditHeadline, buildIndex, copyText, decodeRows, domainSlug, downloadText, fetchPool,
  getJson, searchRows, shelfMarkdown, SORTS, toneClass, fetchRubric,
} from './lib.js'
import AuditPool from './AuditPool.jsx'
import IdeaAtlas from './IdeaAtlas.jsx'
import IdeaInspector from './IdeaInspector.jsx'
import IdeaForge from './IdeaForge.jsx'

const SHELF_KEY = 'ideasgalore.shelf.v1'

export default function App() {
  const [packed, setPacked] = useState(null)
  const [stats, setStats] = useState(null)
  const [movesMeta, setMovesMeta] = useState({})
  const [error, setError] = useState(null)
  const [tab, setTab] = useState('index')
  const [query, setQuery] = useState('')
  const [sector, setSector] = useState(null)
  const [moveSel, setMoveSel] = useState([])
  const [minCool, setMinCool] = useState(0)
  const [depthOnly, setDepthOnly] = useState(false)
  const [event, setEvent] = useState(null)
  const [sort, setSort] = useState('coolness')
  const [limit, setLimit] = useState(60)
  const [selected, setSelected] = useState(null)
  const [shards, setShards] = useState({})
  const [shelf, setShelf] = useState(() => {
    try { return JSON.parse(localStorage.getItem(SHELF_KEY)) || [] } catch { return [] }
  })
  const [shelfOpen, setShelfOpen] = useState(false)
  const [poolOpen, setPoolOpen] = useState(false)
  const [pool, setPool] = useState(null)
  const [rubric, setRubric] = useState(null)
  const [toast, setToast] = useState(null)
  const searchRef = useRef(null)

  // ---- catalog load (Tier 1 + stats + move vocabulary) ---------------------
  useEffect(() => {
    let alive = true
    Promise.all([getJson('catalog-packed.json'), getJson('catalog-stats.json'), getJson('data/moves.json')])
      .then(([p, s, m]) => { if (alive) { setPacked(p); setStats(s); setMovesMeta(m.moves || {}) } })
    fetchRubric().then((r) => alive && setRubric(r))
    fetchPool().then((d) => alive && setPool(d))
      .catch((e) => alive && setError(String(e.message || e)))
    return () => { alive = false }
  }, [])

  const rows = useMemo(() => (packed ? decodeRows(packed) : []), [packed])
  const sectors = useMemo(() => packed?.sectors || {}, [packed])
  const index = useMemo(() => buildIndex(rows), [rows])
  const events = useMemo(() => {
    const by = new Map()
    rows.forEach((r) => {
      if (!r.event) return
      const cur = by.get(r.event) || { title: r.event, org: r.eventOrg, count: 0, slug: r.eventSlug, hue: r.eventHue }
      cur.count += 1
      by.set(r.event, cur)
    })
    return [...by.values()].sort((a, b) => b.count - a.count)
  }, [rows])

  // ---- deep shard loading: one domain file per need, cached (Tier 2) ------
  const ensureShard = useCallback(async (domain) => {
    const slug = domainSlug(domain)
    if (shards[slug]) return shards[slug]
    try {
      const data = await getJson(`data/details/${slug}.json`)
      setShards((s) => ({ ...s, [slug]: data }))
      return data
    } catch {
      return {}
    }
  }, [shards])

  const detail = selected ? (shards[domainSlug(selected.domain)] || {})[selected.id] : null

  const open = useCallback(async (row) => {
    setSelected(row)
    window.location.hash = row ? `id=${encodeURIComponent(row.id)}` : ''
    if (row) await ensureShard(row.domain)
  }, [ensureShard])

  // deep link: #id=<slug> opens the inspector
  useEffect(() => {
    if (!rows.length) return
    const m = /id=([^&]+)/.exec(window.location.hash)
    if (m) {
      const row = rows.find((r) => r.id === decodeURIComponent(m[1]))
      if (row) open(row)
    }
  }, [rows, open])

  useEffect(() => {
    const onKey = (e) => {
      const typing = /INPUT|TEXTAREA|SELECT/.test(e.target?.tagName || '')
      if (e.key === '/' && !typing) { e.preventDefault(); searchRef.current?.focus() }
      if (e.key === 'Escape') { setSelected(null); setShelfOpen(false) }
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [])

  useEffect(() => { localStorage.setItem(SHELF_KEY, JSON.stringify(shelf)) }, [shelf])

  const flash = (msg) => { setToast(msg); setTimeout(() => setToast(null), 2200) }

  // ---- filtering + ranking -------------------------------------------------
  const filtered = useMemo(() => {
    if (!rows.length) return []
    let base = query.trim()
      ? searchRows(rows, index, query, 400).map((h) => h.row)
      : rows.slice()
    if (sector) base = base.filter((r) => r.domain === sector)
    if (moveSel.length) base = base.filter((r) => moveSel.some((m) => r.moves.includes(m)))
    if (event) base = base.filter((r) => r.event === event)
    if (depthOnly) base = base.filter((r) => r.depth === 'deep')
    if (minCool > 0) base = base.filter((r) => r.coolness >= minCool)
    const withSpec = base.map((r) => ({ ...r, specificity: (shards[domainSlug(r.domain)] || {})[r.id]?.specificity }))
    return withSpec.sort(SORTS[sort] || SORTS.coolness)
  }, [rows, index, query, sector, moveSel, event, depthOnly, minCool, sort, shards])

  const moveCounts = useMemo(() => {
    const c = {}
    filtered.forEach((r) => r.moves.forEach((m) => { c[m] = (c[m] || 0) + 1 }))
    return c
  }, [filtered])

  const toggleMove = (m) => setMoveSel((s) => (s.includes(m) ? s.filter((x) => x !== m) : [...s, m]))
  const reset = () => { setQuery(''); setSector(null); setMoveSel([]); setEvent(null); setMinCool(0); setDepthOnly(false); setLimit(60) }
  const active = query || sector || moveSel.length || event || minCool > 0 || depthOnly
  const inShelf = (id) => shelf.includes(id)

  if (error) {
    return (
      <div className="mx-auto max-w-xl px-6 py-24 text-center">
        <LibraryBig className="mx-auto mb-3 h-7 w-7 text-signal-700" />
        <h1 className="font-display text-2xl">The catalog has not been built yet</h1>
        <p className="mt-2 text-sm text-bone-700">{error}</p>
        <pre className="ink-panel mt-4 text-left">python3 pipeline/ingest_seed.py{'\n'}python3 pipeline/shard_builder.py{'\n'}python3 pipeline/build_agent_api.py</pre>
      </div>
    )
  }

  if (!packed) {
    return (
      <div className="flex min-h-screen items-center justify-center gap-2 text-bone-600">
        <Loader2 className="h-4 w-4 animate-spin" />
        <span className="micro">opening the vault…</span>
      </div>
    )
  }

  return (
    <div className="min-h-screen pb-24">
      {/* ── masthead ─────────────────────────────────────────── */}
      <header className="sticky top-0 z-30 border-b border-bone-300 bg-bone-100/95 backdrop-blur">
        <div className="mx-auto flex max-w-[1400px] flex-wrap items-center gap-x-4 gap-y-2 px-4 py-3 sm:px-6">
          <div className="flex items-baseline gap-2.5">
            <LibraryBig className="h-5 w-5 self-center text-signal-700" />
            <h1 className="font-display text-[22px] font-semibold leading-none tracking-tight">
              Ideas Galore
            </h1>
            <span className="micro hidden sm:inline">hackathon inspiration index</span>
          </div>

          <nav className="ml-auto flex items-center gap-1">
            {[['index', 'Index', Layers], ['atlas', 'Atlas', Boxes], ['forge', 'Remix', Sparkles]].map(([id, label, Icon]) => (
              <button key={id} onClick={() => setTab(id)}
                className={`btn-quiet ${tab === id ? '!border-signal-500 !bg-signal-100 !text-signal-700' : ''}`}>
                <Icon className="h-3.5 w-3.5" />{label}
              </button>
            ))}
            {stats?.records_hazarded > 0 && (
              <span className="stamp border-signal-500 text-signal-700 hidden lg:inline"
                title="records carrying a regulated-claim hazard note">
                {stats.records_hazarded} hazard-noted
              </span>
            )}
            <button onClick={() => setShelfOpen(true)} className="btn-quiet ml-1">
              <Archive className="h-3.5 w-3.5" />Shelf
              <span className="font-mono text-[10px] text-bone-500">{shelf.length}</span>
            </button>
          </nav>

          <div className="w-full order-3 flex items-center gap-2 sm:w-auto sm:order-none sm:ml-2 sm:flex-1">
            <div className="relative flex-1">
              <Search className="pointer-events-none absolute left-2.5 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-bone-500" />
              <input
                ref={searchRef}
                value={query}
                onChange={(e) => { setQuery(e.target.value); setLimit(60) }}
                placeholder="search mechanisms, moves, hackathons…   ( / )"
                className="w-full rounded border border-bone-300 bg-bone-50 py-1.5 pl-8 pr-8 font-mono text-[12px] placeholder:text-bone-500 focus:border-bone-400"
              />
              {query && (
                <button onClick={() => setQuery('')} className="absolute right-2 top-1/2 -translate-y-1/2 text-bone-500 hover:text-signal-700">
                  <X className="h-3.5 w-3.5" />
                </button>
              )}
            </div>
            <button title="Random muse" onClick={() => open(filtered[Math.floor(Math.random() * Math.max(filtered.length, 1))] || rows[0])}
              className="btn-quiet !px-2"><Dice5 className="h-3.5 w-3.5" /></button>
          </div>
        </div>
        <div className="double-rule" />
      </header>

      {/* ── corpus telemetry strip ───────────────────────────── */}
      <div className="mx-auto max-w-[1400px] px-4 pt-3 sm:px-6">
        <div className="flex flex-wrap items-center gap-x-5 gap-y-1 font-mono text-[10.5px] uppercase tracking-label text-bone-600">
          <span title="only records that passed the evidence audit are in the catalog">
            <b className="text-bone-900">{stats?.total ?? rows.length}</b> audited in catalog
          </span>
          <button onClick={() => setPoolOpen(true)} className="underline decoration-dotted hover:text-signal-700"
            title="held out of the catalog by the audit — leads, not vetted examples">
            <b className="text-bone-900">{stats?.pool_records ?? pool?.count ?? 0}</b> unaudited pool
          </button>
          <span><b className="text-bone-900">{Object.keys(movesMeta).length}</b> moves</span>
          <span><b className="text-bone-900">{events.length}</b> hackathons</span>
          <span><b className="text-bone-900">{stats?.deep_records ?? 0}</b> deep</span>
          <span>tier1 <b className="text-bone-900">{stats?.tier1_gzip_kb}KB</b>/{stats?.tier1_budget_kb}KB gz</span>
          <span className="hidden md:inline">built {stats?.generated_at}</span>
          <span className="ml-auto hidden items-center gap-1 text-bone-500 md:flex">
            <Command className="h-3 w-3" /> press / to search · click any plate for the deep sheet
          </span>
        </div>
      </div>

      {tab === 'index' && (
        <main className="mx-auto max-w-[1400px] px-4 pt-4 sm:px-6">
          {/* sector rail */}
          <div className="flex gap-1.5 overflow-x-auto pb-1">
            <button onClick={() => setSector(null)} className={`pill shrink-0 ${!sector ? 'pill-active' : ''}`}>
              All sectors<span className="text-bone-500">{rows.length}</span>
            </button>
            {Object.entries(sectors).map(([name, meta]) => {
              const count = rows.filter((r) => r.domain === name).length
              if (!count) return null
              return (
                <button key={name} onClick={() => setSector(sector === name ? null : name)}
                  className={`pill shrink-0 ${sector === name ? 'pill-active' : ''}`}>
                  <span className="h-2 w-2 rounded-full" style={{ background: meta.hue }} />
                  {name.replace(' & ', ' & ').replace(', Story & Play', '')}
                  <span className="text-bone-500">{count}</span>
                </button>
              )
            })}
          </div>

          {/* filter bar */}
          <div className="mt-3 flex flex-wrap items-center gap-x-4 gap-y-2 border-y border-bone-300 bg-bone-50/60 px-3 py-2">
            <div className="flex items-center gap-1.5">
              <span className="micro">sort</span>
              {Object.keys(SORTS).map((k) => (
                <button key={k} onClick={() => setSort(k)}
                  className={`font-mono text-[10px] uppercase tracking-label px-1.5 py-0.5 rounded ${sort === k ? 'bg-signal-500 text-bone-50' : 'text-bone-600 hover:bg-bone-200'}`}>
                  {k}
                </button>
              ))}
            </div>
            <label className="flex items-center gap-2">
              <span className="micro">min coolness</span>
              <input type="range" min="0" max="0.6" step="0.02" value={minCool}
                onChange={(e) => setMinCool(parseFloat(e.target.value))} className="w-24" />
              <span className="font-mono text-[10px] text-bone-700">{minCool.toFixed(2)}</span>
            </label>
            <label className="flex cursor-pointer items-center gap-1.5">
              <input type="checkbox" checked={depthOnly} onChange={(e) => setDepthOnly(e.target.checked)} className="accent-signal-500" />
              <span className="micro">deep records only</span>
            </label>
            <select value={event || ''} onChange={(e) => setEvent(e.target.value || null)}
              className="rounded border border-bone-300 bg-bone-50 px-1.5 py-1 font-mono text-[10px] uppercase tracking-label text-bone-700">
              <option value="">any hackathon</option>
              {events.map((ev) => <option key={ev.title} value={ev.title}>{ev.title.slice(0, 40)} ({ev.count})</option>)}
            </select>
            {active && (
              <button onClick={reset} className="btn-quiet ml-auto"><RotateCcw className="h-3 w-3" />reset</button>
            )}
            <span className={`micro ${active ? '' : 'ml-auto'}`}>
              {filtered.length} plate{filtered.length === 1 ? '' : 's'}
            </span>
          </div>

          {/* move chips */}
          <div className="mt-3 flex flex-wrap items-center gap-1.5">
            <span className="micro mr-1 text-bone-500">moves</span>
            {Object.keys(movesMeta)
              .sort((a, b) => (moveCounts[b] || 0) - (moveCounts[a] || 0) || a.localeCompare(b))
              .map((m) => (
                <button key={m} onClick={() => toggleMove(m)} title={movesMeta[m]?.definition}
                  className={`pill !py-0.5 ${moveSel.includes(m) ? 'pill-active' : ''}`}>
                  {m.replace(/-/g, ' ')}
                  <span className="text-bone-500">{moveCounts[m] || 0}</span>
                </button>
              ))}
          </div>

          {/* grid */}
          <div className="mt-4 grid grid-cols-1 gap-2.5 sm:grid-cols-2 lg:grid-cols-3 2xl:grid-cols-4">
            {filtered.slice(0, limit).map((row, i) => (
              <PlateCard key={row.id} row={row} rubric={rubric}
                hue={sectors[row.domain]?.hue || '#877c63'}
                rank={i} onOpen={() => open(row)} inShelf={inShelf(row.id)}
                onShelf={() => {
                  setShelf((s) => (s.includes(row.id) ? s.filter((x) => x !== row.id) : [...s, row.id]))
                  flash(inShelf(row.id) ? 'removed from shelf' : `${row.name} accessioned`)
                }}
                moveMeta={movesMeta} />
            ))}
          </div>

          {filtered.length > limit && (
            <div className="mt-5 flex justify-center">
              <button className="btn-signal" onClick={() => setLimit((l) => l + 120)}>
                show {Math.min(120, filtered.length - limit)} more of {filtered.length - limit}
              </button>
            </div>
          )}
          {!filtered.length && (
            <div className="plate mt-8 p-8 text-center">
              <p className="font-display text-lg">Nothing accessioned under those constraints.</p>
              <p className="mt-1 text-sm text-bone-700">
              The catalog is audited-only, so an empty result is an honest one: loosen the coolness floor,
              drop a move filter, or open the {' '}
              <button className="underline decoration-dotted" onClick={() => setPoolOpen(true)}>unaudited pool</button>
              {' '}({stats?.pool_records ?? 0} records) to see what has not been checked yet.
            </p>
              <button className="btn-quiet mt-3" onClick={reset}>reset filters</button>
            </div>
          )}
        </main>
      )}

      {tab === 'atlas' && (
        <main className="mx-auto max-w-[1400px] px-4 pt-4 sm:px-6">
          <IdeaAtlas rows={filtered.length ? filtered : rows} sectors={sectors} movesMeta={movesMeta}
            onOpen={open} query={query} />
        </main>
      )}

      {tab === 'forge' && (
        <main className="mx-auto max-w-[1400px] px-4 pt-4 sm:px-6">
          <IdeaForge rows={rows} onOpen={open} onJump={() => setTab('index')} />
        </main>
      )}

      {/* ── shelf drawer ─────────────────────────────────────── */}
      {shelfOpen && (
        <aside className="fixed inset-y-0 right-0 z-40 w-full max-w-md border-l border-bone-300 bg-bone-50 p-4 shadow-none overflow-y-auto">
          <div className="flex items-center gap-2">
            <Archive className="h-4 w-4 text-signal-700" />
            <h2 className="font-display text-lg">Your shelf</h2>
            <button onClick={() => setShelfOpen(false)} className="ml-auto btn-quiet"><X className="h-3 w-3" /></button>
          </div>
          <p className="mt-1 text-[12px] text-bone-700">
            Ideas you kept for later. Export it as a markdown brief and hand it to a collaborator — or to an agent.
          </p>
          <div className="mt-3 space-y-1.5">
            {shelf.length === 0 && <p className="micro text-bone-500">empty — click the star on any plate</p>}
            {shelf.map((id) => {
              const row = rows.find((r) => r.id === id)
              if (!row) return null
              return (
                <div key={id} className="plate flex items-start gap-2 p-2">
                  <button onClick={() => { open(row); setShelfOpen(false) }} className="flex-1 text-left">
                    <p className="font-display text-[15px] leading-tight">{row.name}</p>
                    <p className="micro mt-0.5 truncate">{row.event || 'unattributed'}</p>
                  </button>
                  <button onClick={() => setShelf((s) => s.filter((x) => x !== id))} className="text-bone-500 hover:text-signal-700">
                    <X className="h-3.5 w-3.5" />
                  </button>
                </div>
              )
            })}
          </div>
          {shelf.length > 0 && (
            <div className="mt-4 flex gap-2">
              <button className="btn-signal" onClick={async () => {
                const md = shelfMarkdown(shelf, rows, Object.values(shards).reduce((a, s) => ({ ...a, ...s }), {}))
                flash((await copyText(md)) ? 'brief copied as markdown' : 'copy blocked by browser')
              }}>copy as brief</button>
              <button className="btn-quiet" onClick={() => downloadText('idea-shelf.md',
                shelfMarkdown(shelf, rows, Object.values(shards).reduce((a, s) => ({ ...a, ...s }), {})))}>
                download .md
              </button>
              <button className="btn-quiet ml-auto" onClick={() => setShelf([])}>clear</button>
            </div>
          )}
        </aside>
      )}

      {selected && (
        <IdeaInspector row={selected} detail={detail} moveMeta={movesMeta} sector={sectors[selected.domain]}
          rubric={rubric}
          rows={rows} shards={shards} onClose={() => open(null)} onOpen={open}
          inShelf={inShelf(selected.id)}
          onShelf={() => setShelf((s) => (s.includes(selected.id) ? s.filter((x) => x !== selected.id) : [...s, selected.id]))}
          flash={flash} />
      )}

      <AuditPool open={poolOpen} pool={pool} stats={stats} onClose={() => setPoolOpen(false)} />

      {toast && (
        <div className="fixed bottom-5 left-1/2 z-50 -translate-x-1/2">
          <div className="stamp !border-bone-900 !bg-bone-950 !text-bone-100 !px-3 !py-1.5 !text-[10px]">{toast}</div>
        </div>
      )}

      <footer className="mt-14 border-t border-bone-300">
        <div className="mx-auto max-w-[1400px] px-4 py-6 sm:px-6">
          <div className="double-rule -mx-4 mb-4 sm:-mx-6" />
          <p className="font-mono text-[10.5px] uppercase tracking-label leading-relaxed text-bone-600">
            Data: public Devpost pages &amp; the public hackathon API · sector, moves and score are <b className="text-bone-800">derived</b>, never quoted as team claims ·
            {' '}read the corpus as an API: <a className="text-signal-700 hover:underline" href="agents/llms.txt">agents/llms.txt</a> ·
            {' '}<a className="text-signal-700 hover:underline" href="data/ideas.csv">ideas.csv</a> ·
            {' '}<a className="text-signal-700 hover:underline" href="data/ideas.ndjson">ideas.ndjson</a> ·
            {' '}<a className="text-signal-700 hover:underline" href="data/moves.json">moves.json</a> ·
            {' '}<a className="text-signal-700 hover:underline" href="manifest.json">build manifest</a>
          </p>
        </div>
      </footer>
    </div>
  )
}

function PlateCard({ row, hue, rank, onOpen, inShelf, onShelf, moveMeta, rubric }) {
  return (
    <article className="plate rise-in group flex flex-col p-3" style={{ animationDelay: `${Math.min(rank, 18) * 12}ms` }}>
      <span className="tick -left-px -top-px border-l border-t" style={{ borderColor: hue }} />
      <span className="tick -right-px -top-px border-r border-t" style={{ borderColor: hue }} />
      <span className="tick -bottom-px -left-px border-b border-l" style={{ borderColor: hue }} />
      <span className="tick -bottom-px -right-px border-b border-r" style={{ borderColor: hue }} />

      <header className="flex items-start gap-2">
        <span className="mt-1 h-2 w-2 shrink-0 rounded-full" style={{ background: hue }} />
        <button onClick={onOpen} className="flex-1 text-left">
          <h3 className="font-display text-[17px] font-medium leading-[1.15] tracking-[-0.01em] group-hover:text-signal-700">
            {row.name}
          </h3>
        </button>
        <button onClick={onShelf} title={inShelf ? 'remove from shelf' : 'keep for later'} className="shrink-0">
          <Star className={`h-3.5 w-3.5 ${inShelf ? 'fill-brass-500 text-brass-700' : 'text-bone-400 hover:text-brass-500'}`} />
        </button>
      </header>

      <p className="mt-1.5 text-[12.5px] leading-snug text-bone-800 line-clamp-3">{row.hook}</p>

      {!!row.moves.length && (
        <div className="mt-2 flex flex-wrap gap-1">
          {row.moves.map((m) => (
            <span key={m} className="chip !text-[9.5px]" title={moveMeta[m]?.steal_this || m}
              style={{ borderLeft: `2px solid ${hue}` }}>
              {m.replace(/-/g, ' ')}
            </span>
          ))}
        </div>
      )}

      <footer className="mt-auto pt-2.5">
        <div className="flex items-center gap-1.5">
          <span className="accession truncate">{row.accession}</span>
          <span className="leader" />
          <span className="stamp border-signal-500/40 text-signal-700" title="coolness = explainable ranking score">
            {row.coolness.toFixed(2)}
          </span>
          <span className={`stamp ${toneClass(auditHeadline(row, null, rubric).tone)}`}
            title={auditHeadline(row, null, rubric).verdictLabel}>
            {row.verdict === 'strong' ? 'strong' : row.verdict === 'sound-with-caveats' ? 'vetted' : row.verdict || 'unaudited'}
          </span>
          <span className={`stamp ${row.depth === 'deep' ? 'border-brass-500 text-brass-700' : 'border-bone-400 text-bone-500'}`}
            title={row.depth === 'deep' ? 'project page fetched: likes, tags, authored sections' : 'listing row: title, summary, sector, moves'}>
            {row.depth}
          </span>
        </div>
        <p className="mt-1.5 flex items-center gap-1.5 font-mono text-[10px] text-bone-600">
          <span className="truncate" style={{ color: row.eventHue }}>{row.event || 'unattributed'}</span>
          <span className="text-bone-400">·</span>
          {row.likes !== null
            ? <span>{row.likes} likes</span>
            : <span className="text-bone-500">likes n/a</span>}
          {row.award !== 'Unknown' && <><span className="text-bone-400">·</span><span className="text-brass-700">{row.award.replace(' / Overall Winner', '')}</span></>}
          <a href={row.url} target="_blank" rel="noreferrer noopener" onClick={(e) => e.stopPropagation()}
            className="ml-auto text-bone-500 hover:text-signal-700" title="open the original submission">
            <ExternalLink className="h-3 w-3" />
          </a>
        </p>
      </footer>
    </article>
  )
}
