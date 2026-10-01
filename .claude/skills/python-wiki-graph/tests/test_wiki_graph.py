"""Offline tests for wiki_graph.py, against a local mock of the wiki's static export.

Run: uv run pytest .claude/skills/python-wiki-graph/tests -q
Nothing here touches the real wiki, which asks crawlers to go easy.
"""

import importlib.util
import json
import socketserver
import subprocess
import sys
import threading
import urllib.parse
from collections.abc import Iterator
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from time import monotonic
from typing import Any

import pytest

SCRIPT = Path(__file__).parent.parent / "scripts" / "wiki_graph.py"
spec = importlib.util.spec_from_file_location("wiki_graph", SCRIPT)
assert spec and spec.loader
wg = importlib.util.module_from_spec(spec)
sys.modules["wiki_graph"] = wg
spec.loader.exec_module(wg)

HEADER = (
    '<a href="/python/FrontPage.html">Home</a><a href="/python/TitleIndex.html">All</a>'
)


def page(title: str, body: str) -> str:
    return (
        f"<html><head><title>{title} - Python Wiki</title></head><body>"
        f'<div class="banner">This wiki is being archived</div>{HEADER}'
        f'<div id="page"><div id="content">{body}</div></div>'
        "<script>var noise = 1;</script></body></html>"
    )


PAGES = {
    "TitleIndex": (
        "<html><body>"
        + HEADER
        + "<ul>"
        + "".join(
            f'<li><a href="/python/{s}.html">{s}</a></li>'
            for s in [
                "BeginnersGuide",
                "Concurrency",
                "Concurrency(2f)Patterns",
                "PythonSpeed",
                "PythonSpeed(2f)PerformanceTips",
                "CategoryDocumentation",
                "Flaky",
                "Missing",
                "Asking%20for%20Help(2f)Why%20is%20my%20loop%20slow",
                "Two(20)Words",
                "PyCon2006",
                "Unlinked",
            ]
        )
        + "</ul></body></html>"
    ),
    "FrontPage": page(
        "FrontPage",
        '<h1 id="w">The Python Wiki</h1><p>See <a href="/python/Concurrency.html">concurrency</a>'
        ' and <a href="https://example.com/python/Elsewhere.html">elsewhere</a>.</p>'
        '<h2 id="a">Getting Started</h2><a href="/python/BeginnersGuide.html">Guide</a>'
        '<a href="./PythonSpeed.html">Speed</a><a href="/python/FrontPage.html#start">top</a>'
        '<a href="mailto:x@y.z">mail</a>'
        '<h2 id="b">Software</h2><a href="/python/CategoryDocumentation.html">Docs</a>'
        '<a href="/python/Flaky.html">Flaky</a><a href="/python/Missing.html">Gone</a>'
        '<a href="/python/Two%20Words.html">Two words</a>'
        '<a href="/python/Three%20Words.html">Three words</a>',
    ),
    "BeginnersGuide": page(
        "BeginnersGuide",
        '<h2 id="x">Install</h2><p>Use <tt>pip</tt>.</p><pre>print("hi")</pre>'
        '<h2 id="y">Next</h2><a href="./PythonSpeed.html">speed</a><a href="/python/Concurrency.html">c</a>',
    ),
    "Concurrency": page(
        "Concurrency",
        "<h2>Threads</h2><p>Threads share memory. The GIL serialises bytecode.</p>",
    ),
    "PythonSpeed": page(
        "PythonSpeed",
        "<h2>Use the best algorithms</h2><p>A generator avoids a list.</p><h3>Profiling</h3>"
        '<p>Measure first.</p><a href="./PythonSpeed(2f)PerformanceTips.html">tips</a>',
    ),
    "PythonSpeed(2f)PerformanceTips": page(
        "PythonSpeed/PerformanceTips",
        "<h2>String concatenation</h2><p>Use join, not +=.</p><h2>Loops</h2><p>Avoid xrange chatter.</p>",
    ),
    "CategoryDocumentation": page(
        "CategoryDocumentation", '<a href="/python/BeginnersGuide.html">g</a>'
    ),
    "Flaky": page("Flaky", "<p>Works on the second try.</p>"),
    "Two(20)Words": page(
        "Two Words", "<p>The file name escapes the space as (20).</p>"
    ),
    "Three(20)Words": page("Three Words", "<p>Linked, but missing from the index.</p>"),
}


