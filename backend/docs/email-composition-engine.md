# Email Composition Engine v1.0 — Implementation Report

## Architecture

```
AI / Application Code
    │
    └── EmailComposer
            │
            ├── DraftBuilder        → EmailDraft (canonical draft)
            ├── EmailRenderer       → template + branding injection
            │       ├── Template (plain / professional / recruiting / ...)
            │       ├── BrandKit (colors, logo, signature)
            │       └── Footer ("Powered by Loqi")
            ├── BrandingManager     → BrandKit registry
            ├── MailboxManager      → CompanyMailbox registry + sender selection
            ├── AttachmentProcessor → attachment validation
            └── TemplateRegistry    → template metadata registry
                    │
                    └── GmailAdapter (NOT modified)
                            │
                            └── Gmail REST API
```

The Email Composition Engine is a provider-agnostic layer that prepares fully rendered email drafts. It owns everything about *what* an email looks like and *who* it comes from. It delegates all transport concerns (HTTP, OAuth, MIME encoding, Google API) to the Gmail Adapter.

## Package Structure

```
backend/services/email/
    __init__.py          # Public API
    models.py            # EmailDraft, Attachment, CompanyMailbox, BrandKit, TemplateName
    exceptions.py        # EmailCompositionError hierarchy
    branding.py          # BrandingManager — BrandKit lifecycle
    mailbox.py           # MailboxManager — CompanyMailbox lifecycle + sender selection
    attachments.py       # AttachmentProcessor — validation + size limits
    templates.py         # HTML template functions (6 templates)
    template_registry.py # TemplateRegistry — register/lookup template metadata
    renderer.py          # EmailRenderer — applies template + branding to draft
    draft.py             # DraftBuilder + draft_to_gmail_params converter
    composer.py          # EmailComposer — end-to-end draft composition
```

## Models

### EmailDraft

The canonical draft object produced by the composition pipeline and consumed by `draft_to_gmail_params()` for Gmail Adapter integration.

| Field | Type | Required |
|-------|------|----------|
| `subject` | `str` | Yes |
| `body_plain` | `str` | No |
| `body_html` | `str` | No (rendered from template) |
| `preview_text` | `str` | No |
| `to` | `tuple[str, ...]` | No |
| `cc` | `tuple[str, ...]` | No |
| `bcc` | `tuple[str, ...]` | No |
| `reply_to` | `str` | No |
| `attachments` | `tuple[Attachment, ...]` | No |
| `mailbox` | `CompanyMailbox \| None` | No |
| `brand_kit` | `BrandKit \| None` | No |
| `template_name` | `TemplateName` | No (default: PLAIN) |
| `metadata` | `dict[str, Any]` | No |
| `footer` | `str` | No |

Properties: `sender_email`, `sender_display`

### Attachment

| Field | Type | Description |
|-------|------|-------------|
| `filename` | `str` | Display filename |
| `mime_type` | `str` | MIME type (e.g. `application/pdf`) |
| `bytes` | `bytes` | File binary data |
| `content_id` | `str` | Optional CID for inline images |

Supported MIME types: PDF, DOCX, PPTX, XLSX, JPEG, PNG, GIF, WebP, SVG, ZIP, plain text, CSV.

Size limits: 25 MB per attachment, 50 MB total (configurable).

### CompanyMailbox

| Field | Type | Description |
|-------|------|-------------|
| `id` | `str` | Unique identifier |
| `email` | `str` | Email address |
| `display_name` | `str` | Sender display name |
| `signature` | `str` | Email signature |
| `default` | `bool` | Default sender flag |

### BrandKit

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `company_name` | `str` | — | Company name (required) |
| `logo_url` | `str` | `""` | Logo URL for email header |
| `primary_color` | `str` | `#2563eb` | Primary brand color |
| `secondary_color` | `str` | `#1e40af` | Secondary brand color |
| `font_family` | `str` | `Arial, Helvetica, sans-serif` | Email font stack |
| `website` | `str` | `""` | Company website |
| `social_links` | `dict` | `{}` | Social media URLs |
| `signature` | `str` | `""` | Email signature line |

## Templates

6 built-in HTML email templates, all producing responsive email HTML with inline styles:

| Template | Signature Feature | Use Case |
|----------|-----------------|----------|
| **Plain** | Minimal header, clean text | Simple notifications |
| **Professional** | Secondary color accent bar | Business correspondence |
| **Recruiting** | "Apply Now" CTA button | Talent outreach |
| **Newsletter** | Brand-colored dividers | Periodic updates |
| **Proposal** | Metadata block (title, date) | Formal proposals |
| **Product Launch** | Hero section + CTA button | Product announcements |

