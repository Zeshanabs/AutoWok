from __future__ import annotations

import re
from html import unescape
from html.parser import HTMLParser


class _HTMLTextExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.fragments: list[str] = []

    def handle_data(self, data: str) -> None:
        if data:
            self.fragments.append(data)

    def get_text(self) -> str:
        return " ".join(self.fragments)


def extract_readable_text(html: str) -> str:
    if not html:
        return ""
    parser = _HTMLTextExtractor()
    parser.feed(html)
    text = parser.get_text()
    text = unescape(text)
    text = re.sub(r"\s+", " ", text)
    return text.strip()
