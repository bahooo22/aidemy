"""Regression tests for skills/aidemy/scripts. Stdlib only.

Run from the repo root:  python3 -m unittest discover -s tests
Each test names the GitHub issue it guards.
"""
import contextlib
import hashlib
import io
import json
import numpy
import os
import re
import socket
import subprocess
import sys
import tempfile
import types
import unittest
import zipfile
from pathlib import Path
from unittest import mock

SCRIPTS = Path(__file__).resolve().parents[1] / "skills" / "aidemy" / "scripts"
sys.path.insert(0, str(SCRIPTS))

import check_lessons  # noqa: E402
import get_voices  # noqa: E402
import package_class  # noqa: E402
import render_audio  # noqa: E402
import scrape  # noqa: E402
import voice_lab  # noqa: E402


ATOM = """<?xml version="1.0"?>
<feed xmlns="http://www.w3.org/2005/Atom">
<entry>
  <title>Blogger order</title>
  <published>2024-01-02T00:00:00Z</published>
  <content type="html">short summary</content>
  <link rel="replies" type="application/atom+xml" href="https://blog.example.com/feeds/123/comments/default"/>
  <link rel="edit" type="application/atom+xml" href="https://www.blogger.com/feeds/1/posts/default/123"/>
  <link rel="self" type="application/atom+xml" href="https://www.blogger.com/feeds/1/posts/default/123"/>
  <link rel="alternate" type="text/html" href="https://blog.example.com/2024/01/my-post.html"/>
</entry>
<entry>
  <title>No rel at all</title>
  <link href="https://blog.example.com/2024/01/plain.html"/>
</entry>
<entry>
  <title>Enclosure first</title>
  <link rel="enclosure" type="audio/mpeg" href="https://blog.example.com/ep1.mp3"/>
  <link rel="alternate" type="text/html" href="https://blog.example.com/2024/01/ep1.html"/>
</entry>
<entry>
  <title>Only a self link</title>
  <link rel="self" href="https://blog.example.com/feeds/999"/>
</entry>
</feed>"""


class AtomLinks(unittest.TestCase):
    """Issue #2: the entry url is the rel="alternate" link, not the first <link>."""

    def test_prefers_alternate_over_earlier_links(self):
        urls = [it["url"] for it in scrape.feed_items(ATOM)]
        self.assertEqual(urls[0], "https://blog.example.com/2024/01/my-post.html")
        self.assertEqual(urls[1], "https://blog.example.com/2024/01/plain.html")
        self.assertEqual(urls[2], "https://blog.example.com/2024/01/ep1.html")

    def test_falls_back_to_the_only_link(self):
        urls = [it["url"] for it in scrape.feed_items(ATOM)]
        self.assertEqual(urls[3], "https://blog.example.com/feeds/999")


INDEX = """<?xml version="1.0"?>
<sitemapindex xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
<sitemap><loc>https://site.com/post-sitemap1.xml</loc><lastmod>2024-05-01</lastmod></sitemap>
<sitemap><loc>https://site.com/post-sitemap2.xml</loc><lastmod>2024-06-01</lastmod></sitemap>
<sitemap><loc>https://site.com/page-sitemap.xml</loc></sitemap>
</sitemapindex>"""

CHILD = """<?xml version="1.0"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
<url><loc>https://site.com/blog/{a}</loc><lastmod>{da}T10:00:00+00:00</lastmod></url>
<url><loc>https://site.com/blog/{b}</loc><lastmod>{db}</lastmod></url>
<url><loc>https://site.com/about</loc></url>
</urlset>"""

SELF_INDEX = """<sitemapindex><sitemap><loc>https://loop.com/sitemap.xml</loc></sitemap></sitemapindex>"""


class SitemapIndex(unittest.TestCase):
    """Issue #3: a sitemap index is followed instead of yielding zero posts."""

    def test_follows_child_sitemaps(self):
        pages = {
            "https://site.com/sitemap.xml": INDEX,
            "https://site.com/post-sitemap1.xml": CHILD.format(a="one", da="2024-01-05", b="two", db="2024-02-05"),
            "https://site.com/post-sitemap2.xml": CHILD.format(a="three", da="2024-03-05", b="four", db="2024-04-05"),
            "https://site.com/page-sitemap.xml": "<urlset><url><loc>https://site.com/contact</loc></url></urlset>",
        }
        site = {"sitemaps": ["https://site.com/sitemap.xml"], "url_pattern": r"site\.com/blog/"}
        with mock.patch.object(scrape, "fetch", side_effect=lambda u: pages[u]):
            entries = scrape.sitemap_entries(site)
        self.assertEqual(entries, [
            ("2024-04-05", "https://site.com/blog/four"),
            ("2024-03-05", "https://site.com/blog/three"),
            ("2024-02-05", "https://site.com/blog/two"),
            ("2024-01-05", "https://site.com/blog/one"),
        ])

    def test_plain_urlset_still_works(self):
        pages = {"https://site.com/post-sitemap1.xml": CHILD.format(a="x", da="2024-01-01", b="y", db="2024-01-02")}
        site = {"sitemaps": ["https://site.com/post-sitemap1.xml"], "url_pattern": r"site\.com/blog/"}
        with mock.patch.object(scrape, "fetch", side_effect=lambda u: pages[u]):
            entries = scrape.sitemap_entries(site)
        self.assertEqual([u for _, u in entries], ["https://site.com/blog/y", "https://site.com/blog/x"])

    def test_url_in_two_child_sitemaps_is_listed_once(self):
        # WordPress lists posts in its post sitemap and again in its image sitemap.
        pages = {
            "https://site.com/sitemap.xml": "<sitemapindex><sitemap><loc>https://site.com/posts.xml</loc></sitemap>"
                                            "<sitemap><loc>https://site.com/images.xml</loc></sitemap></sitemapindex>",
            "https://site.com/posts.xml": CHILD.format(a="one", da="2024-01-05", b="two", db="2024-02-05"),
            "https://site.com/images.xml": "<urlset><url><loc>https://site.com/blog/one</loc>"
                                           "<lastmod>2024-06-01</lastmod></url></urlset>",
        }
        site = {"sitemaps": ["https://site.com/sitemap.xml"], "url_pattern": r"site\.com/blog/"}
        with mock.patch.object(scrape, "fetch", side_effect=lambda u: pages[u]):
            entries = scrape.sitemap_entries(site)
        self.assertEqual(entries, [("2024-06-01", "https://site.com/blog/one"), ("2024-02-05", "https://site.com/blog/two")])

    def test_self_referencing_index_terminates(self):
        pages = {"https://loop.com/sitemap.xml": SELF_INDEX}
        site = {"sitemaps": ["https://loop.com/sitemap.xml"], "url_pattern": r"loop\.com/"}
        with mock.patch.object(scrape, "fetch", side_effect=lambda u: pages[u]) as f:
            entries = scrape.sitemap_entries(site)
        self.assertEqual(entries, [])
        self.assertLess(f.call_count, 10)


CARD_OK = """**Слушать:** x.mp3 (2 мин)
**Идея в трёх строках**
**Зачем:** чтобы не спорить вслепую
**Кто говорит:** практики
**Попробуй** · быстрый шаг · 5 минут
**Правило** называй точку выхода до разговора
**Пропустить** ничего
**Глубже (опционально)** ссылки
https://example.com/a"""

CARD_TRY_IT_COMMENTED = """<!-- черновик: **Попробуй** заполнить после рендера -->
**Слушать:** x.mp3 (2 мин)
**Идея в трёх строках**
**Зачем:** чтобы не спорить вслепую
**Кто говорит:** практики
**Правило** называй точку выхода до разговора
**Пропустить** ничего
**Глубже (опционально)** ссылки
https://example.com/a"""

CARD_DEMAND_IN_COMMENT = CARD_OK.replace("**Попробуй**", "<!-- заметка: you must fix the ending -->\n**Попробуй**")

CARD_URL_ONLY_IN_COMMENT = CARD_OK.replace("\nhttps://example.com/a", "\n<!-- https://example.com/a -->")

CARD_BAD_URL_IN_COMMENT = CARD_OK + "\n<!-- maybe also https://example.com/never-fetched -->"


class CardComments(unittest.TestCase):
    """Issue #4: every card check runs on the text the learner sees, comments removed."""

    URLS = {"https://example.com/a"}

    def test_clean_card_passes(self):
        self.assertEqual(check_lessons.check_card(CARD_OK, self.URLS), [])

    def test_section_only_inside_a_comment_is_missing(self):
        problems = check_lessons.check_card(CARD_TRY_IT_COMMENTED, self.URLS)
        self.assertIn("card missing '**Попробуй**'", problems)

    def test_demand_phrase_inside_a_mid_card_comment_is_ignored(self):
        self.assertEqual(check_lessons.check_card(CARD_DEMAND_IN_COMMENT, self.URLS), [])

    def test_url_only_inside_a_comment_does_not_count_as_a_source(self):
        problems = check_lessons.check_card(CARD_URL_ONLY_IN_COMMENT, self.URLS)
        self.assertIn("card cites no source", problems)

    def test_unfetched_url_inside_a_comment_does_not_fail(self):
        self.assertEqual(check_lessons.check_card(CARD_BAD_URL_IN_COMMENT, self.URLS), [])


