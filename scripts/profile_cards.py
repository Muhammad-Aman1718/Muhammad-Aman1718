#!/usr/bin/env python3
"""Generate the animated SVG cards shown on the GitHub profile README.

Runs inside GitHub Actions with the default GITHUB_TOKEN, so the profile never
depends on third-party card services that rate-limit or go down.

    python3 scripts/profile_cards.py --out dist            # live data
    python3 scripts/profile_cards.py --out dist --mock m.json  # offline preview
"""

import argparse
import datetime as dt
import json
import math
import os
import time
import urllib.request
from html import escape
from pathlib import Path

USER = os.environ.get("PROFILE_USER", "Muhammad-Aman1718")
FEATURED = [
    "invoice-generator",
    "Task-Management",
    "car-rental-managment-dashboard",
    "Doctor-Appointment-app",
]
HIDDEN_LANGS = {"Jupyter Notebook"}

# ── palette ────────────────────────────────────────────────────────────────
BG_A, BG_B = "#0b1020", "#141a33"
TEXT, MUTED, FAINT = "#e6edf3", "#8b98b8", "#2a3354"
CYAN, VIOLET, PINK, GREEN, AMBER = "#22d3ee", "#a78bfa", "#f472b6", "#34d399", "#fbbf24"
SANS = "'Segoe UI',Ubuntu,'Helvetica Neue',Arial,sans-serif"
MONO = "'JetBrains Mono','Fira Code',Consolas,'Courier New',monospace"

# ── data ───────────────────────────────────────────────────────────────────
API = "https://api.github.com/graphql"


def gql(query, variables):
    token = os.environ["GITHUB_TOKEN"]
    body = json.dumps({"query": query, "variables": variables}).encode()
    req = urllib.request.Request(
        API,
        data=body,
        headers={"Authorization": f"bearer {token}", "Content-Type": "application/json"},
    )
    for attempt in range(4):
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                data = json.load(resp)
            if data.get("errors"):
                raise RuntimeError(data["errors"])
            return data["data"]
        except Exception:
            if attempt == 3:
                raise
            time.sleep(2 ** (attempt + 1))


PROFILE_QUERY = """
query($login: String!) {
  user(login: $login) {
    createdAt
    followers { totalCount }
    pullRequests { totalCount }
    issues { totalCount }
    repositories(first: 100, ownerAffiliations: OWNER, isFork: false, privacy: PUBLIC) {
      totalCount
      nodes {
        stargazerCount
        languages(first: 10, orderBy: {field: SIZE, direction: DESC}) {
          edges { size node { name color } }
        }
      }
    }
  }
}
"""

YEAR_QUERY = """
query($login: String!, $from: DateTime!, $to: DateTime!) {
  user(login: $login) {
    contributionsCollection(from: $from, to: $to) {
      totalCommitContributions
      contributionCalendar { weeks { contributionDays { date contributionCount } } }
    }
  }
}
"""

REPO_QUERY = """
query($owner: String!, $name: String!) {
  repository(owner: $owner, name: $name) {
    name description url stargazerCount forkCount
    primaryLanguage { name color }
  }
}
"""


def fetch():
    user = gql(PROFILE_QUERY, {"login": USER})["user"]
    today = dt.datetime.now(dt.timezone.utc).date()
    start_year = int(user["createdAt"][:4])

    days, commits = {}, 0
    for year in range(start_year, today.year + 1):
        frm = f"{year}-01-01T00:00:00Z"
        to = f"{year}-12-31T23:59:59Z"
        coll = gql(YEAR_QUERY, {"login": USER, "from": frm, "to": to})["user"][
            "contributionsCollection"
        ]
        commits += coll["totalCommitContributions"]
        for week in coll["contributionCalendar"]["weeks"]:
            for d in week["contributionDays"]:
                if d["date"] <= today.isoformat():
                    days[d["date"]] = d["contributionCount"]

    langs = {}
    for repo in user["repositories"]["nodes"]:
        for edge in repo["languages"]["edges"]:
            name = edge["node"]["name"]
            if name in HIDDEN_LANGS:
                continue
            entry = langs.setdefault(name, {"size": 0, "color": edge["node"]["color"] or MUTED})
            entry["size"] += edge["size"]

    projects = []
    for name in FEATURED:
        try:
            repo = gql(REPO_QUERY, {"owner": USER, "name": name})["repository"]
        except Exception:
            repo = None
        if repo:
            projects.append(repo)

    return {
        "today": today.isoformat(),
        "days": days,
        "commits": commits,
        "prs": user["pullRequests"]["totalCount"],
        "issues": user["issues"]["totalCount"],
        "followers": user["followers"]["totalCount"],
        "repos": user["repositories"]["totalCount"],
        "stars": sum(r["stargazerCount"] for r in user["repositories"]["nodes"]),
        "langs": langs,
        "projects": projects,
    }


