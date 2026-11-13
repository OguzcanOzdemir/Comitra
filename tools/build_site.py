"""Generate the GitHub Pages site (site/index.html, sitemap, robots, manifest).

Run after editing:  python tools/build_site.py
"""

from __future__ import annotations

import json
import os
import sys
from datetime import date
from html import escape

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from comitra import __version__  # noqa: E402

SITE = os.path.join(ROOT, "site")
BASE = "https://oguzcanozdemir.github.io/Comitra/"
REPO = "https://github.com/OguzcanOzdemir/Comitra"
LATEST = REPO + "/releases/latest"

ICONS = {
    "search": '<path d="M11 4a7 7 0 1 0 0 14 7 7 0 0 0 0-14Zm9 16-4.3-4.3" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"/>',
    "branch": '<g fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><circle cx="6" cy="5" r="2"/><circle cx="6" cy="19" r="2"/><circle cx="18" cy="7" r="2"/><path d="M6 7v10M18 9c0 5-12 3-12 8"/></g>',
    "filter": '<path d="M4 5h16l-6 8v5l-4 2v-7L4 5Z" fill="none" stroke="currentColor" stroke-width="2" stroke-linejoin="round"/>',
    "bolt": '<path d="M13 2 4 14h7l-1 8 9-12h-7l1-8Z" fill="none" stroke="currentColor" stroke-width="2" stroke-linejoin="round"/>',
    "lock": '<g fill="none" stroke="currentColor" stroke-width="2"><rect x="5" y="11" width="14" height="10" rx="2"/><path d="M8 11V8a4 4 0 0 1 8 0v3"/></g>',
    "refresh": '<path d="M20 11a8 8 0 0 0-14.9-3M4 5v4h4M4 13a8 8 0 0 0 14.9 3M20 19v-4h-4" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/>',
    "diff": '<g fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><rect x="4" y="3" width="16" height="18" rx="2"/><path d="M9 9h6M12 6v6M9 16h6"/></g>',
    "usb": '<g fill="none" stroke="currentColor" stroke-width="2" stroke-linejoin="round"><rect x="7" y="9" width="10" height="12" rx="2"/><path d="M9 9V3h6v6M10 5.5h.01M14 5.5h.01"/></g>',
    "terminal": '<g fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="3" y="4" width="18" height="16" rx="2"/><path d="m7 9 3 3-3 3M13 15h4"/></g>',
    "download": '<path d="M12 3v12m0 0-5-5m5 5 5-5M5 21h14" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/>',
    "github": '<path fill="currentColor" d="M12 2a10 10 0 0 0-3.2 19.5c.5.1.7-.2.7-.5v-1.7c-2.8.6-3.4-1.2-3.4-1.2-.5-1.2-1.1-1.5-1.1-1.5-.9-.6.1-.6.1-.6 1 .1 1.5 1 1.5 1 .9 1.5 2.3 1.1 2.9.8.1-.6.4-1.1.6-1.3-2.2-.3-4.6-1.1-4.6-5 0-1.1.4-2 1-2.7-.1-.3-.4-1.3.1-2.7 0 0 .8-.3 2.7 1a9.4 9.4 0 0 1 5 0c1.9-1.3 2.7-1 2.7-1 .5 1.4.2 2.4.1 2.7.6.7 1 1.6 1 2.7 0 3.9-2.4 4.7-4.6 5 .4.3.7.9.7 1.9v2.8c0 .3.2.6.7.5A10 10 0 0 0 12 2Z"/>',
    "windows": '<path fill="currentColor" d="M3 5.5 10.5 4.4v7.1H3V5.5Zm8.5-1.2L21 3v8.5h-9.5V4.3ZM3 12.5h7.5v7.1L3 18.5v-6Zm8.5 0H21V21l-9.5-1.3v-7.2Z"/>',
    "apple": '<path fill="currentColor" d="M16.4 12.6c0-2.4 2-3.6 2.1-3.6-1.1-1.7-2.9-1.9-3.5-1.9-1.5-.2-2.9.9-3.7.9-.8 0-1.9-.9-3.2-.8-1.6 0-3.1 1-4 2.4-1.7 3-.4 7.4 1.2 9.8.8 1.2 1.8 2.5 3 2.4 1.2 0 1.7-.8 3.1-.8 1.5 0 1.9.8 3.2.8 1.3 0 2.2-1.2 3-2.4.9-1.4 1.3-2.7 1.3-2.8 0 0-2.5-1-2.5-4ZM14 5.5c.7-.8 1.1-1.9 1-3-1 0-2.1.7-2.8 1.5-.6.7-1.2 1.8-1 2.9 1.1.1 2.1-.6 2.8-1.4Z"/>',
    "linux": '<path fill="currentColor" d="M12 2c-2.2 0-3.6 1.9-3.6 4.6 0 1.4.3 2.3-.5 3.6C6.6 12.3 5 14 5 16.3c0 .9.3 1.6.7 2.1-.5.3-.9.8-.7 1.4.3.9 1.6.9 2.6 1.3 1 .4 1.8 1.1 2.7.8.6-.2.8-.7.8-1.2h1.8c0 .5.2 1 .8 1.2.9.3 1.7-.4 2.7-.8 1-.4 2.3-.4 2.6-1.3.2-.6-.2-1.1-.7-1.4.4-.5.7-1.2.7-2.1 0-2.3-1.6-4-2.9-6.1-.8-1.3-.5-2.2-.5-3.6C15.6 3.9 14.2 2 12 2Zm-1.5 4.2c.4 0 .7.5.7 1.1s-.3 1.1-.7 1.1-.7-.5-.7-1.1.3-1.1.7-1.1Zm3 0c.4 0 .7.5.7 1.1s-.3 1.1-.7 1.1-.7-.5-.7-1.1.3-1.1.7-1.1ZM12 9.3c.9 0 2 .6 2 1 0 .5-1.2 1.2-2 1.2s-2-.7-2-1.2c0-.4 1.1-1 2-1Z"/>',
}