class ZipMembers(unittest.TestCase):
    """Issue #5: two mp3s in one lesson folder keep distinct names in the zip."""

    def test_duplicate_mp3s_keep_distinct_member_names(self):
        with tempfile.TemporaryDirectory() as td:
            ws = Path(td)
            one = ws / "class" / "01-lesson"
            two = ws / "class" / "02-other"
            one.mkdir(parents=True)
            two.mkdir(parents=True)
            (one / "old.mp3").write_bytes(b"OLD AUDIO")
            (one / "new.mp3").write_bytes(b"NEW AUDIO")
            (two / "other.mp3").write_bytes(b"OTHER")
            out = ws / "deliver"
            out.mkdir()
            made = package_class.zip_audio(ws, out, 1024 * 1024)
            with zipfile.ZipFile(made[0]) as z:
                names = z.namelist()
                self.assertEqual(len(names), 3)
                self.assertEqual(len(set(names)), 3, names)
                # A folder with one mp3 keeps the numbered lesson name the learner sees today.
                self.assertIn("02-other.mp3", names)
                self.assertEqual(z.read("02-other.mp3"), b"OTHER")
                payloads = {z.read(n) for n in names}
                self.assertEqual(payloads, {b"OLD AUDIO", b"NEW AUDIO", b"OTHER"})


REPO = Path(__file__).resolve().parents[1]


class ClassManifest(unittest.TestCase):
    """The manifest copies what render_audio left in render.json next to each mp3:
    engine, voice, pitch and device per host, the real length, then the course
    total. A lesson that was never rendered through the engine gets a note instead
    of a crash, so an unfinished course can still be packed."""

    def render(self, folder, stem, length, host_a, host_b, dev):
        folder.mkdir(parents=True, exist_ok=True)
        (folder / f"{stem}.mp3").write_bytes(b"AUDIO")
        (folder / f"{stem}.json").write_text(json.dumps({
            "mp3": f"{stem}.mp3", "length": length, "turns": 6, "device": dev,
            "hosts": {"A": {"engine": host_a[0], "voice": host_a[1], "pitch": host_a[2]},
                      "B": {"engine": host_b[0], "voice": host_b[1], "pitch": host_b[2]}},
        }, ensure_ascii=False), encoding="utf-8")

    def pack(self, ws):
        out = ws / "deliver"
        out.mkdir(exist_ok=True)
        return package_class.write_manifest(ws, out).read_text(encoding="utf-8")

    def test_line_names_file_length_both_hosts_and_device(self):
        with tempfile.TemporaryDirectory() as td:
            ws = Path(td)
            self.render(ws / "class" / "01-fokusy", "lesson", "2:05",
                        ("piper", "ru_RU-denis-medium", None), ("kokoro", "dima", -4.0), "cpu")
            text = self.pack(ws)
        # The whole line, not a substring: "cpu" also sits in the total, so a line
        # that dropped its own device still matched an assertIn.
        self.assertEqual(next(line for line in text.splitlines() if line.startswith("01-fokusy\t")),
                         "01-fokusy\tlesson.mp3\t2:05"
                         "\tA: piper/ru_RU-denis-medium/none\tB: kokoro/dima/-4\tdevice=cpu")
        self.assertIn("итог: 1 урок · 2:05 · устройства: cpu", text)

    def test_lesson_folder_leads_the_line(self):
        with tempfile.TemporaryDirectory() as td:
            ws = Path(td)
            self.render(ws / "class" / "01-a", "lesson", "1:00",
                        ("piper", "a", None), ("piper", "b", None), "cpu")
            self.render(ws / "class" / "02-b", "lesson", "1:00",
                        ("piper", "a", None), ("piper", "b", None), "cpu")
            text = self.pack(ws)
        # Two lessons hold the same mp3 name; the folder is what tells the lines apart.
        self.assertEqual(len([l for l in text.splitlines() if l.endswith("lesson.mp3\t1:00"
                                                   "\tA: piper/a/none\tB: piper/b/none\tdevice=cpu")]), 2)
        self.assertTrue(any(l.startswith("01-a\t") for l in text.splitlines()))
        self.assertTrue(any(l.startswith("02-b\t") for l in text.splitlines()))

    def test_missing_render_json_is_a_line_not_a_crash(self):
        with tempfile.TemporaryDirectory() as td:
            ws = Path(td)
            self.render(ws / "class" / "01-fokusy", "lesson", "2:05",
                        ("piper", "a", None), ("piper", "b", None), "cpu")
            silent = ws / "class" / "02-bez-sinteza"
            silent.mkdir(parents=True)
            (silent / "lesson.mp3").write_bytes(b"AUDIO")
            text = self.pack(ws)
        self.assertIn("02-bez-sinteza\tнет render.json", text)
        self.assertIn("итог: 2 урока · 2:05", text)

    def test_every_device_used_by_the_course_is_listed(self):
        with tempfile.TemporaryDirectory() as td:
            ws = Path(td)
            self.render(ws / "class" / "01-a", "lesson", "1:30",
                        ("kokoro", "sveta", None), ("kokoro", "dima", None), "cuda")
            self.render(ws / "class" / "02-b", "lesson", "2:00",
                        ("silero", "aidar", None), ("silero", "baya", None), "cpu")
            self.render(ws / "class" / "03-c", "lesson", "1:00",
                        ("kokoro", "masha", None), ("kokoro", "dima", None), "cuda")
            text = self.pack(ws)
        self.assertIn("устройства: cuda, cpu", text)
        self.assertIn("итог: 3 урока · 4:30", text)

    def test_lesson_count_agrees_in_russian(self):
        forms = [package_class.plural(n, "урок", "урока", "урок") for n in (1, 2, 5, 11, 12, 21, 24, 25)]
        self.assertEqual(forms, ["урок", "урока", "урок", "урок", "урок", "урок", "урока", "урок"])


def quiet():
    """Capture stdout and stderr together; returns (context manager, buffer)."""
    buf = io.StringIO()
    stack = contextlib.ExitStack()
    stack.enter_context(contextlib.redirect_stdout(buf))
    stack.enter_context(contextlib.redirect_stderr(buf))
    return stack, buf