class Handler(BaseHTTPRequestHandler):
    hits: list[tuple[float, str]] = []
    flaky_seen = False

    def do_GET(self) -> None:
        name = urllib.parse.unquote(
            self.path.removeprefix("/python/").removesuffix(".html")
        )
        Handler.hits.append((monotonic(), self.path))
        if name == "Flaky" and not Handler.flaky_seen:
            Handler.flaky_seen = True
            self.send_response(429)
            self.send_header("Retry-After", "0")
            self.end_headers()
            return
        body = PAGES.get(name)
        if body is None:
            self.send_response(404)
            self.end_headers()
            return
        data = body.encode()
        self.send_response(200)
        self.send_header("Content-Type", "text/html")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, *args: Any) -> None:  # keep test output quiet
        pass


class LocalServer(ThreadingHTTPServer):
    """HTTPServer.server_bind does a reverse-DNS lookup that can stall for tens of seconds."""

    def server_bind(self) -> None:
        socketserver.TCPServer.server_bind(self)
        self.server_name, self.server_port = "127.0.0.1", self.server_address[1]


@pytest.fixture()
def server() -> Iterator[str]:
    Handler.hits = []
    Handler.flaky_seen = False
    httpd = LocalServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{httpd.server_address[1]}/python/"
    httpd.shutdown()


def run(
    cmd: str, cache: Path, base: str, *extra: str
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            cmd,
            "--cache-dir",
            str(cache),
            "--base-url",
            base,
            "--delay",
            "0.05",
            *extra,
        ],
        capture_output=True,
        text=True,
        timeout=60,
    )


def graph_of(cache: Path) -> dict[str, Any]:
    return json.loads((cache / "graph.json").read_text())


# --------------------------------------------------------------------------- pure functions


def test_decode_name_and_classify() -> None:
    assert (
        wg.decode_name("PythonSpeed(2f)PerformanceTips")
        == "PythonSpeed/PerformanceTips"
    )
    assert wg.decode_name("Asking%20for%20Help.html") == "Asking for Help"
    assert wg.classify("CategoryDocumentation") == "category"
    assert wg.classify("Asking for Help/why") == "question"
    assert wg.classify("PyCon2006") == "event"
    assert wg.classify("Concurrency") == "page"


def test_decode_name_handles_grouped_utf8_bytes() -> None:
    # Taken from real page names: runs of unsafe characters are escaped as UTF-8 bytes.
    assert (
        wg.decode_name("thread started using(2027)bg(2720)ends")
        == "thread started using 'bg' ends"
    )
    assert (
        wg.decode_name("error(3a20)exceptions(2e222e20)How")
        == 'error: exceptions.". How'
    )
    assert wg.decode_name("caf(c3a9)") == "café"
    assert "\ufffd" in wg.decode_name("broken(ffffff)name")  # invalid bytes never raise


@pytest.mark.parametrize("broken", ["TitleIndex", "FrontPage"])
def test_a_changed_wiki_fails_loudly_not_quietly(
    tmp_path: Path, server: str, broken: str
) -> None:
    """If the markup changes, report 'unavailable': never a near-empty graph called ready."""
    saved = PAGES[broken]
    PAGES[broken] = "<html><body><p>a redesigned wiki</p></body></html>"
    try:
        result = run("ensure", tmp_path, server)
    finally:
        PAGES[broken] = saved
    assert result.returncode == 0, result.stderr
    assert "unavailable" in result.stdout and "markup may have changed" in result.stdout
    assert not (tmp_path / "graph.json").exists()


def test_parse_page_extracts_content_only() -> None:
    parsed = wg.parse_page(PAGES["BeginnersGuide"])
    assert parsed.title == "BeginnersGuide"
    assert [h.text for h in parsed.headings] == ["Install", "Next"]
    assert (
        "This wiki is being archived" not in parsed.text and "noise" not in parsed.text
    )
    assert "`pip`" in parsed.text and '```\nprint("hi")\n```' in parsed.text
    assert [(link.href, link.section) for link in parsed.links] == [
        ("./PythonSpeed.html", "Next"),
        ("/python/Concurrency.html", "Next"),
    ]


