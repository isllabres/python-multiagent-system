#!/usr/bin/env python3
"""Graph of The Python Wiki, so code can be reviewed against it.

The Python Wiki (https://wiki.python.org/python/FrontPage.html) is being archived as a static site
and says it is served mostly to bots and crawlers. This tool therefore crawls as little as it can
and remembers everything:

  1. one request for the "All Pages" index (about 3,400 page names: the skeleton of the graph),
  2. one for the FrontPage (its sections, and the pages linked under each),
  3. one per page linked from the FrontPage (about 40), for the links between them.

That is a single bounded crawl of roughly 45 requests, at least --delay seconds apart, cached for
--ttl-days (default 180: the archive no longer changes). Any other page is fetched one at a time,
only when `read` asks for it, and cached too. The delay holds across processes, and a hard cap per
run keeps a bug from turning this into a crawler.

Commands:
  ensure     build the graph if it is missing or stale, then print its status. Never fails the caller
  build      force a rebuild
  map        the sections of the FrontPage and the largest page families
  search     rank pages for the topics found in a piece of code
  neighbors  parent, subpages, and the links in and out of a page
  read       a page's outline, one section, or its text (bounded), fetched on demand
  export     the graph as DOT or JSON

Standard library only.
"""

import argparse
import difflib
import json
import math
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import Counter
from collections.abc import Sequence
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from typing import Any
from hashlib import sha1
from html.parser import HTMLParser
from pathlib import Path

DEFAULT_BASE = "https://wiki.python.org/python/"
DEFAULT_CACHE = ".claude/cache/python-wiki"
USER_AGENT = (
    "ds-lab-python-wiki-graph/1.0 (code-review helper; single-threaded, cached, "
    "at most one request per second)"
)
NAV_PAGES = frozenset({"FrontPage", "TitleIndex", "RecentChanges"})
ROOT = "FrontPage"
MAX_REQUESTS_PER_RUN = 80
ARCHIVE_NOTE = "[archived wiki snapshot: verify against the current Python docs; Python 2-era content is common]"
HEADINGS = {f"h{n}" for n in range(1, 7)}
BLOCKS = {"p", "div", "ul", "ol", "table", "tr", "hr", "blockquote", "dl"}
KIND_FACTOR = {
    "question": 0.4,
    "event": 0.4,
    "idea": 0.6,
    "wiki-meta": 0.3,
    "category": 0.8,
    "dead-link": 0.0,
}
# MoinMoin escapes runs of unsafe characters as their UTF-8 bytes in hex: `(2027)` is " '".
HEX_ESCAPE = re.compile(r"\(((?:[0-9a-fA-F]{2})+)\)")


class FetchError(Exception):
    """A page could not be fetched (network error, HTTP error, or the request cap)."""

    def __init__(self, message: str, status: int | None = None) -> None:
        super().__init__(message)
        self.status = status


# --------------------------------------------------------------------------- names and kinds


def decode_name(stem: str) -> str:
    """Turn a served file stem into the page title: `A(2f)B` -> `A/B`, `(c3a9)` -> `é`."""
    name = urllib.parse.unquote(stem).removesuffix(".html")
    return HEX_ESCAPE.sub(
        lambda m: bytes.fromhex(m.group(1)).decode("utf-8", errors="replace"), name
    )


def encode_name(title: str) -> str:
    """Inverse of `decode_name`: the file stem the wiki actually serves a page under.

    Only ASCII letters, digits and `_` stay as they are; every other run of characters becomes its
    UTF-8 bytes in hex inside parentheses. Checked against all 3,431 names of the real index. It
    matters: the FrontPage links to `Two%20Words.html`, which is a 404, while the page lives at
    `Two(20)Words.html`.
    """
    out: list[str] = []
    pending = bytearray()
    for ch in title:
        if ch.isascii() and (ch.isalnum() or ch == "_"):
            if pending:
                out.append(f"({pending.hex()})")
                pending.clear()
            out.append(ch)
        else:
            pending += ch.encode("utf-8")
    if pending:
        out.append(f"({pending.hex()})")
    return "".join(out)


