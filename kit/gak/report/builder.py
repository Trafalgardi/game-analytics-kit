"""Versioned HTML reports: create a version, build it, list everything in reports/index.html.

Layout (DESIGN.md section 6):

    analytics/reports/<slug>/vNNN/
        report.src.html   body fragment the agent writes (placeholders allowed)
        report.md         short summary for chat and messengers
        assets/           svg charts, screenshots
        work/             scratch scripts (git-ignored)
        meta.json
        report.html       built: standalone document, opens from disk
        artifact.html     built: same content without <html>/<head>/<body> (Claude Artifact)

A built version is final. Changing it means `new_version(..., from_version=N)` and building
the new folder; `build(..., force=True)` exists for repairing a broken build only.

Placeholders in report.src.html (HTML comments are dropped before they are resolved):
    {{svg:assets/x.svg}}                inlined SVG
    {{img:assets/x.png}}                data URI (png, jpg, jpeg, webp, gif)
    {{html:assets/x.html}}              inlined HTML fragment (keymetrics / dropoff --format html)
    {{meta:field}} / {{meta:a.b}}       value from meta.json; also the computed fields
                                        version_label ("v001"), built_date (21.09.2026 in ru,
                                        2026-09-21 otherwise) and window (the data window as
                                        people write it: 08–21.09.2026 / Sep 8–21, 2026)

Kinds (meta.json "kind", DESIGN.md section 6): "full" and "question" share one skeleton of
numbered blocks and are checked at build (_check_structure); a version made before kinds
existed has no kind and no check.
"""
from __future__ import annotations

import base64
import html
import json
import re
import shutil
import sqlite3
import subprocess
import sys
from collections import Counter
from datetime import datetime
from html.parser import HTMLParser
from pathlib import Path

try:  # Python 3.11+
    import tomllib
except ModuleNotFoundError:  # pragma: no cover - the kit requires 3.11+, keep a clear error
    tomllib = None

__all__ = ["ReportError", "new_version", "build", "build_index"]

HERE = Path(__file__).resolve().parent
SIZE_WARN_BYTES = 15 * 1024 * 1024
SLUG_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
VERSION_DIR_RE = re.compile(r"^v(\d{3,})$")
PLACEHOLDER_RE = re.compile(r"\{\{([^{}\n]{0,300})\}\}")
COMMENT_RE = re.compile(r"<!--.*?-->", re.S)
IMG_MIME = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
            ".webp": "image/webp", ".gif": "image/gif"}
KINDS = ("full", "question")
# The fixed skeleton: block ids in order, their numbers, and which kind needs which.
BLOCKS = ["summary", "product", "revenue", "tech", "countries", "hypotheses", "actions", "data", "method"]
BLOCK_NUMBERS = {"summary": 1, "product": 2, "revenue": 3, "tech": 4, "countries": 5, "hypotheses": 6,
                 "actions": 7}
REQUIRED_BLOCKS = {
    "full": ["summary", "product", "revenue", "tech", "countries", "hypotheses", "actions", "method"],
    "question": ["summary", "hypotheses", "actions", "method"],
}
HYP_ID_RE = re.compile(r"^h\d+$")
VOID_TAGS = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "source", "track", "wbr"}

FONTS_HTML = (
    '<link rel="preconnect" href="https://fonts.googleapis.com">\n'
    '<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>\n'
    '<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Oxanium:wght@500;700'
    '&family=IBM+Plex+Mono:wght@400;600&family=IBM+Plex+Sans:wght@400;500;600&display=swap">'
)


class ReportError(Exception):
    """A report operation failed; the message says what to fix."""


# --------------------------------------------------------------------------- public API