def test_encode_name_is_the_inverse_of_decode_name() -> None:
    # Real names from the index, including the ones that need every rule.
    for stem in (
        "PythonSpeed(2f)PerformanceTips",
        "2(2e)x(2d)vs(2d)3(2e)x(2d)survey",
        "GUI(20)Programming(20)in(20)Python",
        "using(2027)bg(2720)ends",
        "caf(c3a9)",
        "snake_case_Name9",
    ):
        assert wg.encode_name(wg.decode_name(stem)) == stem
    assert wg.encode_name("Two Words") == "Two(20)Words"


def test_code_comments_are_not_headings() -> None:
    parsed = wg.parse_page(
        page(
            "Sort",
            "<h2>Sorting</h2><pre># sort in place\nxs.sort()</pre><h2>Loops</h2><p>text</p>",
        )
    )
    sections = wg.split_sections(parsed.text)
    assert [title for _, title, _ in sections] == ["Sorting", "Loops"]
    assert "# sort in place" in sections[0][2], (
        "the comment stays in the body of its section"
    )


def test_stem_of_stays_on_the_wiki() -> None:
    base = "http://h/python/"
    assert wg.stem_of("./A(2f)B.html", base + "X.html", base) == "A(2f)B"
    assert wg.stem_of("/python/GUI%20Programming.html", base, base) == "GUI Programming"
    assert wg.stem_of("https://example.com/python/A.html", base, base) is None
    assert wg.stem_of("/python/FrontPage.html#start", base, base) == "FrontPage"
    assert wg.stem_of("/other/A.html", base, base) is None


def test_request_cap_is_enforced(tmp_path: Path, server: str) -> None:
    fetcher = wg.Fetcher(server, tmp_path, delay=0.0, max_requests=2)
    fetcher.get("Concurrency")
    fetcher.get("PythonSpeed")
    with pytest.raises(wg.FetchError, match="request cap"):
        fetcher.get("BeginnersGuide")
    assert len(Handler.hits) == 2


# --------------------------------------------------------------------------- the crawl


def test_build_makes_the_graph(tmp_path: Path, server: str) -> None:
    result = run("ensure", tmp_path, server)
    assert result.returncode == 0, result.stderr
    assert "graph ready" in result.stdout
    data = graph_of(tmp_path)
    nodes = {n["id"]: n for n in data["nodes"]}
    assert {"section:(intro)", "section:Getting Started", "section:Software"} <= set(
        nodes
    )
    assert nodes["Concurrency"]["sections"] == ["(intro)"]
    assert nodes["PythonSpeed/PerformanceTips"]["parent"] == "PythonSpeed"
    assert nodes["Asking for Help/Why is my loop slow"]["kind"] == "question"
    assert nodes["CategoryDocumentation"]["kind"] == "category"
    assert nodes["PythonSpeed"]["fetched"] and not nodes["Unlinked"]["fetched"]
    two = nodes["Two Words"]
    assert two["fetched"] and two["raw"] == "Two(20)Words", (
        "fetched under its real name"
    )
    three = nodes[
        "Three Words"
    ]  # not in the index: the name has to be derived, not copied
    assert three["fetched"] and three["raw"] == "Three(20)Words"
    edges = {tuple(e) for e in data["edges"]}
    assert ("FrontPage", "section:Software", "contains") in edges
    assert ("section:Getting Started", "BeginnersGuide", "section") in edges
    assert ("BeginnersGuide", "PythonSpeed", "link") in edges
    assert ("PythonSpeed", "PythonSpeed/PerformanceTips", "sub") in edges
    assert not any("Elsewhere" in n for n in nodes), "must not follow other hosts"
    assert not {"TitleIndex", "RecentChanges"} & set(nodes), "navigation is not content"
    assert (tmp_path / ".gitignore").read_text() == "*\n"


def test_one_failed_page_does_not_sink_the_build(tmp_path: Path, server: str) -> None:
    run("ensure", tmp_path, server)
    meta = graph_of(tmp_path)["meta"]
    assert any("Missing" in e for e in meta["errors"])
    nodes = {n["id"]: n for n in graph_of(tmp_path)["nodes"]}
    assert nodes["Flaky"]["fetched"], "a 429 with Retry-After is retried"
    assert not nodes["Missing"]["fetched"] and nodes["Missing"]["kind"] == "dead-link"


