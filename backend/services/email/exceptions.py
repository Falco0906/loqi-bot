from __future__ import annotations


class EmailCompositionError(Exception):
    pass


class UnknownTemplateError(EmailCompositionError):
    pass


class BrandKitNotFoundError(EmailCompositionError):
    pass


class MailboxNotFoundError(EmailCompositionError):
    pass


class InvalidAttachmentError(EmailCompositionError):
    pass


class DraftValidationError(EmailCompositionError):
    pass


class RenderingError(EmailCompositionError):
    pass


class TemplateRenderError(EmailCompositionError):
    pass
