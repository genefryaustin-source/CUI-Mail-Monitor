import io
import logging
from typing import Optional


def extract_text_from_bytes(data: bytes, filename: Optional[str] = None) -> str:
    """
    Multi-format extractor:
    - PDF
    - DOCX
    - EML (email)
    - fallback (plain text)

    GUARANTEES non-empty return
    """

    filename = (filename or "").lower()
    text = ""

    # ----------------------------
    # 📄 PDF
    # ----------------------------
    if filename.endswith(".pdf") or data[:4] == b"%PDF":
        try:
            from pypdf import PdfReader
            reader = PdfReader(io.BytesIO(data))

            pages = []
            for i, page in enumerate(reader.pages):
                try:
                    page_text = page.extract_text() or ""
                    if page_text.strip():
                        pages.append(page_text)
                except Exception as pe:
                    logging.warning(f"[extract][pdf] page {i} failed: {pe}")

            text = "\n".join(pages)

            if text.strip():
                logging.info(f"[extract][pdf] success len={len(text)} file={filename}")
                return text

        except Exception as e:
            logging.warning(f"[extract][pdf] failed: {e}")

    # ----------------------------
    # 📝 DOCX
    # ----------------------------
    if filename.endswith(".docx"):
        try:
            from docx import Document
            doc = Document(io.BytesIO(data))

            paragraphs = [p.text for p in doc.paragraphs if p.text.strip()]
            text = "\n".join(paragraphs)

            if text.strip():
                logging.info(f"[extract][docx] success len={len(text)} file={filename}")
                return text

        except Exception as e:
            logging.warning(f"[extract][docx] failed: {e}")

    # ----------------------------
    # 📧 EMAIL (.eml)
    # ----------------------------
    if filename.endswith(".eml"):
        try:
            import email
            msg = email.message_from_bytes(data)

            parts = []

            if msg.is_multipart():
                for part in msg.walk():
                    content_type = part.get_content_type()
                    payload = part.get_payload(decode=True)

                    if payload and content_type == "text/plain":
                        parts.append(payload.decode(errors="ignore"))
            else:
                payload = msg.get_payload(decode=True)
                if payload:
                    parts.append(payload.decode(errors="ignore"))

            text = "\n".join([p for p in parts if p.strip()])

            if text.strip():
                logging.info(f"[extract][email] success len={len(text)} file={filename}")
                return text

        except Exception as e:
            logging.warning(f"[extract][email] failed: {e}")

    # ----------------------------
    # 🔤 FALLBACK (utf-8 → latin-1)
    # ----------------------------
    try:
        text = data.decode("utf-8", errors="ignore")
        if not text.strip():
            text = data.decode("latin-1", errors="ignore")

    except Exception as e:
        logging.warning(f"[extract][fallback] decode failed: {e}")

    # ----------------------------
    # 🚨 FINAL GUARANTEE
    # ----------------------------
    if not text or not text.strip():
        logging.error(f"[extract] EMPTY TEXT — forcing placeholder file={filename}")
        return "[NO TEXT EXTRACTED]"

    logging.info(f"[extract][fallback] success len={len(text)} file={filename}")
    return text.strip()