# ── helpers ────────────────────────────────────────────────────────────────
def fmt(n):
    return f"{n:,}"


def fmt_date(iso, with_year=True):
    d = dt.date.fromisoformat(iso)
    return d.strftime("%b %-d, %Y") if with_year else d.strftime("%b %-d")


def streaks(days, today):
    ordered = sorted(days)
    longest, run, run_start = (0, None, None), 0, None
    for i, day in enumerate(ordered):
        if days[day] > 0:
            run_start = day if run == 0 else run_start
            run += 1
            if run > longest[0]:
                longest = (run, run_start, day)
        else:
            run = 0

    # today without contributions yet does not break the streak
    cursor = dt.date.fromisoformat(today)
    if days.get(today, 0) == 0:
        cursor -= dt.timedelta(days=1)
    current, end = 0, cursor
    while days.get(cursor.isoformat(), 0) > 0:
        current += 1
        cursor -= dt.timedelta(days=1)
    current_range = (cursor + dt.timedelta(days=1)).isoformat(), end.isoformat()
    return current, current_range, longest


def card(w, h, body, extra_css="", defs=""):
    return f"""<svg xmlns="http://www.w3.org/2000/svg" width="{w}" height="{h}" viewBox="0 0 {w} {h}" fill="none">
<defs>
  <linearGradient id="bg" x1="0" y1="0" x2="1" y2="1">
    <stop offset="0" stop-color="{BG_A}"/><stop offset="1" stop-color="{BG_B}"/>
  </linearGradient>
  <linearGradient id="accent" x1="0" y1="0" x2="1" y2="0">
    <stop offset="0" stop-color="{CYAN}"/><stop offset=".5" stop-color="{VIOLET}"/><stop offset="1" stop-color="{PINK}"/>
  </linearGradient>
  <radialGradient id="glow" cx="1" cy="0" r="1">
    <stop offset="0" stop-color="{VIOLET}" stop-opacity=".22"/><stop offset="1" stop-color="{VIOLET}" stop-opacity="0"/>
  </radialGradient>
  {defs}
</defs>
<style>
  text {{ font-family: {SANS}; }}
  .mono {{ font-family: {MONO}; }}
  .title {{ font-size: 15px; font-weight: 700; fill: url(#accent); letter-spacing: .4px; }}
  .label {{ font-size: 11px; font-weight: 600; fill: {MUTED}; letter-spacing: 1.2px; }}
  .muted {{ fill: {MUTED}; }}
  .fade {{ animation: fade .7s ease-out backwards; }}
  @keyframes fade {{ from {{ opacity: 0; transform: translateY(6px); }} to {{ opacity: 1; transform: translateY(0); }} }}
  {extra_css}
</style>
<rect x=".5" y=".5" width="{w - 1}" height="{h - 1}" rx="16" fill="url(#bg)"/>
<rect x=".5" y=".5" width="{w - 1}" height="{h - 1}" rx="16" fill="url(#glow)"/>
<rect x=".5" y=".5" width="{w - 1}" height="{h - 1}" rx="16" stroke="url(#accent)" stroke-opacity=".45"/>
{body}
</svg>
"""


def delay(i, step=0.08, base=0.1):
    return f'style="animation-delay:{base + i * step:.2f}s"'