def classify(page_id: str) -> str:
    """Rough kind of a page from its title, used to rank documentation above chatter."""
    if page_id.startswith("Category"):
        return "category"
    if page_id.startswith("Asking for Help"):
        return "question"
    if page_id.startswith("CodingProjectIdeas"):
        return "idea"
    if page_id.startswith("HelpOn"):
        return "wiki-meta"
    if re.match(
        r"(PyCon|EuroPython|PyData|SciPy|Sprint)|.*(Sprint|Conference)$", page_id
    ):
        return "event"
    return "page"


def tokenize(text: str) -> list[str]:
    """Lower-case words, splitting CamelCase: `PythonSpeed/PerformanceTips` -> python speed ..."""
    spaced = re.sub(r"([a-z0-9])([A-Z])", r"\1 \2", text)
    return re.findall(r"[a-z0-9]+", spaced.lower())


def page_url(base: str, stem: str) -> str:
    """URL of a page from its file stem (special characters percent-encoded)."""
    return base + urllib.parse.quote(stem, safe="()'!*,~-_.") + ".html"


def stem_of(href: str, page_url: str, base: str) -> str | None:
    """File stem of an in-wiki page link, or None for anything else (other hosts, anchors)."""
    absolute = urllib.parse.urlsplit(urllib.parse.urljoin(page_url, href))
    origin = urllib.parse.urlsplit(base)
    if absolute.netloc != origin.netloc or not absolute.path.startswith(origin.path):
        return None
    tail = absolute.path[len(origin.path) :]
    if not tail.endswith(".html"):
        return None
    return urllib.parse.unquote(tail[: -len(".html")])


# --------------------------------------------------------------------------- HTML parsing


@dataclass
class Heading:
    level: int
    id: str
    text: str


@dataclass
class Link:
    href: str
    text: str
    section: str | None


@dataclass
class ParsedPage:
    title: str
    text: str
    headings: list[Heading]
    links: list[Link]


class _PageParser(HTMLParser):
    """Extract the `#content` div of a wiki page: readable text, headings and links.

    Each link remembers the level-2 heading it sits under, which is how the FrontPage's
    sections are recovered.
    """

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.title_parts: list[str] = []
        self.parts: list[str] = []
        self.headings: list[Heading] = []
        self.links: list[Link] = []
        self._in_title = False
        self._depth = 0
        self._skip = 0
        self._pre = False
        self._heading: tuple[int, str] | None = None
        self._heading_text: list[str] = []
        self._section: str | None = None
        self._href: str | None = None
        self._link_text: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        a = {k: v or "" for k, v in attrs}
        if tag == "title":
            self._in_title = True
        elif tag == "div":
            if a.get("id") == "content" and not self._depth:
                self._depth = 1
            elif self._depth:
                self._depth += 1
        elif self._depth:
            self._open_in_content(tag, a)

    def _open_in_content(self, tag: str, a: dict[str, str]) -> None:
        if tag in ("script", "style"):
            self._skip += 1
        elif tag in HEADINGS:
            self._heading, self._heading_text = (int(tag[1]), a.get("id", "")), []
        elif tag == "pre":
            self._pre = True
            self.parts.append("\n```\n")
        elif tag in ("tt", "code"):
            self.parts.append("`")
        elif tag == "li":
            self.parts.append("\n- ")
        elif tag in ("td", "th"):
            self.parts.append(" | ")
        elif tag == "br" or tag in BLOCKS:
            self.parts.append("\n")
        elif tag == "a" and a.get("href"):
            self._href, self._link_text = a["href"], []

    def handle_endtag(self, tag: str) -> None:
        if tag == "title":
            self._in_title = False
        elif tag == "div" and self._depth:
            self._depth -= 1
        elif self._depth:
            self._close_in_content(tag)

    def _close_in_content(self, tag: str) -> None:
        if tag in ("script", "style"):
            self._skip = max(0, self._skip - 1)
        elif tag in HEADINGS and self._heading is not None:
            level, hid = self._heading
            text = re.sub(r"\s+", " ", "".join(self._heading_text)).strip()
            self.headings.append(Heading(level, hid, text))
            self.parts.append(f"\n{'#' * level} {text}\n")
            if level == 2:
                self._section = text
            self._heading = None
        elif tag == "pre":
            self._pre = False
            self.parts.append("\n```\n")
        elif tag in ("tt", "code"):
            self.parts.append("`")
        elif tag == "a" and self._href is not None:
            text = re.sub(r"\s+", " ", "".join(self._link_text)).strip()
            self.links.append(Link(self._href, text, self._section))
            self._href = None
        elif tag in BLOCKS or tag == "li":
            self.parts.append("\n")

    def handle_data(self, data: str) -> None:
        if self._in_title:
            self.title_parts.append(data)
        elif self._depth and not self._skip:
            if self._heading is not None:
                self._heading_text.append(data)
                return
            text = data if self._pre else re.sub(r"\s+", " ", data)
            if self._href is not None:
                self._link_text.append(text)
            self.parts.append(text)


