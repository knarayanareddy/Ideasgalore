# Agent recipes — Ideas Galore

All reads are plain static files. `https://knarayanareddy.github.io/Ideasgalore` is the site root (also works from a local
checkout: `python3 -m http.server -d web/dist`).

## Top 20 by coolness, one line each

```bash
curl -sL https://knarayanareddy.github.io/Ideasgalore/data/ideas.csv | head -1
curl -sL https://knarayanareddy.github.io/Ideasgalore/data/ideas.csv | tail -n +2 | sort -t, -k10 -gr | head -20
```

## Every project that demonstrates a given move

```bash
curl -sL https://knarayanareddy.github.io/Ideasgalore/data/ideas.ndjson | \
  jq -c 'select(.moves | index("price-before-generate")) |
          {name, url, domain, coolness}'
```

## Ideas for a goal, ranked by specificity (not popularity)

```bash
curl -sL https://knarayanareddy.github.io/Ideasgalore/data/ideas.ndjson | \
  jq -r 'select(.specificity? // .coolness_parts.specificity > 0.5)
         | [.coolness_parts.specificity, .name, .url] | @tsv' | sort -gr | head -10
```

## Sector shard, then pull one record's deep intel (two hops, never the whole corpus)

```bash
curl -sL https://knarayanareddy.github.io/Ideasgalore/data/details/public-trust-safety-and-compliance.json | jq 'keys[:5]'
curl -sL https://knarayanareddy.github.io/Ideasgalore/data/details/public-trust-safety-and-compliance.json | jq '.["realityCheCk"] // .[] | select(.id=="complianceguardian-kcqs32")'
```

## Which events is this corpus biased toward?

```bash
curl -sL https://knarayanareddy.github.io/Ideasgalore/data/hackathons.json | jq -r '.events[] | [.project_count, .title, .prize_usd] | @tsv'
```

## Build brief for the next hackathon (curated collisions)

```bash
curl -sL https://knarayanareddy.github.io/Ideasgalore/data/remixes.json | jq '.recipes[0] | {title, the_wedge, first_48_hours, kill_criteria}'
```

## Verify what you loaded

```bash
curl -sIL https://knarayanareddy.github.io/Ideasgalore/catalog-packed.json | grep -i etag        # revalidate, don't refetch
curl -sL https://knarayanareddy.github.io/Ideasgalore/manifest.json | jq '.corpus_sha256, .scoring_version'
```

## Politeness expected of you

- Cache the response (ETag/`If-None-Match`); these files change weekly, not per minute.
- Never bulk-fetch `data/details/*.json` in a loop; fetch the one shard you need.
- Keep `url` attribution in anything you render, and respect `agents/ethics.json`.
