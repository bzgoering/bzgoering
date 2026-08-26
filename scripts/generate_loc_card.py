#!/usr/bin/env python3
"""
Builds a "real LOC per language" card, computed by scanning actual file
contents with tokei across every repo you own — not GitHub's per-repo
"primary language" label.

Env vars:
    GH_USERNAME   - github username to scan (defaults to repo owner)
    GH_TOKEN      - token used for the GitHub API + cloning private repos
    EXCLUDE_REPOS - comma-separated repo names to skip (optional)
    EXCLUDE_LANGS - comma-separated language names to skip (optional)
    MAX_REPOS     - cap on number of repos scanned (default 200)
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile
from collections import defaultdict

import requests

USERNAME = os.environ["GH_USERNAME"]
TOKEN = os.environ.get("GH_TOKEN", "")
EXCLUDE_REPOS = {r.strip() for r in os.environ.get("EXCLUDE_REPOS", "").split(",") if r.strip()}
EXCLUDE_LANGS = {l.strip().lower() for l in os.environ.get("EXCLUDE_LANGS", "").split(",") if l.strip()}
MAX_REPOS = int(os.environ.get("MAX_REPOS", "200"))

API = "https://api.github.com"
HEADERS = {"Accept": "application/vnd.github+json"}
if TOKEN:
    HEADERS["Authorization"] = f"Bearer {TOKEN}"

# Languages tokei counts that are noise for a "what language do you write" card
NOISE_LANGS = {
    "json", "yaml", "toml", "markdown", "text", "svg", "html", "xml",
    "plain text", "batch", "ini", "gitignore", "dockerfile", "lock",
    "jupyter config", "properties",
}


def list_repos(username: str):
    repos = []
    page = 1
    while True:
        resp = requests.get(
            f"{API}/users/{username}/repos",
            headers=HEADERS,
            params={"per_page": 100, "page": page, "type": "owner"},
            timeout=30,
        )
        resp.raise_for_status()
        batch = resp.json()
        if not batch:
            break
        repos.extend(batch)
        page += 1
        if len(repos) >= MAX_REPOS:
            break
    return repos[:MAX_REPOS]


def clone_repo(clone_url: str, dest: str, token: str) -> bool:
    if token:
        clone_url = clone_url.replace("https://", f"https://x-access-token:{token}@")
    result = subprocess.run(
        ["git", "clone", "--depth", "1", "--single-branch", clone_url, dest],
        capture_output=True, text=True,
    )
    return result.returncode == 0


def tokei_counts(path: str):
    result = subprocess.run(
        ["tokei", path, "--output", "json"],
        capture_output=True, text=True,
    )
    if result.returncode != 0:
        return {}
    try:
        data = json.loads(result.stdout)
    except json.JSONDecodeError:
        return {}
    counts = {}
    for lang, stats in data.items():
        if lang == "Total":
            continue
        code = stats.get("code", 0)
        if code > 0:
            counts[lang] = code
    return counts


def aggregate(username: str):
    totals = defaultdict(int)
    repos = list_repos(username)
    for repo in repos:
        name = repo["name"]
        if name in EXCLUDE_REPOS or repo.get("fork"):
            continue
        with tempfile.TemporaryDirectory() as tmp:
            dest = os.path.join(tmp, name)
            ok = clone_repo(repo["clone_url"], dest, TOKEN)
            if not ok:
                print(f"skip {name}: clone failed", file=sys.stderr)
                continue
            counts = tokei_counts(dest)
            for lang, code in counts.items():
                if lang.lower() in NOISE_LANGS or lang.lower() in EXCLUDE_LANGS:
                    continue
                totals[lang] += code
    return totals


# --- SVG rendering: "radical" theme palette ---------------------------------

RADICAL_BG = "#141321"
RADICAL_TITLE = "#fe428e"
RADICAL_TEXT = "#a9fef7"
RADICAL_BAR_BG = "#2b2b3d"
PALETTE = [
    "#fe428e", "#a9fef7", "#f8d847", "#00d4ff", "#ff8906",
    "#7cfc00", "#c792ea", "#ff6961", "#4ecdc4", "#ffb347",
]

CARD_WIDTH = 400
ROW_HEIGHT = 30
TOP_N = 8


def render_svg(totals: dict, out_path: str, username: str):
    ranked = sorted(totals.items(), key=lambda kv: kv[1], reverse=True)[:TOP_N]
    total_lines = sum(v for _, v in ranked) or 1
    height = 60 + ROW_HEIGHT * len(ranked) + 20

    rows = []
    for i, (lang, lines) in enumerate(ranked):
        pct = lines / total_lines * 100
        y = 60 + i * ROW_HEIGHT
        bar_max_w = CARD_WIDTH - 40 - 90
        bar_w = max(2, bar_max_w * pct / 100)
        color = PALETTE[i % len(PALETTE)]
        rows.append(f'''
        <text x="20" y="{y + 14}" fill="{RADICAL_TEXT}" font-size="12" font-family="'Segoe UI', Ubuntu, sans-serif">{lang}</text>
        <rect x="20" y="{y + 18}" width="{bar_max_w}" height="6" rx="3" fill="{RADICAL_BAR_BG}"/>
        <rect x="20" y="{y + 18}" width="{bar_w:.1f}" height="6" rx="3" fill="{color}"/>
        <text x="{CARD_WIDTH - 20}" y="{y + 14}" fill="{RADICAL_TEXT}" font-size="12" text-anchor="end" font-family="'Segoe UI', Ubuntu, sans-serif">{pct:.1f}%</text>
        ''')

    svg = f'''<svg xmlns="http://www.w3.org/2000/svg" width="{CARD_WIDTH}" height="{height}" viewBox="0 0 {CARD_WIDTH} {height}">
  <rect x="0" y="0" width="{CARD_WIDTH}" height="{height}" rx="10" fill="{RADICAL_BG}" stroke="#30294f"/>
  <text x="20" y="30" fill="{RADICAL_TITLE}" font-size="16" font-weight="bold" font-family="'Segoe UI', Ubuntu, sans-serif">Top Languages by Lines of Code</text>
  {''.join(rows)}
</svg>'''

    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    with open(out_path, "w") as f:
        f.write(svg)


def main():
    totals = aggregate(USERNAME)
    if not totals:
        print("no language data collected", file=sys.stderr)
    render_svg(totals, "profile-summary-card-output/lang-loc-card.svg", USERNAME)
    print(json.dumps(totals, indent=2))


if __name__ == "__main__":
    main()