def parse_page(html: str) -> ParsedPage:
    """Parse one wiki page into text, headings and links."""
    parser = _PageParser()
    parser.feed(html)
    text = "".join(parser.parts)
    text = re.sub(r"[ \t]+\n", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text).strip()
    title = (
        re.sub(r"\s+", " ", "".join(parser.title_parts))
        .strip()
        .removesuffix(" - Python Wiki")
    )
    return ParsedPage(title, text, parser.headings, parser.links)


def parse_title_index(html: str, base: str) -> list[str]:
    """Page stems listed by the "All Pages" index, which uses a different template (no #content)."""
    seen: dict[str, None] = {}
    origin = base + "TitleIndex.html"
    for href in re.findall(r'<a\s[^>]*href="([^"]+)"', html):
        stem = stem_of(href, origin, base)
        if stem and decode_name(stem) not in NAV_PAGES:
            seen.setdefault(stem)
    return list(seen)


def split_sections(text: str) -> list[tuple[int, str, str]]:
    """(level, title, body) for the intro and every heading of a page's cleaned text."""
    sections: list[tuple[int, str, str]] = []
    level, title = 0, "(intro)"
    body: list[str] = []
    in_code = False
    for line in text.split("\n"):
        if line.startswith("```"):
            in_code = not in_code
        m = None if in_code else re.match(r"^(#{1,6}) (.+)$", line)
        if m:
            sections.append((level, title, "\n".join(body).strip()))
            level, title, body = len(m.group(1)), m.group(2), []
        else:
            body.append(line)
    sections.append((level, title, "\n".join(body).strip()))
    return [s for s in sections if s[2] or s[0]]


# --------------------------------------------------------------------------- the graph


@dataclass
class Node:
    id: str
    raw: str
    kind: str = "page"
    parent: str | None = None
    sections: list[str] = field(default_factory=list)
    fetched: bool = False
    in_links: int = 0


@dataclass
class Graph:
    nodes: dict[str, Node] = field(default_factory=dict)
    edges: list[tuple[str, str, str]] = field(default_factory=list)
    meta: dict[str, Any] = field(default_factory=dict)
    _seen: set[tuple[str, str, str]] = field(
        default_factory=set, init=False, repr=False
    )

    def add_page(self, stem: str) -> Node:
        """Add (or return) the node of a page. Its file stem is always the canonical one."""
        page_id = decode_name(stem)
        if page_id not in self.nodes:
            parent = page_id.rsplit("/", 1)[0] if "/" in page_id else None
            self.nodes[page_id] = Node(
                page_id, encode_name(page_id), classify(page_id), parent
            )
        return self.nodes[page_id]

    def add_edge(self, src: str, dst: str, kind: str) -> None:
        """Add an edge once; a repeated (src, dst, kind) is ignored."""
        edge = (src, dst, kind)
        if edge not in self._seen:
            self._seen.add(edge)
            self.edges.append(edge)

    def children(self, page_id: str) -> list[str]:
        return sorted(n.id for n in self.nodes.values() if n.parent == page_id)

    def section_ids(self) -> list[str]:
        return [n.id for n in self.nodes.values() if n.kind == "section"]

    def finish(self) -> None:
        """Recompute the derived fields: in-link counts."""
        counts = Counter(dst for _, dst, kind in self.edges if kind == "link")
        for node in self.nodes.values():
            node.in_links = counts.get(node.id, 0)


def save_graph(graph: Graph, cache: Path) -> None:
    cache.mkdir(parents=True, exist_ok=True)
    gitignore = cache / ".gitignore"
    if not gitignore.exists():
        gitignore.write_text("*\n", encoding="utf-8")
    payload = {
        "meta": graph.meta,
        "nodes": [asdict(n) for n in graph.nodes.values()],
        "edges": [list(e) for e in graph.edges],
    }
    (cache / "graph.json").write_text(
        json.dumps(payload, ensure_ascii=False), encoding="utf-8"
    )


