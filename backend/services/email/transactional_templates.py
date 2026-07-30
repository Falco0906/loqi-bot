from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass
class TemplateResult:
    subject: str
    html: str
    plain_text: str


def _base_html(content: str, company_name: str = "Loqi") -> str:
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<style>
  body {{ margin:0; padding:0; font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif; background:#f4f4f5; }}
  .container {{ max-width:600px; margin:0 auto; padding:24px 16px; }}
  .card {{ background:#ffffff; border-radius:8px; padding:32px; box-shadow:0 1px 3px rgba(0,0,0,0.08); }}
  .header {{ text-align:center; padding-bottom:24px; border-bottom:1px solid #e4e4e7; margin-bottom:24px; }}
  .logo {{ font-size:24px; font-weight:700; color:#18181b; }}
  .content {{ font-size:15px; line-height:1.6; color:#3f3f46; }}
  .button {{ display:inline-block; padding:12px 28px; margin:16px 0; font-size:15px; font-weight:600;
             color:#ffffff; background:#2563eb; border-radius:6px; text-decoration:none; }}
  .footer {{ margin-top:24px; padding-top:24px; border-top:1px solid #e4e4e7; font-size:13px; color:#a1a1aa; text-align:center; }}
  .footer a {{ color:#2563eb; text-decoration:none; }}
</style>
</head>
<body>
<div class="container">
  <div class="card">
    <div class="header"><div class="logo">{company_name}</div></div>
    <div class="content">{content}</div>
    <div class="footer">
      <p>&copy; {company_name} &mdash; All rights reserved.</p>
    </div>
  </div>
</div>
</body>
</html>"""


def _wrap_plain(content: str) -> str:
    return content.strip()


def render_verification_email(
    verification_url: str,
    company_name: str = "Loqi",
) -> TemplateResult:
    html_content = f"""<p>Welcome! Please verify your email address to get started.</p>
<p style="text-align:center"><a href="{verification_url}" class="button">Verify Email</a></p>
<p>If the button doesn't work, copy and paste this link into your browser:</p>
<p style="word-break:break-all;font-size:13px;color:#71717a">{verification_url}</p>
<p>This link expires in 15 minutes.</p>"""
    return TemplateResult(
        subject=f"Verify your email — {company_name}",
        html=_base_html(html_content, company_name),
        plain_text=_wrap_plain(
            f"Welcome! Please verify your email address to get started.\n\n"
            f"Verify your email: {verification_url}\n\n"
            f"This link expires in 15 minutes.\n\n— {company_name}",
        ),
    )


def render_password_reset_email(
    reset_url: str,
    company_name: str = "Loqi",
) -> TemplateResult:
    html_content = f"""<p>We received a request to reset your password.</p>
<p style="text-align:center"><a href="{reset_url}" class="button">Reset Password</a></p>
<p>If the button doesn't work, copy and paste this link into your browser:</p>
<p style="word-break:break-all;font-size:13px;color:#71717a">{reset_url}</p>
<p>This link expires in 15 minutes. If you didn't request a password reset, you can safely ignore this email.</p>"""
    return TemplateResult(
        subject=f"Reset your password — {company_name}",
        html=_base_html(html_content, company_name),
        plain_text=_wrap_plain(
            f"We received a request to reset your password.\n\n"
            f"Reset your password: {reset_url}\n\n"
            f"This link expires in 15 minutes. If you didn't request a password reset, "
            f"you can safely ignore this email.\n\n— {company_name}",
        ),
    )


def render_invitation_email(
    inviter_name: str,
    organization_name: str,
    accept_url: str,
    company_name: str = "Loqi",
) -> TemplateResult:
    html_content = f"""<p><strong>{inviter_name}</strong> has invited you to join <strong>{organization_name}</strong> on {company_name}.</p>
<p style="text-align:center"><a href="{accept_url}" class="button">Accept Invitation</a></p>
<p>If the button doesn't work, copy and paste this link into your browser:</p>
<p style="word-break:break-all;font-size:13px;color:#71717a">{accept_url}</p>
<p>This invitation expires in 7 days.</p>"""
    return TemplateResult(
        subject=f"You've been invited to {organization_name} — {company_name}",
        html=_base_html(html_content, company_name),
        plain_text=_wrap_plain(
            f"{inviter_name} has invited you to join {organization_name} on {company_name}.\n\n"
            f"Accept invitation: {accept_url}\n\n"
            f"This invitation expires in 7 days.\n\n— {company_name}",
        ),
    )


def render_welcome_email(
    name: str,
    company_name: str = "Loqi",
) -> TemplateResult:
    html_content = f"""<p>Welcome to {company_name}, {name}!</p>
<p>We're excited to have you on board. Here are a few things you can do to get started:</p>
<ul>
  <li><strong>Complete your profile</strong> — Add your details and preferences.</li>
  <li><strong>Explore the dashboard</strong> — Get familiar with your workspace.</li>
  <li><strong>Connect your accounts</strong> — Link Gmail, Calendar, and more.</li>
</ul>
<p>If you have any questions, just reply to this email. We're here to help!</p>"""
    return TemplateResult(
        subject=f"Welcome to {company_name}!",
        html=_base_html(html_content, company_name),
        plain_text=_wrap_plain(
            f"Welcome to {company_name}, {name}!\n\n"
            f"We're excited to have you on board. Here are a few things you can do to get started:\n\n"
            f"- Complete your profile — Add your details and preferences.\n"
            f"- Explore the dashboard — Get familiar with your workspace.\n"
            f"- Connect your accounts — Link Gmail, Calendar, and more.\n\n"
            f"If you have any questions, just reply to this email. We're here to help!\n\n— {company_name}",
        ),
    )


def render_billing_receipt_email(
    recipient_name: str,
    amount: str,
    plan_name: str,
    invoice_url: str,
    company_name: str = "Loqi",
) -> TemplateResult:
    html_content = f"""<p>Hi {recipient_name},</p>
<p>Thank you for your payment. Here's your receipt:</p>
<table style="width:100%;border-collapse:collapse;margin:16px 0;">
  <tr><td style="padding:8px 0;color:#71717a">Plan</td><td style="padding:8px 0;font-weight:600;text-align:right">{plan_name}</td></tr>
  <tr><td style="padding:8px 0;color:#71717a;border-top:1px solid #e4e4e7">Amount paid</td><td style="padding:8px 0;font-weight:600;text-align:right;border-top:1px solid #e4e4e7">{amount}</td></tr>
</table>
<p style="text-align:center"><a href="{invoice_url}" class="button">View Invoice</a></p>"""
    return TemplateResult(
        subject=f"Your receipt from {company_name}",
        html=_base_html(html_content, company_name),
        plain_text=_wrap_plain(
            f"Hi {recipient_name},\n\n"
            f"Thank you for your payment. Here's your receipt:\n\n"
            f"Plan: {plan_name}\n"
            f"Amount paid: {amount}\n\n"
            f"View invoice: {invoice_url}\n\n— {company_name}",
        ),
    )


def render_subscription_cancelled_email(
    recipient_name: str,
    plan_name: str,
    effective_date: str,
    company_name: str = "Loqi",
) -> TemplateResult:
    html_content = f"""<p>Hi {recipient_name},</p>
<p>Your <strong>{plan_name}</strong> subscription has been cancelled.</p>
<p>Your access will continue until <strong>{effective_date}</strong>. After that, your account will be downgraded to the free tier.</p>
<p>If you change your mind, you can resubscribe at any time.</p>"""
    return TemplateResult(
        subject=f"Subscription cancelled — {company_name}",
        html=_base_html(html_content, company_name),
        plain_text=_wrap_plain(
            f"Hi {recipient_name},\n\n"
            f"Your {plan_name} subscription has been cancelled.\n\n"
            f"Your access will continue until {effective_date}. After that, your account "
            f"will be downgraded to the free tier.\n\n"
            f"If you change your mind, you can resubscribe at any time.\n\n— {company_name}",
        ),
    )


def render_subscription_renewed_email(
    recipient_name: str,
    plan_name: str,
    amount: str,
    next_billing_date: str,
    company_name: str = "Loqi",
) -> TemplateResult:
    html_content = f"""<p>Hi {recipient_name},</p>
<p>Your <strong>{plan_name}</strong> subscription has been renewed.</p>
<table style="width:100%;border-collapse:collapse;margin:16px 0;">
  <tr><td style="padding:8px 0;color:#71717a">Plan</td><td style="padding:8px 0;font-weight:600;text-align:right">{plan_name}</td></tr>
  <tr><td style="padding:8px 0;color:#71717a;border-top:1px solid #e4e4e7">Amount</td><td style="padding:8px 0;font-weight:600;text-align:right;border-top:1px solid #e4e4e7">{amount}</td></tr>
  <tr><td style="padding:8px 0;color:#71717a;border-top:1px solid #e4e4e7">Next billing</td><td style="padding:8px 0;font-weight:600;text-align:right;border-top:1px solid #e4e4e7">{next_billing_date}</td></tr>
</table>"""
    return TemplateResult(
        subject=f"Subscription renewed — {company_name}",
        html=_base_html(html_content, company_name),
        plain_text=_wrap_plain(
            f"Hi {recipient_name},\n\n"
            f"Your {plan_name} subscription has been renewed.\n\n"
            f"Plan: {plan_name}\n"
            f"Amount: {amount}\n"
            f"Next billing date: {next_billing_date}\n\n— {company_name}",
        ),
    )


TEMPLATE_RENDERERS: dict[str, Any] = {
    "verification": render_verification_email,
    "password_reset": render_password_reset_email,
    "invitation": render_invitation_email,
    "welcome": render_welcome_email,
    "billing_receipt": render_billing_receipt_email,
    "subscription_cancelled": render_subscription_cancelled_email,
    "subscription_renewed": render_subscription_renewed_email,
}
