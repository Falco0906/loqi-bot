from __future__ import annotations

import re
from typing import Any

import pytest

from services.email import (
    Attachment,
    BrandKit,
    BrandingManager,
    BrandKitNotFoundError,
    CompanyMailbox,
    DraftBuilder,
    DraftValidationError,
    EmailComposer,
    EmailCompositionError,
    EmailDraft,
    EmailRenderer,
    InvalidAttachmentError,
    MailboxManager,
    MailboxNotFoundError,
    RenderingError,
    TemplateName,
    TemplateRegistry,
    UnknownTemplateError,
    AttachmentProcessor,
    draft_to_gmail_params,
    render_template,
)


# ── Fixtures ─────────────────────────────────────────────────────────────────


@pytest.fixture
def brand_kit() -> BrandKit:
    return BrandKit(
        company_name="Loqi",
        logo_url="https://loqi.ai/logo.png",
        primary_color="#2563eb",
        secondary_color="#1e40af",
        font_family="Arial, sans-serif",
        website="https://loqi.ai",
        signature="— Team Loqi",
    )


@pytest.fixture
def mailbox() -> CompanyMailbox:
    return CompanyMailbox(
        id="sales",
        email="sales@loqi.ai",
        display_name="Loqi Sales",
        signature="— Loqi Sales Team",
        default=True,
    )


@pytest.fixture
def attachment() -> Attachment:
    return Attachment(
        filename="report.pdf",
        mime_type="application/pdf",
        bytes=b"%PDF-1.4 mock",
    )


@pytest.fixture
def draft() -> EmailDraft:
    return EmailDraft(
        subject="Hello",
        body_plain="Hello world",
        to=("user@example.com",),
    )


@pytest.fixture
def full_draft(brand_kit, mailbox, attachment) -> EmailDraft:
    return EmailDraft(
        subject="Weekly Report",
        body_plain="Here is the report",
        body_html="<p>Here is the <b>report</b></p>",
        preview_text="Weekly report preview",
        to=("alice@example.com", "bob@example.com"),
        cc=("carol@example.com",),
        bcc=("dave@example.com",),
        reply_to="replies@loqi.ai",
        attachments=(attachment,),
        mailbox=mailbox,
        brand_kit=brand_kit,
        template_name=TemplateName.PROFESSIONAL,
        metadata={"source": "test"},
        footer="Powered by Loqi",
    )


# ── Models ───────────────────────────────────────────────────────────────────


class TestAttachment:
    def test_create(self):
        a = Attachment(filename="f.pdf", mime_type="application/pdf", bytes=b"data")
        assert a.filename == "f.pdf"
        assert a.mime_type == "application/pdf"
        assert a.bytes == b"data"
        assert a.content_id == ""

    def test_create_with_content_id(self):
        a = Attachment(filename="f.png", mime_type="image/png", bytes=b"img", content_id="cid:123")
        assert a.content_id == "cid:123"

    def test_empty_filename_raises(self):
        with pytest.raises(ValueError, match="filename is required"):
            Attachment(filename="", mime_type="text/plain", bytes=b"x")

    def test_empty_mime_type_raises(self):
        with pytest.raises(ValueError, match="mime_type is required"):
            Attachment(filename="f.txt", mime_type="", bytes=b"x")

    def test_empty_bytes_raises(self):
        with pytest.raises(ValueError, match="bytes data is required"):
            Attachment(filename="f.txt", mime_type="text/plain", bytes=b"")

    def test_frozen(self):
        a = Attachment(filename="f.pdf", mime_type="application/pdf", bytes=b"data")
        with pytest.raises(Exception):
            a.filename = "other.pdf"  # type: ignore[misc]

    def test_repr(self):
        a = Attachment(filename="f.pdf", mime_type="application/pdf", bytes=b"data")
        r = repr(a)
        assert "f.pdf" in r
        assert "application/pdf" in r


class TestCompanyMailbox:
    def test_create(self):
        mb = CompanyMailbox(id="support", email="support@loqi.ai")
        assert mb.id == "support"
        assert mb.email == "support@loqi.ai"
        assert mb.display_name == ""
        assert mb.default is False

    def test_create_with_all_fields(self):
        mb = CompanyMailbox(
            id="sales",
            email="sales@loqi.ai",
            display_name="Loqi Sales",
            signature="— Sales Team",
            default=True,
        )
        assert mb.id == "sales"
        assert mb.email == "sales@loqi.ai"
        assert mb.display_name == "Loqi Sales"
        assert mb.signature == "— Sales Team"
        assert mb.default is True

    def test_empty_id_raises(self):
        with pytest.raises(ValueError, match="id is required"):
            CompanyMailbox(id="", email="x@y.com")

    def test_invalid_email_raises(self):
        with pytest.raises(ValueError, match="Invalid email"):
            CompanyMailbox(id="x", email="notanemail")

    def test_frozen(self):
        mb = CompanyMailbox(id="x", email="x@y.com")
        with pytest.raises(Exception):
            mb.id = "y"  # type: ignore[misc]


class TestBrandKit:
    def test_create(self):
        b = BrandKit(company_name="Loqi")
        assert b.company_name == "Loqi"
        assert b.primary_color == "#2563eb"

    def test_create_with_all_fields(self):
        b = BrandKit(
            company_name="Loqi Inc",
            logo_url="https://loqi.ai/logo.png",
            primary_color="#ff0000",
            secondary_color="#00ff00",
            font_family="Georgia",
            website="https://loqi.ai",
            social_links={"twitter": "https://twitter.com/loqi"},
            signature="— Loqi",
        )
        assert b.company_name == "Loqi Inc"
        assert b.logo_url == "https://loqi.ai/logo.png"
        assert b.primary_color == "#ff0000"
        assert b.secondary_color == "#00ff00"
        assert b.font_family == "Georgia"
        assert b.website == "https://loqi.ai"
        assert b.social_links == {"twitter": "https://twitter.com/loqi"}
        assert b.signature == "— Loqi"

    def test_empty_company_name_raises(self):
        with pytest.raises(ValueError, match="company_name is required"):
            BrandKit(company_name="")

    def test_frozen(self):
        b = BrandKit(company_name="Loqi")
        with pytest.raises(Exception):
            b.company_name = "Other"  # type: ignore[misc]