def icon(name: str) -> str:
    return f'<svg viewBox="0 0 24 24" aria-hidden="true">{ICONS[name]}</svg>'


T = {
    "en": {
        "path": "index.html",
        "url": BASE,
        "locale": "en_US",
        "title": "Comitra – Search Git Commits Across All Your Repositories (Free, Windows · macOS · Linux)",
        "desc": "Comitra is a free, open-source, offline desktop app that finds every git repository on your computer and searches commits on all branches by message, author, date, branch and hash in milliseconds.",
        "keywords": "git commit search, search git commits across repositories, git log search tool, find commit across branches, search all git repos, git history search, desktop git tool, offline git search, free git tool",
        "nav": ["Features", "How it works", "Query language", "Download", "FAQ"],
        "badge": "Free and open source · v{v}",
        "h1": "Search commits across <em>all your git repos</em>",
        "lead": "Comitra finds every git repository on your computer, indexes the commits on all branches and lets you find them by message, author, date, branch or hash in milliseconds. No internet needed, your data never leaves your machine.",
        "cta_dl": "Download",
        "cta_gh": "View on GitHub",
        "note": "Windows 10/11 · macOS 11+ · Linux · Requires git",
        "alt_shot": "Comitra search screen with highlighted results, the filter panel and commit details",
        "stats": [("4.6 s", "to index 100,000 commits"), ("~30 ms", "full-text search"), ("0 bytes", "of data sent anywhere"), ("3", "operating systems")],
        "feat_h": "Stop wondering which repo that commit was in",
        "feat_p": "Find the commit that got lost among dozens of repos and hundreds of branches, from a single search box.",
        "features": [
            ("search", "Smart full-text search", "Case- and accent-insensitive, Unicode aware. Exact phrases, prefixes (<code>login*</code>) and exclusions (<code>-wip</code>)."),
            ("branch", "Every repo, every branch", "Discovers all repositories in your folders automatically. Indexes local and remote branches, tags, submodules and bare repos."),
            ("filter", "Powerful filters", "Author and co-author, date ranges and presets, repository, branch (<code>feature/*</code>), hash, changed file, merge commits, time of day and weekday."),
            ("bolt", "Results in milliseconds", "A local SQLite FTS5 index. Smooth scrolling through millions of results, match highlighting and grouping by repo, author or day."),
            ("refresh", "Smart incremental updates", "Only changed repositories are rescanned. Old-dated commits arriving via fetch are never missed. Commits lost to force-pushes are flagged, not deleted."),
            ("diff", "Commit details and diff", "Full message, both dates, co-authors, branches containing the commit, changed files and a colored diff in one place."),
            ("terminal", "Open with one click", "Open the repository in your file manager, terminal or editor (VS Code and others). Copy the hash with one keystroke."),
            ("lock", "Fully offline and private", "No telemetry, no account, no cloud. The index lives only on your computer. Nothing touches the network except an optional <code>git fetch</code>."),
            ("usb", "Installed or portable", "The Windows installer needs no admin rights. The portable edition keeps its data in its own folder, so you can carry it on a USB stick."),
        ],
        "how_h": "Get started in three steps",
        "how_p": "Installation and the first index usually take less than a minute.",
        "steps": [
            ("Download and open", "Download the package for your operating system. All you need is git installed."),
            ("Add a folder", "Pick the folder that holds your projects (e.g. <code>~/projects</code>). Comitra finds and indexes every repository inside."),
            ("Search", "Start typing. Results appear as you type. Narrow them down with the filter panel or the query language."),
        ],
        "query_h": "Do everything from the search box",
        "query_p": "Click filters in the panel or type them. Both stay in sync instantly.",
        "query_points": [
            ("Date presets", "today, yesterday, last 7 days, last 30 days, this month, this year, a single day or a range"),
            ("Saved searches", "keep the filter combinations you use often and jump back to recent searches"),
            ("Export", "save results as CSV or JSON"),
            ("Keyboard first", "<kbd>Ctrl</kbd>/<kbd>⌘</kbd>+<kbd>K</kbd> to search, shortcuts for copying hashes and opening repos"),
            ("Command line", "the same queries work in the terminal with <code>comitra-cli search</code>"),
        ],
        "code": [
            ('<span class="c"># Alice\'s payment commits from the last 7 days, no WIP</span>', ""),
            ('<span class="k">author:</span>alice <span class="k">date:</span>7d payment <span class="s">-wip</span>', ""),
            ("", ""),
            ('<span class="c"># On feature branches, exact phrase</span>', ""),
            ('<span class="k">branch:</span>feature/* <span class="s">"payment error"</span>', ""),
            ("", ""),
            ('<span class="c"># Friday evening, no merge commits</span>', ""),
            ('<span class="k">day:</span>fri <span class="k">hour:</span>18-23 <span class="k">merge:</span>hide', ""),
            ("", ""),
            ('<span class="c"># Commits touching a folder in October</span>', ""),
            ('<span class="k">file:</span>src/auth/ <span class="k">date:</span>2026-10', ""),
            ("", ""),
            ('<span class="c"># Jump straight to a short hash</span>', ""),
            ('a1b2c3d', ""),
        ],
        "dl_h": "Download Comitra",
        "dl_p": "It's free. Choose the installer or the portable edition that runs without installing anything.",
        "recommended": "Recommended",
        "installer": "Installer",
        "portable": "Portable",
        "dl": {
            "windows": ("Windows", "Windows 10 / 11, 64-bit", "Installer (.exe)", "Portable (.zip)"),
            "macos": ("macOS", "macOS 11+, Apple Silicon and Intel", "Apple Silicon (.dmg)", "Intel (.dmg)", "Portable (.zip)"),
            "linux": ("Linux", "x86_64; Ubuntu 22.04+, Fedora, Debian, Arch…", "AppImage", "Portable (.tar.gz)"),
        },
        "release_tpl": "Latest release: {v} · {d}",
        "release_default": "All releases and release notes are on GitHub.",
        "all_releases": "All releases",
        "callout": "<b>Seeing a warning on first launch?</b> The packages are not code-signed yet. On Windows click <i>More info → Run anyway</i> in SmartScreen; on macOS right-click the app and choose <i>Open</i>. On Linux make the AppImage executable: <code>chmod +x Comitra-*.AppImage</code>. Comitra needs <a href=\"https://git-scm.com/downloads\" rel=\"noopener\">git</a> to be installed.",
        "faq_h": "Frequently asked questions",
        "faq": [
            ("Is Comitra free?", "Yes. Comitra is MIT-licensed, open source and completely free. No account or sign-up needed."),
            ("Is my code or commit history sent anywhere?", "No. Comitra works fully offline and has no telemetry. The index is a SQLite file on your computer. If you enable it, it only runs <code>git fetch</code> against your own git servers."),
            ("Which operating systems are supported?", "Windows 10/11 (64-bit), macOS 11 or later (Apple Silicon and Intel) and x86_64 Linux distributions. Every platform has an installer and a portable package."),
            ("How many repositories and commits can it handle?", "Hundreds of repositories and millions of commits are fine. A 100,000-commit repository is indexed in about 5 seconds and searches take milliseconds. Later updates only rescan repositories that changed."),
            ("Does it find commits on remote branches?", "Yes. All local and remote-tracking branches on your computer are indexed. Turn on \"Run git fetch before updating\" in settings to pick up your teammates' new commits."),
            ("What happens after a force-push or rebase?", "Commits that are no longer reachable from any branch are flagged instead of deleted. They are hidden by default; show them with the <code>unreachable:include</code> filter."),
            ("What is the portable edition?", "The portable edition needs no installation and keeps its settings and index in a <code>comitra-data</code> folder next to the program. Copy the folder to a USB stick and use it on another computer."),
            ("Do I need a GitHub, GitLab or Bitbucket account?", "No. Comitra only reads git folders on your computer. It doesn't matter where your repositories are hosted, or whether they are hosted at all."),
        ],
        "footer": "Comitra – MIT-licensed, open-source git commit search tool.",
        "f_links": [("GitHub", REPO), ("Releases", REPO + "/releases"), ("Report a bug", REPO + "/issues"), ("Design document", REPO + "/blob/HEAD/docs/DESIGN.md")],
    },
}


