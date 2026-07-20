from __future__ import annotations

import base64
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.utils import formatdate, formataddr
from typing import Any


class MimeMessage:
    """Builder for RFC 2822-compliant email messages.

    Produces messages encoded for the Gmail API ``raw`` field (base64url).

    Usage::

        raw = (MimeMessage()
               .to(["alice@example.com"])
               .subject("Hello")
               .plain("Hello Alice!")
               .build())
        # → base64url-encoded RFC 2822 string
    """

    def __init__(self) -> None:
        self._to: list[str] = []
        self._cc: list[str] = []
        self._bcc: list[str] = []
        self._subject: str = ""
        self._body_plain: str = ""
        self._body_html: str = ""
        self._reply_to: str = ""
        self._from: str = ""
        self._extra_headers: dict[str, str] = {}

    def to(self, addresses: str | list[str]) -> MimeMessage:
        if isinstance(addresses, str):
            self._to = [addresses]
        else:
            self._to = list(addresses)
        return self

    def cc(self, addresses: str | list[str]) -> MimeMessage:
        if isinstance(addresses, str):
            self._cc = [addresses]
        else:
            self._cc = list(addresses)
        return self

    def bcc(self, addresses: str | list[str]) -> MimeMessage:
        if isinstance(addresses, str):
            self._bcc = [addresses]
        else:
            self._bcc = list(addresses)
        return self

    def subject(self, text: str) -> MimeMessage:
        self._subject = text
        return self

    def plain(self, text: str) -> MimeMessage:
        self._body_plain = text
        return self

    def html(self, text: str) -> MimeMessage:
        self._body_html = text
        return self

    def reply_to(self, address: str) -> MimeMessage:
        self._reply_to = address
        return self

    def from_(self, address: str) -> MimeMessage:
        self._from = address
        return self

    def header(self, name: str, value: str) -> MimeMessage:
        self._extra_headers[name] = value
        return self

    def build(self) -> str:
        msg: MIMEMultipart | MIMEText
        has_html = bool(self._body_html)
        has_plain = bool(self._body_plain)

        if has_html and has_plain:
            msg = MIMEMultipart("alternative")
            if self._body_plain:
                msg.attach(MIMEText(self._body_plain, "plain"))
            if self._body_html:
                msg.attach(MIMEText(self._body_html, "html"))
        elif has_html:
            msg = MIMEText(self._body_html, "html")
        else:
            msg = MIMEText(self._body_plain or "", "plain")

        msg["To"] = ", ".join(self._to)
        msg["Subject"] = self._subject
        msg["Date"] = formatdate(timeval=None, localtime=True)

        if self._cc:
            msg["Cc"] = ", ".join(self._cc)
        if self._bcc:
            msg["Bcc"] = ", ".join(self._bcc)
        if self._reply_to:
            msg["Reply-To"] = self._reply_to
        if self._from:
            msg["From"] = self._from

        for name, value in self._extra_headers.items():
            msg[name] = value

        return msg.as_string()

    def encode(self) -> str:
        raw = self.build()
        return base64.urlsafe_b64encode(raw.encode("utf-8")).decode("ascii")

    def reset(self) -> MimeMessage:
        self._to = []
        self._cc = []
        self._bcc = []
        self._subject = ""
        self._body_plain = ""
        self._body_html = ""
        self._reply_to = ""
        self._from = ""
        self._extra_headers = {}
        return self
