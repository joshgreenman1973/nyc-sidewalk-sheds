# NYC sidewalk shed tracker

Interactive map of every active sidewalk shed in New York City, joined to Local
Law 11 facade filings, building-distress signals and 311 scaffold complaints.

**Live: https://joshgreenman1973.github.io/nyc-sidewalk-sheds/**

Data refreshes automatically every night from NYC Open Data. If the refresh ever
stops, a watchdog opens an issue on this repo rather than letting the site quietly
serve stale numbers.

## Why this version exists

This is a rebuild of an earlier tracker whose updates had stopped working. Two
things were wrong, and both are worth stating plainly because they shaped the
design here:

1. **The nightly refresh never existed.** The original README described a nightly
   GitHub Actions workflow "applied separately because the initial push token
   lacked the `workflow` scope." It was never applied. There was no
   `.github/workflows` directory, so nothing ever ran and the published data sat
   frozen for roughly three months.

2. **An upstream schema change silently corrupted the zombie count.** DOB's job
   filings dataset (`w9ak-ipjd`) encodes its `shed` flag as `'YES'`/`'NO'`; it
   previously used `'1'`/`'0'`. The build filtered on `shed='0'`, which after the
   change matched *zero* rows. Zombie detection works by finding buildings *with*
   recent non-shed work, so matching nothing meant every long-standing shed got
   flagged a zombie — inflating the count roughly fivefold. Nothing errored.

The second one is the more instructive failure: the shed count stayed correct, so
any check that only counted rows would have passed it. That is why validation here
checks *derived* metrics, not just volume.

## How it works

- `scripts/build_data.py` pulls eight NYC Open Data endpoints and writes small
  JSON snapshots into `data/`.
- `scripts/socrata.py` is the only thing that touches the network. Every request
  retries with backoff and carries an app token when one is configured. The old
  version retried only its main fetch, so a blip on any of the chunked PLUTO/FISP
  loops aborted the whole run.
- `scripts/validate.py` gates publication. If the data fails a sanity check,
  **nothing is written** — a stale-but-correct site beats a fresh-but-wrong one.
- `index.html` + `assets/` is a static site. Leaflet, vanilla JS, no build step.

### The automation

| Workflow | Schedule | Does |
|---|---|---|
| `refresh.yml` | 07:20 UTC daily | Rebuilds data, commits only if something changed |
| `staleness-check.yml` | 13:45 UTC daily | Opens an issue if published data is >3 days old |

Both can be run manually from the Actions tab. If a genuine jump in shed counts
trips the swing guard, re-run `refresh.yml` with `allow_swing` checked.

## The Socrata app token (optional, and probably unnecessary)

**You almost certainly don't need one.** A full build makes roughly **46 requests**,
once a day. Socrata throttles anonymous traffic [by IP address][tokens] against a
shared pool, and 46 requests/day is nowhere near any plausible limit — the build has
run anonymously without a single throttle.

The one theoretical argument for a token: GitHub Actions runners share IP addresses
with a lot of other CI traffic, and the anonymous pool is per-IP, so in principle
someone else's requests could crowd ours. That is an inference, not something
observed here, and the retry logic (5 attempts, ≥30s backoff on a 429) should absorb
it anyway. If throttling ever does bite, the staleness watchdog will file an issue
and the run log will show the 429s.

So: add a token if that happens, not before.

[tokens]: https://dev.socrata.com/docs/app-tokens

If you do want one (free, ~2 minutes) — take the **App Token**, not the Secret Token:

1. Sign up at https://data.cityofnewyork.us/profile/edit/developer_settings and
   create an app token.
2. Add it to this repo:
   ```bash
   gh secret set SOCRATA_APP_TOKEN --repo joshgreenman1973/nyc-sidewalk-sheds
   ```
   The workflow picks it up automatically. `data/build_meta.json` records whether
   the last build used one.

## Local development

```bash
export SOCRATA_APP_TOKEN=...        # optional
python3 scripts/build_data.py       # ~3 minutes, writes data/*.json
python3 -m http.server 8765         # serve
open http://localhost:8765
```

## Methodology and caveats

See [methodology.html](methodology.html) for the full pass, including what
"zombie" does and does not mean. In short: a zombie is a shed up more than a year
whose building has no recent non-shed work filed and no unsafe facade filing. It
is an inference from permit records, not a finding that a specific shed is
unjustified.

## Embedding

The page posts `embed-resize` and `embed-state` `postMessage` events to its parent
and supports deep-link parameters: `?view=zombies`, `?boro=Manhattan`,
`?dur=1825-99999`, `?zombie=1`, `?q=NYCHA`, `?embed=1`.

## Sources

All NYC Open Data:

| Dataset | ID | Used for |
|---|---|---|
| DOB NOW: Build approved permits | `rbx6-tga4` | Active + historical shed permits |
| DOB permit issuance (legacy) | `ipu4-2q9a` | Pre-DOB-NOW erection dates |
| DOB NOW job filings | `w9ak-ipjd` | Zombie detection |
| PLUTO | `64uk-42ks` | Owner, year built, units |
| FISP / Local Law 11 | `xubg-57si` | Facade safety status |
| HPD violations | `wvxf-dwi5` | Open class B/C counts |
| HPD Alternative Enforcement | `hcir-3275` | Distressed-building flag |
| 311 service requests | `erm2-nwe9` | Scaffold Safety complaints |