class TestTemplateName:
    def test_values(self):
        assert TemplateName.PLAIN.value == "plain"
        assert TemplateName.PROFESSIONAL.value == "professional"
        assert TemplateName.RECRUITING.value == "recruiting"
        assert TemplateName.NEWSLETTER.value == "newsletter"
        assert TemplateName.PROPOSAL.value == "proposal"
        assert TemplateName.PRODUCT_LAUNCH.value == "product_launch"

    def test_from_string(self):
        assert TemplateName("plain") == TemplateName.PLAIN
        assert TemplateName("professional") == TemplateName.PROFESSIONAL

    def test_invalid_raises(self):
        with pytest.raises(ValueError):
            TemplateName("invalid_template")


class TestEmailDraft:
    def test_create_minimal(self):
        d = EmailDraft(subject="Hello")
        assert d.subject == "Hello"
        assert d.body_plain == ""
        assert d.to == ()
        assert d.template_name == TemplateName.PLAIN

    def test_create_full(self, full_draft):
        d = full_draft
        assert d.subject == "Weekly Report"
        assert len(d.to) == 2
        assert len(d.attachments) == 1
        assert d.mailbox is not None
        assert d.brand_kit is not None
        assert d.template_name == TemplateName.PROFESSIONAL
        assert d.metadata == {"source": "test"}
        assert d.footer == "Powered by Loqi"

    def test_empty_subject_raises(self):
        with pytest.raises(ValueError, match="subject is required"):
            EmailDraft(subject="")

    def test_sender_email_with_mailbox(self, mailbox):
        d = EmailDraft(subject="Hi", mailbox=mailbox)
        assert d.sender_email == "sales@loqi.ai"

    def test_sender_email_without_mailbox(self):
        d = EmailDraft(subject="Hi")
        assert d.sender_email == ""

    def test_sender_display_with_display_name(self, mailbox):
        d = EmailDraft(subject="Hi", mailbox=mailbox)
        assert d.sender_display == "Loqi Sales"

    def test_sender_display_falls_back_to_email(self):
        mb = CompanyMailbox(id="x", email="bot@loqi.ai")
        d = EmailDraft(subject="Hi", mailbox=mb)
        assert d.sender_display == "bot@loqi.ai"

    def test_frozen(self):
        d = EmailDraft(subject="Hi")
        with pytest.raises(Exception):
            d.subject = "Changed"  # type: ignore[misc]

    def test_template_name_enum_coercion(self):
        d = EmailDraft(subject="Hi", template_name=TemplateName.NEWSLETTER)
        assert d.template_name == TemplateName.NEWSLETTER


# ── Exceptions ───────────────────────────────────────────────────────────────


class TestExceptions:
    def test_base_exception(self):
        e = EmailCompositionError("test")
        assert str(e) == "test"

    def test_unknown_template_error(self):
        e = UnknownTemplateError("unknown")
        assert isinstance(e, EmailCompositionError)

    def test_brand_kit_not_found(self):
        e = BrandKitNotFoundError("missing")
        assert isinstance(e, EmailCompositionError)

    def test_mailbox_not_found(self):
        e = MailboxNotFoundError("missing")
        assert isinstance(e, EmailCompositionError)

    def test_invalid_attachment(self):
        e = InvalidAttachmentError("bad")
        assert isinstance(e, EmailCompositionError)

    def test_draft_validation_error(self):
        e = DraftValidationError("invalid")
        assert isinstance(e, EmailCompositionError)

    def test_rendering_error(self):
        e = RenderingError("failed")
        assert isinstance(e, EmailCompositionError)

    def test_hierarchy(self):
        errors = [
            UnknownTemplateError("x"),
            BrandKitNotFoundError("x"),
            MailboxNotFoundError("x"),
            InvalidAttachmentError("x"),
            DraftValidationError("x"),
            RenderingError("x"),
        ]
        for e in errors:
            assert isinstance(e, EmailCompositionError)
            assert isinstance(e, Exception)


# ── BrandingManager ──────────────────────────────────────────────────────────


class TestBrandingManager:
    def test_register(self):
        mgr = BrandingManager()
        kid = mgr.register(BrandKit(company_name="Loqi"))
        assert kid == "loqi"

    def test_register_with_id(self):
        mgr = BrandingManager()
        kid = mgr.register(BrandKit(company_name="Loqi"), kit_id="custom")
        assert kid == "custom"

    def test_register_sets_default(self):
        mgr = BrandingManager()
        mgr.register(BrandKit(company_name="Alpha"))
        assert mgr.default is not None
        assert mgr.default.company_name == "Alpha"

    def test_get(self):
        mgr = BrandingManager()
        mgr.register(BrandKit(company_name="Loqi"))
        kit = mgr.get("loqi")
        assert kit.company_name == "Loqi"

    def test_get_missing_raises(self):
        mgr = BrandingManager()
        with pytest.raises(BrandKitNotFoundError, match="not found"):
            mgr.get("nonexistent")

    def test_set_default(self):
        mgr = BrandingManager()
        mgr.register(BrandKit(company_name="A"), kit_id="a")
        mgr.register(BrandKit(company_name="B"), kit_id="b")
        mgr.set_default("b")
        assert mgr.default.company_name == "B"

    def test_set_default_missing_raises(self):
        mgr = BrandingManager()
        with pytest.raises(BrandKitNotFoundError):
            mgr.set_default("missing")

    def test_default_none_when_empty(self):
        mgr = BrandingManager()
        assert mgr.default is None

    def test_remove(self):
        mgr = BrandingManager()
        mgr.register(BrandKit(company_name="Loqi"))
        mgr.remove("loqi")
        assert mgr.default is None
        assert mgr.has("loqi") is False

    def test_remove_non_default(self):
        mgr = BrandingManager()
        mgr.register(BrandKit(company_name="A"), kit_id="a")
        mgr.register(BrandKit(company_name="B"), kit_id="b")
        mgr.remove("b")
        assert mgr.has("a") is True
        assert mgr.has("b") is False

    def test_remove_updates_default(self):
        mgr = BrandingManager()
        mgr.register(BrandKit(company_name="A"), kit_id="a")
        mgr.register(BrandKit(company_name="B"), kit_id="b")
        mgr.set_default("a")
        mgr.remove("a")
        assert mgr.default.company_name == "B"

    def test_list(self):
        mgr = BrandingManager()
        mgr.register(BrandKit(company_name="A"), kit_id="a")
        mgr.register(BrandKit(company_name="B"), kit_id="b")
        kits = mgr.list()
        assert len(kits) == 2
        assert "a" in kits
        assert "b" in kits

    def test_list_returns_copy(self):
        mgr = BrandingManager()
        mgr.register(BrandKit(company_name="A"), kit_id="a")
        kits = mgr.list()
        kits["new"] = BrandKit(company_name="X")
        assert mgr.has("new") is False

    def test_has(self):
        mgr = BrandingManager()
        mgr.register(BrandKit(company_name="Loqi"))
        assert mgr.has("loqi") is True
        assert mgr.has("missing") is False

    def test_register_multiple_preserves_default(self):
        mgr = BrandingManager()
        mgr.register(BrandKit(company_name="First"))
        mgr.register(BrandKit(company_name="Second"))
        assert mgr.default.company_name == "First"