def asset_btn(asset: str, label: str, primary: bool = False) -> str:
    cls = "btn btn-primary" if primary else "btn btn-ghost"
    return (f'<a class="{cls}" href="{LATEST}" data-asset="{asset}" rel="nofollow">{icon("download")}'
            f"<span>{label}</span> <small></small></a>")


def page(lang: str) -> str:
    t = T[lang]
    prefix = ""
    a = "assets/"
    anchors = ["features", "how", "query", "download", "faq"]
    nav = "".join(f'<li><a href="#{anchors[i]}">{n}</a></li>' for i, n in enumerate(t["nav"]))
    stats = "".join(f'<div class="stat"><b>{v}</b><span>{l}</span></div>' for v, l in t["stats"])
    feats = "".join(f'<article class="card"><div class="ico">{icon(i)}</div><h3>{h}</h3><p>{p}</p></article>'
                    for i, h, p in t["features"])
    steps = "".join(f'<article class="card step"><h3>{h}</h3><p>{p}</p></article>' for h, p in t["steps"])
    qpoints = "".join(f"<li><b>{h}:</b> {p}</li>" for h, p in t["query_points"])
    code = "\n".join(l for l, _ in t["code"])
    d = t["dl"]
    dl = (
        f'<article class="card dl" id="dl-windows"><h3>{icon("windows")}{d["windows"][0]}<span class="tag">{t["recommended"]}</span></h3>'
        f'<p class="req">{d["windows"][1]}</p>{asset_btn("windows-setup", d["windows"][2], True)}{asset_btn("windows-portable", d["windows"][3])}</article>'
        f'<article class="card dl" id="dl-macos"><h3>{icon("apple")}{d["macos"][0]}<span class="tag">{t["recommended"]}</span></h3>'
        f'<p class="req">{d["macos"][1]}</p>{asset_btn("macos-arm64", d["macos"][2], True)}{asset_btn("macos-x64", d["macos"][3])}{asset_btn("macos-portable", d["macos"][4])}</article>'
        f'<article class="card dl" id="dl-linux"><h3>{icon("linux")}{d["linux"][0]}<span class="tag">{t["recommended"]}</span></h3>'
        f'<p class="req">{d["linux"][1]}</p>{asset_btn("linux-appimage", d["linux"][2], True)}{asset_btn("linux-portable", d["linux"][3])}</article>'
    )
    faq = "".join(f"<details><summary>{q}</summary><p>{ans}</p></details>" for q, ans in t["faq"])
    flinks = "".join(f'<a href="{u}" rel="noopener">{n}</a>' for n, u in t["f_links"])

    def strip_tags(s: str) -> str:
        import re

        return re.sub(r"<[^>]+>", "", s)

    ld = [
        {
            "@context": "https://schema.org",
            "@type": "SoftwareApplication",
            "name": "Comitra",
            "alternateName": "Comitra Git Commit Search",
            "description": t["desc"],
            "applicationCategory": "DeveloperApplication",
            "applicationSubCategory": "Version control",
            "operatingSystem": "Windows 10, Windows 11, macOS 11+, Linux",
            "softwareVersion": __version__,
            "license": "https://opensource.org/licenses/MIT",
            "isAccessibleForFree": True,
            "offers": {"@type": "Offer", "price": "0", "priceCurrency": "USD"},
            "downloadUrl": LATEST,
            "installUrl": t["url"] + "#" + anchors[3],
            "url": t["url"],
            "image": BASE + "assets/icon-512.png",
            "screenshot": BASE + "assets/screenshot-light.png",
            "codeRepository": REPO,
            "inLanguage": "en",
            "softwareRequirements": "git",
            "featureList": [strip_tags(h) for _, h, _ in t["features"]],
        },
        {
            "@context": "https://schema.org",
            "@type": "FAQPage",
            "mainEntity": [
                {"@type": "Question", "name": q, "acceptedAnswer": {"@type": "Answer", "text": strip_tags(ans)}}
                for q, ans in t["faq"]
            ],
        },
        {"@context": "https://schema.org", "@type": "WebSite", "name": "Comitra", "url": BASE, "inLanguage": lang},
    ]
    ld_html = "".join(f'<script type="application/ld+json">{json.dumps(x, ensure_ascii=False)}</script>' for x in ld)
    hero_shot = (
        f'<picture><source srcset="{a}screenshot-dark.webp" media="(prefers-color-scheme: dark)" type="image/webp">'
        f'<source srcset="{a}screenshot-light.webp" type="image/webp">'
        f'<img src="{a}screenshot-light.png" width="1400" height="860" alt="{escape(t["alt_shot"])}" fetchpriority="high"></picture>'
    )
    return f"""<!doctype html>
<html lang="{lang}">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{escape(t["title"])}</title>
<meta name="description" content="{escape(t["desc"])}">
<meta name="keywords" content="{escape(t["keywords"])}">
<meta name="robots" content="index, follow, max-image-preview:large">
<meta name="theme-color" content="#2563eb">
<meta name="color-scheme" content="light dark">
<link rel="canonical" href="{t["url"]}">
<meta property="og:type" content="website">
<meta property="og:site_name" content="Comitra">
<meta property="og:title" content="{escape(t["title"])}">
<meta property="og:description" content="{escape(t["desc"])}">
<meta property="og:url" content="{t["url"]}">
<meta property="og:image" content="{BASE}assets/og-image.png">
<meta property="og:image:width" content="1200">
<meta property="og:image:height" content="630">
<meta property="og:locale" content="{t["locale"]}">
<meta name="twitter:card" content="summary_large_image">
<meta name="twitter:title" content="{escape(t["title"])}">
<meta name="twitter:description" content="{escape(t["desc"])}">
<meta name="twitter:image" content="{BASE}assets/og-image.png">
<link rel="icon" href="{a}favicon.ico" sizes="any">
<link rel="icon" type="image/png" sizes="32x32" href="{a}favicon-32.png">
<link rel="apple-touch-icon" href="{a}apple-touch-icon.png">
<link rel="manifest" href="{prefix}site.webmanifest">
<link rel="stylesheet" href="{prefix}style.css">
{ld_html}
</head>
<body>
<a class="skip" href="#main">Skip to content</a>
<header class="top"><div class="wrap nav">
<a class="brand" href="{t["url"]}"><img src="{a}icon-192.png" width="30" height="30" alt="">Comitra</a>
<ul>{nav}<li><a href="{REPO}" rel="noopener">GitHub</a></li></ul>
</div></header>
<main id="main">
<section class="hero"><div class="wrap">
<span class="badge">{t["badge"].format(v=__version__)}</span>
<h1>{t["h1"]}</h1>
<p class="lead">{t["lead"]}</p>
<div class="cta">
<a class="btn btn-primary" id="hero-download" href="#{anchors[3]}">{icon("download")}<span>{t["cta_dl"]}</span></a>
<a class="btn btn-ghost" href="{REPO}" rel="noopener">{icon("github")}<span>{t["cta_gh"]}</span></a>
</div>
<p class="note">{t["note"]}</p>
<div class="shot">{hero_shot}</div>
<div class="stats">{stats}</div>
</div></section>

<section id="{anchors[0]}"><div class="wrap">
<div class="section-head"><h2>{t["feat_h"]}</h2><p>{t["feat_p"]}</p></div>
<div class="grid">{feats}</div>
</div></section>

<section id="{anchors[1]}" class="alt"><div class="wrap">
<div class="section-head"><h2>{t["how_h"]}</h2><p>{t["how_p"]}</p></div>
<div class="steps">{steps}</div>
</div></section>

<section id="{anchors[2]}"><div class="wrap split">
<div><div class="section-head" style="text-align:left;margin:0 0 20px"><h2>{t["query_h"]}</h2><p>{t["query_p"]}</p></div>
<ul class="check">{qpoints}</ul></div>
<pre class="code" aria-label="query examples">{code}</pre>
</div></section>

<section id="{anchors[3]}" class="alt"><div class="wrap">
<div class="section-head"><h2>{t["dl_h"]}</h2><p>{t["dl_p"]}</p></div>
<div class="dl-grid">{dl}</div>
<p class="release-info" id="release-info" data-template="{escape(t["release_tpl"])}">{t["release_default"]} <a href="{REPO}/releases">{t["all_releases"]} →</a></p>
<div class="callout">{t["callout"]}</div>
</div></section>

<section id="{anchors[4]}"><div class="wrap">
<div class="section-head"><h2>{t["faq_h"]}</h2></div>
<div class="faq">{faq}</div>
</div></section>
</main>
<footer><div class="wrap">
<span>© {date.today().year} {t["footer"]}</span>
<nav>{flinks}</nav>
</div></footer>
<script src="{prefix}app.js" defer></script>
</body>
</html>
"""