# ── cards ──────────────────────────────────────────────────────────────────
def render_streak(data):
    days, today = data["days"], data["today"]
    total = sum(days.values())
    first = min((d for d, c in days.items() if c > 0), default=today)
    current, (cur_from, cur_to), (best, best_from, best_to) = streaks(days, today)
    w, h = 1000, 210
    col = w / 3

    def side(x, value, label, sub, color, i):
        return f"""<g class="fade" {delay(i)}>
  <text x="{x}" y="92" text-anchor="middle" class="mono" font-size="40" font-weight="800" fill="{color}">{value}</text>
  <text x="{x}" y="124" text-anchor="middle" class="label">{label}</text>
  <text x="{x}" y="150" text-anchor="middle" font-size="12" class="muted">{sub}</text>
</g>"""

    cur_sub = (
        f"{fmt_date(cur_from, False)} – {fmt_date(cur_to, False)}" if current else "Start a new streak today!"
    )
    best_sub = f"{fmt_date(best_from, False)} – {fmt_date(best_to)}" if best else "—"
    ring = 2 * math.pi * 46

    body = f"""
<text x="28" y="36" class="title">🔥 CONTRIBUTION STREAK</text>
<line x1="{col}" y1="62" x2="{col}" y2="170" stroke="{FAINT}"/>
<line x1="{2 * col}" y1="62" x2="{2 * col}" y2="170" stroke="{FAINT}"/>
{side(col / 2, fmt(total), "TOTAL CONTRIBUTIONS", f"{fmt_date(first)} – Present", CYAN, 0)}
<g transform="translate({w / 2} 104)">
  <circle r="46" stroke="{FAINT}" stroke-width="7"/>
  <circle r="46" stroke="url(#accent)" stroke-width="7" stroke-linecap="round" transform="rotate(-90)"
          stroke-dasharray="{ring:.1f}" class="ring"/>
  <circle cy="-46" r="15" fill="{BG_A}"/>
  <text y="-39" text-anchor="middle" font-size="19" fill="{TEXT}" class="flame">🔥</text>
  <text y="13" text-anchor="middle" class="mono fade" font-size="36" font-weight="800" fill="{TEXT}" {delay(2)}>{current}</text>
</g>
<text x="{w / 2}" y="178" text-anchor="middle" class="label fade" {delay(3)}>CURRENT STREAK</text>
<text x="{w / 2}" y="197" text-anchor="middle" font-size="12" class="muted fade" {delay(4)}>{cur_sub}</text>
{side(col * 2.5, f"{best}", "LONGEST STREAK", best_sub, PINK, 1)}
"""
    css = f"""
  .ring {{ animation: ring 1.4s .3s cubic-bezier(.3,.7,.3,1) backwards; }}
  @keyframes ring {{ from {{ stroke-dashoffset: {ring:.1f}; }} }}
  .flame {{ animation: flicker 1.6s ease-in-out infinite; transform-origin: center; transform-box: fill-box; }}
  @keyframes flicker {{ 0%,100% {{ transform: scale(1); }} 50% {{ transform: scale(1.18) rotate(-4deg); }} }}
"""
    return card(w, h, body, css)