def load_graph(cache: Path) -> Graph | None:
    path = cache / "graph.json"
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        graph = Graph(meta=data["meta"])
        graph.nodes = {n["id"]: Node(**n) for n in data["nodes"]}
        for s, d, k in data["edges"]:
            graph.add_edge(s, d, k)
    except (OSError, ValueError, KeyError, TypeError):
        return None
    return graph


def page_path(cache: Path, stem: str) -> Path:
    return cache / "pages" / f"{sha1(stem.encode('utf-8')).hexdigest()[:16]}.json"


def load_page(cache: Path, stem: str) -> dict[str, Any] | None:
    path = page_path(cache, stem)
    if not path.is_file():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


# --------------------------------------------------------------------------- polite fetching


class Fetcher:
    """One request at a time, at least `delay` seconds apart even across processes, capped."""

    def __init__(
        self,
        base: str,
        cache: Path,
        delay: float,
        max_requests: int = MAX_REQUESTS_PER_RUN,
    ) -> None:
        self.base = base
        self.cache = cache
        self.delay = delay
        self.max_requests = max_requests
        self.count = 0

    def get(self, stem: str) -> str:
        """Fetch one page by file stem and return its HTML."""
        if self.count >= self.max_requests:
            raise FetchError(f"request cap of {self.max_requests} reached for this run")
        url = page_url(self.base, stem)
        for attempt in range(3):
            self._wait()
            self.count += 1
            try:
                return self._request(url)
            except urllib.error.HTTPError as err:
                if err.code in (429, 503) and attempt < 2:
                    time.sleep(min(self._retry_after(err), 30.0))
                    continue
                raise FetchError(f"HTTP {err.code} for {url}", err.code) from err
            except (urllib.error.URLError, TimeoutError, OSError) as err:
                raise FetchError(f"{type(err).__name__} for {url}: {err}") from err
        raise FetchError(f"gave up on {url}")

    def _request(self, url: str) -> str:
        request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
        try:
            with urllib.request.urlopen(request, timeout=20) as response:
                return response.read().decode("utf-8", errors="replace")
        finally:
            self._mark()

    @staticmethod
    def _retry_after(err: urllib.error.HTTPError) -> float:
        try:
            return float(err.headers.get("Retry-After", "5"))
        except ValueError:
            return 5.0

    def _stamp(self) -> Path:
        return self.cache / ".last_request"

    def _wait(self) -> None:
        try:
            last = float(self._stamp().read_text(encoding="utf-8"))
        except (OSError, ValueError):
            last = 0.0
        remaining = self.delay - (time.time() - last)
        if remaining > 0:
            time.sleep(remaining)

    def _mark(self) -> None:
        self.cache.mkdir(parents=True, exist_ok=True)
        self._stamp().write_text(str(time.time()), encoding="utf-8")


# --------------------------------------------------------------------------- building


@dataclass
class Config:
    base: str
    cache: Path
    delay: float
    ttl_days: float = 180.0
    max_fetch: int = 60


def ingest_page(graph: Graph, cfg: Config, stem: str, html: str) -> ParsedPage:
    """Cache a fetched page and add its links to the graph."""
    parsed = parse_page(html)
    node = graph.add_page(stem)
    node.fetched = True
    targets: dict[str, None] = {}
    for link in parsed.links:
        target = stem_of(link.href, page_url(cfg.base, stem), cfg.base)
        if target is None or decode_name(target) in NAV_PAGES:
            continue
        other = graph.add_page(target)
        if other.id != node.id:
            graph.add_edge(node.id, other.id, "link")
            targets.setdefault(other.id)
    record = {
        "id": node.id,
        "url": page_url(cfg.base, stem),
        "fetched_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "title": parsed.title,
        "text": parsed.text,
        "headings": [asdict(h) for h in parsed.headings],
        "links": list(targets),
    }
    path = page_path(cfg.cache, stem)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(record, ensure_ascii=False), encoding="utf-8")
    return parsed