# ── MailboxManager ───────────────────────────────────────────────────────────


class TestMailboxManager:
    def test_register(self):
        mgr = MailboxManager()
        mid = mgr.register(CompanyMailbox(id="sales", email="sales@loqi.ai"))
        assert mid == "sales"

    def test_register_sets_default_when_default_flag(self):
        mgr = MailboxManager()
        mgr.register(CompanyMailbox(id="a", email="a@loqi.ai", default=False))
        mgr.register(CompanyMailbox(id="b", email="b@loqi.ai", default=True))
        assert mgr.default.id == "b"

    def test_register_sets_default_when_first(self):
        mgr = MailboxManager()
        mgr.register(CompanyMailbox(id="first", email="f@loqi.ai"))
        assert mgr.default.id == "first"

    def test_get(self):
        mgr = MailboxManager()
        mgr.register(CompanyMailbox(id="sales", email="s@loqi.ai"))
        mb = mgr.get("sales")
        assert mb.email == "s@loqi.ai"

    def test_get_missing_raises(self):
        mgr = MailboxManager()
        with pytest.raises(MailboxNotFoundError, match="not found"):
            mgr.get("nonexistent")

    def test_set_default(self):
        mgr = MailboxManager()
        mgr.register(CompanyMailbox(id="a", email="a@loqi.ai"))
        mgr.register(CompanyMailbox(id="b", email="b@loqi.ai"))
        mgr.set_default("b")
        assert mgr.default.id == "b"

    def test_set_default_missing_raises(self):
        mgr = MailboxManager()
        with pytest.raises(MailboxNotFoundError):
            mgr.set_default("missing")

    def test_default_none_when_empty(self):
        mgr = MailboxManager()
        assert mgr.default is None

    def test_remove(self):
        mgr = MailboxManager()
        mgr.register(CompanyMailbox(id="x", email="x@loqi.ai"))
        mgr.remove("x")
        assert mgr.has("x") is False

    def test_remove_updates_default(self):
        mgr = MailboxManager()
        mgr.register(CompanyMailbox(id="a", email="a@loqi.ai"))
        mgr.register(CompanyMailbox(id="b", email="b@loqi.ai"))
        mgr.set_default("a")
        mgr.remove("a")
        assert mgr.default.id == "b"

    def test_list(self):
        mgr = MailboxManager()
        mgr.register(CompanyMailbox(id="a", email="a@loqi.ai"))
        mgr.register(CompanyMailbox(id="b", email="b@loqi.ai"))
        mbs = mgr.list()
        assert len(mbs) == 2

    def test_has(self):
        mgr = MailboxManager()
        mgr.register(CompanyMailbox(id="x", email="x@loqi.ai"))
        assert mgr.has("x") is True
        assert mgr.has("y") is False

    def test_select_sender_by_preferred(self):
        mgr = MailboxManager()
        mgr.register(CompanyMailbox(id="a", email="a@loqi.ai"))
        mgr.register(CompanyMailbox(id="b", email="b@loqi.ai"))
        mb = mgr.select_sender(preferred="b")
        assert mb.id == "b"

    def test_select_sender_default(self):
        mgr = MailboxManager()
        mgr.register(CompanyMailbox(id="a", email="a@loqi.ai"))
        mb = mgr.select_sender()
        assert mb.id == "a"

    def test_select_sender_preferred_missing_raises(self):
        mgr = MailboxManager()
        mgr.register(CompanyMailbox(id="a", email="a@loqi.ai"))
        with pytest.raises(MailboxNotFoundError):
            mgr.select_sender(preferred="missing")

    def test_select_sender_empty_raises(self):
        mgr = MailboxManager()
        with pytest.raises(MailboxNotFoundError, match="No mailboxes"):
            mgr.select_sender()


# ── AttachmentProcessor ──────────────────────────────────────────────────────