def render_stats(data):
    total = sum(data["days"].values())
    items = [
        ("CONTRIBUTIONS", total, CYAN, "⚡"),
        ("COMMITS", data["commits"], VIOLET, "📝"),
        ("PULL REQUESTS", data["prs"], PINK, "🔀"),
        ("PUBLIC REPOS", data["repos"], GREEN, "📦"),
        ("STARS EARNED", data["stars"], AMBER, "⭐"),
        ("FOLLOWERS", data["followers"], CYAN, "👥"),
    ]
    w, h = 495, 230
    cells = []
    for i, (label, value, color, icon) in enumerate(items):
        cx = 24 + (i % 2) * 230
        cy = 58 + (i // 2) * 56
        cells.append(f"""<g class="fade" {delay(i)}>
  <rect x="{cx}" y="{cy}" width="216" height="46" rx="10" fill="#ffffff" fill-opacity=".03" stroke="{color}" stroke-opacity=".25"/>
  <text x="{cx + 14}" y="{cy + 29}" font-size="17" fill="{TEXT}">{icon}</text>
  <text x="{cx + 44}" y="{cy + 20}" class="label" font-size="10">{label}</text>
  <text x="{cx + 44}" y="{cy + 38}" class="mono" font-size="17" font-weight="800" fill="{color}">{fmt(value)}</text>
</g>""")
    body = '<text x="24" y="36" class="title">📊 GITHUB STATS</text>\n' + "\n".join(cells)
    return card(w, h, body)


def render_langs(data):
    langs = sorted(data["langs"].items(), key=lambda kv: -kv[1]["size"])[:8]
    total = sum(v["size"] for _, v in langs) or 1
    w, h = 495, 230
    bar_x, bar_w = 24, w - 48

    segs, x = [], bar_x
    for name, v in langs:
        seg = bar_w * v["size"] / total
        segs.append(f'<rect x="{x:.1f}" y="56" width="{max(seg, 0.1):.1f}" height="10" fill="{v["color"]}"/>')
        x += seg

    legend = []
    for i, (name, v) in enumerate(langs):
        lx = 30 + (i % 2) * 225
        ly = 98 + (i // 2) * 30
        pct = 100 * v["size"] / total
        legend.append(f"""<g class="fade" {delay(i, base=.4)}>
  <circle cx="{lx}" cy="{ly - 4}" r="5" fill="{v['color']}"/>
  <text x="{lx + 14}" y="{ly}" font-size="13" fill="{TEXT}">{escape(name)}</text>
  <text x="{lx + 195}" y="{ly}" text-anchor="end" class="mono muted" font-size="12">{pct:.1f}%</text>
</g>""")

    body = f"""<text x="24" y="36" class="title">💻 MOST USED LANGUAGES</text>
<clipPath id="bar"><rect x="{bar_x}" y="56" width="{bar_w}" height="10" rx="5"/></clipPath>
<g clip-path="url(#bar)"><rect x="{bar_x}" y="56" width="{bar_w}" height="10" fill="{FAINT}"/><g class="grow">{''.join(segs)}</g></g>
{chr(10).join(legend)}"""
    css = """
  .grow { transform-origin: 24px 0; animation: grow 1.2s .2s cubic-bezier(.3,.7,.3,1) backwards; }
  @keyframes grow { from { transform: scaleX(0); } }
"""
    return card(w, h, body, css)


def render_activity(data, span=30):
    today = dt.date.fromisoformat(data["today"])
    dates = [(today - dt.timedelta(days=span - 1 - i)) for i in range(span)]
    counts = [data["days"].get(d.isoformat(), 0) for d in dates]
    w, h = 1000, 290
    left, right, top, bottom = 56, 28, 70, 240
    peak = max(counts) or 1
    nice = max(4, math.ceil(peak / 4) * 4)
    step_x = (w - left - right) / (span - 1)

    pts = [(left + i * step_x, bottom - (bottom - top) * c / nice) for i, c in enumerate(counts)]
    line = f"M{pts[0][0]:.1f},{pts[0][1]:.1f}"
    for (x0, y0), (x1, y1) in zip(pts, pts[1:]):
        mx = (x0 + x1) / 2
        line += f" C{mx:.1f},{y0:.1f} {mx:.1f},{y1:.1f} {x1:.1f},{y1:.1f}"
    area = f"{line} L{pts[-1][0]:.1f},{bottom} L{pts[0][0]:.1f},{bottom} Z"

    grid = []
    for i in range(5):
        y = bottom - (bottom - top) * i / 4
        grid.append(f'<line x1="{left}" y1="{y:.1f}" x2="{w - right}" y2="{y:.1f}" stroke="{FAINT}" stroke-dasharray="3 5"/>')
        grid.append(f'<text x="{left - 12}" y="{y + 4:.1f}" text-anchor="end" class="mono muted" font-size="11">{nice * i // 4}</text>')
    for i, d in enumerate(dates):
        if i % 5 == 0 or i == span - 1:
            grid.append(f'<text x="{left + i * step_x:.1f}" y="{bottom + 22}" text-anchor="middle" class="muted" font-size="11">{d.strftime("%b %-d")}</text>')

    dots = "".join(
        f'<circle cx="{x:.1f}" cy="{y:.1f}" r="{4 if c else 2.5}" fill="{BG_A}" stroke="{CYAN if c else FAINT}" stroke-width="2" class="fade" {delay(i, .04, .9)}/>'
        for i, ((x, y), c) in enumerate(zip(pts, counts))
    )
    month_total = sum(counts)
    best_i = max(range(span), key=lambda i: counts[i])

    defs = f"""<linearGradient id="area" x1="0" y1="0" x2="0" y2="1">
    <stop offset="0" stop-color="{VIOLET}" stop-opacity=".45"/><stop offset="1" stop-color="{VIOLET}" stop-opacity="0"/>
  </linearGradient>"""
    body = f"""<text x="28" y="36" class="title">📈 CONTRIBUTION ACTIVITY · LAST {span} DAYS</text>
<text x="{w - 28}" y="36" text-anchor="end" font-size="13" class="muted"><tspan class="mono" font-weight="800" fill="{CYAN}">{fmt(month_total)}</tspan> contributions · best day <tspan class="mono" font-weight="800" fill="{PINK}">{counts[best_i]}</tspan></text>
{''.join(grid)}
<path d="{area}" fill="url(#area)" class="fade" style="animation-delay:.8s;animation-duration:1.2s"/>
<path d="{line}" stroke="url(#accent)" stroke-width="3" stroke-linecap="round" pathLength="1" class="draw"/>
{dots}"""
    css = """
  .draw { stroke-dasharray: 1; animation: draw 1.8s .2s ease-in-out backwards; }
  @keyframes draw { from { stroke-dashoffset: 1; } }
"""
    return card(w, h, body, css, defs)


def wrap(text, width, lines=2):
    out, cur = [], ""
    for word in text.split():
        if cur and len(cur) + 1 + len(word) > width:
            out.append(cur)
            cur = word
        else:
            cur = f"{cur} {word}".strip()
    out.append(cur)
    if len(out) > lines:
        out = out[:lines]
        out[-1] = out[-1][: width - 1].rstrip(" ,.") + "…"
    return out


REPO_ICON = (
    "M2 2.5A2.5 2.5 0 0 1 4.5 0h8.75a.75.75 0 0 1 .75.75v12.5a.75.75 0 0 1-.75.75h-2.5a.75.75 0 0 1 0-1.5"
    "h1.75v-2h-8a1 1 0 0 0-.714 1.7.75.75 0 1 1-1.072 1.05A2.495 2.495 0 0 1 2 11.5Zm10.5-1h-8a1 1 0 0 0-1 1"
    "v6.708A2.486 2.486 0 0 1 4.5 9h8ZM5 12.25a.25.25 0 0 1 .25-.25h3.5a.25.25 0 0 1 .25.25v3.25a.25.25 0 0 1"
    "-.4.2l-1.45-1.087a.25.25 0 0 0-.3 0L5.4 15.7a.25.25 0 0 1-.4-.2Z"
)


def render_project(repo):
    w, h = 495, 150
    desc = repo.get("description") or "A project by Muhammad Aman — open the repo to explore the code."
    lines = wrap(desc, 62)
    lang = repo.get("primaryLanguage") or {"name": "Code", "color": MUTED}
    desc_svg = "".join(
        f'<text x="24" y="{78 + i * 20}" font-size="13" class="muted fade" {delay(i + 1)}>{escape(t)}</text>'
        for i, t in enumerate(lines)
    )
    body = f"""<g transform="translate(24 24) scale(1.15)"><path d="{REPO_ICON}" fill="{CYAN}"/></g>
<text x="52" y="40" font-size="17" font-weight="700" fill="{TEXT}" class="fade">{escape(repo["name"])}</text>
<text x="{w - 24}" y="40" text-anchor="end" font-size="16" fill="url(#accent)">↗</text>
{desc_svg}
<g class="fade" {delay(3)}>
  <circle cx="30" cy="126" r="6" fill="{lang["color"] or MUTED}"/>
  <text x="44" y="131" font-size="13" fill="{TEXT}">{escape(lang["name"])}</text>
  <text x="{w - 24}" y="131" text-anchor="end" font-size="13" class="mono muted">★ {repo["stargazerCount"]}   ⑂ {repo["forkCount"]}</text>
</g>"""
    return card(w, h, body)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", default="dist")
    parser.add_argument("--mock", help="JSON file with pre-fetched data (offline preview)")
    args = parser.parse_args()

    data = json.loads(Path(args.mock).read_text()) if args.mock else fetch()
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)

    files = {
        "streak.svg": render_streak(data),
        "stats.svg": render_stats(data),
        "languages.svg": render_langs(data),
        "activity.svg": render_activity(data),
    }
    for repo in data["projects"]:
        files[f"project-{repo['name']}.svg"] = render_project(repo)
    for name, svg in files.items():
        (out / name).write_text(svg, encoding="utf-8")
        print(f"wrote {out / name}")


if __name__ == "__main__":
    main()
