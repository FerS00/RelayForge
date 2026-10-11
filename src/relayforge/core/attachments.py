from __future__ import annotations

import base64
import hashlib
import io
import warnings
import zipfile
from pathlib import Path
from typing import Any
from xml.etree import ElementTree

from PIL import Image
from pypdf import PdfReader, apply_configuration
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from relayforge.core.ids import new_ulid
from relayforge.db.models import Attachment, Conversation
from relayforge.security.redact import redact_text

MAX_BYTES = 8 * 1024 * 1024
MAX_BODY = 12 * 1024 * 1024
MAX_TEXT = 64_000
TEXT_TYPES = {
    ".txt": "text/plain",
    ".md": "text/plain",
    ".log": "text/plain",
    ".json": "application/json",
    ".csv": "text/csv",
}
IMAGE_TYPES = {
    ".png": ("PNG", "image/png"),
    ".jpg": ("JPEG", "image/jpeg"),
    ".jpeg": ("JPEG", "image/jpeg"),
    ".webp": ("WEBP", "image/webp"),
}


class AttachmentError(ValueError):
    def __init__(self, code: str, status: int = 422) -> None:
        self.code, self.status = code, status
        super().__init__(code)


def validate_content(name: str, data: bytes) -> tuple[str, bytes, str, str]:
    if not 1 <= len(name) <= 180 or any(c in name for c in "/\\") or any(ord(c) < 32 for c in name):
        raise AttachmentError("attachment_name_invalid")
    if not data or len(data) > MAX_BYTES:
        raise AttachmentError("attachment_size_invalid", 413)
    suffix = Path(name).suffix.lower()
    text, state = "", "ready"
    try:
        if suffix in TEXT_TYPES:
            text = redact_text(data.decode("utf-8-sig"))
            data = text.encode("utf-8")
            media = TEXT_TYPES[suffix]
        elif suffix in IMAGE_TYPES:
            expected, media = IMAGE_TYPES[suffix]
            with warnings.catch_warnings():
                warnings.simplefilter("error", Image.DecompressionBombWarning)
                with Image.open(io.BytesIO(data)) as image:
                    if image.format != expected or image.width * image.height > 20_000_000:
                        raise AttachmentError("attachment_image_invalid")
                    image.verify()
        elif suffix == ".pdf":
            if not data.startswith(b"%PDF-"):
                raise AttachmentError("attachment_document_invalid")
            with apply_configuration(
                maximum_declared_stream_length=MAX_BYTES,
                array_based_stream_maximum_output_length=MAX_BYTES,
                zlib_maximum_output_length=MAX_BYTES,
                lzw_maximum_output_length=MAX_BYTES,
                run_length_maximum_output_length=MAX_BYTES,
                image_maximum_buffer_size=MAX_BYTES,
            ):
                reader = PdfReader(io.BytesIO(data))
                if reader.is_encrypted or len(reader.pages) > 100:
                    raise AttachmentError("attachment_document_invalid")
                for page in reader.pages:
                    text += page.extract_text() or ""
                    if len(text) > MAX_TEXT:
                        raise AttachmentError("attachment_text_limit", 413)
            text = redact_text(text)
            state = "ready" if text.strip() else "no_text_extracted"
            media = "application/pdf"
        elif suffix == ".docx":
            with zipfile.ZipFile(io.BytesIO(data)) as archive:
                infos = archive.infolist()
                if len(infos) > 500 or sum(i.file_size for i in infos) > MAX_BYTES:
                    raise AttachmentError("attachment_document_limit", 413)
                if any("vba" in i.filename.lower() for i in infos):
                    raise AttachmentError("attachment_document_invalid")
                document = ElementTree.fromstring(archive.read("word/document.xml"))
                text = redact_text(" ".join(document.itertext()))
            media = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
        else:
            raise AttachmentError("attachment_type_unsupported")
    except AttachmentError:
        raise
    except Exception as exc:
        raise AttachmentError("attachment_content_invalid") from exc
    if len(text) > MAX_TEXT:
        raise AttachmentError("attachment_text_limit", 413)
    return media, data, text, state


class AttachmentService:
    def __init__(self, sessions: sessionmaker[Session], storage: Path) -> None:
        self.sessions, self.storage = sessions, storage

    def create(self, conversation_id: str, name: str, encoded: str) -> dict[str, Any]:
        with self.sessions() as session:
            if session.get(Conversation, conversation_id) is None:
                raise AttachmentError("conversation_not_found", 404)
        try:
            original = base64.b64decode(encoded, validate=True)
        except (ValueError, UnicodeError) as exc:
            raise AttachmentError("attachment_base64_invalid") from exc
        media, content, text, state = validate_content(name, original)
        identifier = new_ulid()
        self.storage.mkdir(parents=True, exist_ok=True)
        target = self.storage / identifier
        row = Attachment(
            id=identifier,
            conversation_id=conversation_id,
            name=redact_text(name),
            media_type=media,
            size_bytes=len(original),
            sha256=hashlib.sha256(original).hexdigest(),
            stored_sha256=hashlib.sha256(content).hexdigest(),
            storage_name=identifier,
            extracted_text=text,
            state=state,
        )
        with target.open("xb") as output:
            output.write(content)
        try:
            with self.sessions.begin() as session:
                session.add(row)
        except Exception:
            target.unlink(missing_ok=True)
            raise
        return self.metadata(row)

    @staticmethod
    def metadata(row: Attachment) -> dict[str, Any]:
        return {
            "id": row.id,
            "name": row.name,
            "media_type": row.media_type,
            "size_bytes": row.size_bytes,
            "sha256": row.sha256,
            "stored_sha256": row.stored_sha256,
            "state": row.state,
            "message_id": row.message_id,
            "created_at": row.created_at,
        }

    def get(self, conversation_id: str, attachment_id: str) -> Attachment:
        with self.sessions() as session:
            row = session.scalar(
                select(Attachment).where(
                    Attachment.id == attachment_id, Attachment.conversation_id == conversation_id
                )
            )
            if row is None:
                raise AttachmentError("attachment_not_found", 404)
            session.expunge(row)
            return row

    def path(self, row: Attachment) -> Path:
        root = self.storage.resolve(strict=True)
        target = (root / row.storage_name).resolve(strict=True)
        if not target.is_relative_to(root) or not target.is_file():
            raise AttachmentError("attachment_storage_invalid")
        if hashlib.sha256(target.read_bytes()).hexdigest() != row.stored_sha256:
            raise AttachmentError("attachment_integrity_failed")
        return target