class TestAttachmentProcessor:
    def test_validate_valid(self, attachment):
        ap = AttachmentProcessor()
        ap.validate(attachment)

    def test_construct_empty_filename_raises(self):
        with pytest.raises(ValueError, match="filename is required"):
            Attachment(filename="", mime_type="text/plain", bytes=b"x")

    def test_construct_empty_mime_type_raises(self):
        with pytest.raises(ValueError, match="mime_type is required"):
            Attachment(filename="f.txt", mime_type="", bytes=b"x")

    def test_construct_empty_bytes_raises(self):
        with pytest.raises(ValueError, match="bytes data is required"):
            Attachment(filename="f.txt", mime_type="text/plain", bytes=b"")

    def test_validate_exceeds_max_size(self):
        ap = AttachmentProcessor(max_size=10)
        a = Attachment(filename="big.pdf", mime_type="application/pdf", bytes=b"x" * 20)
        with pytest.raises(InvalidAttachmentError, match="exceeds max size"):
            ap.validate(a)

    def test_validate_batch_valid(self, attachment):
        ap = AttachmentProcessor()
        ap.validate_batch((attachment,))

    def test_validate_batch_exceeds_total(self):
        ap = AttachmentProcessor(max_total=30)
        a1 = Attachment(filename="f1.pdf", mime_type="application/pdf", bytes=b"x" * 20)
        a2 = Attachment(filename="f2.pdf", mime_type="application/pdf", bytes=b"y" * 20)
        with pytest.raises(InvalidAttachmentError, match="exceeds max"):
            ap.validate_batch((a1, a2))

    def test_supported_mime_types(self):
        types = AttachmentProcessor.supported_mime_types()
        assert "application/pdf" in types
        assert "image/jpeg" in types
        assert "image/png" in types
        assert "application/zip" in types
        assert "text/plain" in types
        assert "text/csv" in types

    def test_default_max_size(self):
        ap = AttachmentProcessor()
        assert ap._max_size == 25 * 1024 * 1024

    def test_default_max_total(self):
        ap = AttachmentProcessor()
        assert ap._max_total == 50 * 1024 * 1024

    def test_custom_limits(self):
        ap = AttachmentProcessor(max_size=100, max_total=200)
        assert ap._max_size == 100
        assert ap._max_total == 200


# ── Templates ────────────────────────────────────────────────────────────────


class TestRenderTemplate:
    def test_plain_template(self):
        html = render_template("plain", body_html="<p>Hello</p>")
        assert "<p>Hello</p>" in html
        assert "<!DOCTYPE html>" in html
        assert "background-color:#f4f4f4" in html

    def test_professional_template(self):
        html = render_template("professional", body_html="<p>Hello</p>")
        assert "<p>Hello</p>" in html
        assert "</html>" in html

    def test_recruiting_template(self):
        html = render_template("recruiting", body_html="<p>Hello</p>")
        assert "<p>Hello</p>" in html
        assert "Apply Now" in html

    def test_newsletter_template(self):
        html = render_template("newsletter", body_html="<p>Hello</p>")
        assert "<p>Hello</p>" in html
        assert "#2563eb" in html

    def test_proposal_template(self):
        html = render_template("proposal", body_html="<p>Proposal</p>")
        assert "<p>Proposal</p>" in html

    def test_proposal_template_with_metadata(self):
        html = render_template(
            "proposal",
            body_html="<p>Content</p>",
            proposal_title="Q1 Proposal",
            proposal_date="2026-01-15",
        )
        assert "Q1 Proposal" in html
        assert "2026-01-15" in html

    def test_product_launch_template(self):
        html = render_template("product_launch", body_html="<p>New Product</p>")
        assert "<p>New Product</p>" in html

    def test_product_launch_with_cta(self):
        html = render_template(
            "product_launch",
            body_html="<p>Launch</p>",
            product_name="Loqi 2.0",
            cta_url="https://loqi.ai",
            cta_text="Learn More",
        )
        assert "Loqi 2.0" in html
        assert "Learn More" in html
        assert "https://loqi.ai" in html

    def test_unknown_template_raises(self):
        with pytest.raises(ValueError, match="Unknown template"):
            render_template("nonexistent", body_html="<p>x</p>")

    def test_with_plain_text_fallback(self):
        html = render_template("plain", body_plain="Hello\nWorld")
        assert "Hello" in html
        assert "<br>" in html

    def test_template_with_branding(self, brand_kit):
        html = render_template(
            "plain",
            body_html="<p>Content</p>",
            branding=brand_kit,
        )
        assert "Loqi" in html
        assert "#2563eb" in html
        assert "https://loqi.ai/logo.png" in html

    def test_template_with_footer(self):
        html = render_template(
            "plain",
            body_html="<p>Content</p>",
            footer="Powered by Loqi",
        )
        assert "Powered by Loqi" in html

    def test_template_with_preview_text(self):
        html = render_template(
            "plain",
            body_html="<p>Content</p>",
            preview_text="Preview here",
        )
        assert "Preview here" in html
        assert "display:none" in html

    def test_professional_accent_bar(self):
        html = render_template("professional", body_html="<p>Hi</p>")
        assert "height:4px" in html

    def test_recruiting_no_branding(self):
        html = render_template("recruiting", body_html="<p>Hi</p>")
        assert "Apply Now" in html

    def test_newsletter_divider(self):
        html = render_template("newsletter", body_html="<p>Hi</p>")
        assert "border-top:2px solid" in html

    def test_product_launch_no_product_name(self):
        html = render_template("product_launch", body_html="<p>Hi</p>")
        assert "<p>Hi</p>" in html
        # Should not crash without product_name
        assert "</html>" in html

    def test_product_launch_with_cta_no_product_name(self):
        html = render_template(
            "product_launch",
            body_html="<p>Hi</p>",
            cta_url="https://loqi.ai",
            cta_text="Get Started",
        )
        assert "Get Started" in html
        assert "https://loqi.ai" in html

    def test_all_templates_produce_valid_html(self):
        for name in ("plain", "professional", "recruiting", "newsletter", "proposal", "product_launch"):
            html = render_template(name, body_html="<p>Test</p>")
            assert html.startswith("<!DOCTYPE html>")
            assert html.endswith("</html>")
            assert "<body" in html

    def test_signature_in_footer(self, brand_kit):
        html = render_template("plain", body_html="<p>Hi</p>", branding=brand_kit)
        assert "— Team Loqi" in html

    def test_website_in_footer(self, brand_kit):
        html = render_template("plain", body_html="<p>Hi</p>", branding=brand_kit)
        assert "https://loqi.ai" in html

    def test_responsive_viewport(self):
        html = render_template("plain", body_html="<p>Hi</p>")
        assert "width=device-width" in html