def long_html(words=300, paras=1):
    return "".join("<p>" + "word " * (words // paras) + "</p>" for _ in range(paras))


class SubstackNotJson(unittest.TestCase):
    """A Substack host answering HTML (bot check, login page) fails that author, not the run."""

    def test_other_authors_still_run(self):
        with tempfile.TemporaryDirectory() as td:
            ws = Path(td)
            (ws / "sources.json").write_text(json.dumps({"authors": [
                {"name": "First", "substack": "first.substack.com"},
                {"name": "Second", "substack": "second.substack.com"}]}))
            stack, buf = quiet()
            with stack, mock.patch.object(scrape, "fetch", return_value="<html>Just a moment...</html>"):
                scrape.main(ws)
            out = buf.getvalue()
        self.assertIn("First: FAILED", out)
        self.assertIn("Second: FAILED", out)
        self.assertIn("not JSON", out)


class CheckerUrlForms(unittest.TestCase):
    """The same page in a slightly different spelling is the same page."""

    URLS = {"https://www.a.com/post"}

    def test_harmless_variants_pass(self):
        for variant in ["https://www.a.com/post/", "https://www.a.com/post#method", "**https://www.a.com/post**",
                        "https://www.a.com/post;", "http://a.com/post", "https://www.a.com/post."]:
            self.assertEqual(check_lessons.check_card(CARD_OK.replace("https://example.com/a", variant), self.URLS),
                             [], variant)

    def test_a_different_page_still_fails(self):
        problems = check_lessons.check_card(CARD_OK.replace("https://example.com/a", "https://www.a.com/post-2"), self.URLS)
        self.assertEqual(len(problems), 1)
        self.assertIn("not in raw/", problems[0])

    def test_plan_uses_the_same_forms(self):
        with tempfile.TemporaryDirectory() as td:
            ws = Path(td)
            (ws / "class").mkdir()
            (ws / "class" / "lesson-plan.md").write_text("Lesson 1 draws on https://www.a.com/post/ and http://a.com/post#x")
            stack, buf = quiet()
            with stack:
                failed = check_lessons.check_plan(ws, self.URLS)
        self.assertFalse(failed, buf.getvalue())


SITEMAP_TWO = ("<urlset><url><loc>https://s.com/blog/a</loc></url>"
               "<url><loc>https://s.com/blog/b</loc></url></urlset>")
THIN_PAGE = "<html><body><main>too short</main></body></html>"


class PersonModeReasons(unittest.TestCase):
    """Sitemap and RSS modes name every page they did not save, like web mode does."""

    def test_sitemap_mode_prints_reasons(self):
        pages = {"https://s.com/sitemap.xml": SITEMAP_TWO, "https://s.com/blog/a": THIN_PAGE, "https://s.com/blog/b": THIN_PAGE}
        with tempfile.TemporaryDirectory() as td:
            stack, buf = quiet()
            with stack, mock.patch.object(scrape, "fetch", side_effect=lambda u: pages[u]), \
                    mock.patch.object(scrape, "fetch_bytes", side_effect=lambda u: pages[u].encode()), \
                    mock.patch.object(scrape.time, "sleep"):
                scrape.scrape_sitemap(Path(td), {"name": "Site Person"},
                                      {"sitemaps": ["https://s.com/sitemap.xml"], "url_pattern": r"s\.com/blog/"})
        out = buf.getvalue()
        self.assertIn("thin or JavaScript-only", out)
        self.assertIn("https://s.com/blog/a", out)
        self.assertIn("https://s.com/blog/b", out)

    def test_rss_mode_prints_reasons(self):
        feed = ('<rss><channel><item><title>t</title><link>https://s.com/blog/a</link>'
                '<description>short</description></item></channel></rss>')
        with tempfile.TemporaryDirectory() as td:
            stack, buf = quiet()
            with stack, mock.patch.object(scrape, "fetch_bytes", side_effect=lambda u: (feed if u.endswith("/feed") else THIN_PAGE).encode()), \
                    mock.patch.object(scrape.time, "sleep"):
                scrape.scrape_rss(Path(td), {"name": "Feed Person"}, {"feed": "https://s.com/feed"})
        out = buf.getvalue()
        self.assertIn("thin or JavaScript-only", out)
        self.assertIn("https://s.com/blog/a", out)


class WebFilenames(unittest.TestCase):
    """Two pages that would share a filename both stay on disk."""

    def test_same_slug_same_date_keeps_both(self):
        with tempfile.TemporaryDirectory() as td:
            out = Path(td)
            web = {"name": "web"}
            scrape.write_post(out, web, "A", "undated", "https://docs.example.com/guide/intro", "word " * 200)
            scrape.write_post(out, web, "B", "undated", "https://docs.example.com/tutorial/intro", "word " * 200)
            scrape.write_post(out, web, "A again", "undated", "https://docs.example.com/guide/intro", "word " * 201)
            files = sorted(p.name for p in out.glob("*.md"))
            self.assertEqual(len(files), 2, files)
            self.assertEqual(scrape.urls_on_disk(out),
                             {"https://docs.example.com/guide/intro", "https://docs.example.com/tutorial/intro"})


class SubstackLimits(unittest.TestCase):
    """Substack mode honours limit and min_words like the other modes."""

    def test_limit_and_min_words(self):
        archive = [{"slug": "one", "post_date": "2024-03-01T00:00:00Z", "canonical_url": "https://j.substack.com/p/one"},
                   {"slug": "short", "post_date": "2024-02-01T00:00:00Z", "canonical_url": "https://j.substack.com/p/short"},
                   {"slug": "three", "post_date": "2024-01-01T00:00:00Z", "canonical_url": "https://j.substack.com/p/three"},
                   {"slug": "four", "post_date": "2023-12-01T00:00:00Z", "canonical_url": "https://j.substack.com/p/four"}]
        calls = []

        def get_json(url):
            calls.append(url)
            if "/archive" in url:
                return [] if "offset=4" in url else archive
            slug = url.rsplit("/", 1)[-1]
            body = "<p>tiny</p>" if slug == "short" else long_html()
            return {"title": slug, "body_html": body, "canonical_url": f"https://j.substack.com/p/{slug}", "audience": "everyone"}

        with tempfile.TemporaryDirectory() as td:
            ws = Path(td)
            stack, buf = quiet()
            with stack, mock.patch.object(scrape, "get_json", side_effect=get_json), mock.patch.object(scrape.time, "sleep"):
                scrape.scrape_substack(ws, {"name": "Jane", "substack": "j.substack.com", "limit": 2, "min_words": 150},
                                       "j.substack.com")
            urls = scrape.urls_on_disk(ws / "raw" / "jane")
        self.assertEqual(urls, {"https://j.substack.com/p/one", "https://j.substack.com/p/three"})
        self.assertIn("https://j.substack.com/p/short", buf.getvalue())
        self.assertFalse(any(u.endswith("/posts/four") for u in calls), "stopped at the limit")
        self.assertFalse(any("offset=4" in u for u in calls), "no archive page past the limit")


ATOM_XHTML = """<feed xmlns="http://www.w3.org/2005/Atom"><entry><title>t</title>
<link rel="alternate" href="https://x.com/p"/>
<content type="xhtml"><div xmlns="http://www.w3.org/1999/xhtml"><p>%s</p><p>%s</p></div></content>
</entry></feed>""" % ("alpha " * 200, "beta " * 200)


class AtomXhtml(unittest.TestCase):
    """<content type="xhtml"> carries the post as child elements, not text."""

    def test_xhtml_content_is_read(self):
        html = next(scrape.feed_items(ATOM_XHTML))["html"]
        text = scrape.to_text(html)
        self.assertEqual(len(text.split()), 400)
        self.assertIn("\n", text.strip(), "paragraph break kept")


class RssLimitSemantics(unittest.TestCase):
    """limit is the number of posts on disk, in RSS mode as in sitemap mode."""

    def test_limit_counts_posts_on_disk(self):
        items = "".join(f"<item><title>t{i}</title><link>https://s.com/blog/{i}</link>"
                        f"<description><![CDATA[{long_html()}]]></description></item>" for i in range(3))
        feed = f"<rss><channel>{items}</channel></rss>".encode()
        with tempfile.TemporaryDirectory() as td:
            ws = Path(td)
            out = scrape.out_dir(ws, {"name": "Feed Person"})
            scrape.write_post(out, {"name": "Feed Person"}, "t9", "2024-01-01", "https://s.com/blog/9", "word " * 200)
            stack, buf = quiet()
            with stack, mock.patch.object(scrape, "fetch_bytes", return_value=feed), mock.patch.object(scrape.time, "sleep"):
                scrape.scrape_rss(ws, {"name": "Feed Person"}, {"feed": "https://s.com/feed", "limit": 2})
            self.assertEqual(len(scrape.urls_on_disk(out)), 2)
        self.assertIn("2 posts on disk", buf.getvalue())


class VersionStrings(unittest.TestCase):
    """The site's structured data names the same version as the plugin."""

    def test_site_matches_plugin(self):
        plugin = json.loads((REPO / ".claude-plugin" / "plugin.json").read_text())["version"]
        site = re.search(r'"softwareVersion":\s*"([^"]+)"', (REPO / "docs" / "index.html").read_text()).group(1)
        self.assertEqual(site, plugin)


class Utf8Reading(unittest.TestCase):
    """Pages and feeds are read as UTF-8, as in v0.3.1. One stray byte costs that byte,
    never the page or the feed. Other encodings are a known gap: GitHub issue #6."""

    def test_utf8_feed_with_one_stray_byte_keeps_its_items(self):
        feed = (b'<?xml version="1.0" encoding="utf-8"?><rss><channel><item><title>It\x92s caf\xc3\xa9</title>'
                b'<link>https://x.com/1</link><description>' + b"word " * 200 + b'</description></item></channel></rss>')
        with tempfile.TemporaryDirectory() as td:
            ws = Path(td)
            stack, buf = quiet()
            with stack, mock.patch.object(scrape, "fetch_bytes", return_value=feed):
                scrape.scrape_rss(ws, {"name": "Feed Person"}, {"feed": "https://x.com/feed"})
            self.assertEqual(scrape.urls_on_disk(ws / "raw" / "feed-person"), {"https://x.com/1"}, buf.getvalue())

    def save(self, page):
        with tempfile.TemporaryDirectory() as td:
            out = Path(td)
            with mock.patch.object(scrape, "fetch_bytes", return_value=page):
                self.assertTrue(scrape.save_page(out, {"name": "web"}, "https://x.com/p", "", 150))
            return next(out.glob("*.md")).read_text(encoding="utf-8")

    def test_utf8_page_with_one_stray_byte(self):
        text = self.save(b'<html><head><meta charset="utf-8"></head><body><main><h1>Caf\xc3\xa9</h1>'
                         + b"word " * 200 + b"It\x92s</main></body></html>")
        self.assertIn("Café", text)
        self.assertNotIn("Ã", text)

    def test_page_declared_latin1_but_sent_as_utf8(self):
        text = self.save(b'<html><head><meta charset="iso-8859-1"></head><body><main><h1>caf\xc3\xa9</h1>'
                         + b"word " * 200 + b"</main></body></html>")
        self.assertIn("café", text)
        self.assertNotIn("Ã", text)


class CheckerUrlEdges(unittest.TestCase):
    """Urls that really end in marks, carry parentheses or sit in backticks still match."""

    def card(self, cite):
        return CARD_OK.replace("https://example.com/a", cite)

    def test_url_that_really_ends_in_an_underscore(self):
        self.assertEqual(check_lessons.check_card(self.card("https://x.com/wiki/Foo_"), {"https://x.com/wiki/Foo_"}), [])
        self.assertEqual(check_lessons.check_card(self.card("https://x.com/yes!"), {"https://x.com/yes!"}), [])

    def test_wikipedia_parentheses_in_a_markdown_link(self):
        url = "https://en.wikipedia.org/wiki/Mercury_(planet)"
        self.assertEqual(check_lessons.check_card(self.card(f"[Mercury]({url})"), {url}), [])

    def test_backticked_url(self):
        self.assertEqual(check_lessons.check_card(self.card("`https://a.com/post`"), {"https://a.com/post"}), [])


class CheckerLocale(unittest.TestCase):
    """The checker reads raw/ as UTF-8, the encoding scrape.py writes, whatever the locale."""

    def test_non_utf8_locale(self):
        with tempfile.TemporaryDirectory() as td:
            ws = Path(td)
            (ws / "raw" / "web").mkdir(parents=True)
            (ws / "raw" / "web" / "p.md").write_text("---\nauthor: web\ntitle: \"Иван\"\nurl: https://example.com/a\n---\n\nИван\n",
                                                    encoding="utf-8")
            lesson = ws / "class" / "01-x"
            lesson.mkdir(parents=True)
            (lesson / "card.md").write_text(CARD_OK.replace("people", "Иван"), encoding="utf-8")
            (lesson / "script.txt").write_text("\n".join(["A: " + "word " * 15, "B: " + "word " * 15] * 10), encoding="utf-8")
            env = dict(os.environ, LC_ALL="ru_RU.CP1251", PYTHONUTF8="0")
            r = subprocess.run([sys.executable, str(SCRIPTS / "check_lessons.py"), str(ws)], env=env,
                               capture_output=True, text=True, encoding="utf-8", errors="replace")
        self.assertNotIn("UnicodeDecodeError", r.stderr)
        self.assertIn("ok   01-x", r.stdout, r.stdout + r.stderr)


class SubstackPaging(unittest.TestCase):
    """No archive request past the limit."""

    def run_substack(self, ws, calls):
        pages = {0: [{"slug": "one", "post_date": "2024-03-01", "canonical_url": "https://j.substack.com/p/one"},
                     {"slug": "two", "post_date": "2024-02-01", "canonical_url": "https://j.substack.com/p/two"}],
                 2: [{"slug": "three", "post_date": "2024-01-01", "canonical_url": "https://j.substack.com/p/three"}]}

        def get_json(url):
            calls.append(url)
            if "/archive" in url:
                return pages.get(int(re.search(r"offset=(\d+)", url).group(1)), [])
            slug = url.rsplit("/", 1)[-1]
            return {"title": slug, "body_html": long_html(), "canonical_url": f"https://j.substack.com/p/{slug}",
                    "audience": "everyone"}

        stack, _ = quiet()
        with stack, mock.patch.object(scrape, "get_json", side_effect=get_json), mock.patch.object(scrape.time, "sleep"):
            scrape.scrape_substack(ws, {"name": "Jane", "limit": 2}, "j.substack.com")

    def test_limit_reached_at_a_page_boundary(self):
        calls = []
        with tempfile.TemporaryDirectory() as td:
            self.run_substack(Path(td), calls)
        self.assertFalse(any("offset=2" in u for u in calls), calls)

    def test_rerun_already_at_the_limit(self):
        with tempfile.TemporaryDirectory() as td:
            ws = Path(td)
            self.run_substack(ws, [])
            calls = []
            self.run_substack(ws, calls)
        self.assertEqual(calls, [])


class NonUtf8RawFile(unittest.TestCase):
    """A raw/ file that isn't UTF-8 (v0.3.1 on a Windows locale, or added by hand) doesn't stop the run."""

    def test_run_continues(self):
        feed = ('<rss><channel><item><title>t</title><link>https://b.com/1</link><description>'
                + "word " * 200 + '</description></item></channel></rss>').encode()
        with tempfile.TemporaryDirectory() as td:
            ws = Path(td)
            (ws / "sources.json").write_text(json.dumps({"authors": [
                {"name": "Ann", "site": {"kind": "rss", "feed": "https://a.com/feed"}},
                {"name": "Bob", "site": {"kind": "rss", "feed": "https://b.com/feed"}}]}))
            (ws / "raw" / "ann").mkdir(parents=True)
            (ws / "raw" / "ann" / "old.md").write_bytes(b"---\ntitle: caf\xe9\nurl: https://a.com/old\n---\n\ncaf\xe9\n")
            stack, buf = quiet()
            with stack, mock.patch.object(scrape, "fetch_bytes", return_value=feed):
                scrape.main(ws)
            self.assertIn("https://a.com/old", scrape.urls_on_disk(ws / "raw" / "ann"))
            self.assertEqual(scrape.urls_on_disk(ws / "raw" / "bob"), {"https://b.com/1"}, buf.getvalue())


class SubstackSkipRecord(unittest.TestCase):
    """A resume does not fetch teasers and short posts again; a lower min_words does."""

    ARCHIVE = [{"slug": s, "post_date": "2024-01-01", "canonical_url": f"https://j.substack.com/p/{s}"}
               for s in ("long", "teaser", "short")]

    def run_once(self, ws, min_words=150):
        calls = []

        def get_json(url):
            calls.append(url)
            if "/archive" in url:
                return self.ARCHIVE if "offset=0" in url else []
            slug = url.rsplit("/", 1)[-1]
            body = {"long": long_html(), "teaser": "<p>" + "word " * 40 + "</p>", "short": "<p>tiny</p>"}[slug]
            return {"title": slug, "body_html": body, "canonical_url": f"https://j.substack.com/p/{slug}",
                    "audience": "only_paid" if slug == "teaser" else "everyone"}

        stack, buf = quiet()
        with stack, mock.patch.object(scrape, "get_json", side_effect=get_json), mock.patch.object(scrape.time, "sleep"):
            scrape.scrape_substack(ws, {"name": "Jane", "min_words": min_words}, "j.substack.com")
        return [u for u in calls if "/posts/" in u], buf.getvalue()

    def test_resume_skips_what_was_skipped(self):
        with tempfile.TemporaryDirectory() as td:
            ws = Path(td)
            first, out1 = self.run_once(ws)
            second, out2 = self.run_once(ws)
            self.assertEqual(len(first), 3)
            self.assertIn("paywalled teaser (40 words)", out1)
            self.assertEqual(second, [])
            self.assertIn("2 skipped on an earlier run", out2)
            self.assertEqual([p.name for p in (ws / "raw" / "jane").glob("*.md")], ["2024-01-01-long.md"])

    def test_lower_min_words_fetches_them_again(self):
        with tempfile.TemporaryDirectory() as td:
            ws = Path(td)
            self.run_once(ws)
            again, _ = self.run_once(ws, min_words=30)
            self.assertEqual(again, ["https://j.substack.com/api/v1/posts/teaser"])
            self.assertIn("https://j.substack.com/p/teaser", scrape.urls_on_disk(ws / "raw" / "jane"))


class VoiceHostPair(unittest.TestCase):
    """AIDEMY_VOICE_* takes `engine:voice[:pitch]`, a bare name, or nothing."""

    def test_prefixed_bare_shifted_and_empty(self):
        self.assertEqual(render_audio.split_spec("piper:ru_RU-denis-medium"),
                         ("piper", "ru_RU-denis-medium", None))
        self.assertEqual(render_audio.split_spec("piper:irina:-4"), ("piper", "irina", -4.0))
        self.assertEqual(render_audio.split_spec("piper:irina:2.5"), ("piper", "irina", 2.5))
        self.assertEqual(render_audio.split_spec("ru_RU-irina-medium"),
                         (None, "ru_RU-irina-medium", None))
        self.assertEqual(render_audio.split_spec(""), (None, "", None))

    def test_forced_engine_fills_a_spec_without_one(self):
        env = {"AIDEMY_TTS": "piper", "AIDEMY_VOICE_B": "irina"}
        with mock.patch.dict(os.environ, env, clear=True):
            plan = render_audio.hosts()
        self.assertEqual(plan["A"], ("piper", "ru_RU-denis-medium", None))
        self.assertEqual(plan["B"], ("piper", "irina", None))

    def test_one_voice_makes_b_borrow_a(self):
        env = {"AIDEMY_VOICE_A": "piper:irina:2", "AIDEMY_VOICE_B": "piper:denis",
               "AIDEMY_ONE_VOICE": "1"}
        with mock.patch.dict(os.environ, env, clear=True):
            plan = render_audio.hosts()
        self.assertEqual(plan["A"], plan["B"])
        self.assertEqual(plan["A"], ("piper", "irina", 2.0))

    def test_one_voice_with_empty_env_still_fills_both(self):
        """The bug this guards: copying the raw empty spec left B on a default voice."""
        with mock.patch.dict(os.environ, {"AIDEMY_ONE_VOICE": "1"}, clear=True), \
                mock.patch.object(render_audio, "ready", side_effect=lambda e: e == "piper"):
            plan = render_audio.hosts()
        self.assertEqual(plan["A"], plan["B"])
        self.assertEqual(plan["A"], ("piper", "ru_RU-denis-medium", None))

    def test_unknown_engine_is_named(self):
        with mock.patch.dict(os.environ, {"AIDEMY_VOICE_A": "elevenlabs:rachel"}, clear=True):
            with self.assertRaises(SystemExit) as ctx:
                render_audio.hosts()
        self.assertIn("elevenlabs", str(ctx.exception))

    def test_nothing_usable_names_the_fix(self):
        with mock.patch.dict(os.environ, {}, clear=True), \
                mock.patch.object(render_audio, "ready", return_value=False):
            with self.assertRaises(SystemExit) as ctx:
                render_audio.hosts()
        self.assertIn("get_voices.py", str(ctx.exception))


class VoiceEngineChoice(unittest.TestCase):
    """AIDEMY_TTS decides; otherwise the first engine usable on this machine."""

    def test_auto_picks_the_best_ready_engine(self):
        with mock.patch.dict(os.environ, {}, clear=True), \
                mock.patch.object(render_audio, "ready", side_effect=lambda e: e == "silero"):
            plan = render_audio.hosts()
        self.assertEqual(plan["A"], ("silero", "aidar", None))
        self.assertEqual(plan["B"], ("silero", "baya", None))

    def test_piper_is_ready_only_with_both_default_models(self):
        with tempfile.TemporaryDirectory() as td, \
                mock.patch.dict(os.environ, {"AIDEMY_MODEL_DIR": td}, clear=True), \
                mock.patch.object(render_audio.importlib.util, "find_spec", return_value=object()):
            self.assertFalse(render_audio.ready("piper"))
            (Path(td) / "piper").mkdir()
            for voice in render_audio.DEFAULT_VOICES["piper"]:
                (Path(td) / "piper" / f"{voice}.onnx").write_bytes(b"x")
            self.assertTrue(render_audio.ready("piper"))


class VoiceDeviceChoice(unittest.TestCase):
    """AIDEMY_DEVICE decides where the torch engines run. Each refusal names which
    half is missing: "no torch in this Python" and "torch says no CUDA" are fixed
    differently, and a machine that only has a CPU must not be told to install."""

    no_cuda = types.SimpleNamespace(cuda=types.SimpleNamespace(is_available=lambda: False))

    def test_cpu_needs_no_torch_at_all(self):
        # Reading anything off torch fails here, so a cpu that was decided after
        # the import cannot pass this test.
        def refuse(name):
            raise AssertionError("torch на пути AIDEMY_DEVICE=cpu не читают")

        no_torch = types.ModuleType("torch")
        no_torch.__getattr__ = refuse
        with mock.patch.dict(os.environ, {"AIDEMY_DEVICE": "cpu"}, clear=True), \
                mock.patch.dict(sys.modules, {"torch": no_torch}):
            self.assertEqual(render_audio.device(), "cpu")

    def test_auto_stays_on_cpu_when_cuda_is_out(self):
        with mock.patch.dict(os.environ, {"AIDEMY_DEVICE": "auto"}, clear=True), \
                mock.patch.dict(sys.modules, {"torch": self.no_cuda}):
            self.assertEqual(render_audio.device(), "cpu")

    def test_forced_cuda_without_cuda_names_the_gpu(self):
        with mock.patch.dict(os.environ, {"AIDEMY_DEVICE": "cuda"}, clear=True), \
                mock.patch.dict(sys.modules, {"torch": self.no_cuda}):
            with self.assertRaises(SystemExit) as ctx:
                render_audio.device()
        self.assertIn("torch.cuda.is_available", str(ctx.exception))

    def test_forced_cuda_without_torch_names_the_missing_package(self):
        with mock.patch.dict(os.environ, {"AIDEMY_DEVICE": "cuda"}, clear=True), \
                mock.patch.dict(sys.modules, {"torch": None}):
            with self.assertRaises(SystemExit) as ctx:
                render_audio.device()
        self.assertIn("AIDEMY_DEVICE=cuda", str(ctx.exception))
        self.assertIn("not installed", str(ctx.exception))


class CardSynthesisLine(unittest.TestCase):
    """The card names the engine that spoke. The line sits under Слушать and is
    replaced, not stacked: a re-render used to leave two synthesis lines."""

    CARD = "**Слушать:** x.mp3 (0:12)\n**Идея в трёх строках**\n"
    pair = {"A": ("piper", "ru_RU-denis-medium", None), "B": ("piper", "ru_RU-irina-medium", -4.0)}

    def test_line_sits_under_listen_and_names_both_hosts(self):
        with tempfile.TemporaryDirectory() as td:
            card = Path(td) / "card.md"
            card.write_text(self.CARD, encoding="utf-8")
            render_audio.stamp_synthesis(card, self.pair, "cpu")
            lines = card.read_text(encoding="utf-8").splitlines()
        self.assertEqual(lines[0], "**Слушать:** x.mp3 (0:12)")
        self.assertEqual(lines[1], "**Синтез:** piper (ru_RU-denis-medium) / piper (ru_RU-irina-medium -4), cpu")

    def test_second_render_replaces_the_line(self):
        with tempfile.TemporaryDirectory() as td:
            card = Path(td) / "card.md"
            card.write_text(self.CARD, encoding="utf-8")
            render_audio.stamp_synthesis(card, self.pair, "cpu")
            render_audio.stamp_synthesis(card, {"A": ("silero", "aidar", None),
                                                "B": ("silero", "baya", None)}, "cuda")
            text = card.read_text(encoding="utf-8")
        self.assertEqual(text.count("**Синтез:**"), 1, text)
        self.assertIn("**Синтез:** silero (aidar) / silero (baya), cuda", text)

    def test_card_with_the_line_still_passes_the_gate(self):
        # check_lessons.py is not changed by this feature, so the extra line must
        # not become a missing section or a banned dash.
        card = CARD_OK.replace("**Слушать:** x.mp3 (2 мин)",
                               "**Слушать:** x.mp3 (2 мин)\n**Синтез:** piper (a) / piper (b), cpu")
        self.assertEqual(check_lessons.check_card(card, {"https://example.com/a"}), [])


class VoiceAudioTags(unittest.TestCase):
    """Both engines would read a stage direction aloud, so it is stripped."""

    def test_tags_gone_and_edges_trimmed(self):
        self.assertEqual(render_audio.strip_tags("Смотри [смеётся] на цену"), "Смотри  на цену")
        self.assertEqual(render_audio.strip_tags("  [пауза] начало "), "начало")


class VoicePiperModelLoadedOnce(unittest.TestCase):
    """Each host model loads once per lesson: the CLI paid 2.2 s of load per turn."""

    def test_two_hosts_four_turns_two_loads(self):
        loads = []
        fake = types.ModuleType("piper")

        class FakeVoice:
            class config:
                sample_rate = 22050

            @classmethod
            def load(cls, path):
                loads.append(path)
                return cls()

            def synthesize_wav(self, text, wav_file, syn_config=None):
                # What PiperVoice does for real: header from the audio chunk, then frames.
                wav_file.setnchannels(1)
                wav_file.setsampwidth(2)
                wav_file.setframerate(22050)
                wav_file.writeframes(b"\x00\x00" * 2205)

        fake.PiperVoice = FakeVoice
        fake.SynthesisConfig = lambda **kwargs: kwargs
        with tempfile.TemporaryDirectory() as td, mock.patch.dict(sys.modules, {"piper": fake}), \
                mock.patch.dict(os.environ, {"AIDEMY_MODEL_DIR": td}, clear=True):
            (Path(td) / "piper").mkdir()
            for voice in ("va", "vb"):
                (Path(td) / "piper" / f"{voice}.onnx").write_bytes(b"x")
            tmp = Path(td) / "parts"
            tmp.mkdir()
            plan = {"A": ("piper", "va", None), "B": ("piper", "vb", None)}
            parts = render_audio.piper_parts(
                [(0, "A", "раз"), (1, "B", "два"), (2, "A", "три"), (3, "B", "четыре")], tmp, plan, "cpu")
            sizes = [part[0].stat().st_size for part in parts.values()]
        self.assertEqual(len(loads), 2)
        self.assertEqual(sorted(parts), [0, 1, 2, 3])
        self.assertEqual(len(set(sizes)), 1)
        self.assertGreater(sizes[0], 4000)  # header + 0.1 s of 22050 Hz mono 16-bit


class VoiceMixedEngines(unittest.TestCase):
    """Two hosts may speak through different engines: parts still come back in
    turn order, each carrying its host's pitch."""

    def test_turn_order_and_pitch_survive_mixing(self):
        def first(items, tmp, plan, dev):
            return {i: (tmp / f"a{i}.wav", 24000) for i, _, _ in items}

        def second(items, tmp, plan, dev):
            return {i: (tmp / f"b{i}.wav", 22050) for i, _, _ in items}

        plan = {"A": ("say", "v", None), "B": ("piper", "w", -4.0)}
        with tempfile.TemporaryDirectory() as td, \
                mock.patch.dict(render_audio.ENGINE_PARTS, {"say": first, "piper": second}, clear=True):
            parts, dev = render_audio.build_parts([("A", "x"), ("B", "y"), ("A", "z")], Path(td), plan)
        self.assertEqual([part[0].name for part in parts], ["a0.wav", "b1.wav", "a2.wav"])
        self.assertEqual([part[2] for part in parts], [None, -4.0, None])
        self.assertEqual(dev, "cpu")

    def test_unwired_engine_is_reported_by_name(self):
        plan = {"A": ("kokoro", "dima", None), "B": ("kokoro", "sveta", None)}
        with tempfile.TemporaryDirectory() as td, \
                mock.patch.dict(render_audio.ENGINE_PARTS, {"piper": lambda *a: {}}, clear=True):
            with self.assertRaises(SystemExit) as ctx:
                render_audio.build_parts([("A", "x")], Path(td), plan)
        self.assertIn("kokoro", str(ctx.exception))


class VoicePitchInNormalize(unittest.TestCase):
    """Pitch is the transpose in the per-part pass, and only that pass."""

    def test_shift_becomes_asetrate_and_atempo(self):
        calls = []
        with tempfile.TemporaryDirectory() as td, \
                mock.patch.object(render_audio.subprocess, "run",
                                  side_effect=lambda cmd, check: calls.append(cmd)):
            render_audio.normalize([(Path(td) / "a.wav", 22050, -4.0),
                                    (Path(td) / "b.wav", 24000, None)], Path(td))
        shifted = calls[0][calls[0].index("-af") + 1]
        plain = calls[1][calls[1].index("-af") + 1]
        self.assertIn("asetrate=22050*", shifted)
        self.assertIn("atempo=", shifted)
        self.assertIn("dynaudnorm", shifted)
        self.assertEqual(plain, "dynaudnorm")


class VoiceRenderRecord(unittest.TestCase):
    """render.json says what really spoke, so the card and manifest never guess."""

    def test_record_keeps_engine_voice_pitch_and_device(self):
        with tempfile.TemporaryDirectory() as td:
            out = Path(td) / "01-lesson.mp3"
            plan = {"A": ("kokoro", "dima", None), "B": ("kokoro", "sveta", 1.5)}
            render_audio.describe(out, [("A", "x")] * 3, plan, "cuda", "2:05")
            meta = json.loads((Path(td) / "01-lesson.json").read_text(encoding="utf-8"))
        self.assertEqual(meta["device"], "cuda")
        self.assertEqual(meta["length"], "2:05")
        self.assertEqual(meta["turns"], 3)
        self.assertEqual(meta["hosts"]["B"], {"engine": "kokoro", "voice": "sveta", "pitch": 1.5})

    def test_one_voice_plan_prints_one_label(self):
        same = {"A": ("piper", "irina", None), "B": ("piper", "irina", None)}
        self.assertEqual(render_audio.label(same), "piper (irina)")
        mixed = {"A": ("ko", "dima", None), "B": ("pi", "irina", None)}
        self.assertEqual(render_audio.label(mixed), "ko (dima) / pi (irina)")


CATALOG_FIXTURE = {
    "ru_RU-denis-medium": {"files": {
        "ru/ru_RU/denis/medium/ru_RU-denis-medium.onnx.json": {"size_bytes": 2, "md5_digest": "cd"},
        "ru/ru_RU/denis/medium/ru_RU-denis-medium.onnx": {"size_bytes": 5, "md5_digest": "ab"},
    }}
}


class VoicePlan(unittest.TestCase):
    """plans() turns a voice name into catalog files with their size and digest."""

    def test_every_file_of_the_voice_is_planned(self):
        with mock.patch.dict(os.environ, {"AIDEMY_MODEL_DIR": "/models"}, clear=True):
            entries = get_voices.plans(CATALOG_FIXTURE, ["ru_RU-denis-medium"])
        self.assertEqual([(e[1].name, e[1].parent.name, e[2], e[3]) for e in entries],
                         [("ru_RU-denis-medium.onnx", "piper", 5, "ab"),
                          ("ru_RU-denis-medium.onnx.json", "piper", 2, "cd")])
        self.assertTrue(entries[0][0].startswith(get_voices.BASE))

    def test_unknown_voice_is_named(self):
        with self.assertRaises(KeyError) as ctx:
            get_voices.plans(CATALOG_FIXTURE, ["ru_RU-ghost-medium"])
        self.assertIn("ru_RU-ghost-medium", str(ctx.exception))

    def test_two_voices_do_not_share_one_license_card(self):
        """MODEL_CARD is the only catalog name without the voice in it."""
        two = {}
        for voice, digest in (("ru_RU-denis-medium", "a" * 32), ("ru_RU-irina-medium", "b" * 32)):
            two[voice] = {"files": {f"ru/ru_RU/{voice.split('-')[1]}/medium/{voice}.onnx":
                                    {"size_bytes": 5, "md5_digest": digest},
                                    f"ru/ru_RU/{voice.split('-')[1]}/medium/MODEL_CARD":
                                    {"size_bytes": 276, "md5_digest": digest}}}
        with mock.patch.dict(os.environ, {"AIDEMY_MODEL_DIR": "/models"}, clear=True):
            entries = get_voices.plans(two, list(two))
        names = [e[1].name for e in entries]
        self.assertEqual(len(names), len(set(names)))
        self.assertIn("MODEL_CARD-ru_RU-denis-medium", names)
        self.assertIn("MODEL_CARD-ru_RU-irina-medium", names)


class VoiceDiskGuard(unittest.TestCase):
    """Space is measured before the first byte moves, headroom included."""

    def probe(self, free_mib, needed_mib):
        with tempfile.TemporaryDirectory() as td, \
                mock.patch.object(get_voices.shutil, "disk_usage", return_value=mock.Mock(free=free_mib * get_voices.MIB)):
            return get_voices.room_ok(Path(td) / "piper", needed_mib * get_voices.MIB)

    def test_roomy_volume_passes(self):
        ok, _ = self.probe(free_mib=100, needed_mib=5)
        self.assertTrue(ok)

    def test_headroom_is_part_of_the_bill(self):
        ok, free = self.probe(free_mib=60, needed_mib=5)
        self.assertFalse(ok)
        self.assertEqual(free, 60 * get_voices.MIB)

    def test_missing_target_dir_is_measured_on_its_parent_volume(self):
        with tempfile.TemporaryDirectory() as td, \
                mock.patch.object(get_voices.shutil, "disk_usage") as usage:
            usage.return_value = mock.Mock(free=1000 * get_voices.MIB)
            get_voices.room_ok(Path(td) / "no" / "such" / "piper", get_voices.MIB)
        self.assertEqual(str(usage.call_args[0][0]), str(Path(td)))


class VoiceReuseGuard(unittest.TestCase):
    """A file counts as ready only when size and md5 both match the catalog."""

    def test_wrong_bytes_at_right_size_is_not_reused(self):
        with tempfile.TemporaryDirectory() as td:
            saved = Path(td) / "v.onnx"
            saved.write_bytes(b"abcd")
            good = hashlib.md5(b"abcd").hexdigest()
            self.assertTrue(get_voices.is_current(saved, 4, good))
            self.assertFalse(get_voices.is_current(saved, 5, good))
            self.assertFalse(get_voices.is_current(saved, 4, "0" * 32))
            self.assertFalse(get_voices.is_current(Path(td) / "gone.onnx", 4, good))

    def test_empty_file_is_not_current(self):
        with tempfile.TemporaryDirectory() as td:
            empty = Path(td) / "e.onnx"
            empty.write_bytes(b"")
            self.assertFalse(get_voices.is_current(empty, 0, hashlib.md5(b"").hexdigest()))


class VoicesCliRefusesForeignEngine(unittest.TestCase):
    """A request for an engine without a downloader stops with a named reason,
    before any network call."""

    def test_exit_names_the_engine_and_the_scope(self):
        with mock.patch.object(get_voices, "fetch_piper") as piper, \
                mock.patch.object(get_voices, "fetch_kokoro") as kokoro:
            with self.assertRaises(SystemExit) as ctx:
                get_voices.main(["elevenlabs:rachel"])
        self.assertIn("elevenlabs", str(ctx.exception))
        self.assertIn("piper", str(ctx.exception))
        self.assertIn("silero", str(ctx.exception))
        piper.assert_not_called()
        kokoro.assert_not_called()


class VoiceKokoroEngine(unittest.TestCase):
    """The checkpoint loads once per lesson, the voice pack once per voice, and the
    style index is clamped: a long line would index past the 510 style vectors."""

    def test_checkpoint_once_pack_per_voice_and_clamped_style(self):
        calls = {"models": [], "packs": [], "styles": []}

        class FakeTensor:
            def cpu(self):
                return self

            def numpy(self):
                return numpy.zeros(2400, dtype="float32")

        class FakeKModel:
            def __init__(self, repo_id=None, model=None):
                calls["models"].append(model)

            def eval(self):
                return self

            def to(self, device):
                return self

            def __call__(self, phonemes, style, speed, return_output=False):
                calls["styles"].append(style)
                return types.SimpleNamespace(audio=FakeTensor())

        class FakeG2P:
            def __call__(self, text):
                return list("a" * 4000), set()  # longer than the 510-entry pack

        fake_kokoro = types.ModuleType("kokoro")
        fake_kokoro.KModel = FakeKModel
        fake_g2p = types.ModuleType("ru_g2p")
        fake_g2p.RuG2P = FakeG2P
        fake_torch = types.SimpleNamespace(
            device=lambda name: name,
            load=lambda path, map_location=None, weights_only=True: calls["packs"].append((path, weights_only)) or list(range(510)),
            no_grad=lambda: contextlib.nullcontext(),
        )
        plan = {"A": ("kokoro", "sveta", None), "B": ("kokoro", "masha", None)}
        with tempfile.TemporaryDirectory() as td, \
                mock.patch.dict(sys.modules, {"kokoro": fake_kokoro, "ru_g2p": fake_g2p, "torch": fake_torch}), \
                mock.patch.dict(os.environ, {"AIDEMY_MODEL_DIR": td}, clear=True):
            root = Path(td) / "kokoro"
            (root / "voices").mkdir(parents=True)
            for voice in ("sveta", "masha", "dima"):
                (root / "voices" / f"{voice}.pt").write_bytes(b"x")
            (root / "kokoro-ru-v2-base.pth").write_bytes(b"x")
            tmp = Path(td) / "parts"
            tmp.mkdir()
            parts = render_audio.kokoro_parts([(0, "A", "первая"), (1, "B", "вторая")], tmp, plan, "cpu")
        self.assertEqual(len(calls["models"]), 1)          # sveta and masha share base
        self.assertEqual(len(calls["packs"]), 2)           # one pack per voice
        self.assertEqual(calls["styles"], [509, 509])      # clamped to the last vector
        self.assertTrue(all(weights_only for _, weights_only in calls["packs"]))
        self.assertEqual(sorted(parts), [0, 1])
        self.assertEqual(parts[0][1], 24000)

    def test_missing_weights_names_the_fetch_command(self):
        plan = {"A": ("kokoro", "dima", None), "B": ("kokoro", "sveta", None)}
        fake = types.SimpleNamespace(device=lambda name: name, load=lambda *a, **k: [], no_grad=lambda: contextlib.nullcontext())
        with tempfile.TemporaryDirectory() as td, \
                mock.patch.dict(sys.modules, {"kokoro": types.ModuleType("kokoro"),
                                              "ru_g2p": types.ModuleType("ru_g2p"), "torch": fake}), \
                mock.patch.dict(os.environ, {"AIDEMY_MODEL_DIR": td}, clear=True):
            with self.assertRaises(SystemExit) as ctx:
                render_audio.kokoro_parts([(0, "A", "текст")], Path(td), plan, "cpu")
        self.assertIn("get_voices.py kokoro", str(ctx.exception))

    def test_unknown_kokoro_voice_is_named(self):
        plan = {"A": ("kokoro", "ghost", None), "B": ("kokoro", "sveta", None)}
        fake = types.SimpleNamespace(device=lambda name: name, load=lambda *a, **k: [],
                                     no_grad=lambda: contextlib.nullcontext())
        with tempfile.TemporaryDirectory() as td, \
                mock.patch.dict(os.environ, {"AIDEMY_MODEL_DIR": td}, clear=True), \
                mock.patch.dict(sys.modules, {"kokoro": types.ModuleType("kokoro"),
                                              "ru_g2p": types.ModuleType("ru_g2p"), "torch": fake}):
            (Path(td) / "kokoro").mkdir()
            with self.assertRaises(SystemExit) as ctx:
                render_audio.kokoro_parts([(0, "A", "текст")], Path(td), plan, "cpu")
        self.assertIn("ghost", str(ctx.exception))
        self.assertEqual(render_audio.KOKORO_CHECKPOINTS["dima"], "kokoro-ru-v2-dima.pth")


class VoiceKokoroPlan(unittest.TestCase):
    """The downloader takes the weights, the packs, the G2P and espeak data, and
    leaves samples and pictures behind."""

    def test_repo_files_are_filtered(self):
        rows = [types.SimpleNamespace(rfilename=n, size=s) for n, s in [
            ("kokoro-ru-v2-base.pth", 100), ("voices/sveta.pt", 5),
            ("ru_g2p.py", 1), ("espeak-data/ru_dict", 2), ("config.json", 1),
            ("samples/sveta_01.wav", 300), ("eval-wer.png", 90), ("README.md", 3)]]
        plan = dict(get_voices.kokoro_plan(rows))
        self.assertIn("kokoro-ru-v2-base.pth", plan)
        self.assertIn("voices/sveta.pt", plan)
        self.assertIn("espeak-data/ru_dict", plan)
        self.assertNotIn("samples/sveta_01.wav", plan)
        self.assertNotIn("eval-wer.png", plan)
        self.assertEqual(sum(plan.values()), 109)


class VoiceLabPairs(unittest.TestCase):
    """Pairs are A+B, the grid is the eleven from the plan, and a refusal from one
    pair does not stop the lab."""

    def test_parse_pairs_and_slug(self):
        self.assertEqual(voice_lab.parse_pairs(["kokoro:dima+piper:irina"]),
                         [("kokoro:dima", "piper:irina")])
        with self.assertRaises(SystemExit):
            voice_lab.parse_pairs(["kokoro:dima"])
        self.assertEqual(voice_lab.slug("kokoro:dima", "piper:ru_RU-irina-medium"),
                         "kokoro-dima__piper-ru-ru-irina-medium")
        self.assertTrue(voice_lab.slug("piper:a", "piper:a", one_voice=True).endswith("__one"))

    def test_grid_has_eleven_pairs(self):
        self.assertEqual(len(voice_lab.GRID), 11)

    def test_second_run_keeps_the_first_runs_records(self):
        def fake_main(script, out):
            Path(out).write_text("mp3", encoding="utf-8")
            Path(out).with_suffix(".json").write_text(
                '{"length": "0:12", "device": "cpu"}', encoding="utf-8")

        with tempfile.TemporaryDirectory() as td, \
                mock.patch.object(voice_lab.render_audio, "main", side_effect=fake_main):
            voice_lab.main(["--pairs", "piper:a+piper:b", "--out", td])
            voice_lab.main(["--pairs", "piper:c+piper:d", "--out", td])
            record = json.loads((Path(td) / "lab.json").read_text(encoding="utf-8"))
        self.assertEqual(len(record["rendered"]), 2)

    def test_refused_pair_is_recorded_and_the_run_continues(self):
        calls = []

        def fake_main(script, out):
            calls.append(out)
            if "silero" in out:
                raise SystemExit("engine 'silero' is not wired into this build yet")
            Path(out).write_text("mp3", encoding="utf-8")
            Path(out).with_suffix(".json").write_text(
                '{"length": "0:12", "device": "cpu"}', encoding="utf-8")

        with tempfile.TemporaryDirectory() as td, \
                mock.patch.object(voice_lab.render_audio, "main", side_effect=fake_main), \
                mock.patch.dict(os.environ, {"AIDEMY_VOICE_A": "before"}, clear=True):
            voice_lab.main(["--pairs", "silero:aidar+silero:baya", "piper:a+piper:b", "--out", td])
            record = json.loads((Path(td) / "lab.json").read_text(encoding="utf-8"))
            self.assertEqual(os.environ["AIDEMY_VOICE_A"], "before")
        self.assertEqual(len(record["rendered"]), 1)
        self.assertEqual(len(record["skipped"]), 1)
        self.assertIn("not wired", record["skipped"][0]["reason"])
        self.assertEqual(len(calls), 2)


class VoiceSileroEngine(unittest.TestCase):
    """Silero v5 takes the speaker by name, one string per call, and every line is
    written at 48 kHz."""

    def fake_torch(self, calls):
        class FakeTensor:
            def squeeze(self, dim):
                return self

            def cpu(self):
                return self

            def numpy(self):
                return numpy.zeros(480, dtype="float32")

        class FakeModel:
            def apply_tts(self, text=None, speaker=None, sample_rate=None):
                calls.append((text, speaker, sample_rate))
                return FakeTensor()

        importer = lambda path: types.SimpleNamespace(load_pickle=lambda a, b: FakeModel())
        return types.SimpleNamespace(package=types.SimpleNamespace(PackageImporter=importer))

    def test_speaker_per_host_and_rate(self):
        calls = []
        plan = {"A": ("silero", "aidar", None), "B": ("silero", "baya", None)}
        with tempfile.TemporaryDirectory() as td, \
                mock.patch.dict(sys.modules, {"torch": self.fake_torch(calls)}), \
                mock.patch.dict(os.environ, {"AIDEMY_MODEL_DIR": td}, clear=True):
            (Path(td) / "silero").mkdir()
            (Path(td) / "silero" / render_audio.SILERO_MODEL).write_bytes(b"x")
            tmp = Path(td) / "parts"
            tmp.mkdir()
            parts = render_audio.silero_parts([(0, "A", "раз [пауза]"), (1, "B", "два")], tmp, plan, "cpu")
        self.assertEqual([call[1] for call in calls], ["aidar", "baya"])
        self.assertEqual(calls[0][0], "раз")
        self.assertEqual({call[2] for call in calls}, {48000})
        self.assertEqual(parts[0][1], 48000)

    def test_unknown_voice_is_named_before_loading(self):
        plan = {"A": ("silero", "ghost", None), "B": ("silero", "baya", None)}
        with tempfile.TemporaryDirectory() as td, \
                mock.patch.dict(os.environ, {"AIDEMY_MODEL_DIR": td}, clear=True):
            (Path(td) / "silero").mkdir()
            (Path(td) / "silero" / render_audio.SILERO_MODEL).write_bytes(b"x")
            with self.assertRaises(SystemExit) as ctx:
                render_audio.silero_parts([(0, "A", "текст")], Path(td), plan, "cpu")
        self.assertIn("ghost", str(ctx.exception))

    def test_missing_weights_names_the_fetch_command(self):
        plan = {"A": ("silero", "aidar", None), "B": ("silero", "baya", None)}
        with tempfile.TemporaryDirectory() as td, \
                mock.patch.dict(os.environ, {"AIDEMY_MODEL_DIR": td}, clear=True):
            (Path(td) / "silero").mkdir()
            with self.assertRaises(SystemExit) as ctx:
                render_audio.silero_parts([(0, "A", "текст")], Path(td), plan, "cpu")
        self.assertIn("get_voices.py silero", str(ctx.exception))


class VoiceSileroDownload(unittest.TestCase):
    """One weights file, five speakers, and a size check because the host has no md5."""

    def test_unknown_voice_is_named(self):
        with self.assertRaises(SystemExit) as ctx:
            get_voices.fetch_silero(["ghost"])
        self.assertIn("ghost", str(ctx.exception))

    def test_ready_file_is_reused_without_download(self):
        with tempfile.TemporaryDirectory() as td, \
                mock.patch.dict(os.environ, {"AIDEMY_MODEL_DIR": td}, clear=True), \
                mock.patch.object(get_voices, "remote_size", return_value=10), \
                mock.patch.object(get_voices, "fetch") as fetch:
            (Path(td) / "silero").mkdir()
            (Path(td) / "silero" / get_voices.SILERO_MODEL).write_bytes(b"x")
            self.assertTrue(get_voices.fetch_silero(["aidar"]))
        fetch.assert_not_called()

    def test_size_mismatch_removes_the_file(self):
        with tempfile.TemporaryDirectory() as td, \
                mock.patch.dict(os.environ, {"AIDEMY_MODEL_DIR": td}, clear=True), \
                mock.patch.object(get_voices, "remote_size", return_value=10):

            def lying_fetch(url, target):
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(b"short")

            with mock.patch.object(get_voices, "fetch", side_effect=lying_fetch):
                with self.assertRaises(SystemExit) as ctx:
                    get_voices.fetch_silero(["aidar"])
            self.assertIn("size mismatch", str(ctx.exception))
            self.assertFalse((Path(td) / "silero" / get_voices.SILERO_MODEL).exists())


class GateRussian(unittest.TestCase):
    """The gate speaks Russian: card sections, demand phrases, dashes, and a word
    corridor that follows the engine's measured pace."""

    URLS = {"https://example.com/a"}

    def test_russian_sections_are_the_ones_found(self):
        self.assertEqual(check_lessons.check_card(CARD_OK, self.URLS), [])
        broken = CARD_OK.replace("**Правило**", "**Rule to keep**")
        self.assertIn("card missing '**Правило**'", check_lessons.check_card(broken, self.URLS))

    def test_russian_demand_phrase_fails(self):
        card = CARD_OK.replace("**Пропустить** ничего", "**Пропустить** ничего. ты должен решить сам")
        problems = check_lessons.check_card(card, self.URLS)
        self.assertTrue(any("demand phrase" in p for p in problems), problems)

    def test_dashes_are_allowed_where_the_voice_was_measured(self):
        """Rendered on this machine: "Фокус это приём." against the same line with
        "—" and with "--" on piper, silero and kokoro. None of them said the sign;
        piper's pause moved 0.13 s to 0.16 s, silero gained 0.14 s, kokoro's G2P
        dropped the sign entirely. So the ban was a guess, and it cost the first
        live course run three failed attempts on one lesson."""
        card = CARD_OK.replace("**Правило** называй точку выхода до разговора",
                               "**Правило** — называй точку выхода до разговора")
        self.assertEqual(check_lessons.check_card(card, self.URLS), [])
        problems, _ = check_lessons.check_script("A: цена — это выбор\nB: да\nA: да", (1, 10))
        self.assertEqual(problems, [])

    def test_the_mac_voice_still_refuses_an_emdash(self):
        with mock.patch.dict(os.environ, {"AIDEMY_TTS": "say"}):
            self.assertTrue(check_lessons.uses_say())
            problems, _ = check_lessons.check_script("A: цена — это выбор\nB: да\nA: да", (1, 10))
        self.assertTrue(any("emdash" in p for p in problems), problems)

    def test_double_hyphen_fails_the_card_and_the_mac_voice(self):
        card = CARD_OK.replace("**Правило** ", "**Правило** -- ")
        self.assertTrue(any("double hyphen" in p for p in check_lessons.check_card(card, self.URLS)))
        with mock.patch.dict(os.environ, {"AIDEMY_TTS": "say"}):
            problems, _ = check_lessons.check_script("A: один -- два\nB: три", (1, 10))
        self.assertTrue(any("double hyphen" in p for p in problems))

    def test_word_corridor_follows_the_engine(self):
        self.assertEqual(check_lessons.word_range({}), (300, 383))
        self.assertEqual(check_lessons.word_range({"AIDEMY_TTS": "kokoro"}), (250, 313))
        self.assertEqual(check_lessons.word_range({"AIDEMY_VOICE_A": "piper:x",
                                                   "AIDEMY_VOICE_B": "kokoro:y"}), (300, 313))

    def test_short_lesson_passes_on_kokoro_and_fails_on_piper(self):
        text = "A: " + " ".join(["слово"] * 260) + "\nB: ещё реплика"
        short, _ = check_lessons.check_script(text, (250, 313))
        self.assertEqual(short, [])
        long_enough, _ = check_lessons.check_script(text, (300, 383))
        self.assertTrue(any("words" in p for p in long_enough), long_enough)


class NoSocketsHere:
    """Any attempt to open a socket lands here. Used as a stand-in for
    socket.socket: urllib reaches the network through that name, so replacing it
    catches a real call rather than one particular import."""

    def __init__(self, *args, **kwargs):
        raise AssertionError("сеть запрещена")


class NoNetworkInSynthesis(unittest.TestCase):
    """scrape.py is the only script allowed to talk to the web: a card check and a
    lesson synthesis must work on a machine with no route out."""

    def test_the_socket_probe_actually_bites(self):
        # Without this control the offline test below could pass by never being tried.
        with mock.patch.object(socket, "socket", NoSocketsHere):
            with self.assertRaises(AssertionError):
                socket.create_connection(("example.com", 80), timeout=1)

    def test_card_gate_and_piper_synthesis_open_no_socket(self):
        fake = types.ModuleType("piper")

        class FakeVoice:
            class config:
                sample_rate = 22050

            @classmethod
            def load(cls, path):
                return cls()

            def synthesize_wav(self, text, wav_file, syn_config=None):
                wav_file.setnchannels(1)
                wav_file.setsampwidth(2)
                wav_file.setframerate(22050)
                wav_file.writeframes(b"\x00\x00" * 2205)

        fake.PiperVoice = FakeVoice
        fake.SynthesisConfig = lambda **kwargs: kwargs
        with mock.patch.object(socket, "socket", NoSocketsHere), \
                tempfile.TemporaryDirectory() as td, \
                mock.patch.dict(sys.modules, {"piper": fake}), \
                mock.patch.dict(os.environ, {"AIDEMY_MODEL_DIR": td}, clear=True):
            (Path(td) / "piper").mkdir()
            for voice in ("va", "vb"):
                (Path(td) / "piper" / f"{voice}.onnx").write_bytes(b"x")
            self.assertEqual(check_lessons.check_card(CARD_OK, {"https://example.com/a"}), [])
            tmp = Path(td) / "parts"
            tmp.mkdir()
            parts = render_audio.piper_parts(
                [(0, "A", "раз"), (1, "B", "два"), (2, "A", "три")], tmp,
                {"A": ("piper", "va", None), "B": ("piper", "vb", None)}, "cpu")
        self.assertEqual(sorted(parts), [0, 1, 2])


class CardTimeAndLabel(unittest.TestCase):
    """Two defects the acceptance run exposed: a Russian card never got its real
    time, and a mixed pair lost the pitch of the second host in the label."""

    def test_russian_listen_line_gets_real_time(self):
        with tempfile.TemporaryDirectory() as td:
            card = Path(td) / "card.md"
            card.write_text("**Слушать:** x.mp3 (2 мин)\n**Идея в трёх строках**\n", encoding="utf-8")
            with mock.patch.object(render_audio.subprocess, "run", return_value=mock.Mock(stdout="125.0\n")):
                length = render_audio.stamp_card(card, Path(td) / "x.mp3")
            text = card.read_text(encoding="utf-8")
        self.assertEqual(length, "2:05")
        self.assertIn("(2:05)", text)
        self.assertNotIn("(2 мин)", text)

    def test_english_listen_line_still_works(self):
        with tempfile.TemporaryDirectory() as td:
            card = Path(td) / "card.md"
            card.write_text("**Listen:** x.mp3 (2 min)\n", encoding="utf-8")
            with mock.patch.object(render_audio.subprocess, "run", return_value=mock.Mock(stdout="61.0\n")):
                render_audio.stamp_card(card, Path(td) / "x.mp3")
            self.assertIn("(1:01)", card.read_text(encoding="utf-8"))

    def test_mixed_label_keeps_the_pitch(self):
        plan = {"A": ("kokoro", "dima", None), "B": ("piper", "irina", -4.0)}
        self.assertEqual(render_audio.label(plan), "kokoro (dima) / piper (irina -4)")


class StyleBriefs(unittest.TestCase):
    """A style changes the register of the speech and nothing the gate checks, and
    the briefs must not drift away from the numbers the gate really enforces."""

    SKILL_DIR = Path(check_lessons.__file__).resolve().parents[1]

    def brief(self):
        return (self.SKILL_DIR / "references" / "style-briefs.md").read_text(encoding="utf-8")

    def test_every_preset_is_written_with_examples_of_tone(self):
        text = self.brief()
        presets = re.findall(r"^### (.+)$", text, flags=re.M)
        self.assertGreaterEqual(len(presets), 3)
        for preset in presets:
            block = text.split(f"### {preset}", 1)[1].split("###")[0]
            examples = [line for line in block.splitlines() if line.startswith("- «")]
            self.assertGreaterEqual(len(examples), 3, f"{preset}: no examples of tone")
        self.assertIn("style-briefs.md", (self.SKILL_DIR / "SKILL.md").read_text(encoding="utf-8"))

    def test_a_joking_style_does_not_excuse_a_demand(self):
        card = CARD_OK.replace("**Правило** называй", "**Правило** ты должен называть")
        problems = check_lessons.check_card(card, {"https://example.com/a"})
        self.assertTrue(any("demand phrase" in p for p in problems), problems)

    def test_the_numbers_in_the_briefs_are_the_gate_numbers(self):
        expected = {tuple(sorted(pair)) for pair in check_lessons.WORD_RANGE.values()}
        for name in ("references/writer-brief.md", "references/lesson-design.md"):
            text = (self.SKILL_DIR / name).read_text(encoding="utf-8")
            pairs = {tuple(sorted((int(low), int(high)))) for low, high in
                     re.findall(r"(\d{3})\s*[–-]\s*(\d{3})", text)}
            self.assertTrue(expected <= pairs, f"{name} lost the word corridor: {sorted(pairs)}")

    def test_the_skill_calls_scripts_through_the_running_container(self):
        text = (self.SKILL_DIR / "SKILL.md").read_text(encoding="utf-8")
        self.assertIn("docker compose ps", text)
        self.assertIn("docker compose exec -T aidemy python skills/aidemy/scripts/", text)


if __name__ == "__main__":
    unittest.main()