def test_second_call_makes_no_requests(tmp_path: Path, server: str) -> None:
    run("ensure", tmp_path, server)
    before = len(Handler.hits)
    again = run("ensure", tmp_path, server)
    assert "graph ready" in again.stdout
    assert len(Handler.hits) == before


def test_stale_cache_is_rebuilt(tmp_path: Path, server: str) -> None:
    run("ensure", tmp_path, server)
    before = len(Handler.hits)
    run("ensure", tmp_path, server, "--ttl-days", "0")
    assert len(Handler.hits) > before


def test_offline_and_unreachable_never_fail_the_caller(
    tmp_path: Path, server: str
) -> None:
    offline = run("ensure", tmp_path / "a", server, "--offline")
    assert offline.returncode == 0 and "unavailable" in offline.stdout
    assert Handler.hits == []
    dead = run("ensure", tmp_path / "b", "http://127.0.0.1:1/python/")
    assert dead.returncode == 0 and "unavailable" in dead.stdout


def test_requests_are_spaced_by_the_delay(tmp_path: Path, server: str) -> None:
    subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "ensure",
            "--cache-dir",
            str(tmp_path),
            "--base-url",
            server,
            "--delay",
            "0.3",
        ],
        capture_output=True,
        timeout=120,
    )
    times = [t for t, _ in Handler.hits]
    gaps = [b - a for a, b in zip(times, times[1:], strict=False)]
    assert len(times) > 5 and min(gaps) >= 0.25, f"smallest gap {min(gaps):.3f}s"


# --------------------------------------------------------------------------- using the graph


def test_search_prefers_documentation_over_chatter(tmp_path: Path, server: str) -> None:
    run("ensure", tmp_path, server)
    out = run("search", tmp_path, server, "speed", "loop").stdout.splitlines()
    assert out[0].split()[1] == "PythonSpeed"
    ids = [line.split(maxsplit=1)[1] for line in out]
    slow = next(i for i, line in enumerate(ids) if line.startswith("Asking for Help"))
    assert slow > 0, "a user question ranks below the documentation"
    assert "No page matches" in run("search", tmp_path, server, "zzzz").stdout


def test_read_fetches_once_then_serves_from_cache(tmp_path: Path, server: str) -> None:
    run("ensure", tmp_path, server)
    before = len(Handler.hits)
    outline = run("read", tmp_path, server, "PythonSpeed/PerformanceTips", "--outline")
    assert (
        "String concatenation" in outline.stdout
        and "archived wiki snapshot" in outline.stdout
    )
    assert len(Handler.hits) == before + 1
    section = run(
        "read", tmp_path, server, "PythonSpeed(2f)PerformanceTips", "--section", "loops"
    )
    assert "xrange" in section.stdout and "join" not in section.stdout
    cut = run(
        "read", tmp_path, server, "PythonSpeed/PerformanceTips", "--max-chars", "20"
    )
    assert "continue with --offset 20" in cut.stdout
    assert len(Handler.hits) == before + 1, "later reads use the cache"
    assert graph_of(tmp_path)["nodes"]  # the graph was updated and still loads


def test_neighbors_and_unknown_page(tmp_path: Path, server: str) -> None:
    run("ensure", tmp_path, server)
    out = run("neighbors", tmp_path, server, "PythonSpeed").stdout
    assert "PythonSpeed/PerformanceTips" in out and "BeginnersGuide" in out
    bad = run("read", tmp_path, server, "Concurency")
    assert bad.returncode != 0 and "Did you mean: Concurrency" in bad.stderr


def test_map_lists_every_section(tmp_path: Path, server: str) -> None:
    run("ensure", tmp_path, server)
    out = run("map", tmp_path, server).stdout
    for section in ("(intro)", "Getting Started", "Software"):
        assert f"## {section}" in out
    assert "Largest page families" in out


def test_dead_links_are_neither_searched_nor_read(tmp_path: Path, server: str) -> None:
    run("ensure", tmp_path, server)
    assert "Missing" not in run("search", tmp_path, server, "missing").stdout
    before = len(Handler.hits)
    result = run(
        "read", tmp_path, server, "Missing"
    )  # already known dead: no request at all
    assert result.returncode == 1 and "dead link" in result.stderr
    assert len(Handler.hits) == before