# ── TemplateRegistry ─────────────────────────────────────────────────────────


class TestTemplateRegistry:
    def test_register(self):
        reg = TemplateRegistry()
        reg.register("custom", display_name="Custom", description="Custom template")
        info = reg.get("custom")
        assert info["name"] == "custom"
        assert info["display_name"] == "Custom"

    def test_get_missing_raises(self):
        reg = TemplateRegistry()
        with pytest.raises(UnknownTemplateError, match="not registered"):
            reg.get("missing")

    def test_list_empty(self):
        reg = TemplateRegistry()
        assert reg.list() == []

    def test_list_after_register(self):
        reg = TemplateRegistry()
        reg.register("a")
        reg.register("b")
        assert len(reg.list()) == 2

    def test_has(self):
        reg = TemplateRegistry()
        reg.register("exists")
        assert reg.has("exists") is True
        assert reg.has("missing") is False

    def test_remove(self):
        reg = TemplateRegistry()
        reg.register("t")
        reg.remove("t")
        assert reg.has("t") is False

    def test_remove_missing_raises(self):
        reg = TemplateRegistry()
        with pytest.raises(UnknownTemplateError):
            reg.remove("missing")

    def test_register_builtins(self):
        reg = TemplateRegistry()
        reg.register_builtins()
        assert reg.has("plain")
        assert reg.has("professional")
        assert reg.has("recruiting")
        assert reg.has("newsletter")
        assert reg.has("proposal")
        assert reg.has("product_launch")
        assert len(reg.list()) == 6

    def test_builtin_display_names(self):
        reg = TemplateRegistry()
        reg.register_builtins()
        assert reg.get("plain")["display_name"] == "Plain"
        assert reg.get("product_launch")["display_name"] == "Product Launch"

    def test_register_duplicate_overwrites(self):
        reg = TemplateRegistry()
        reg.register("t", display_name="First")
        reg.register("t", display_name="Second")
        assert reg.get("t")["display_name"] == "Second"

    def test_register_default_display_name(self):
        reg = TemplateRegistry()
        reg.register("cool_template")
        assert reg.get("cool_template")["display_name"] == "Cool Template"


# ── EmailRenderer ────────────────────────────────────────────────────────────


class TestEmailRenderer:
    def test_render_plain_draft(self, draft):
        renderer = EmailRenderer()
        result = renderer.render(draft)
        assert result.subject == "Hello"
        assert "<!DOCTYPE html>" in result.body_html
        assert "Hello world" in result.body_html

    def test_render_preserves_body_plain(self, draft):
        renderer = EmailRenderer()
        result = renderer.render(draft)
        assert result.body_plain == "Hello world"

    def test_render_with_branding(self, draft, brand_kit):
        d = EmailDraft(subject="Hi", body_plain="Hello", brand_kit=brand_kit)
        renderer = EmailRenderer()
        result = renderer.render(d)
        assert "Loqi" in result.body_html
        assert "#2563eb" in result.body_html

    def test_render_with_footer(self, draft):
        d = EmailDraft(subject="Hi", body_plain="Hello", footer="Powered by Loqi")
        renderer = EmailRenderer()
        result = renderer.render(d)
        assert "Powered by Loqi" in result.body_html

    def test_render_with_template_name(self, draft):
        d = EmailDraft(
            subject="Hi",
            body_html="<p>Hello</p>",
            template_name=TemplateName.PROFESSIONAL,
        )
        renderer = EmailRenderer()
        result = renderer.render(d)
        assert "height:4px" in result.body_html  # accent bar

    def test_render_recruiting_template(self):
        d = EmailDraft(
            subject="Job Offer",
            body_html="<p>You're hired</p>",
            template_name=TemplateName.RECRUITING,
        )
        renderer = EmailRenderer()
        result = renderer.render(d)
        assert "Apply Now" in result.body_html

    def test_render_preserves_metadata(self, draft):
        d = EmailDraft(subject="Hi", body_plain="Hello", metadata={"key": "val"})
        renderer = EmailRenderer()
        result = renderer.render(d)
        assert result.metadata == {"key": "val"}

    def test_render_preserves_recipients(self):
        d = EmailDraft(
            subject="Hi",
            body_plain="Hello",
            to=("a@b.com", "c@d.com"),
            cc=("e@f.com",),
        )
        renderer = EmailRenderer()
        result = renderer.render(d)
        assert result.to == ("a@b.com", "c@d.com")
        assert result.cc == ("e@f.com",)

    def test_render_preserves_mailbox(self, draft, mailbox):
        d = EmailDraft(subject="Hi", body_plain="Hello", mailbox=mailbox)
        renderer = EmailRenderer()
        result = renderer.render(d)
        assert result.mailbox is mailbox

    def test_render_preserves_attachments(self, draft, attachment):
        d = EmailDraft(subject="Hi", body_plain="Hello", attachments=(attachment,))
        renderer = EmailRenderer()
        result = renderer.render(d)
        assert len(result.attachments) == 1

    def test_render_inject_branding(self, draft, brand_kit):
        d = EmailDraft(subject="Hi", body_plain="Hello", brand_kit=brand_kit)
        renderer = EmailRenderer()
        result = renderer.inject_branding(d)
        assert "Loqi" in result.body_html

    def test_renderer_brand_style(self, brand_kit):
        styles = EmailRenderer.brand_style(brand_kit)
        assert styles["company_name"] == "Loqi"
        assert styles["primary_color"] == "#2563eb"

    def test_renderer_brand_style_none(self):
        styles = EmailRenderer.brand_style(None)
        assert styles["company_name"] == ""

    def test_render_with_body_html_only(self):
        d = EmailDraft(subject="Hi", body_html="<b>Hello</b>")
        renderer = EmailRenderer()
        result = renderer.render(d)
        assert "<b>Hello</b>" in result.body_html

    def test_render_with_preview_text(self):
        d = EmailDraft(subject="Hi", body_plain="Hello", preview_text="Preview")
        renderer = EmailRenderer()
        result = renderer.render(d)
        assert "Preview" in result.body_html

    def test_render_footer_preserved(self):
        d = EmailDraft(subject="Hi", body_plain="Hello", footer="Custom footer")
        renderer = EmailRenderer()
        result = renderer.render(d)
        assert "Custom footer" in result.body_html


