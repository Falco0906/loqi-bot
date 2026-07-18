from __future__ import annotations
import re
from services.reply_generation.generation_models import ReplyDraft, ValidationIssue, ValidationSeverity


PLACEHOLDER_PATTERNS = [
    r'\[.*?\]',
    r'\{.*?\}',
    r'<.*?>',
]

HALLUCINATED_PRICE_PATTERNS = [
    r'\$\s*\d+[kKmMbB]?\s*(?:per|a|each|month|year)',
]

PROHIBITED_PATTERNS = [
    r'(?i)just\s+(shoot|ping|holler)',
    r'(?i)per\s+your\s+request',
    r'(?i)as\s+per\s+our\s+conversation',
    r'(?i)i\s+am\s+writing\s+to\s+(you\s+)?today',
    r'(?i)hope\s+this\s+(email|message|finds|helps)',
]

MARKDOWN_PATTERNS = [
    r'#{1,6}\s',
    r'\*\*.*?\*\*',
    r'__.*?__',
    r'`.*?`',
]

DATE_PATTERNS = [
    r'\b\d{1,2}/\d{1,2}/\d{2,4}\b',
    r'\b(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\s+\d{1,2},?\s+\d{4}\b',
    r'\b(?:Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday)\b',
    r'\b(?:tomorrow|next\s+(?:week|month))\b',
]

CTA_PHRASES = [
    r'(?i)let\s+(\w+\s+)?know',
    r'(?i)(schedule|book|set\s+up)\s+a',
    r'(?i)would\s+(you|that)\s+(work|be\s+great)',
    r'(?i)what\s+(do\s+you\s+think|are\s+your\s+thoughts)',
    r'(?i)feel\s+free\s+to',
    r'(?i)(call|email|reply|reach\s+out)',
    r'(?i)looking\s+forward\s+to',
    r'(?i)(questions|thoughts|feedback)',
]


def validate_draft(draft: ReplyDraft) -> list[ValidationIssue]:
    """Validate a generated reply draft. Returns list of issues."""
    issues: list[ValidationIssue] = []
    content = draft.content.strip()

    if not content:
        issues.append(ValidationIssue(
            severity=ValidationSeverity.ERROR,
            code="empty_response",
            message="Generated reply is empty.",
        ))
        return issues

    _check_length(issues, content)
    _check_placeholders(issues, content)
    _check_hallucinated_prices(issues, content)
    _check_prohibited_phrases(issues, content)
    _check_markdown_artifacts(issues, content)
    _check_newlines(issues, content)
    _check_hallucinated_dates(issues, content)
    _check_repetition(issues, content)
    _check_missing_cta(issues, content)
    _check_unsupported_claims(issues, content)
    _check_unsolicited_promise(issues, content)
    _check_html_content(issues, content)

    return issues


def _check_length(issues: list[ValidationIssue], content: str) -> None:
    if len(content) < 20:
        issues.append(ValidationIssue(
            severity=ValidationSeverity.WARNING,
            code="too_short",
            message=f"Reply is very short ({len(content)} chars).",
        ))
    elif len(content) > 5000:
        issues.append(ValidationIssue(
            severity=ValidationSeverity.WARNING,
            code="too_long",
            message=f"Reply exceeds 5000 characters ({len(content)} chars).",
        ))


def _check_placeholders(issues: list[ValidationIssue], content: str) -> None:
    for pattern in PLACEHOLDER_PATTERNS:
        matches = re.findall(pattern, content)
        for match in matches:
            stripped = match.strip("[]{}<> ")
            if stripped.lower() in ("name", "company", "email", "phone", "date", "insert", "recipient"):
                issues.append(ValidationIssue(
                    severity=ValidationSeverity.ERROR,
                    code="placeholder_remaining",
                    message=f"Unresolved placeholder: {match}",
                    field=match,
                ))


def _check_hallucinated_prices(issues: list[ValidationIssue], content: str) -> None:
    for pattern in HALLUCINATED_PRICE_PATTERNS:
        matches = re.findall(pattern, content)
        for match in matches:
            issues.append(ValidationIssue(
                severity=ValidationSeverity.WARNING,
                code="hallucinated_price",
                message=f"Possible hallucinated price: {match}",
                field=match,
            ))


