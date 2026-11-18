#!/usr/bin/env python3
"""Generate GitHub stats cards that include private repositories.

Public stats services can only see public repos. This script uses a personal
access token (env GH_TOKEN) to read your own private repos too, and writes
aggregate numbers only (no private repo names) to assets/*.svg.
"""
import datetime as dt
import json
import os
import pathlib
import urllib.request
from html import escape

TOKEN = os.environ["GH_TOKEN"]
OUT = pathlib.Path(__file__).resolve().parent.parent / "assets"
EXCLUDE_LANGS = {"HTML", "CSS", "Shell", "Blade", "CMake", "C++", "C", "Swift", "Objective-C", "Ruby", "Makefile", "Batchfile"}
# Flutter projects ship generated iOS/Android/desktop runner code (C++, Swift, CMake...).
# Excluding it keeps the chart focused on code you actually wrote.

BG, BORDER, TITLE, TEXT, MUTED, ACCENT = "#0d1117", "#30363d", "#58a6ff", "#e6edf3", "#8b949e", "#00b4ab"
FONT = "font-family:'Segoe UI',Ubuntu,'Helvetica Neue',Sans-Serif"


def gql(query, **variables):
    req = urllib.request.Request(
        "https://api.github.com/graphql",
        data=json.dumps({"query": query, "variables": variables}).encode(),
        headers={"Authorization": f"bearer {TOKEN}", "Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=60) as r:
        body = json.load(r)
    if "errors" in body:
        raise SystemExit(f"GraphQL error: {body['errors']}")
    return body["data"]


def fetch():
    user = gql("{ viewer { login name createdAt followers { totalCount } } }")["viewer"]

    repos, cursor = [], None
    while True:
        page = gql(
            """query($cursor: String) { viewer { repositories(first: 100, after: $cursor,
                 ownerAffiliations: OWNER, isFork: false) {
               pageInfo { hasNextPage endCursor }
               nodes { isPrivate stargazerCount
                 languages(first: 20, orderBy: {field: SIZE, direction: DESC}) {
                   edges { size node { name color } } } } } } }""",
            cursor=cursor,
        )["viewer"]["repositories"]
        repos += page["nodes"]
        if not page["pageInfo"]["hasNextPage"]:
            break
        cursor = page["pageInfo"]["endCursor"]

    # Contribution totals, one year window at a time (API limit), since account creation.
    now = dt.datetime.now(dt.timezone.utc)
    start = dt.datetime.fromisoformat(user["createdAt"].replace("Z", "+00:00"))
    total, last_year, start_iter = 0, 0, start
    while start_iter < now:
        end = min(start_iter + dt.timedelta(days=365), now)
        cc = gql(
            """query($from: DateTime!, $to: DateTime!) { viewer {
                 contributionsCollection(from: $from, to: $to) {
                   contributionCalendar { totalContributions } } } }""",
            **{"from": start_iter.isoformat(), "to": end.isoformat()},
        )["viewer"]["contributionsCollection"]["contributionCalendar"]["totalContributions"]
        total += cc
        start_iter = end
    last_year = gql(
        "{ viewer { contributionsCollection { contributionCalendar { totalContributions } } } }"
    )["viewer"]["contributionsCollection"]["contributionCalendar"]["totalContributions"]

    langs = {}
    for repo in repos:
        for e in repo["languages"]["edges"]:
            name = e["node"]["name"]
            if name in EXCLUDE_LANGS:
                continue
            size, color = langs.get(name, (0, e["node"]["color"] or MUTED))
            langs[name] = (size + e["size"], color)

    all_bytes = sum(size for size, _ in langs.values()) or 1
    top = sorted(langs.items(), key=lambda kv: -kv[1][0])
    top = [kv for kv in top if kv[1][0] / all_bytes >= 0.001][:6]  # drop languages under 0.1%

    return {
        "name": user["name"] or user["login"],
        "years": round((now - start).days / 365.25, 1),
        "total": total,
        "last_year": last_year,
        "repos": len(repos),
        "private": sum(r["isPrivate"] for r in repos),
        "stars": sum(r["stargazerCount"] for r in repos),
        "langs": top,
    }


def card(w, h, title, body):
    return f"""<svg xmlns="http://www.w3.org/2000/svg" width="{w}" height="{h}" viewBox="0 0 {w} {h}" role="img" aria-label="{escape(title)}">
<style>
  .t {{ {FONT}; font-size: 18px; font-weight: 600; fill: {TITLE}; }}
  .l {{ {FONT}; font-size: 14px; fill: {MUTED}; }}
  .v {{ {FONT}; font-size: 14px; font-weight: 700; fill: {TEXT}; }}
  .big {{ {FONT}; font-size: 30px; font-weight: 700; fill: {TEXT}; }}
  .fade {{ opacity: 0; animation: in .6s ease-out forwards; }}
  @keyframes in {{ to {{ opacity: 1; }} }}
  @keyframes grow {{ from {{ width: 0; }} }}
</style>
<rect x="0.5" y="0.5" width="{w - 1}" height="{h - 1}" rx="10" fill="{BG}" stroke="{BORDER}"/>
<text x="25" y="38" class="t">{escape(title)}</text>
{body}
</svg>
"""


def stats_svg(s):
    rows = [
        ("Total contributions", f"{s['total']:,}"),
        ("Contributions (last 12 months)", f"{s['last_year']:,}"),
        ("Repositories", f"{s['repos']}  ({s['private']} private)"),
        ("Years on GitHub", f"{s['years']}"),
    ]
    body = []
    for i, (label, value) in enumerate(rows):
        y = 78 + i * 30
        body.append(
            f'<g class="fade" style="animation-delay:{150 * i}ms">'
            f'<circle cx="31" cy="{y - 5}" r="4" fill="{ACCENT}"/>'
            f'<text x="45" y="{y}" class="l">{escape(label)}</text>'
            f'<text x="430" y="{y}" class="v" text-anchor="end">{escape(value)}</text></g>'
        )
    return card(455, 205, "GitHub Activity · public + private", "\n".join(body))


def langs_svg(s):
    total = sum(size for _, (size, _) in s["langs"]) or 1
    width, x = 405, 25
    bar = [f'<clipPath id="r"><rect x="25" y="58" width="{width}" height="10" rx="5"/></clipPath><g clip-path="url(#r)">']
    for name, (size, color) in s["langs"]:
        w = width * size / total
        bar.append(f'<rect x="{x:.1f}" y="58" width="{w + 0.5:.1f}" height="10" fill="{color}" style="animation:grow .8s ease-out"/>')
        x += w
    bar.append("</g>")
    items = []
    for i, (name, (size, color)) in enumerate(s["langs"]):
        col, row = i % 2, i // 2
        ix, iy = 25 + col * 210, 100 + row * 30
        items.append(
            f'<g class="fade" style="animation-delay:{120 * i}ms">'
            f'<circle cx="{ix + 6}" cy="{iy - 5}" r="6" fill="{color}"/>'
            f'<text x="{ix + 20}" y="{iy}" class="v">{escape(name)}</text>'
            f'<text x="{ix + 190}" y="{iy}" class="l" text-anchor="end">{100 * size / total:.1f}%</text></g>'
        )
    return card(455, 205, "Most Used Languages", "\n".join(bar + items))


def main():
    s = fetch()
    OUT.mkdir(exist_ok=True)
    (OUT / "stats.svg").write_text(stats_svg(s))
    (OUT / "languages.svg").write_text(langs_svg(s))
    print(json.dumps({k: v for k, v in s.items() if k != "langs"}), [n for n, _ in s["langs"]])


if __name__ == "__main__":
    main()