Every template injects: header (company name + logo), footer (signature + website), free-tier footer, preview text, and brand colors.

## Branding System

`BrandingManager` manages `BrandKit` instances:

- `register(kit, kit_id="")` → returns kit_id
- `get(kit_id)` → BrandKit or raises `BrandKitNotFoundError`
- `set_default(kit_id)` → change default kit
- `remove(kit_id)` → remove kit, adjusts default
- `default` → current default kit (or None)
- `list()` → dict of all kits
- `has(kit_id)` → bool

## Mailbox System

`MailboxManager` manages `CompanyMailbox` instances:

- `register(mailbox)` → returns mailbox.id
- `get(mailbox_id)` → CompanyMailbox or raises `MailboxNotFoundError`
- `set_default(mailbox_id)` → change default
- `remove(mailbox_id)` → removes, adjusts default
- `default` → current default (or None)
- `list()` → dict of all mailboxes
- `select_sender(preferred="")` → preferred or default or raises

First registered mailbox or one with `default=True` becomes default.

## Composer

`EmailComposer` is the top-level orchestrator:

```python
composer = EmailComposer()

draft = composer.compose(
    subject="Hello",
    body_text="Plain text body",
    body_html="<p>HTML body</p>",
    preview_text="Preview text",
    to=["alice@example.com"],
    cc=["bob@example.com"],
    attachments=[Attachment(...)],
    mailbox=mailbox_obj,
    brand_kit=brand_kit_obj,
    template_name=TemplateName.PROFESSIONAL,
    footer="Powered by Loqi",
)
```

`compose_from_ai()` accepts AI-generated output as a dict:

```python
draft = composer.compose_from_ai(ai_output, mailbox="sales", brand_kit="loqi")
```

## Rendering Pipeline

```
compose() / compose_from_ai()
    │
    ├── DraftBuilder.build() → partial EmailDraft
    │
    ├── AttachmentProcessor.validate_batch() — validates attachments (skipped if none)
    │
    └── EmailRenderer.render(draft) → fully rendered EmailDraft
            │
            ├── Resolve template function by TemplateName
            ├── Call template function(body_html, body_plain, preview_text, branding, footer)
            ├── Template produces complete HTML email
            └── Return new EmailDraft with body_html = rendered HTML
```

## Gmail Adapter Integration

```python
from services.email import draft_to_gmail_params

draft = composer.compose(subject="Hello", to="user@example.com")
params = draft_to_gmail_params(draft)

# params = {
#     "to": ["user@example.com"],
#     "subject": "Hello",
#     "body_plain": "",
#     "body_html": "<!DOCTYPE html>...fully rendered...",
# }

# Pass params to GmailAdapter:
context = AdapterContext.build(action="gmail_send_email", params=params)
result = await gmail_adapter.execute(context)
```

## Provider Agnostic Design

The Email Composition Engine imports nothing from:
- `services.adapters.google`
- `services.adapters.http`
- `httpx`
- `google`

Future providers (Outlook, SMTP, SendGrid, Amazon SES, Resend) can reuse 100% of this layer. Only the final adapter call changes.

## Frozen Layer Boundaries

| Component | Status |
|-----------|--------|
| `services/email/` (all files) | FROZEN — Email Composition Engine v1.0 |
| `tests/test_email_composition_engine.py` | FROZEN — test suite |

## Extension Points (non-breaking)

- Adding new template functions in `templates.py` + registering in `TEMPLATE_FUNCTIONS`
- Adding new request/response models in `models.py`
- Adding new template metadata in `template_registry.py`
- Adding new validation rules to `AttachmentProcessor`
- Adding new mailbox routing strategies to `MailboxManager`

## RFC-Required Changes

- Adding HTTP logic, OAuth, or transport concerns
- Adding imports from `services.adapters.google` or `services.adapters.http`
- Creating Gmail-specific dependencies
- Modifying frozen Gmail Adapter or platform layers

## Test Coverage

174 tests across 10 test classes:

| Test Class | Tests |
|-----------|-------|
| TestAttachment | 6 |
| TestCompanyMailbox | 5 |
| TestBrandKit | 4 |
| TestTemplateName | 3 |
| TestEmailDraft | 10 |
| TestExceptions | 8 |
| TestBrandingManager | 12 |
| TestMailboxManager | 14 |
| TestAttachmentProcessor | 9 |
| TestRenderTemplate | 22 |
| TestTemplateRegistry | 11 |
| TestEmailRenderer | 17 |
| TestDraftBuilder | 13 |
| TestDraftToGmailParams | 4 |
| TestEmailComposer | 24 |
| TestEndToEnd | 7 |
| **Total** | **174** |