# ── DraftBuilder ─────────────────────────────────────────────────────────────


class TestDraftBuilder:
    def test_build_minimal(self):
        d = DraftBuilder().subject("Test").to("user@example.com").build()
        assert d.subject == "Test"
        assert d.to == ("user@example.com",)

    def test_build_all_fields(self, brand_kit, mailbox, attachment):
        d = (
            DraftBuilder()
            .subject("Full Draft")
            .body_plain("Plain text")
            .body_html("<p>HTML</p>")
            .preview_text("Preview")
            .to(["a@b.com", "c@d.com"])
            .cc("e@f.com")
            .bcc("g@h.com")
            .reply_to("replies@loqi.ai")
            .add_attachment(attachment)
            .mailbox(mailbox)
            .brand_kit(brand_kit)
            .template_name(TemplateName.PROPOSAL)
            .metadata({"source": "test"})
            .footer("Powered by Loqi")
            .build()
        )
        assert d.subject == "Full Draft"
        assert d.body_plain == "Plain text"
        assert d.body_html == "<p>HTML</p>"
        assert d.preview_text == "Preview"
        assert d.to == ("a@b.com", "c@d.com")
        assert d.cc == ("e@f.com",)
        assert d.bcc == ("g@h.com",)
        assert d.reply_to == "replies@loqi.ai"
        assert len(d.attachments) == 1
        assert d.mailbox is mailbox
        assert d.brand_kit is brand_kit
        assert d.template_name == TemplateName.PROPOSAL
        assert d.metadata == {"source": "test"}
        assert d.footer == "Powered by Loqi"

    def test_template_name_from_string(self):
        d = DraftBuilder().subject("Hi").to("a@b.com").template_name("plain").build()
        assert d.template_name == TemplateName.PLAIN

    def test_template_name_from_string_invalid_raises(self):
        with pytest.raises(ValueError):
            DraftBuilder().subject("Hi").to("a@b.com").template_name("invalid").build()

    def test_build_without_subject_raises(self):
        with pytest.raises(DraftValidationError, match="subject is required"):
            DraftBuilder().to("a@b.com").build()

    def test_reset(self):
        builder = DraftBuilder().subject("Hi").to("a@b.com")
        builder.reset()
        with pytest.raises(DraftValidationError):
            builder.build()

    def test_reset_clears_all(self):
        builder = (
            DraftBuilder()
            .subject("Hi")
            .to("a@b.com")
            .body_plain("text")
            .footer("footer")
        )
        builder.reset()
        builder.subject("New").to("c@d.com")
        d = builder.build()
        assert d.subject == "New"
        assert d.to == ("c@d.com",)
        assert d.body_plain == ""
        assert d.footer == ""

    def test_builder_returns_self(self):
        builder = DraftBuilder()
        assert builder.subject("hi") is builder
        assert builder.to("a@b.com") is builder
        assert builder.body_plain("text") is builder
        assert builder.reset() is builder

    def test_to_str_converts_to_list(self):
        d = DraftBuilder().subject("Hi").to("a@b.com").build()
        assert d.to == ("a@b.com",)

    def test_cc_str_converts_to_list(self):
        d = DraftBuilder().subject("Hi").to("a@b.com").cc("c@d.com").build()
        assert d.cc == ("c@d.com",)

    def test_bcc_str_converts_to_list(self):
        d = DraftBuilder().subject("Hi").to("a@b.com").bcc("e@f.com").build()
        assert d.bcc == ("e@f.com",)

    def test_multiple_attachments(self, attachment):
        a2 = Attachment(filename="f2.txt", mime_type="text/plain", bytes=b"data2")
        d = (
            DraftBuilder()
            .subject("Hi")
            .to("a@b.com")
            .add_attachment(attachment)
            .add_attachment(a2)
            .build()
        )
        assert len(d.attachments) == 2

    def test_metadata_isolated(self):
        meta = {"key": "val"}
        builder = DraftBuilder().subject("Hi").to("a@b.com").metadata(meta)
        meta["extra"] = "should not affect"
        d = builder.build()
        assert d.metadata == {"key": "val"}


# ── draft_to_gmail_params ────────────────────────────────────────────────────


class TestDraftToGmailParams:
    def test_basic(self):
        d = EmailDraft(subject="Hello", body_plain="World", to=("a@b.com",))
        params = draft_to_gmail_params(d)
        assert params["to"] == ["a@b.com"]
        assert params["subject"] == "Hello"
        assert params["body_plain"] == "World"
        assert params["body_html"] == ""

    def test_with_all_fields(self, full_draft):
        params = draft_to_gmail_params(full_draft)
        assert params["to"] == ["alice@example.com", "bob@example.com"]
        assert params["subject"] == "Weekly Report"
        assert "cc" in params
        assert "bcc" in params
        assert "reply_to" in params

    def test_empty_cc_bcc_omitted(self):
        d = EmailDraft(subject="Hi", body_plain="Hello", to=("a@b.com",))
        params = draft_to_gmail_params(d)
        assert "cc" not in params
        assert "bcc" not in params

    def test_reply_to_omitted_when_empty(self):
        d = EmailDraft(subject="Hi", body_plain="Hello", to=("a@b.com",))
        params = draft_to_gmail_params(d)
        assert "reply_to" not in params


# ── EmailComposer ────────────────────────────────────────────────────────────