def build(cfg: Config) -> Graph:
    """The bounded crawl: index, front page, then the pages the front page links to."""
    fetcher = Fetcher(cfg.base, cfg.cache, cfg.delay)
    graph = Graph()
    catalogue = parse_title_index(fetcher.get("TitleIndex"), cfg.base)
    if not catalogue:
        raise FetchError(
            "the All Pages index lists no pages: the wiki's markup may have changed"
        )
    for stem in catalogue:
        graph.add_page(stem)

    front = parse_page(fetcher.get(ROOT))
    graph.nodes[ROOT] = Node(ROOT, ROOT, "root")
    front_links = [
        (link, stem_of(link.href, page_url(cfg.base, ROOT), cfg.base))
        for link in front.links
    ]
    wiki_links = [
        (link, stem)
        for link, stem in front_links
        if stem and decode_name(stem) not in NAV_PAGES
    ]
    titles = ["(intro)"] if any(link.section is None for link, _ in wiki_links) else []
    titles += [h.text for h in front.headings if h.level == 2]
    if not any(h.level == 2 for h in front.headings):
        raise FetchError(
            "the FrontPage has no sections: the wiki's markup may have changed"
        )
    for title in titles:
        graph.nodes[f"section:{title}"] = Node(
            f"section:{title}", f"section:{title}", "section"
        )
        graph.add_edge(ROOT, f"section:{title}", "contains")
    direct: dict[str, None] = {}
    for link, stem in wiki_links:
        assert stem is not None
        node = graph.add_page(stem)
        title = link.section or "(intro)"
        if title not in node.sections:
            node.sections.append(title)
        graph.add_edge(f"section:{title}", node.id, "section")
        direct.setdefault(node.id)

    errors: list[str] = []
    failed_in_a_row = 0
    for page_id in list(direct)[: cfg.max_fetch]:
        node = graph.nodes[page_id]
        try:
            ingest_page(graph, cfg, node.raw, fetcher.get(node.raw))
            failed_in_a_row = 0
        except FetchError as err:
            errors.append(str(err))
            if err.status == 404:  # a dead link inside the archive, not a sick site
                node.kind = "dead-link"
                continue
            failed_in_a_row += 1
            if failed_in_a_row >= 3:  # the site is unwell: stop asking
                break
    for node in graph.nodes.values():
        if node.parent and node.parent in graph.nodes:
            graph.add_edge(node.parent, node.id, "sub")
    graph.finish()
    graph.meta = {
        "built_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "base": cfg.base,
        "pages": sum(n.kind not in ("section", "root") for n in graph.nodes.values()),
        "fetched": sum(n.fetched for n in graph.nodes.values()),
        "sections": [
            n.id.removeprefix("section:")
            for n in graph.nodes.values()
            if n.kind == "section"
        ],
        "requests": fetcher.count,
        "errors": errors,
    }
    save_graph(graph, cfg.cache)
    return graph


def age_days(graph: Graph) -> float:
    built = datetime.fromisoformat(str(graph.meta["built_at"]))
    return (datetime.now(UTC) - built).total_seconds() / 86400


# --------------------------------------------------------------------------- resolving pages


def resolve(graph: Graph, query: str, base: str = DEFAULT_BASE) -> Node:
    """Find a node from a title, a `(2f)` file stem or a URL; suggest close matches on a miss."""
    candidates = [query]
    stem = stem_of(query, base, base) if query.startswith("http") else None
    if stem:
        candidates.append(stem)
    for cand in candidates:
        page_id = decode_name(cand)
        if page_id in graph.nodes:
            return graph.nodes[page_id]
    lowered = {n.lower(): n for n in graph.nodes}
    if decode_name(query).lower() in lowered:
        return graph.nodes[lowered[decode_name(query).lower()]]
    near = difflib.get_close_matches(
        decode_name(query), list(graph.nodes), n=5, cutoff=0.5
    )
    hint = f" Did you mean: {', '.join(near)}?" if near else " Try `search` first."
    raise SystemExit(f"No page called '{query}'.{hint}")


def read_or_fetch(graph: Graph, cfg: Config, node: Node) -> dict[str, Any]:
    """The cached page record, fetching (one request) and caching it if this is the first read."""
    record = load_page(cfg.cache, node.raw)
    if record is not None:
        return record
    fetcher = Fetcher(cfg.base, cfg.cache, cfg.delay, max_requests=3)
    try:
        ingest_page(graph, cfg, node.raw, fetcher.get(node.raw))
    except FetchError as err:
        if err.status == 404:
            node.kind = "dead-link"
            save_graph(graph, cfg.cache)
        raise
    graph.finish()
    save_graph(graph, cfg.cache)
    loaded = load_page(cfg.cache, node.raw)
    if loaded is None:
        raise FetchError(f"could not cache {node.id}")
    return loaded


