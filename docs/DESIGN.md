# Ideas Galore — Locked Design System ("Field Museum of Ideas", v1)

> This file is the authority on visual decisions. It exists because the reference
> project (`toolscour`) documented that its v1 look was the statistical average of
> its training data — "AI slop" — and had to be rebuilt. We refuse to inherit that
> either aesthetically or as a process. **Deviation from this file requires a written
> argument in `docs/EXPERT_PANEL.md`, not a Tailwind class.**

## 1 · Concept

**The catalogue is a museum accession record; the vault is night.**

Ideas Galore files hackathon projects the way a field museum files specimens:
an accession number, a shelf (sector), a label with a plain-language diagnosis,
and a provenance line saying who observed what. So the chrome is uncoated paper:
bone card stock, warm graphite ink, hairline rules, dotted leader lines, brass
metadata, one specimen-vermilion signal. Serif display for the *idea*, mono for
*everything the machine knows*.

Exactly two surfaces are dark: the **Atlas** viewport (a physical vault you look
into) and **ink panels** (quotes/code stamped onto paper). That contrast *is* the
concept — do not harmonize it away.

Anti-cliché commitments, made deliberately:
- No violet/indigo/fuchsia anywhere (the 2019-Tailwind-default hue that now
  predicts model-generated UI). No blue→purple gradients. No gradient text.
- No dark-mode-by-default chrome (dark is now the standard, not a statement).
- No drop shadows for elevation: **hairline rules do the work.**
- No 3-card marketing grid, no glassmorphism, no pill-everything (radius ladder below).

## 2 · Palette (1 dominant + 1 quiet accent + data spectrum + neutral ramp)

| Token | Value | Use |
| --- | --- | --- |
| `bone-100` | `#f4f1ea` | page canvas (uncoated paper) |
| `bone-50` | `#fbf9f4` | cards / plates, raised surfaces |
| `bone-200` | `#ece7db` | wells, inputs, inset rows |
| `bone-300 / 400` | `#ddd6c2 / #c7bda6` | hairline / strong rules |
| `signal-500` | `#c9421a` | **the only primary.** Solid CTA fills (with `bone-50` ink text), active filters, hover titles, kill-criteria edge. |
| `signal-700` | `#8f2f12` | vermilion as *ink* on paper: links, score emphasis, focus rings. |
| `brass-500 / 700` | `#b28e3c / #7c6220` | accession numbers, leader dots, corner ticks, `DEEP` stamp. Quiet, never a CTA. |
| text | bone ramp | body `bone-800/900`, secondary `bone-600`, micro `bone-500` |
| `gallery-900/950` | `#101010 / #0a0a0b` | Atlas canvas only |
| spectrum | 10 hues + museum grey | **sector identity — data only** (dots, chips, atlas nodes, sparkline). Never chrome. Locked in `pipeline/taxonomy_hacks.py::DOMAINS[*].hue`, shipped as `data/sectors.json` so UI and agents share one source. |

Rules
1. Sector hues are **never** used for buttons, links, or backgrounds — only to identify data.
2. No sector hue within 12° of the brand vermilion, and none in the 250°–290° violet band (`HUES_LOCKED` in the taxonomy).
3. Exactly one chromatic CTA style: `signal-500` fill, `bone-50` label, `signal-700` border.
4. APCA on paper: body ≥ Lc 75, mono micro-labels ≥ Lc 60, hairlines ≥ Lc 30. In the dark canvas, labels ≥ Lc 70.

## 3 · Typography

| Role | Face | Rules |
| --- | --- | --- |
| Display | **Newsreader** (600/500) | Wordmark, project titles, section heads. `tracking-[-0.015em]`, sentence case, never all-caps, weight ≤ 600. |
| Body / UI | **Public Sans** (400/500/600) | Every readable sentence. 12.5–13.5px for labels/summaries, `leading-snug`. |
| Machine | **IBM Plex Mono** (400/500) | Accession numbers, scores, chips, filters, stats strip, field keys, CLI, provenance stamps. Mono says *this is data, not prose*. |

Banned: Inter, Roboto, Space Grotesk, system-ui as the primary body face, `bg-clip-text` gradients.

## 4 · Radius, rules & rhythm (three-step vocabulary)

- inline chips, inputs, buttons: **4px** · plates/cards: **8px** · modal/hero panels: **10px** · true pills only for filter pills (9999px)
- borders: 1px `bone-300`, hover `bone-400`; **double rule** (1px + 3px double) under the masthead and above the footer
- spacing rhythm: 4px base; plate padding 12px; section gap 24px; max width 1400px
- `tracking-label: 0.12em` for micro-labels, `tracking-accession: 0.16em` for accession numbers

## 5 · Signature details (the anti-generic layer)

1. **Accession numbers** — every plate carries a mono `ACC·0042`, and the same id
   appears in exports so a citation and a card are the same object.
2. **Spectral dots** — sector chips, atlas nodes and inspector rules share one hue
   per sector; the dot is the *only* decoration the hue is allowed to produce.
3. **Dotted leader lines** in the inspector (`key ……… value`), like a printed catalogue.
4. **Corner ticks** in the sector hue on plate hover; brass focus rings.
5. **Depth stamps** — `LISTING` vs `DEEP` is a visible, honest badge on every card,
   because a one-line gallery row and a fetched project page are not the same evidence.
6. **Provenance stamps** — `field:observed / derived / editorial` chips in the
   inspector. Uncertainty is part of the product.
7. **Ink panels** — team quotes are stamped as dark ink blocks on paper, capped at
   220 characters (see `docs/DATA_ETHICS.md`).
8. **One motion moment** — plate rise-in (28px→0, 280ms, staggered ≤18 cards) plus the
   tick reveal. Everything else is static. `prefers-reduced-motion` disables both.

## 6 · Don't

- Don't add violet/indigo/fuchsia or a blue→purple gradient anywhere.
- Don't shadow a plate to lift it; use a hairline.
- Don't widen the palette beyond §2, or use a sector hue for chrome.
- Don't radius >10px except filter pills. Don't blur anything except the sticky masthead.
- Don't chromatic-ize body copy; vermilion text is for links and score emphasis only.
- Don't "harmonize" the Atlas into the paper theme.

## 7 · Sector spectrum v1 (locked)

| Shelf | Hue |
| --- | --- |
| Agentic Autonomy & Orchestration | `#0b7285` teal |
| Developer Tooling & Code Intelligence | `#3b5bdb` cobalt |
| Health, Care & Human Performance | `#c2255c` berry |
| Climate, Energy & the Physical World | `#2b8a3e` forest |
| Public Trust, Safety & Compliance | `#495057` graphite (deliberately colourless) |
| Money, Commerce & Marketplaces | `#b2710d` bronze |
| Creative Media, Story & Play | `#e64980` rose |
| Learning & Knowledge Systems | `#087f5b` pine |
| Accessibility & Assistive Tech | `#5c940d` olive |
| Data, Retrieval & Memory Infrastructure | `#7f5539` earth |
| *Emerging & Cross-Domain* (unshelved) | `#868e96` museum grey |

The last row is not a sector: it is the classifier saying *"the submission's own
text was too thin to place."* We ship that honesty instead of silently filing
strays under the closest bucket.