class TestEmailComposer:
    def test_compose_basic(self):
        composer = EmailComposer()
        draft = composer.compose(
            subject="Hello",
            to="user@example.com",
        )
        assert draft.subject == "Hello"
        assert draft.to == ("user@example.com",)
        assert draft.template_name == TemplateName.PLAIN

    def test_compose_full(self, mailbox, brand_kit, attachment):
        composer = EmailComposer()
        draft = composer.compose(
            subject="Campaign",
            body_text="Hello there",
            body_html="<p>Hello there</p>",
            preview_text="Preview",
            to=["a@b.com", "c@d.com"],
            cc="e@f.com",
            bcc="g@h.com",
            reply_to="replies@loqi.ai",
            attachments=[attachment],
            mailbox=mailbox,
            brand_kit=brand_kit,
            template_name=TemplateName.PROFESSIONAL,
            footer="Powered by Loqi",
            metadata={"campaign": "test"},
        )
        assert draft.subject == "Campaign"
        assert draft.body_plain == "Hello there"
        assert "Hello there" in draft.body_html
        assert draft.template_name == TemplateName.PROFESSIONAL
        assert draft.mailbox is mailbox
        assert draft.brand_kit is brand_kit
        assert len(draft.attachments) == 1
        assert draft.footer == "Powered by Loqi"

    def test_compose_applies_renderer(self, brand_kit):
        composer = EmailComposer()
        draft = composer.compose(
            subject="Hello",
            to="user@example.com",
            brand_kit=brand_kit,
            template_name=TemplateName.PROFESSIONAL,
        )
        assert "Loqi" in draft.body_html
        assert "height:4px" in draft.body_html  # professional accent bar

    def test_compose_from_ai(self):
        composer = EmailComposer()
        ai = {
            "subject": "AI Draft",
            "body_text": "Generated by AI",
            "preview_text": "AI Preview",
            "to": ["lead@example.com"],
            "metadata": {"model": "gpt-4"},
        }
        draft = composer.compose_from_ai(ai)
        assert draft.subject == "AI Draft"
        assert draft.body_plain == "Generated by AI"
        assert draft.to == ("lead@example.com",)
        assert draft.metadata == {"model": "gpt-4"}

    def test_compose_from_ai_with_body_html(self):
        composer = EmailComposer()
        ai = {
            "subject": "HTML Draft",
            "body_html": "<p>Rich content</p>",
            "to": ["lead@example.com"],
        }
        draft = composer.compose_from_ai(ai)
        assert "Rich content" in draft.body_html

    def test_compose_from_ai_with_mailbox_id(self, mailbox):
        composer = EmailComposer()
        composer.mailboxes.register(mailbox)
        draft = composer.compose_from_ai(
            {"subject": "Test", "to": ["lead@example.com"]},
            mailbox="sales",
        )
        assert draft.mailbox is mailbox

    def test_compose_from_ai_with_mailbox_object(self, mailbox):
        composer = EmailComposer()
        draft = composer.compose_from_ai(
            {"subject": "Test", "to": ["lead@example.com"]},
            mailbox=mailbox,
        )
        assert draft.mailbox is mailbox

    def test_compose_from_ai_with_brand_kit_id(self, brand_kit):
        composer = EmailComposer()
        composer.branding.register(brand_kit)
        draft = composer.compose_from_ai(
            {"subject": "Test", "to": ["lead@example.com"]},
            brand_kit="loqi",
        )
        assert draft.brand_kit is brand_kit

    def test_compose_from_ai_with_brand_kit_object(self, brand_kit):
        composer = EmailComposer()
        draft = composer.compose_from_ai(
            {"subject": "Test", "to": ["lead@example.com"]},
            brand_kit=brand_kit,
        )
        assert draft.brand_kit is brand_kit

    def test_compose_from_ai_with_template(self):
        composer = EmailComposer()
        draft = composer.compose_from_ai(
            {"subject": "Test", "to": ["lead@example.com"]},
            template_name=TemplateName.RECRUITING,
        )
        assert draft.template_name == TemplateName.RECRUITING

    def test_compose_with_mailbox_object(self, mailbox):
        composer = EmailComposer()
        draft = composer.compose(
            subject="Hi",
            to="user@example.com",
            mailbox=mailbox,
        )
        assert draft.mailbox is mailbox

    def test_compose_with_mailbox_id(self, mailbox):
        composer = EmailComposer()
        composer.mailboxes.register(mailbox)
        draft = composer.compose(
            subject="Hi",
            to="user@example.com",
            mailbox="sales",
        )
        assert draft.mailbox is mailbox

    def test_compose_with_mailbox_none_uses_default(self, mailbox):
        composer = EmailComposer()
        composer.mailboxes.register(mailbox)
        draft = composer.compose(
            subject="Hi",
            to="user@example.com",
        )
        assert draft.mailbox is mailbox

    def test_compose_with_brand_kit_object(self, brand_kit):
        composer = EmailComposer()
        draft = composer.compose(
            subject="Hi",
            to="user@example.com",
            brand_kit=brand_kit,
        )
        assert draft.brand_kit is brand_kit

    def test_compose_with_brand_kit_id(self, brand_kit):
        composer = EmailComposer()
        composer.branding.register(brand_kit)
        draft = composer.compose(
            subject="Hi",
            to="user@example.com",
            brand_kit="loqi",
        )
        assert draft.brand_kit is brand_kit

    def test_compose_with_brand_kit_none_uses_default(self, brand_kit):
        composer = EmailComposer()
        composer.branding.register(brand_kit)
        draft = composer.compose(
            subject="Hi",
            to="user@example.com",
        )
        assert draft.brand_kit is brand_kit

    def test_compose_with_invalid_attachment_raises(self):
        ap = AttachmentProcessor(max_size=10)
        composer = EmailComposer(attachment_processor=ap)
        big = Attachment(filename="big.pdf", mime_type="application/pdf", bytes=b"x" * 20)
        with pytest.raises(InvalidAttachmentError):
            composer.compose(
                subject="Hi",
                to="user@example.com",
                attachments=[big],
            )

    def test_compose_html_rendering(self, brand_kit):
        composer = EmailComposer()
        draft = composer.compose(
            subject="Test",
            to="a@b.com",
            body_html="<b>Bold text</b>",
            brand_kit=brand_kit,
            template_name=TemplateName.PROFESSIONAL,
        )
        assert "<b>Bold text</b>" in draft.body_html
        assert "Loqi" in draft.body_html

    def test_compose_without_recipients(self):
        composer = EmailComposer()
        draft = composer.compose(subject="Hi", body_text="text")
        assert draft.to == ()

    def test_compose_preserves_template_name(self):
        composer = EmailComposer()
        draft = composer.compose(
            subject="Hi",
            to="a@b.com",
            template_name=TemplateName.PROPOSAL,
        )
        assert draft.template_name == TemplateName.PROPOSAL

    def test_compose_with_empty_subject_raises(self):
        composer = EmailComposer()
        with pytest.raises(DraftValidationError, match="subject is required"):
            composer.compose(subject="")

    def test_compose_from_ai_empty_subject_raises(self):
        composer = EmailComposer()
        with pytest.raises(DraftValidationError, match="subject is required"):
            composer.compose_from_ai({"body_text": "no subject"})

    def test_composer_uses_custom_dependencies(self):
        branding = BrandingManager()
        mailboxes = MailboxManager()
        attrs = AttachmentProcessor()
        templates = TemplateRegistry()
        renderer = EmailRenderer()
        composer = EmailComposer(
            renderer=renderer,
            branding_manager=branding,
            mailbox_manager=mailboxes,
            attachment_processor=attrs,
            template_registry=templates,
        )
        assert composer.renderer is renderer
        assert composer.branding is branding
        assert composer.mailboxes is mailboxes
        assert composer.attachments is attrs
        assert composer.templates is templates