def new_version(analytics_dir: Path, slug: str, title: str, from_version: int | None = None,
                kind: str | None = None) -> Path:
    """Create reports/<slug>/vNNN/ (next number) and return its path.

    Without from_version the body starts from the scaffold of `kind` (full | question,
    default question) with the title and the block names in the report language.
    With from_version the body, report.md and assets/ are copied from that version, and
    kind / subtitle / question / data_window / sources_used are carried over.
    """
    if kind is not None and kind not in KINDS:
        raise ReportError(f"unknown report kind {kind!r}: use {' or '.join(KINDS)}")
    analytics_dir = Path(analytics_dir).resolve()
    _check_slug(slug)
    cfg = _load_config(analytics_dir)
    language = str(cfg.get("project", {}).get("report_language") or "ru")
    slug_dir = analytics_dir / "reports" / slug
    existing = _version_numbers(slug_dir)
    number = (max(existing) + 1) if existing else 1

    prev_dir, prev_meta, prev_number = None, {}, None
    if from_version is not None:
        prev_number = _parse_version(from_version)
        prev_dir = slug_dir / _vname(prev_number)
        if not prev_dir.is_dir():
            have = ", ".join(_vname(n) for n in existing) or "none"
            raise ReportError(f"cannot copy from {slug}/{_vname(prev_number)}: no such version (have: {have})")
        prev_meta = _read_meta(prev_dir, missing_ok=True)

    title = (title or "").strip() or str(prev_meta.get("title") or "").strip()
    if not title:
        raise ReportError("a report needs a title: pass --title \"...\"")
    if prev_dir is None:
        kind = kind or "question"
    else:  # a version made before kinds existed stays without one unless asked
        kind = kind or prev_meta.get("kind") or None

    vdir = slug_dir / _vname(number)
    vdir.mkdir(parents=True, exist_ok=False)
    (vdir / "assets").mkdir()
    (vdir / "work").mkdir()
    created = _now()

    if prev_dir is not None and (prev_dir / "report.src.html").is_file():
        shutil.copy2(prev_dir / "report.src.html", vdir / "report.src.html")
        if (prev_dir / "report.md").is_file():
            shutil.copy2(prev_dir / "report.md", vdir / "report.md")
        if (prev_dir / "assets").is_dir():
            shutil.copytree(prev_dir / "assets", vdir / "assets", dirs_exist_ok=True)
    else:
        _write(vdir / "report.src.html", _scaffold(kind or "question", language, title))
    if not (vdir / "report.md").is_file():
        _write(vdir / "report.md", _md_template(title, slug, number, created, language))

    meta = {
        "slug": slug,
        "version": number,
        "kind": kind,
        "title": title,
        "subtitle": prev_meta.get("subtitle", ""),
        "question": prev_meta.get("question", ""),
        "language": language,
        "created_at": created.isoformat(timespec="seconds"),
        "built_at": None,
        "previous_version": prev_number,
        "data_window": dict(prev_meta.get("data_window") or {"since": None, "until": None}),
        "sources_used": list(prev_meta.get("sources_used") or []),
    }
    _write_meta(vdir, meta)
    build_index(analytics_dir)
    return vdir


def build(analytics_dir: Path, slug: str, version: int | None = None, *, force: bool = False) -> Path:
    """Build report.html and artifact.html for one version (latest by default).

    Refuses a version that is already built unless force=True. Returns report.html.
    """
    analytics_dir = Path(analytics_dir).resolve()
    _check_slug(slug)
    slug_dir = analytics_dir / "reports" / slug
    numbers = _version_numbers(slug_dir)
    if not numbers:
        raise ReportError(f"no versions of report '{slug}' under {slug_dir}; run `report new {slug} --title ...` first")
    number = _parse_version(version) if version is not None else max(numbers)
    vdir = slug_dir / _vname(number)
    if number not in numbers:
        raise ReportError(f"{slug}/{_vname(number)} does not exist (have: {', '.join(_vname(n) for n in numbers)})")
    meta = _read_meta(vdir)
    if meta.get("built_at") and not force:
        raise ReportError(
            f"{slug}/{_vname(number)} was built at {meta['built_at']} and a built version is final. "
            f"To change it: `report new {slug} --from v{number}`, edit the new version, build it. "
            f"(force=True / --force rebuilds in place and is only for repairing a broken build.)")
    src_path = vdir / "report.src.html"
    if not src_path.is_file():
        raise ReportError(f"missing {src_path}")

    now = _now()
    ctx = dict(meta)
    ctx["built_at"] = now.isoformat(timespec="seconds")
    ctx["built_date"] = _fmt_date(now.date().isoformat(), str(meta.get("language") or "ru"))
    ctx["version_label"] = _vname(number)
    window = meta.get("data_window") or {}
    ctx["window"] = window_label(window.get("since"), window.get("until"), str(meta.get("language") or "ru"))
    ctx.setdefault("slug", slug)
    source = src_path.read_text(encoding="utf-8-sig")
    body, problems = _resolve(source, vdir, ctx)
    if problems:
        lines = "\n".join(f"  - {p}" for p in problems)
        raise ReportError(f"{slug}/{_vname(number)}: {len(problems)} placeholder problem(s) in report.src.html, "
                          f"nothing was written:\n{lines}")
    kind = meta.get("kind")
    if kind in KINDS:
        problems = _check_structure(source, body, kind)
        if problems:
            lines = "\n".join(f"  - {p}" for p in problems)
            raise ReportError(f"{slug}/{_vname(number)}: {len(problems)} structure problem(s) in report.src.html "
                              f"(a {kind} report, DESIGN.md section 6), nothing was written:\n{lines}")

    css = _css()
    title = str(meta.get("title") or slug)
    language = str(meta.get("language") or "ru")
    kit_version = _kit_version(analytics_dir)
    report_html = _fill(_template("shell.html"), {
        "lang": html.escape(language), "title": html.escape(title, quote=False),
        "generator": html.escape(f"game-analytics-kit {kit_version}"),
        "fonts": FONTS_HTML, "css": css, "body": body})
    artifact_html = (f"<title>{html.escape(title, quote=False)}</title>\n{FONTS_HTML}\n"
                     f"<style>\n{css}\n</style>\n{body}\n")
    _write(vdir / "report.html", report_html)
    _write(vdir / "artifact.html", artifact_html)

    if meta.get("built_at") and force:
        meta.setdefault("first_built_at", meta["built_at"])
    meta["built_at"] = ctx["built_at"]
    meta["kit_version"] = kit_version
    meta["project_git_commit"] = _git_commit(analytics_dir.parent)
    meta["db_snapshot"] = _db_snapshot(analytics_dir)
    meta["sizes"] = {
        "report.html": (vdir / "report.html").stat().st_size,
        "artifact.html": (vdir / "artifact.html").stat().st_size,
        "report.src.html": src_path.stat().st_size,
        "assets": sum(p.stat().st_size for p in (vdir / "assets").rglob("*") if p.is_file())
        if (vdir / "assets").is_dir() else 0,
    }
    _write_meta(vdir, meta)
    build_index(analytics_dir)

    todo = len(re.findall(r"\bTODO\b", COMMENT_RE.sub("", body)))
    if todo:
        _say(f"warning: {todo} TODO marker(s) left in the built body of {slug}/{_vname(number)}")
    size = meta["sizes"]["report.html"]
    if size > SIZE_WARN_BYTES:
        _say(f"warning: report.html is {size / 1048576:.1f} MB (> 15 MB): too big to publish as an Artifact "
             f"and heavy to forward; shrink screenshots (jpg/webp, smaller width)")
    return vdir / "report.html"