# --------------------------------------------------------------------------- ranking


def page_matches(
    node: Node, query: Sequence[str], graph: Graph, record: dict[str, Any] | None
) -> tuple[float, list[str]]:
    """Score one page for the query tokens; also which tokens matched, for the explanation."""
    title = tokenize(node.id)
    score, hit = 0.0, []
    heads: set[str] = set()
    body: Counter[str] = Counter()
    if record:
        heads = {t for h in record["headings"] for t in tokenize(h["text"])}
        body = Counter(tokenize(str(record["text"])))
    for token in query:
        got = 0.0
        if token in title:
            got += 3.0
        elif len(token) >= 4 and any(
            len(t) >= 4 and (t.startswith(token) or token.startswith(t)) for t in title
        ):
            got += 1.5
        if token in heads:
            got += 2.0
        if body[token]:
            got += min(3.0, 0.5 * math.log1p(body[token]))
        if got:
            hit.append(token)
            score += got
    if node.parent and node.parent in graph.nodes and not score:
        inherited = sum(3.0 for t in query if t in tokenize(node.parent))
        score += 0.4 * inherited
    if score:
        score += 0.3 * math.log1p(node.in_links) + (0.5 if node.sections else 0.0)
    return score * KIND_FACTOR.get(node.kind, 1.0), hit


# --------------------------------------------------------------------------- commands


def status_lines(graph: Graph, cfg: Config) -> list[str]:
    meta = graph.meta
    sections = meta.get("sections", [])
    lines = [
        f"Python Wiki graph ready: {meta['pages']:,} pages, {len(sections)} FrontPage sections, "
        f"{meta['fetched']} fetched, built {str(meta['built_at'])[:10]} (cache: {cfg.cache})",
        "Sections: " + "; ".join(str(s) for s in sections),
    ]
    if meta.get("errors"):
        lines.append(
            f"Warning: {len(meta['errors'])} page(s) failed to fetch: {meta['errors']}"
        )
    lines.append(
        "Next: `map` to review the sections, `search <topics>` to find pages, "
        "`read <page> --outline` to go deeper."
    )
    return lines


def cmd_ensure(args: argparse.Namespace, cfg: Config) -> int:
    graph = load_graph(cfg.cache)
    fresh = graph is not None and age_days(graph) <= cfg.ttl_days
    if graph is None or not fresh:
        if args.offline:
            print(
                "Python Wiki graph unavailable (offline and nothing cached). Continue with "
                "python-standards alone and say so in the report."
            )
            return 0
        try:
            print(
                f"Building the Python Wiki graph (about {cfg.max_fetch + 2} requests, "
                f"{cfg.delay:g}s apart)...",
                file=sys.stderr,
            )
            graph = build(cfg)
        except (
            Exception
        ) as err:  # CLI boundary: a bug here must not stop the caller's validation
            if graph is None:
                print(
                    f"Python Wiki graph unavailable ({type(err).__name__}: {err}). Continue "
                    f"with python-standards alone and say so in the report."
                )
                return 0
            print(f"Warning: could not refresh ({err}); using the cached graph.")
    for line in status_lines(graph, cfg):
        print(line)
    return 0


def cmd_build(args: argparse.Namespace, cfg: Config) -> int:
    try:
        graph = build(cfg)
    except FetchError as err:
        print(f"Build failed: {err}", file=sys.stderr)
        return 1
    for line in status_lines(graph, cfg):
        print(line)
    return 0


def need_graph(cfg: Config) -> Graph:
    graph = load_graph(cfg.cache)
    if graph is None:
        raise SystemExit("No graph yet: run `ensure` first.")
    return graph


