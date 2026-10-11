import io
import zipfile

import pytest
from pypdf import PdfWriter

from relayforge.core.attachments import AttachmentError, validate_content


def test_text_is_redacted_before_storage_and_agent_context():
    media, stored, text, state = validate_content(
        "error.log", b"Authorization: Bearer sk-abcdefghijklmnop1234567890"
    )
    assert media == "text/plain" and state == "ready"
    assert "sk-abcdefghijklmnop1234567890" not in text
    assert stored == text.encode()


def test_scanned_pdf_is_labeled_without_ocr_claim():
    writer = PdfWriter()
    writer.add_blank_page(width=100, height=100)
    output = io.BytesIO()
    writer.write(output)
    media, _, text, state = validate_content("scan.pdf", output.getvalue())
    assert media == "application/pdf" and not text and state == "no_text_extracted"


def test_docx_extracts_text_and_rejects_expansion_limit():
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("word/document.xml", "<document><p>Evidence content</p></document>")
    assert "Evidence content" in validate_content("evidence.docx", output.getvalue())[2]
    bomb = io.BytesIO()
    with zipfile.ZipFile(bomb, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("word/document.xml", b"x" * (8 * 1024 * 1024 + 1))
    with pytest.raises(AttachmentError, match="document_limit"):
        validate_content("bomb.docx", bomb.getvalue())


def test_text_size_and_type_limits():
    with pytest.raises(AttachmentError, match="text_limit"):
        validate_content("long.txt", b"x" * 64001)
    with pytest.raises(AttachmentError, match="type_unsupported"):
        validate_content("page.html", b"<p>hello</p>")