def build_index(analytics_dir: Path) -> Path:
    """Write reports/index.html: every report, newest built version first, with its history."""
    analytics_dir = Path(analytics_dir).resolve()
    cfg = _load_config(analytics_dir)
    lang = str(cfg.get("project", {}).get("report_language") or "ru")
    t = _INDEX_TEXT["ru" if lang == "ru" else "en"]
    reports_dir = analytics_dir / "reports"
    reports_dir.mkdir(parents=True, exist_ok=True)

    reports = []
    for slug_dir in sorted(p for p in reports_dir.iterdir() if p.is_dir() and SLUG_RE.match(p.name)):
        versions = []
        for n in sorted(_version_numbers(slug_dir), reverse=True):
            vdir = slug_dir / _vname(n)
            try:
                meta = _read_meta(vdir)
            except ReportError:
                meta = {}
            built = bool(meta.get("built_at")) and (vdir / "report.html").is_file()
            versions.append((n, vdir, meta, built))
        if versions:
            reports.append((slug_dir.name, versions))

    def sort_key(item):
        _, versions = item
        built = [m.get("built_at") for _, _, m, b in versions if b]
        return max(built) if built else max(str(m.get("created_at") or "") for _, _, m, _ in versions)
    reports.sort(key=sort_key, reverse=True)

    entries = [_index_entry(slug, versions, t, lang) for slug, versions in reports]
    if not entries:
        entries = [f'<div class="rempty">{t["empty"]}</div>']
    project = str(cfg.get("project", {}).get("name") or "").strip()
    count = t["count"](len(reports))
    eyebrow = f"{html.escape(project)} · {count}" if project else count
    kit_version = _kit_version(analytics_dir)
    now = _now()
    out = _fill(_template("index.html"), {
        "lang": html.escape(lang), "title": html.escape(f"{t['heading']} — {project}" if project else t["heading"]),
        "generator": html.escape(f"game-analytics-kit {kit_version}"), "fonts": FONTS_HTML, "css": _css(),
        "eyebrow": eyebrow, "heading": t["heading"], "standfirst": t["standfirst"],
        "entries": "\n".join(entries),
        "footer": html.escape(f"{t['generated']} {_fmt_date(now.date().isoformat(), lang)} "
                              f"{now.strftime('%H:%M')} · game-analytics-kit {kit_version}"),
    })
    path = reports_dir / "index.html"
    _write(path, out)
    return path


# --------------------------------------------------------------------------- placeholders