def cmd_map(args: argparse.Namespace, cfg: Config) -> int:
    graph = need_graph(cfg)
    print(
        f"{graph.meta['pages']:,} pages in the wiki; the FrontPage has these sections:\n"
    )
    for sid in graph.section_ids():
        title = sid.removeprefix("section:")
        if args.section and args.section.lower() not in title.lower():
            continue
        pages = sorted(
            (graph.nodes[d] for s, d, k in graph.edges if s == sid and k == "section"),
            key=lambda n: (-n.in_links, n.id),
        )
        print(f"## {title}  ({len(pages)} pages)")
        for n in pages:
            subs = len(graph.children(n.id))
            flags = ", ".join(
                x
                for x in (
                    "fetched" if n.fetched else "",
                    f"{n.in_links} in" if n.in_links else "",
                    f"{subs} sub" if subs else "",
                    n.kind if n.kind != "page" else "",
                )
                if x
            )
            print(f"  {n.id}" + (f"   [{flags}]" if flags else ""))
        print()
    if args.section:
        return 0
    families = Counter(
        n.id.split("/")[0]
        for n in graph.nodes.values()
        if n.kind in ("page", "category")
    )
    on_front = {n.id for n in graph.nodes.values() if n.sections}
    print(
        "## Largest page families (a page and its subpages); * = not linked from the FrontPage"
    )
    for name, count in families.most_common(args.families):
        if count >= 3:
            print(f"  {name}{'' if name in on_front else ' *'}   ({count} pages)")
    return 0


def cmd_search(args: argparse.Namespace, cfg: Config) -> int:
    graph = need_graph(cfg)
    tokens = [t for term in args.terms for t in tokenize(term)]
    if not tokens:
        raise SystemExit("Give at least one search term.")
    ranked: list[tuple[float, Node, list[str]]] = []
    for node in graph.nodes.values():
        if node.kind in ("root", "section") or (args.kind and node.kind != args.kind):
            continue
        record = load_page(cfg.cache, node.raw) if node.fetched else None
        if args.fetched and record is None:
            continue
        score, hit = page_matches(node, tokens, graph, record)
        if score > 0:
            ranked.append((score, node, hit))
    ranked.sort(key=lambda r: (-r[0], len(r[1].id)))
    if not ranked:
        print(
            "No page matches. Try a synonym, a broader word, or `map` to browse the sections."
        )
        return 0
    for score, node, hit in ranked[: args.top]:
        where = f"  in: {'; '.join(node.sections)}" if node.sections else ""
        tag = f" ({node.kind})" if node.kind != "page" else ""
        print(
            f"{score:5.1f}  {node.id}{tag}{' [fetched]' if node.fetched else ''}"
            f"  matched: {', '.join(hit)}{where}"
        )
    return 0


def cmd_neighbors(args: argparse.Namespace, cfg: Config) -> int:
    graph = need_graph(cfg)
    node = resolve(graph, args.page, cfg.base)
    out = sorted({d for s, d, k in graph.edges if s == node.id and k == "link"})
    inc = sorted({s for s, d, k in graph.edges if d == node.id and k == "link"})
    print(f"{node.id}  ({node.kind}{', fetched' if node.fetched else ', not fetched'})")
    print(f"  parent:     {node.parent or '-'}")
    print(f"  sections:   {'; '.join(node.sections) or '-'}")
    for label, items in (
        ("subpages", graph.children(node.id)),
        ("links to", out),
        ("linked from", inc),
    ):
        shown = items[: args.limit]
        more = f" (+{len(items) - len(shown)} more)" if len(items) > len(shown) else ""
        print(f"  {label + ':':11} {', '.join(shown) or '-'}{more}")
    if not node.fetched:
        print("  (links out are only known for fetched pages: `read` fetches one)")
    return 0


def cmd_read(args: argparse.Namespace, cfg: Config) -> int:
    graph = need_graph(cfg)
    node = resolve(graph, args.page, cfg.base)
    if node.kind == "dead-link":
        print(
            f"{node.id} is a dead link in the archive (it returned 404): nothing to read.",
            file=sys.stderr,
        )
        return 1
    try:
        record = read_or_fetch(graph, cfg, node)
    except FetchError as err:
        print(f"Could not read {node.id}: {err}", file=sys.stderr)
        return 1
    text = str(record["text"])
    print(f"# {record['title'] or node.id}\n{record['url']}\n{ARCHIVE_NOTE}\n")
    sections = split_sections(text)
    if args.outline:
        for level, title, body in sections:
            print(f"{'  ' * max(level - 1, 0)}{title}  ({len(body):,} chars)")
        return 0
    if args.section:
        wanted = [
            i for i, s in enumerate(sections) if args.section.lower() in s[1].lower()
        ]
        if not wanted:
            raise SystemExit(
                f"No heading contains '{args.section}'. Use --outline to list them."
            )
        first = wanted[0]
        level = sections[first][0]
        chosen = [sections[first]]
        for lvl, title, body in sections[first + 1 :]:
            if lvl and lvl <= level:
                break
            chosen.append((lvl, title, body))
        text = "\n\n".join(f"{'#' * max(lv, 1)} {t}\n{b}" for lv, t, b in chosen)
    window = text[args.offset : args.offset + args.max_chars]
    print(window)
    if args.offset + args.max_chars < len(text):
        print(
            f"\n[... {len(text):,} chars in total; continue with --offset {args.offset + args.max_chars}]"
        )
    return 0


