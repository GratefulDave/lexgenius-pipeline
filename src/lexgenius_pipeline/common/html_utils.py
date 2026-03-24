"""Shared HTML parsing utilities for scrape-based connectors."""
from __future__ import annotations

from html.parser import HTMLParser


class LinkExtractorParser(HTMLParser):
    """Minimal HTML parser that extracts ``<a>`` links and their text.

    After calling ``feed(html)``, results are available in ``self.links``
    as a list of ``{"text": ..., "href": ...}`` dicts.
    """

    def __init__(self) -> None:
        super().__init__()
        self.links: list[dict[str, str]] = []
        self._current_data: list[str] = []
        self._in_a = False
        self._current_href = ""

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str]]) -> None:
        if tag == "a":
            self._in_a = True
            self._current_data = []
            for attr, val in attrs:
                if attr == "href":
                    self._current_href = val

    def handle_data(self, data: str) -> None:
        if self._in_a:
            self._current_data.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag == "a" and self._in_a:
            text = "".join(self._current_data).strip()
            if text and self._current_href:
                self.links.append({"text": text, "href": self._current_href})
            self._in_a = False
            self._current_href = ""