def _resolve(src: str, vdir: Path, ctx: dict) -> tuple[str, list[str]]:
    """Resolve every placeholder in src. Returns (body, problems); problems empty on success."""
    # Comments are dropped (they hold notes and commented-out examples); keep line numbers.
    src = COMMENT_RE.sub(lambda m: "\n" * m.group(0).count("\n"), src)
    problems: list[str] = []
    vroot = vdir.resolve()

    def line_of(pos: int) -> int:
        return src.count("\n", 0, pos) + 1

    def repl(m: re.Match) -> str:
        raw = m.group(0)
        where = f"line {line_of(m.start())}: {raw if len(raw) < 90 else raw[:87] + '...'}"
        kind, sep, arg = m.group(1).strip().partition(":")
        kind, arg = kind.strip().lower(), arg.strip()
        if not sep or not arg or kind not in ("svg", "img", "html", "meta"):
            problems.append(f"{where}: unknown placeholder; use {{{{svg:assets/x.svg}}}}, "
                            f"{{{{img:assets/x.png}}}}, {{{{html:assets/x.html}}}} or {{{{meta:field}}}} "
                            f"(write a literal '{{{{' as &#123;&#123;)")
            return raw
        if kind == "meta":
            value, err = _meta_value(ctx, arg)
            if err:
                problems.append(f"{where}: {err}")
                return raw
            return value
        suffix = Path(arg).suffix.lower()
        if kind == "svg" and suffix != ".svg":
            problems.append(f"{where}: {{{{svg:...}}}} needs an .svg file (use {{{{img:...}}}} for pictures)")
            return raw
        if kind == "img" and suffix not in IMG_MIME:
            problems.append(f"{where}: unsupported image type {suffix or '(none)'}; use png, jpg, jpeg, webp or gif")
            return raw
        if kind == "html" and suffix not in (".html", ".htm"):
            problems.append(f"{where}: {{{{html:...}}}} needs an .html fragment")
            return raw
        path = (vdir / arg).resolve()
        if not path.is_relative_to(vroot):
            problems.append(f"{where}: path leaves the version folder")
            return raw
        if not path.is_file():
            problems.append(f"{where}: missing asset {arg}")
            return raw
        if kind == "img":
            return f"data:{IMG_MIME[suffix]};base64," + base64.b64encode(path.read_bytes()).decode("ascii")
        if kind == "html":
            fragment = path.read_text(encoding="utf-8-sig")
            if re.search(r"<(!doctype|html|head|body)[\s>]", fragment, re.I):
                problems.append(f"{where}: {arg} is a whole document; embed a fragment (no <html>/<body>)")
                return raw
            return COMMENT_RE.sub("", fragment).strip()
        text = _clean_svg(path.read_text(encoding="utf-8-sig"))
        if "<svg" not in text:
            problems.append(f"{where}: {arg} has no <svg> element")
            return raw
        return text

    body = PLACEHOLDER_RE.sub(repl, src)
    spans = [m.span() for m in PLACEHOLDER_RE.finditer(src)]
    for m in re.finditer(r"\{\{", src):  # an opening pair that never closes
        if not any(a <= m.start() < b for a, b in spans):
            near = " ".join(src[max(0, m.start() - 20):m.start() + 30].split())
            problems.append(f"line {line_of(m.start())}: stray '{{{{' without '}}}}' near '{near}' "
                            f"(a literal pair is &#123;&#123;)")
            break
    return body.strip() + "\n", problems


# --------------------------------------------------------------------------- structure