def cmd_export(args: argparse.Namespace, cfg: Config) -> int:
    graph = need_graph(cfg)
    if args.format == "json":
        out = (cfg.cache / "graph.json").read_text(encoding="utf-8")
    else:
        keep = {
            n.id
            for n in graph.nodes.values()
            if n.kind in ("root", "section") or n.fetched
        }
        lines = [
            "digraph pythonwiki {",
            "  rankdir=LR;",
            "  node [shape=box, fontsize=10];",
        ]
        for n in graph.nodes.values():
            if n.id in keep:
                shape = "ellipse" if n.kind in ("root", "section") else "box"
                lines.append(f'  "{n.id}" [shape={shape}];')
        for s, d, k in graph.edges:
            if s in keep and d in keep and k != "sub":
                lines.append(f'  "{s}" -> "{d}" [label="{k}", fontsize=8];')
        out = "\n".join([*lines, "}"]) + "\n"
    if args.out:
        Path(args.out).write_text(out, encoding="utf-8")
        print(f"Saved: {args.out}")
    else:
        print(out)
    return 0


# --------------------------------------------------------------------------- main


def build_parser() -> argparse.ArgumentParser:
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument(
        "--cache-dir", default=os.environ.get("PYTHON_WIKI_CACHE", DEFAULT_CACHE)
    )
    common.add_argument("--base-url", default=DEFAULT_BASE, help=argparse.SUPPRESS)
    common.add_argument(
        "--delay", type=float, default=1.0, help="seconds between requests"
    )
    common.add_argument("--ttl-days", type=float, default=180.0)
    common.add_argument(
        "--max-fetch", type=int, default=60, help="pages to fetch in a build"
    )

    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser(
        "ensure", parents=[common], help="build if missing or stale, print status"
    )
    p.add_argument("--offline", action="store_true", help="never touch the network")
    sub.add_parser("build", parents=[common], help="force a rebuild")
    p = sub.add_parser("map", parents=[common], help="review the sections")
    p.add_argument("--section", help="only the sections whose title contains this")
    p.add_argument("--families", type=int, default=25)
    p = sub.add_parser("search", parents=[common], help="rank pages for topics")
    p.add_argument("terms", nargs="+")
    p.add_argument("--top", type=int, default=12)
    p.add_argument(
        "--kind", choices=["page", "category", "question", "event", "idea", "wiki-meta"]
    )
    p.add_argument("--fetched", action="store_true", help="only pages already fetched")
    p = sub.add_parser(
        "neighbors", parents=[common], help="parent, subpages, links in and out"
    )
    p.add_argument("page")
    p.add_argument("--limit", type=int, default=25)
    p = sub.add_parser(
        "read", parents=[common], help="outline, one section, or text of a page"
    )
    p.add_argument("page")
    p.add_argument("--outline", action="store_true")
    p.add_argument("--section", help="only the section whose heading contains this")
    p.add_argument("--max-chars", type=int, default=6000)
    p.add_argument("--offset", type=int, default=0)
    p = sub.add_parser("export", parents=[common], help="the graph as DOT or JSON")
    p.add_argument("--format", choices=["dot", "json"], default="dot")
    p.add_argument("--out")
    return ap


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    cfg = Config(
        base=args.base_url if args.base_url.endswith("/") else args.base_url + "/",
        cache=Path(args.cache_dir),
        delay=args.delay,
        ttl_days=args.ttl_days,
        max_fetch=args.max_fetch,
    )
    handlers = {
        "ensure": cmd_ensure,
        "build": cmd_build,
        "map": cmd_map,
        "search": cmd_search,
        "neighbors": cmd_neighbors,
        "read": cmd_read,
        "export": cmd_export,
    }
    return handlers[args.cmd](args, cfg)


if __name__ == "__main__":
    sys.exit(main())
