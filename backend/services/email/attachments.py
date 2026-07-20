from __future__ import annotations

from services.email.models import Attachment
from services.email.exceptions import InvalidAttachmentError

SUPPORTED_MIME_TYPES: set[str] = {
    "application/pdf",
    "application/msword",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "application/vnd.ms-powerpoint",
    "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    "application/vnd.ms-excel",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "image/jpeg",
    "image/png",
    "image/gif",
    "image/webp",
    "image/svg+xml",
    "application/zip",
    "text/plain",
    "text/csv",
}

MAX_ATTACHMENT_SIZE: int = 25 * 1024 * 1024
MAX_TOTAL_ATTACHMENT_SIZE: int = 50 * 1024 * 1024


class AttachmentProcessor:
    def __init__(
        self,
        max_size: int = MAX_ATTACHMENT_SIZE,
        max_total: int = MAX_TOTAL_ATTACHMENT_SIZE,
    ) -> None:
        self._max_size = max_size
        self._max_total = max_total

    def validate(self, attachment: Attachment) -> None:
        if len(attachment.bytes) > self._max_size:
            raise InvalidAttachmentError(
                f"Attachment {attachment.filename!r} exceeds max size "
                f"of {self._max_size} bytes"
            )

    def validate_batch(self, attachments: tuple[Attachment, ...]) -> None:
        total = 0
        for a in attachments:
            self.validate(a)
            total += len(a.bytes)
        if total > self._max_total:
            raise InvalidAttachmentError(
                f"Total attachment size {total} exceeds max of {self._max_total}"
            )

    @staticmethod
    def supported_mime_types() -> set[str]:
        return set(SUPPORTED_MIME_TYPES)