class _Outline(HTMLParser):
    """Sections, ids, internal links, hypotheses and recommendations of a report body."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.stack: list[tuple[str, dict | None, str | None]] = []  # (tag, record, section id)
        self.sections: list[str] = []
        self.ids: list[tuple[str, int]] = []
        self.links: list[tuple[str, int]] = []
        self.hyps: list[dict] = []
        self.acts: list[dict] = []

    def _records(self) -> list[dict]:
        return [record for _, record, _ in self.stack if record is not None]

    def _section(self) -> str | None:
        return next((sid for _, _, sid in reversed(self.stack) if sid), None)

    def _attrs(self, tag: str, attrs: list) -> tuple[set[str], str | None]:
        values = dict(attrs)
        classes = set((values.get("class") or "").split())
        line = self.getpos()[0]
        ident = values.get("id")
        if ident:
            self.ids.append((ident, line))
        href = values.get("href") or ""
        if tag == "a" and href.startswith("#") and len(href) > 1:
            self.links.append((href[1:], line))
            for record in self._records():
                record["links"].append(href[1:])
        for record in self._records():
            if "conf" in classes and classes & {"high", "mid", "low"}:
                record["conf"] = True
            record["eff"] = record.get("eff") or "eff" in classes
            record["measure"] = record.get("measure") or "measure" in classes
        return classes, ident

    def handle_starttag(self, tag, attrs):
        classes, ident = self._attrs(tag, attrs)
        if tag in VOID_TAGS:
            return
        record = None
        line = self.getpos()[0]
        if "hyp" in classes:
            record = {"id": ident, "line": line, "conf": False, "links": []}
            self.hyps.append(record)
        elif "act" in classes:
            record = {"line": line, "links": [], "eff": False, "measure": False, "section": self._section()}
            self.acts.append(record)
        section = ident if tag == "section" and ident else None
        if section:
            self.sections.append(section)
        self.stack.append((tag, record, section))

    def handle_startendtag(self, tag, attrs):
        self._attrs(tag, attrs)

    def handle_endtag(self, tag):
        if any(t == tag for t, _, _ in self.stack):
            while self.stack and self.stack.pop()[0] != tag:
                pass


def _check_structure(source: str, body: str, kind: str) -> list[str]:
    """The fixed skeleton of a full / question report (DESIGN.md section 6)."""
    outline = _Outline()
    outline.feed(COMMENT_RE.sub(lambda m: "\n" * m.group(0).count("\n"), source))
    outline.close()
    problems: list[str] = []
    for block in REQUIRED_BLOCKS[kind]:
        if block not in outline.sections:
            number = BLOCK_NUMBERS.get(block)
            problems.append(f"block #{block} is missing: add <section class=\"block\" id=\"{block}\">"
                            + (f" (block {number})" if number else "")
                            + (" — in a question report keep it, even if short" if kind == "question" else ""))
    present = [s for s in outline.sections if s in BLOCKS]
    if present != sorted(present, key=BLOCKS.index):
        problems.append(f"blocks are out of order: {', '.join(present)}; the order is {', '.join(BLOCKS)}")
    counts = Counter(i for i, _ in outline.ids)
    for ident, count in sorted(counts.items()):
        if count > 1:
            problems.append(f"id \"{ident}\" is used {count} times; ids must be unique")
    known = set(counts) | set(re.findall(r'\sid="([^"]+)"', body))
    for target, line in outline.links:
        if target not in known:
            problems.append(f"line {line}: link #{target} points to no id")
    hyp_ids = set()
    for hyp in outline.hyps:
        where = f"line {hyp['line']}: hypothesis {hyp['id'] or '(no id)'}"
        if not hyp["id"] or not HYP_ID_RE.match(hyp["id"]):
            problems.append(f"{where}: give it id=\"h1\", \"h2\", ... (the recommendations link to it)")
        else:
            hyp_ids.add(hyp["id"])
        if not hyp["conf"]:
            problems.append(f"{where}: no confidence mark (<span class=\"conf high|mid|low\">)")
        if not any(not HYP_ID_RE.match(t) and t not in ("hypotheses", "actions") for t in hyp["links"]):
            problems.append(f"{where}: no link to the numbers it rests on (<a href=\"#<section id>\">)")
    if not outline.hyps and "hypotheses" in outline.sections:
        problems.append("block #hypotheses has no hypothesis (<article class=\"hyp\" id=\"h1\">)")
    actions = [a for a in outline.acts if a["section"] == "actions"]
    if not actions and "actions" in outline.sections:
        problems.append("block #actions has no recommendation (<div class=\"act\">)")
    for act in actions:
        where = f"line {act['line']}: recommendation"
        if not any(t in hyp_ids for t in act["links"]):
            problems.append(f"{where}: no link to a hypothesis (<a href=\"#h1\">H1</a> in its .why line)")
        if not act["eff"]:
            problems.append(f"{where}: no expected effect (<p class=\"eff\">)")
        if not act["measure"]:
            problems.append(f"{where}: no measure (<p class=\"measure\">)")
    return problems


def _meta_value(ctx: dict, dotted: str) -> tuple[str, str | None]:
    value = ctx
    for part in dotted.split("."):
        if not isinstance(value, dict) or part not in value:
            return "", f"meta.json has no field '{dotted}'"
        value = value[part]
    if value is None or value == "" or value == []:
        if dotted == "window":
            return "", "the data window is empty: fill data_window.since and data_window.until in meta.json"
        return "", f"meta.json field '{dotted}' is empty; fill it in meta.json"
    if isinstance(value, dict):
        return "", f"meta.json field '{dotted}' is an object; name one of its fields ({', '.join(value)})"
    if isinstance(value, list):
        value = ", ".join(str(v) for v in value)
    return html.escape(str(value), quote=True), None


def _clean_svg(text: str) -> str:
    text = re.sub(r"^\s*<\?xml[^>]*\?>", "", text)
    text = re.sub(r"<!DOCTYPE[^>\[]*(\[[^\]]*\])?\s*>", "", text, flags=re.I)
    return text.strip()


# --------------------------------------------------------------------------- index

_INDEX_TEXT = {
    "ru": {
        "heading": "Отчёты",
        "standfirst": "Каждая версия отчёта — отдельная папка. Собранная версия не меняется: "
                      "исправление — это новая версия. Сверху — последние.",
        "built": "Собран", "window": "Данные", "versions": "Версий", "draft": "черновик", "kind": "Вид",
        "no_subtitle": "без подзаголовка", "generated": "Собрано", "latest": "последняя",
        "empty": "Отчётов пока нет. Начните с <code>py analytics/ga.py report new &lt;slug&gt; --title \"...\"</code>.",
        "count": lambda n: f"{n} {_ru_plural(n, 'отчёт', 'отчёта', 'отчётов')}",
    },
    "en": {
        "heading": "Reports",
        "standfirst": "Every report version is its own folder. A built version never changes: "
                      "a correction is a new version. Newest first.",
        "built": "Built", "window": "Data", "versions": "Versions", "draft": "draft", "kind": "Kind",
        "no_subtitle": "no subtitle", "generated": "Generated", "latest": "latest",
        "empty": "No reports yet. Start with <code>py analytics/ga.py report new &lt;slug&gt; --title \"...\"</code>.",
        "count": lambda n: f"{n} report{'s' if n != 1 else ''}",
    },
}


def _index_entry(slug: str, versions: list, t: dict, lang: str) -> str:
    built = [v for v in versions if v[3]]
    head_n, head_dir, head_meta, head_built = built[0] if built else versions[0]
    title = html.escape(str(head_meta.get("title") or slug))
    link = f"{slug}/{_vname(head_n)}/report.html"
    h2 = f'<h2><a href="{link}">{title}</a></h2>' if head_built else f"<h2>{title}</h2>"
    subtitle = str(head_meta.get("subtitle") or "").strip()
    sub = (f'<p class="rsub">{html.escape(subtitle)}</p>' if subtitle
           else f'<p class="rsub none">{t["no_subtitle"]}</p>')
    window = head_meta.get("data_window") or {}
    since, until = window.get("since"), window.get("until")
    win = (f"{_fmt_date(since, lang) if since else '…'} – {_fmt_date(until, lang) if until else '…'}"
           if since or until else "—")
    built_at = _fmt_date(str(head_meta.get("built_at"))[:10], lang) if head_built else t["draft"]
    facts = (f'<dl class="rfacts"><div><dt>{t["built"]}</dt><dd>{html.escape(built_at)}</dd></div>'
             f'<div><dt>{t["window"]}</dt><dd>{html.escape(win)}</dd></div>'
             f'<div><dt>{t["versions"]}</dt><dd>{len(versions)}</dd></div>'
             + (f'<div><dt>{t["kind"]}</dt><dd>{_words(lang)["kind_" + kind]}</dd></div>'
                if (kind := head_meta.get("kind")) in KINDS else "") + '</dl>')
    items = []
    for n, vdir, meta, is_built in versions:
        name = _vname(n)
        if is_built:
            cls = ' class="latest"' if n == head_n else ""
            md = f' <a href="{slug}/{name}/report.md">md</a>' if (vdir / "report.md").is_file() else ""
            date = html.escape(_fmt_date(str(meta.get("built_at"))[:10], lang))
            items.append(f'<li{cls}><a class="vn" href="{slug}/{name}/report.html">{name}</a>'
                         f'<span>{date}</span>{md}</li>')
        else:
            items.append(f'<li class="draft"><span class="vn">{name}</span><span>{t["draft"]}</span></li>')
    return (f'<article class="rentry">\n  <div class="rhead">{h2}<span class="rslug">{slug}</span></div>\n'
            f'  {sub}\n  {facts}\n  <ul class="rvers">{"".join(items)}</ul>\n</article>')


MONTHS_EN = ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")


def window_label(since, until, lang: str) -> str:
    """2026-09-08..2026-09-21 -> '08–21.09.2026' (ru) / 'Sep 8–21, 2026' (en); '' when unknown."""
    try:
        a, b = datetime.strptime(str(since), "%Y-%m-%d"), datetime.strptime(str(until), "%Y-%m-%d")
    except ValueError:
        return ""
    if lang == "ru":
        if a.year != b.year:
            return f"{a:%d.%m.%Y}–{b:%d.%m.%Y}"
        if a.month != b.month:
            return f"{a:%d.%m}–{b:%d.%m.%Y}"
        return f"{a:%d}–{b:%d.%m.%Y}" if a != b else f"{b:%d.%m.%Y}"
    ma, mb = MONTHS_EN[a.month - 1], MONTHS_EN[b.month - 1]
    if a.year != b.year:
        return f"{ma} {a.day}, {a.year} – {mb} {b.day}, {b.year}"
    if a.month != b.month:
        return f"{ma} {a.day} – {mb} {b.day}, {b.year}"
    return f"{ma} {a.day}–{b.day}, {b.year}" if a != b else f"{mb} {b.day}, {b.year}"


def _ru_plural(n: int, one: str, few: str, many: str) -> str:
    if n % 10 == 1 and n % 100 != 11:
        return one
    if 2 <= n % 10 <= 4 and not 12 <= n % 100 <= 14:
        return few
    return many


def _fmt_date(value, lang: str) -> str:
    s = str(value or "")
    if lang == "ru" and re.match(r"^\d{4}-\d{2}-\d{2}$", s):
        return f"{s[8:10]}.{s[5:7]}.{s[:4]}"
    return s


# --------------------------------------------------------------------------- build metadata

def _kit_version(analytics_dir: Path) -> str:
    vfile = analytics_dir / "kit" / "VERSION"
    if vfile.is_file():
        text = vfile.read_text(encoding="utf-8").strip()
        if text:
            return text
    try:
        import importlib
        return str(importlib.import_module("gak").__version__)
    except Exception:
        return "unknown"


def _git_commit(project_root: Path) -> str | None:
    try:
        res = subprocess.run(["git", "-C", str(project_root), "rev-parse", "--short", "HEAD"],
                             capture_output=True, text=True, timeout=15)
    except (OSError, subprocess.SubprocessError):
        return None
    out = res.stdout.strip()
    return out if res.returncode == 0 and out else None


def _db_snapshot(analytics_dir: Path) -> dict | None:
    cfg = _load_config(analytics_dir)
    rel = str(cfg.get("database", {}).get("path") or "data/analytics.db")
    db = (analytics_dir / rel).resolve()
    if not db.is_file():
        return None
    snapshot = {"path": rel, "tables": {}}
    try:
        con = sqlite3.connect(db.as_uri() + "?mode=ro", uri=True)
    except sqlite3.Error as exc:
        snapshot["error"] = str(exc)
        return snapshot
    try:
        names = [r[0] for r in con.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table' AND name NOT LIKE 'sqlite\\_%' ESCAPE '\\' "
            "ORDER BY name")]
        for name in names:
            q = '"' + name.replace('"', '""') + '"'
            cols = {r[1] for r in con.execute(f"PRAGMA table_info({q})")}
            if "date" in cols:
                rows, lo, hi = con.execute(f"SELECT count(*), min(date), max(date) FROM {q}").fetchone()
            else:
                (rows,), lo, hi = con.execute(f"SELECT count(*) FROM {q}").fetchone(), None, None
            snapshot["tables"][name] = {"rows": rows, "min_date": lo, "max_date": hi}
        if "meta" in names:  # share of devices synced; absolute counts scale by 1 / rate
            rate = con.execute("SELECT MIN(CAST(value AS REAL)) FROM meta "
                               "WHERE key LIKE '%.sample_rate'").fetchone()[0]
            snapshot["sample_rate"] = 1.0 if rate is None else rate
    except sqlite3.Error as exc:
        snapshot["error"] = str(exc)
    finally:
        con.close()
    return snapshot


# --------------------------------------------------------------------------- helpers

def _load_config(analytics_dir: Path) -> dict:
    path = Path(analytics_dir) / "analytics.toml"
    if not path.is_file() or tomllib is None:
        return {}
    try:
        with path.open("rb") as fh:
            return tomllib.load(fh)
    except (tomllib.TOMLDecodeError, OSError) as exc:
        raise ReportError(f"cannot read {path}: {exc}") from exc


def _check_slug(slug: str) -> None:
    if not isinstance(slug, str) or not SLUG_RE.match(slug) or len(slug) > 80:
        raise ReportError(f"bad report slug {slug!r}: use lowercase latin letters, digits and single hyphens, "
                          f"e.g. ua-roas-1-1-23")


def _parse_version(value) -> int:
    s = str(value).strip().lower().lstrip("v")
    if not s.isdigit() or int(s) < 1:
        raise ReportError(f"bad version {value!r}: use a number like 2 or v002")
    return int(s)


def _vname(number: int) -> str:
    return f"v{number:03d}"


def _version_numbers(slug_dir: Path) -> list[int]:
    if not slug_dir.is_dir():
        return []
    return sorted(int(m.group(1)) for p in slug_dir.iterdir()
                  if p.is_dir() and (m := VERSION_DIR_RE.match(p.name)))


def _read_meta(vdir: Path, missing_ok: bool = False) -> dict:
    path = vdir / "meta.json"
    if not path.is_file():
        if missing_ok:
            return {}
        raise ReportError(f"missing {path}")
    try:
        data = json.loads(path.read_text(encoding="utf-8-sig"))
    except (json.JSONDecodeError, OSError) as exc:
        raise ReportError(f"cannot read {path}: {exc}") from exc
    if not isinstance(data, dict):
        raise ReportError(f"{path} must hold a JSON object")
    return data


def _write_meta(vdir: Path, meta: dict) -> None:
    _write(vdir / "meta.json", json.dumps(meta, ensure_ascii=False, indent=2) + "\n")


# Words the scaffolds and the index need in the report language (__T_<key>__ in a scaffold).
_WORDS = {
    "ru": {
        "summary": "Краткая информация", "product": "Продуктовые метрики", "revenue": "Метрики дохода",
        "tech": "Технические данные", "countries": "Страны", "hypotheses": "Гипотезы",
        "actions": "Рекомендации", "data": "Какие данные нужны", "method": "Методика",
        "answers": "Короткие ответы", "keymetrics": "Ключевые метрики по версиям",
        "dropoff": "Отвалы по шагам и по времени", "interp": "Интерпретация", "basis": "Опора",
        "test": "Как проверить", "effect": "Ожидаемый эффект", "measure": "Как мерить",
        "conf_high": "уверенность высокая", "conf_mid": "уверенность средняя", "conf_low": "уверенность низкая",
        "kind_full": "полный разбор", "kind_question": "вопрос", "window": "Окно данных",
    },
    "en": {
        "summary": "Summary", "product": "Product metrics", "revenue": "Revenue metrics",
        "tech": "Technical data", "countries": "Countries", "hypotheses": "Hypotheses",
        "actions": "Recommendations", "data": "Data I need", "method": "Method",
        "answers": "Short answers", "keymetrics": "Key metrics by version",
        "dropoff": "Drop-off by steps and by time", "interp": "Interpretation", "basis": "Rests on",
        "test": "How to test", "effect": "Expected effect", "measure": "How to measure",
        "conf_high": "confidence high", "conf_mid": "confidence medium", "conf_low": "confidence low",
        "kind_full": "full review", "kind_question": "question", "window": "Data window",
    },
}


def _words(lang: str) -> dict:
    return _WORDS["ru" if lang == "ru" else "en"]


def _scaffold(kind: str, lang: str, title: str) -> str:
    words = _words(lang)
    text = _template(f"scaffold_{kind}.html")
    text = re.sub(r"__T_(\w+)__", lambda m: words.get(m.group(1), m.group(0)), text)
    return text.replace("__TITLE__", html.escape(title, quote=False))


def _md_template(title: str, slug: str, number: int, created: datetime, lang: str) -> str:
    date = created.date().isoformat()
    if lang == "ru":
        return (f"# {title}\n\n{_fmt_date(date, lang)} · {slug} {_vname(number)} · черновик\n\n"
                "Тезис одной строкой.\n\n"
                "**Коротко**\n"
                "- Ответ на первый вопрос: сначала прямой ответ, потом число и n.\n"
                "- Ответ на второй вопрос.\n\n"
                "**Гипотезы**\n"
                "- H1 — утверждение; на чём стоит; уверенность.\n\n"
                "**Что делать**\n"
                "1. Действие (→ H1): ожидаемый эффект, как мерить.\n\n"
                "**Нужны данные:** что и откуда.\n\n"
                "Полный отчёт с таблицами, графиками и методикой — report.html в этой папке (открывается с диска).\n")
    return (f"# {title}\n\n{date} · {slug} {_vname(number)} · draft\n\n"
            "The thesis in one line.\n\n"
            "**Short answers**\n"
            "- Answer to the first question: the direct answer first, then the number and n.\n"
            "- Answer to the second question.\n\n"
            "**Hypotheses**\n"
            "- H1 — the claim; what it rests on; confidence.\n\n"
            "**What to do**\n"
            "1. Action (→ H1): expected effect, how to measure.\n\n"
            "**Data needed:** what and from where.\n\n"
            "Full report with tables, charts and method: report.html in this folder (opens from disk).\n")


def _template(name: str) -> str:
    return (HERE / name).read_text(encoding="utf-8")


def _css() -> str:
    return _template("theme.css").strip()


def _fill(template: str, values: dict) -> str:
    """Single pass, so inserted content (css, body) is never scanned for placeholders again."""
    return re.sub(r"\{\{(\w+)\}\}", lambda m: values.get(m.group(1), m.group(0)), template)


def _write(path: Path, text: str) -> None:
    path.write_text(text, encoding="utf-8", newline="\n")


def _now() -> datetime:
    return datetime.now().astimezone().replace(microsecond=0)


def _say(message: str) -> None:
    try:
        print(message)
    except UnicodeEncodeError:
        enc = getattr(sys.stdout, "encoding", None) or "ascii"
        print(message.encode(enc, "backslashreplace").decode(enc, "replace"))
