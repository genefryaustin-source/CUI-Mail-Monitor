# core/modules/extract.py
from __future__ import annotations

import io
import zipfile
import xml.etree.ElementTree as ET
from typing import Optional

from pypdf import PdfReader


DOCX_NS = {"w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main"}
PPTX_NS = {
    "a": "http://schemas.openxmlformats.org/drawingml/2006/main",
    "p": "http://schemas.openxmlformats.org/presentationml/2006/main",
}


def extract_text_from_bytes(
    file_bytes: bytes,
    filename: Optional[str] = None,
    content_type: Optional[str] = None,
    max_chars: int = 2_000_000,
) -> str:
    """
    Extract text from bytes for PDF/DOCX/PPTX/TXT without PyMuPDF and without lxml.

    - PDF: pypdf
    - DOCX: unzip + parse word/document.xml (stdlib)
    - PPTX: unzip + parse ppt/slides/slide*.xml (stdlib)
    - TXT: decode as utf-8 with fallbacks

    max_chars: safety cap to prevent runaway memory usage
    """
    name = (filename or "").lower()
    ctype = (content_type or "").lower()

    # Determine type
    if name.endswith(".pdf") or "pdf" in ctype:
        text = _extract_pdf(file_bytes)
    elif name.endswith(".docx") or "wordprocessingml" in ctype or "docx" in ctype:
        text = _extract_docx(file_bytes)
    elif name.endswith(".pptx") or "presentationml" in ctype or "pptx" in ctype:
        text = _extract_pptx(file_bytes)
    elif name.endswith(".txt") or "text/plain" in ctype or not name:
        text = _extract_text(file_bytes)
    else:
        # Best-effort fallback: try as text
        text = _extract_text(file_bytes)

    # Hard cap
    if len(text) > max_chars:
        text = text[:max_chars] + "\n\n[TRUNCATED]"
    return text.strip()


def _extract_pdf(file_bytes: bytes) -> str:
    out = []
    reader = PdfReader(io.BytesIO(file_bytes))
    for page in reader.pages:
        try:
            out.append(page.extract_text() or "")
        except Exception:
            out.append("")
    return "\n".join(out)


def _extract_docx(file_bytes: bytes) -> str:
    """
    DOCX is a zip file. Primary text is in word/document.xml.
    """
    out = []
    with zipfile.ZipFile(io.BytesIO(file_bytes)) as z:
        # Some DOCX may not have document.xml in edge cases
        if "word/document.xml" not in z.namelist():
            return ""
        xml_data = z.read("word/document.xml")

    root = ET.fromstring(xml_data)
    # All text runs are in w:t
    for node in root.findall(".//w:t", DOCX_NS):
        if node.text:
            out.append(node.text)
    return " ".join(out)


def _extract_pptx(file_bytes: bytes) -> str:
    """
    PPTX is a zip file. Slide text appears in ppt/slides/slide*.xml.
    """
    out = []
    with zipfile.ZipFile(io.BytesIO(file_bytes)) as z:
        slide_names = sorted(
            [n for n in z.namelist() if n.startswith("ppt/slides/slide") and n.endswith(".xml")]
        )
        for slide in slide_names:
            xml_data = z.read(slide)
            try:
                root = ET.fromstring(xml_data)
            except Exception:
                continue
            # Text nodes are a:t in drawingml
            for node in root.findall(".//a:t", PPTX_NS):
                if node.text:
                    out.append(node.text)
    return " ".join(out)


def _extract_text(file_bytes: bytes) -> str:
    # Try utf-8 first, fall back gently
    for enc in ("utf-8", "utf-16", "latin-1"):
        try:
            return file_bytes.decode(enc)
        except Exception:
            pass
    return ""