def _check_prohibited_phrases(issues: list[ValidationIssue], content: str) -> None:
    for pattern in PROHIBITED_PATTERNS:
        match = re.search(pattern, content)
        if match:
            issues.append(ValidationIssue(
                severity=ValidationSeverity.WARNING,
                code="prohibited_phrase",
                message=f"Prohibited phrase detected: '{match.group()}'",
                field=match.group(),
            ))


def _check_markdown_artifacts(issues: list[ValidationIssue], content: str) -> None:
    for pattern in MARKDOWN_PATTERNS:
        match = re.search(pattern, content)
        if match:
            issues.append(ValidationIssue(
                severity=ValidationSeverity.WARNING,
                code="markdown_artifact",
                message=f"Possible markdown artifact: '{match.group()}'",
                field=match.group(),
            ))


def _check_newlines(issues: list[ValidationIssue], content: str) -> None:
    blank_line_count = sum(1 for line in content.split("\n") if line.strip() == "")
    if blank_line_count > 15:
        issues.append(ValidationIssue(
            severity=ValidationSeverity.WARNING,
            code="excessive_newlines",
            message=f"Reply has {blank_line_count} blank lines.",
        ))


def _check_hallucinated_dates(issues: list[ValidationIssue], content: str) -> None:
    for pattern in DATE_PATTERNS:
        match = re.search(pattern, content)
        if match:
            issues.append(ValidationIssue(
                severity=ValidationSeverity.WARNING,
                code="hallucinated_date",
                message=f"Possible hallucinated date/time reference: '{match.group()}'",
                field=match.group(),
            ))


def _check_repetition(issues: list[ValidationIssue], content: str) -> None:
    sentences = re.split(r'[.!?]+', content)
    seen: set[str] = set()
    for sent in sentences:
        normalized = sent.strip().lower()
        if len(normalized) < 20:
            continue
        if normalized in seen:
            issues.append(ValidationIssue(
                severity=ValidationSeverity.WARNING,
                code="repetition",
                message=f"Repeated sentence: '{sent.strip()[:60]}...'",
            ))
            break
        seen.add(normalized)


def _check_missing_cta(issues: list[ValidationIssue], content: str) -> None:
    has_cta = any(re.search(pattern, content) for pattern in CTA_PHRASES)
    if not has_cta:
        issues.append(ValidationIssue(
            severity=ValidationSeverity.WARNING,
            code="missing_cta",
            message="No call-to-action detected in reply.",
        ))


def _check_unsupported_claims(issues: list[ValidationIssue], content: str) -> None:
    claim_patterns = [
        r'(?i)(#1|leading|top-rated|best-in-class|industry-leading)\s+(platform|solution|provider)',
        r'(?i)guarantee\w*\s+(results|success|roi)',
        r'(?i)(always|never)\s+(deliver|fail|miss)',
    ]
    for pattern in claim_patterns:
        match = re.search(pattern, content)
        if match:
            issues.append(ValidationIssue(
                severity=ValidationSeverity.WARNING,
                code="unsupported_claim",
                message=f"Potentially unsupported claim: '{match.group()}'",
                field=match.group(),
            ))


def _check_unsolicited_promise(issues: list[ValidationIssue], content: str) -> None:
    promise_patterns = [
        r'(?i)we\s+(will|can|could)\s+(guarantee|promise|ensure)',
        r'(?i)you\s+(will|won\'t)\s+(see|get|achieve|save)',
    ]
    for pattern in promise_patterns:
        match = re.search(pattern, content)
        if match:
            issues.append(ValidationIssue(
                severity=ValidationSeverity.WARNING,
                code="unsolicited_promise",
                message=f"Unsolicited promise detected: '{match.group()}'",
                field=match.group(),
            ))


def _check_html_content(issues: list[ValidationIssue], content: str) -> None:
    html_patterns = [
        r'<script[^>]*>',
        r'<iframe[^>]*>',
        r'on\w+\s*=',
        r'href\s*=\s*["\']javascript:',
    ]
    for pattern in html_patterns:
        match = re.search(pattern, content, re.IGNORECASE)
        if match:
            issues.append(ValidationIssue(
                severity=ValidationSeverity.ERROR,
                code="html_injection",
                message=f"HTML/script content detected: '{match.group()}'",
                field=match.group(),
            ))