def main() -> None:
    for lang, t in T.items():
        out = os.path.join(SITE, t["path"])
        os.makedirs(os.path.dirname(out), exist_ok=True)
        with open(out, "w", encoding="utf-8") as fh:
            fh.write(page(lang))
        print("wrote", out)
    today = date.today().isoformat()
    sitemap = f"""<?xml version="1.0" encoding="UTF-8"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
  <url>
    <loc>{BASE}</loc>
    <lastmod>{today}</lastmod>
    <changefreq>weekly</changefreq>
    <priority>1.0</priority>
  </url>
</urlset>
"""
    with open(os.path.join(SITE, "sitemap.xml"), "w", encoding="utf-8") as fh:
        fh.write(sitemap)
    with open(os.path.join(SITE, "robots.txt"), "w", encoding="utf-8") as fh:
        fh.write(f"User-agent: *\nAllow: /\n\nSitemap: {BASE}sitemap.xml\n")
    manifest = {
        "name": "Comitra", "short_name": "Comitra", "start_url": "./", "display": "browser",
        "background_color": "#ffffff", "theme_color": "#2563eb",
        "icons": [{"src": "assets/icon-192.png", "sizes": "192x192", "type": "image/png"},
                  {"src": "assets/icon-512.png", "sizes": "512x512", "type": "image/png"}],
    }
    with open(os.path.join(SITE, "site.webmanifest"), "w", encoding="utf-8") as fh:
        json.dump(manifest, fh, indent=2)
    with open(os.path.join(SITE, "404.html"), "w", encoding="utf-8") as fh:
        fh.write(f"""<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>Page not found – Comitra</title><meta name="robots" content="noindex"><link rel="stylesheet" href="{BASE}style.css"></head>
<body><main class="hero"><div class="wrap"><h1>404</h1><p class="lead">This page does not exist.</p>
<div class="cta"><a class="btn btn-primary" href="{BASE}">Go to the home page</a></div></div></main></body></html>
""")
    open(os.path.join(SITE, ".nojekyll"), "w").close()


if __name__ == "__main__":
    main()
