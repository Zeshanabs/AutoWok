"""Minimal, dependency-free PDF writer for text reports.

Produces a valid PDF 1.4 document with Helvetica text, automatic page breaks
and simple fixed-width tables. It is intentionally small: analytics reports
are text and tables, and this avoids adding a PDF library dependency.
Non-Latin-1 characters are replaced so the output always encodes cleanly.
"""

from __future__ import annotations

from dataclasses import dataclass, field

PAGE_WIDTH = 595  # A4 portrait in points
PAGE_HEIGHT = 842
MARGIN = 48
LINE_HEIGHT = 14
FONT_SIZE = 10
HEADING_SIZE = 14
TITLE_SIZE = 18
MAX_CHARS_PER_LINE = 95


def _escape(text: str) -> str:
    safe = text.encode("latin-1", "replace").decode("latin-1")
    return safe.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)").replace("\r", "").replace("\n", " ")


def _wrap(text: str, width: int = MAX_CHARS_PER_LINE) -> list[str]:
    words = text.split()
    lines: list[str] = []
    current = ""
    for word in words:
        candidate = f"{current} {word}".strip()
        if len(candidate) <= width:
            current = candidate
            continue
        if current:
            lines.append(current)
        while len(word) > width:
            lines.append(word[:width])
            word = word[width:]
        current = word
    if current or not lines:
        lines.append(current)
    return lines


@dataclass
class PdfDocument:
    title: str
    pages: list[list[str]] = field(default_factory=list)
    _y: float = PAGE_HEIGHT - MARGIN

    def __post_init__(self) -> None:
        self.pages.append([])

    # -- layout -----------------------------------------------------------
    def _ensure_space(self, needed: float) -> None:
        if self._y - needed < MARGIN:
            self.pages.append([])
            self._y = PAGE_HEIGHT - MARGIN

    def _text(self, text: str, size: int = FONT_SIZE, *, bold: bool = False, x: float = MARGIN) -> None:
        self._ensure_space(size + 4)
        font = "/F2" if bold else "/F1"
        self.pages[-1].append(f"BT {font} {size} Tf {x:.1f} {self._y:.1f} Td ({_escape(text)}) Tj ET")
        self._y -= size + 4

    def heading(self, text: str, level: int = 1) -> None:
        size = TITLE_SIZE if level == 0 else HEADING_SIZE if level == 1 else FONT_SIZE + 1
        self._y -= 6
        self._text(text, size, bold=True)
        self._y -= 2

    def paragraph(self, text: str) -> None:
        for line in _wrap(text):
            self._text(line)

    def bullet(self, text: str) -> None:
        lines = _wrap(text, MAX_CHARS_PER_LINE - 4)
        for index, line in enumerate(lines):
            self._text(("- " if index == 0 else "  ") + line, x=MARGIN + 8)

    def spacer(self, height: float = LINE_HEIGHT / 2) -> None:
        self._y -= height

    def table(self, headers: list[str], rows: list[list[str]], widths: list[int] | None = None) -> None:
        columns = len(headers)
        if widths is None:
            total = MAX_CHARS_PER_LINE
            widths = [max(6, total // columns)] * columns

        def cell(value: str, width: int) -> str:
            text = value if len(value) <= width else value[: max(1, width - 1)] + "…"
            return text.ljust(width)

        header_line = " ".join(cell(header, widths[index]) for index, header in enumerate(headers))
        self._ensure_space((FONT_SIZE + 4) * 2)
        self._mono(header_line, bold=True)
        self._mono("-" * min(len(header_line), MAX_CHARS_PER_LINE + 10))
        for row in rows:
            self._mono(" ".join(cell(str(value), widths[index]) for index, value in enumerate(row)))
        self.spacer()

    def _mono(self, text: str, *, bold: bool = False) -> None:
        self._ensure_space(FONT_SIZE + 3)
        font = "/F4" if bold else "/F3"
        self.pages[-1].append(f"BT {font} {FONT_SIZE - 1} Tf {MARGIN:.1f} {self._y:.1f} Td ({_escape(text)}) Tj ET")
        self._y -= FONT_SIZE + 3

    # -- serialisation ------------------------------------------------------
    def render(self) -> bytes:
        objects: list[bytes] = []

        def add(body: bytes) -> int:
            objects.append(body)
            return len(objects)

        font_ids = [
            add(b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica /Encoding /WinAnsiEncoding >>"),
            add(b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica-Bold /Encoding /WinAnsiEncoding >>"),
            add(b"<< /Type /Font /Subtype /Type1 /BaseFont /Courier /Encoding /WinAnsiEncoding >>"),
            add(b"<< /Type /Font /Subtype /Type1 /BaseFont /Courier-Bold /Encoding /WinAnsiEncoding >>"),
        ]
        resources = (
            "<< /Font << /F1 {0} 0 R /F2 {1} 0 R /F3 {2} 0 R /F4 {3} 0 R >> >>".format(*font_ids)
        ).encode("latin-1")
        pages_placeholder = add(b"")  # replaced below once page ids are known
        page_ids: list[int] = []
        total_pages = len(self.pages)
        for index, operations in enumerate(self.pages, start=1):
            footer = f"BT /F1 8 Tf {MARGIN:.1f} {MARGIN / 2:.1f} Td ({_escape(self.title)} - page {index} of {total_pages}) Tj ET"
            stream = "\n".join(operations + [footer]).encode("latin-1", "replace")
            content_id = add(b"<< /Length " + str(len(stream)).encode() + b" >>\nstream\n" + stream + b"\nendstream")
            page_ids.append(
                add(
                    (
                        f"<< /Type /Page /Parent {pages_placeholder} 0 R /MediaBox [0 0 {PAGE_WIDTH} {PAGE_HEIGHT}] "
                        f"/Contents {content_id} 0 R /Resources "
                    ).encode("latin-1")
                    + resources
                    + b" >>"
                )
            )
        kids = " ".join(f"{page_id} 0 R" for page_id in page_ids)
        objects[pages_placeholder - 1] = f"<< /Type /Pages /Kids [{kids}] /Count {len(page_ids)} >>".encode("latin-1")
        catalog_id = add(f"<< /Type /Catalog /Pages {pages_placeholder} 0 R >>".encode("latin-1"))
        info_id = add(b"<< /Title (" + _escape(self.title).encode("latin-1", "replace") + b") /Producer (Autowok) >>")

        output = bytearray(b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n")
        offsets: list[int] = []
        for number, body in enumerate(objects, start=1):
            offsets.append(len(output))
            output += f"{number} 0 obj\n".encode("latin-1") + body + b"\nendobj\n"
        xref_offset = len(output)
        output += f"xref\n0 {len(objects) + 1}\n".encode("latin-1")
        output += b"0000000000 65535 f \n"
        for offset in offsets:
            output += f"{offset:010d} 00000 n \n".encode("latin-1")
        output += (
            f"trailer\n<< /Size {len(objects) + 1} /Root {catalog_id} 0 R /Info {info_id} 0 R >>\n"
            f"startxref\n{xref_offset}\n%%EOF\n"
        ).encode("latin-1")
        return bytes(output)
