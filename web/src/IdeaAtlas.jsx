import React, { useEffect, useMemo, useRef, useState } from 'react'

/* The Atlas: one sanctioned dark surface. Sectors sit on a ring; a project's
   height above its shelf is its coolness, so the vault ceiling is the ranking.
   Hand-rolled canvas projection (no three.js), matching the reference repo's
   bundle-weight discipline. Renders on demand: drag / wheel / hover only. */

const FOV = 620
const PITCH = -0.44

function seeded(i) {
  let h = (i + 1) * 2654435761 % 4294967296
  return () => {
    h = (h * 1664525 + 1013904223) % 4294967296
    return h / 4294967296
  }
}

export default function IdeaAtlas({ rows, sectors, movesMeta, onOpen, query }) {
  const wrapRef = useRef(null)
  const canvasRef = useRef(null)
  const [size, setSize] = useState({ w: 900, h: 520 })
  const [hover, setHover] = useState(null)
  const cam = useRef({ yaw: -0.34, zoom: 1, tYaw: -0.34, tZoom: 1, dragging: false, px: 0 })
  const raf = useRef(0)
  const dirty = useRef(true)

  const layout = useMemo(() => {
    const bySector = new Map()
    rows.forEach((r) => {
      if (!bySector.has(r.domain)) bySector.set(r.domain, [])
      bySector.get(r.domain).push(r)
    })
    const names = [...bySector.keys()]
    const pts = []
    names.forEach((name, si) => {
      const bucket = bySector.get(name)
      const angle = (si / Math.max(names.length, 1)) * Math.PI * 2
      const R = 200 + Math.min(bucket.length, 40) * 2.4
      const cx = Math.cos(angle) * R
      const cz = Math.sin(angle) * R
      const rnd = seeded(si * 977)
      bucket.forEach((row, i) => {
        const a = rnd() * Math.PI * 2
        const d = Math.sqrt(rnd()) * (30 + Math.sqrt(bucket.length) * 6)
        pts.push({
          row,
          sector: name,
          x: cx + Math.cos(a) * d,
          z: cz + Math.sin(a) * d,
          y: -40 - row.coolness * 230 - (row.depth === 'deep' ? 26 : 0),
          hue: sectors[name]?.hue || '#868e96',
          r: 2.1 + row.coolness * 4.4 + (row.depth === 'deep' ? 1.1 : 0),
        })
      })
    })
    const anchor = {}
    names.forEach((name, si) => {
      const angle = (si / Math.max(names.length, 1)) * Math.PI * 2
      const R = 200 + Math.min((bySector.get(name) || []).length, 40) * 2.4
      anchor[name] = { x: Math.cos(angle) * R, z: Math.sin(angle) * R, hue: sectors[name]?.hue, count: (bySector.get(name) || []).length, name }
    })
    return { pts, anchor: Object.values(anchor), bySector }
  }, [rows, sectors])

  useEffect(() => {
    const el = wrapRef.current
    if (!el) return
    const ro = new ResizeObserver(([e]) => {
      const { width, height } = e.contentRect
      setSize({ w: Math.max(320, width), h: Math.max(360, height) })
      dirty.current = true
    })
    ro.observe(el)
    return () => ro.disconnect()
  }, [])

  const project = (p, w, h) => {
    const yaw = cam.current.yaw
    const cos = Math.cos(yaw), sin = Math.sin(yaw)
    const x = p.x * cos - p.z * sin
    const z = p.x * sin + p.z * cos
    const zoom = cam.current.zoom
    const depth = z * PITCH + 520
    const s = (FOV / Math.max(depth, 80)) * zoom
    return { sx: w / 2 + x * s, sy: h / 2 + (p.y * 0.9 - z * PITCH * 0.35) * s, s, depth }
  }

  useEffect(() => {
    const canvas = canvasRef.current
    if (!canvas) return
    const ctx = canvas.getContext('2d')
    const dpr = Math.min(window.devicePixelRatio || 1, 2)
    canvas.width = size.w * dpr
    canvas.height = size.h * dpr
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0)

    const draw = () => {
      const { w, h } = size
      ctx.clearRect(0, 0, w, h)
      // floor: engraved concentric shelves
      ctx.save()
      ctx.strokeStyle = 'rgba(178,142,60,0.16)'
      ctx.lineWidth = 1
      for (let ring = 1; ring <= 4; ring += 1) {
        ctx.beginPath()
        for (let a = 0; a <= 64; a += 1) {
          const ang = (a / 64) * Math.PI * 2
          const R = ring * 92
          const p = project({ x: Math.cos(ang) * R, z: Math.sin(ang) * R, y: 0 }, w, h)
          a === 0 ? ctx.moveTo(p.sx, p.sy) : ctx.lineTo(p.sx, p.sy)
        }
        ctx.stroke()
      }
      ctx.restore()

      const sorted = layout.pts
        .map((p) => ({ p, ...project(p, w, h) }))
        .sort((a, b) => b.depth - a.depth)

      const q = (query || '').trim().toLowerCase()
      const matched = q
        ? new Set(layout.pts.filter((p) => `${p.row.name} ${p.row.hook} ${p.row.moves.join(' ')}`.toLowerCase().includes(q)).map((p) => p.row.id))
        : null

      // bridges: shared-move links for the hovered node
      if (hover) {
        const hv = layout.pts.find((p) => p.row.id === hover.id)
        if (hv) {
          ctx.save()
          ctx.lineWidth = 1
          layout.pts.forEach((p) => {
            if (p === hv || !p.row.moves.some((m) => hv.row.moves.includes(m))) return
            const a = project(hv, w, h), b = project(p, w, h)
            ctx.strokeStyle = 'rgba(201,66,26,0.42)'
            ctx.beginPath()
            ctx.moveTo(a.sx, a.sy)
            ctx.quadraticCurveTo((a.sx + b.sx) / 2, (a.sy + b.sy) / 2 - 26, b.sx, b.sy)
            ctx.stroke()
          })
          ctx.restore()
        }
      }

      // sector anchors + labels
      layout.anchor.forEach((a) => {
        const p = project({ x: a.x, y: 0, z: a.z }, w, h)
        ctx.save()
        ctx.fillStyle = a.hue || '#868e96'
        ctx.globalAlpha = 0.5
        ctx.beginPath()
        ctx.arc(p.sx, p.sy, 3.4 * Math.max(p.s, 0.5), 0, Math.PI * 2)
        ctx.fill()
        ctx.globalAlpha = 0.85
        ctx.font = '500 10px "IBM Plex Mono", monospace'
        ctx.fillStyle = '#c7bda6'
        ctx.textAlign = 'center'
        ctx.fillText(`${a.name.toUpperCase().slice(0, 22)} · ${a.count}`, p.sx, p.sy + 15)
        ctx.restore()
      })

      sorted.forEach(({ p, sx, sy, s }) => {
        const dim = matched ? !matched.has(p.row.id) : false
        const isHover = hover?.id === p.row.id
        ctx.save()
        ctx.globalAlpha = dim ? 0.2 : 1
        if (!dim) {
          ctx.shadowColor = p.hue
          ctx.shadowBlur = (isHover ? 16 : 7) * Math.min(s, 1.6)
        }
        ctx.fillStyle = p.hue
        ctx.beginPath()
        ctx.arc(sx, sy, Math.max(1.2, p.r * Math.min(Math.max(s, 0.55), 1.7)) * (isHover ? 1.7 : 1), 0, Math.PI * 2)
        ctx.fill()
        if (p.row.depth === 'deep' && !dim) {
          ctx.shadowBlur = 0
          ctx.strokeStyle = 'rgba(226,203,147,0.85)'
          ctx.lineWidth = 1
          ctx.beginPath()
          ctx.arc(sx, sy, Math.max(3, p.r * s + 3), 0, Math.PI * 2)
          ctx.stroke()
        }
        if ((isHover || (p.row.coolness > 0.42 && s > 0.85 && !dim)) && !draggingLabel()) {
          ctx.shadowBlur = 0
          ctx.font = '500 11px "IBM Plex Mono", monospace'
          ctx.fillStyle = isHover ? '#fbf9f4' : 'rgba(236,231,219,0.62)'
          ctx.textAlign = 'left'
          ctx.fillText(p.row.name.slice(0, 26), sx + 9, sy + 3)
        }
        ctx.restore()
      })

      if (hover) {
        const p = sorted.find((s) => s.p.row.id === hover.id)
        if (p) {
          const text = `${hover.event || 'unattributed'} · coolness ${hover.coolness.toFixed(3)}`
          ctx.save()
          ctx.font = '500 10px "IBM Plex Mono", monospace'
          const tw = ctx.measureText(text).width
          ctx.fillStyle = 'rgba(10,10,11,0.88)'
          ctx.fillRect(p.sx + 12, p.sy - 30, tw + 14, 30)
          ctx.strokeStyle = 'rgba(201,66,26,0.6)'
          ctx.strokeRect(p.sx + 12.5, p.sy - 30.5, tw + 13, 29)
          ctx.fillStyle = '#fbf9f4'
          ctx.fillText(hover.name.slice(0, 34), p.sx + 19, p.sy - 18)
          ctx.fillStyle = '#c7bda6'
          ctx.fillText(text, p.sx + 19, p.sy - 7)
          ctx.restore()
        }
      }
    }

    function draggingLabel() { return cam.current.dragging }

    const loop = () => {
      const c = cam.current
      c.yaw += (c.tYaw - c.yaw) * 0.16
      c.zoom += (c.tZoom - c.zoom) * 0.16
      const settled = Math.abs(c.tYaw - c.yaw) < 0.0008 && Math.abs(c.tZoom - c.zoom) < 0.002
      if (dirty.current || !settled) { draw(); dirty.current = false }
      raf.current = requestAnimationFrame(loop)
    }
    raf.current = requestAnimationFrame(loop)
    return () => cancelAnimationFrame(raf.current)
  }, [size, layout, hover, query, drawDeps()])

  function drawDeps() { return String(rows.length) + String(Object.keys(sectors).length) }

  const pick = (ev) => {
    const rect = canvasRef.current.getBoundingClientRect()
    const mx = ev.clientX - rect.left
    const my = ev.clientY - rect.top
    let best = null
    let bestD = 18
    layout.pts.forEach((p) => {
      const s = project(p, rect.width, rect.height)
      const d = Math.hypot(s.sx - mx, s.sy - my)
      if (d < bestD) { bestD = d; best = p }
    })
    return best
  }

  return (
    <div className="gallery-night relative overflow-hidden rounded-lg border border-bone-300">
      <div ref={wrapRef} className="relative h-[64vh] min-h-[440px] w-full">
        <canvas
          ref={canvasRef}
          style={{ width: size.w, height: size.h, cursor: cam.current.dragging ? 'grabbing' : 'crosshair' }}
          onMouseDown={(e) => { cam.current.dragging = true; cam.current.px = e.clientX }}
          onMouseUp={() => { cam.current.dragging = false }}
          onMouseLeave={() => { cam.current.dragging = false; setHover(null) }}
          onMouseMove={(e) => {
            const c = cam.current
            if (c.dragging) {
              c.tYaw += (e.clientX - c.px) * 0.006
              c.px = e.clientX
            }
            const hit = pick(e)
            setHover(hit ? hit.row : null)
          }}
          onWheel={(e) => {
            e.preventDefault()
            cam.current.tZoom = Math.min(2.4, Math.max(0.45, cam.current.tZoom * (e.deltaY > 0 ? 0.9 : 1.1)))
            dirty.current = true
          }}
          onClick={(e) => { const hit = pick(e); if (hit) onOpen(hit.row) }}
        />
      </div>

      <div className="pointer-events-none absolute left-4 top-3 font-mono text-[10px] uppercase tracking-label text-bone-400">
        the vault · height = coolness · gold ring = deep record · arcs = shared move
      </div>
      <div className="absolute bottom-3 left-4 right-4 flex flex-wrap items-center gap-x-3 gap-y-1">
        {layout.anchor.sort((a, b) => b.count - a.count).map((a) => (
          <span key={a.name} className="flex items-center gap-1.5 font-mono text-[9.5px] uppercase tracking-label text-bone-400">
            <span className="h-1.5 w-1.5 rounded-full" style={{ background: a.hue }} />
            {a.name.length > 24 ? `${a.name.slice(0, 24)}…` : a.name}
          </span>
        ))}
      </div>
      {hover && (
        <div className="absolute right-4 top-3 max-w-[240px]">
          <p className="font-mono text-[10px] uppercase tracking-label text-signal-300">
            {hover.moves.length ? hover.moves.slice(0, 2).join(' · ') : 'no move detected'}
          </p>
          <p className="mt-0.5 line-clamp-2 text-[11px] leading-snug text-bone-200">
            {movesMeta[hover.moves?.[0]]?.steal_this || hover.hook}
          </p>
        </div>
      )}
    </div>
  )
}
