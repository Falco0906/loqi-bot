from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class TemplateName(str, Enum):
    PLAIN = "plain"
    PROFESSIONAL = "professional"
    RECRUITING = "recruiting"
    NEWSLETTER = "newsletter"
    PROPOSAL = "proposal"
    PRODUCT_LAUNCH = "product_launch"


@dataclass(frozen=True)
class Attachment:
    filename: str
    mime_type: str
    bytes: bytes
    content_id: str = ""

    def __post_init__(self) -> None:
        if not self.filename:
            raise ValueError("filename is required")
        if not self.mime_type:
            raise ValueError("mime_type is required")
        if not self.bytes:
            raise ValueError("bytes data is required")


@dataclass(frozen=True)
class CompanyMailbox:
    id: str
    email: str
    display_name: str = ""
    signature: str = ""
    default: bool = False

    def __post_init__(self) -> None:
        if not self.id:
            raise ValueError("id is required")
        if not self.email or "@" not in self.email:
            raise ValueError(f"Invalid email: {self.email!r}")


@dataclass(frozen=True)
class BrandKit:
    company_name: str
    logo_url: str = ""
    primary_color: str = "#2563eb"
    secondary_color: str = "#1e40af"
    font_family: str = "Arial, Helvetica, sans-serif"
    website: str = ""
    social_links: dict[str, str] = field(default_factory=dict)
    signature: str = ""

    def __post_init__(self) -> None:
        if not self.company_name:
            raise ValueError("company_name is required")


@dataclass(frozen=True)
class EmailDraft:
    subject: str
    body_plain: str = ""
    body_html: str = ""
    preview_text: str = ""
    to: tuple[str, ...] = ()
    cc: tuple[str, ...] = ()
    bcc: tuple[str, ...] = ()
    reply_to: str = ""
    attachments: tuple[Attachment, ...] = ()
    mailbox: CompanyMailbox | None = None
    brand_kit: BrandKit | None = None
    template_name: TemplateName = TemplateName.PLAIN
    metadata: dict[str, Any] = field(default_factory=dict)
    footer: str = ""

    def __post_init__(self) -> None:
        if not self.subject:
            raise ValueError("subject is required")

    @property
    def sender_email(self) -> str:
        if self.mailbox:
            return self.mailbox.email
        return ""

    @property
    def sender_display(self) -> str:
        if self.mailbox and self.mailbox.display_name:
            return self.mailbox.display_name
        return self.sender_email
