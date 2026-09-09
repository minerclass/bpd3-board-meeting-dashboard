# BPD3 Board Meeting Dashboard

A standalone, browser-based dashboard for Beach Park CCSD 3 board meeting
information. It currently covers the **2026–27** regular meeting schedule, with
the 2025–26 meeting summaries retained as a collapsible archive.

Everything on the page comes from public district sources:

- [School Board Meetings](https://www.bpd3.org/page/board-of-education-school-board-meetings) — the annual schedule
- [Regular Board Meetings](https://www.bpd3.org/o/bpd3/page/regular-board-meeting) — agendas, minutes, and meeting location

## Contents

| Path | Purpose |
| --- | --- |
| `index.html` | The complete dashboard — timeline, filters, meeting cards, and local page interactions. |
| `scripts/schedule.json` | The schedule data, mirrored into the `#mtg-data` block inside `index.html`. |
| `scripts/update_schedule.py` | Re-reads bpd3.org and updates both files. Standard library only. |
| `.github/workflows/update-schedule.yml` | Runs the updater daily and commits any change. |
| `.github/workflows/pages.yml` | Publishes the site to GitHub Pages on every push to `main`. |

## How the automatic update works

`update-schedule.yml` runs daily at 11:17 UTC. It fetches the two district
pages, parses the schedule and any posted agenda/minutes links, and writes the
result to `scripts/schedule.json` and the matching block in `index.html`. If
nothing changed on bpd3.org, the script writes nothing and no commit is made.
A commit to `main` triggers `pages.yml`, so the live site follows on its own.

The district's pages are Nuxt apps that ship their content as JSON in a
`__NUXT_DATA__` script tag, so the updater parses that payload directly — no
headless browser required.

Two safeguards are worth knowing about:

- If fewer than 8 meetings parse, the script assumes the district redesigned the
  page, prints an error, and **writes nothing** rather than publishing an empty
  schedule.
- GitHub disables scheduled workflows in repositories with no activity for 60
  days. If the daily run stops firing, open the Actions tab and re-enable it, or
  trigger it once with **Run workflow**.

Run it by hand at any time:

```bash
python scripts/update_schedule.py --check   # report drift, write nothing
python scripts/update_schedule.py           # apply the update
```

## Editing meeting content

The updater owns only the schedule facts for each meeting: `date`, `label`,
`agenda`, `minutes`, and the minutes-pending note. These fields are safe to
hand-edit in `scripts/schedule.json` and survive every run:

- `items` — bullet summary shown on the card
- `detail` — the sections behind **View Details**
- `cats` — category tags (`finance`, `curriculum`, `personnel`, `facilities`, `policy`, `community`) that drive the filters
- `sourceNote` — the attribution line under the summary
- `special` — a hearing label, kept until the district's own schedule supplies one

After editing the JSON, run `python scripts/update_schedule.py` to copy it into
`index.html`.

Meetings with no `items` render an "agenda not yet published" placeholder rather
than a summary, so an upcoming meeting is never shown as though it has already
happened. Held/next/scheduled status is computed in the browser from the current
date, so the timeline stays correct between updater runs.

## Publishing

Deployment is automatic from `main` via `.github/workflows/pages.yml`. Pages is
configured to deploy from a GitHub Actions artifact rather than a branch build.

## Privacy notes

The dashboard is a static page. It links to public BPD3 resources and does not
submit meeting notes, searches, or interactions to a server. Notes added through
the **Add Notes** button live in the browser tab only and are lost on reload.