# ── End-to-End Integration ──────────────────────────────────────────────────


class TestEndToEnd:
    def test_compose_and_render(self, brand_kit, mailbox):
        composer = EmailComposer()
        composer.branding.register(brand_kit)
        composer.mailboxes.register(mailbox)
        draft = composer.compose(
            subject="Welcome to Loqi",
            body_text="Hi there,\n\nWelcome to our platform.\n\nBest,\nLoqi Team",
            body_html="<p>Hi there,</p><p>Welcome to our platform.</p>",
            preview_text="Welcome email preview",
            to="newuser@example.com",
            cc="onboarding@loqi.ai",
            mailbox="sales",
            brand_kit="loqi",
            template_name=TemplateName.PROFESSIONAL,
            footer="Powered by Loqi",
        )
        assert draft.subject == "Welcome to Loqi"
        assert draft.body_plain == "Hi there,\n\nWelcome to our platform.\n\nBest,\nLoqi Team"
        assert "<!DOCTYPE html>" in draft.body_html
        assert "Welcome to our platform" in draft.body_html
        assert "Powered by Loqi" in draft.body_html
        assert "Loqi" in draft.body_html  # brand name
        assert "#2563eb" in draft.body_html  # brand color
        assert draft.to == ("newuser@example.com",)
        assert draft.cc == ("onboarding@loqi.ai",)
        assert draft.mailbox is mailbox
        assert draft.brand_kit is brand_kit
        assert draft.template_name == TemplateName.PROFESSIONAL

    def test_compose_from_ai_pipeline(self, brand_kit, mailbox):
        composer = EmailComposer()
        composer.branding.register(brand_kit)
        composer.mailboxes.register(mailbox)
        ai_output = {
            "subject": "Exciting Opportunity",
            "body_html": "<h1>Join Loqi</h1><p>We are hiring!</p>",
            "body_text": "Join Loqi - We are hiring!",
            "preview_text": "Job opportunity at Loqi",
            "to": "candidate@example.com",
            "metadata": {"source": "ai", "confidence": 0.95},
        }
        draft = composer.compose_from_ai(
            ai_output,
            mailbox="sales",
            brand_kit="loqi",
            template_name=TemplateName.RECRUITING,
            footer="Powered by Loqi",
        )
        assert draft.subject == "Exciting Opportunity"
        assert "Join Loqi" in draft.body_html
        assert "Apply Now" in draft.body_html  # recruiting CTA
        assert "Powered by Loqi" in draft.body_html
        assert brand_kit.company_name in draft.body_html
        params = draft_to_gmail_params(draft)
        assert params["to"] == ["candidate@example.com"]
        assert params["subject"] == "Exciting Opportunity"

    def test_render_with_all_templates(self, brand_kit):
        composer = EmailComposer()
        for name in TemplateName:
            draft = composer.compose(
                subject=f"Test {name.value}",
                body_text="Hello",
                to="a@b.com",
                brand_kit=brand_kit,
                template_name=name,
            )
            assert "<!DOCTYPE html>" in draft.body_html
            assert brand_kit.company_name in draft.body_html
            assert draft.subject == f"Test {name.value}"

    def test_compose_with_attachments(self, attachment):
        composer = EmailComposer()
        draft = composer.compose(
            subject="With Attachment",
            body_text="See attached",
            to="a@b.com",
            attachments=[attachment],
        )
        assert len(draft.attachments) == 1
        assert draft.attachments[0].filename == "report.pdf"
        params = draft_to_gmail_params(draft)
        assert params["subject"] == "With Attachment"

    def test_compose_multiple_recipients(self):
        composer = EmailComposer()
        draft = composer.compose(
            subject="Broadcast",
            body_text="Hello everyone",
            to=["a@b.com", "c@d.com", "e@f.com"],
            cc=["g@h.com"],
            bcc=["i@j.com"],
        )
        assert len(draft.to) == 3
        assert len(draft.cc) == 1
        assert len(draft.bcc) == 1

    def test_compose_default_template(self):
        composer = EmailComposer()
        draft = composer.compose(subject="Hi", to="a@b.com")
        assert draft.template_name == TemplateName.PLAIN

    def test_no_http_google_or_gmail_imports(self):
        import services.email as email_pkg

        source = open(email_pkg.__file__).read() if hasattr(email_pkg, "__file__") else ""
        forbidden = ("services.adapters.google", "services.adapters.http", "httpx", "transport")
        for pkg in forbidden:
            assert pkg not in source, f"Import of {pkg} found in email __init__.py"
