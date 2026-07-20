from __future__ import annotations

_DEFAULT_BRAND = {
    "primary_color": "#2563eb",
    "secondary_color": "#1e40af",
    "font_family": "Arial, Helvetica, sans-serif",
    "company_name": "",
    "logo_url": "",
    "website": "",
    "signature": "",
}


def _brand_style(branding: BrandKit | None) -> dict[str, str]:
    if branding is None:
        return dict(_DEFAULT_BRAND)
    return {
        "primary_color": branding.primary_color or "#2563eb",
        "secondary_color": branding.secondary_color or "#1e40af",
        "font_family": branding.font_family or "Arial, Helvetica, sans-serif",
        "company_name": branding.company_name or "",
        "logo_url": branding.logo_url or "",
        "website": branding.website or "",
        "signature": branding.signature or "",
    }


def _build_preview(preview_text: str) -> str:
    if not preview_text:
        return ""
    escaped = preview_text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    return (
        f'<div style="display:none;font-size:1px;color:#ffffff;'
        f'line-height:1px;max-height:0px;max-width:0px;opacity:0;'
        f'overflow:hidden;">{escaped}</div>'
    )


def _build_header(brand: dict[str, str]) -> str:
    logo = ""
    if brand["logo_url"]:
        logo = (
            f'<img src="{brand["logo_url"]}" alt="{brand["company_name"]}" '
            f'style="max-height:50px;display:block;margin-bottom:10px;'
            f'border:0;outline:none;">'
        )
    name = brand["company_name"]
    name_html = (
        f'<h1 style="color:#ffffff;font-family:{brand["font_family"]};'
        f'font-size:24px;margin:0;font-weight:600;">{name}</h1>'
    ) if name else ""
    return (
        f'<table role="presentation" width="100%" cellpadding="0" cellspacing="0" '
        f'style="background-color:{brand["primary_color"]};">'
        f'<tr><td style="padding:30px 20px;text-align:center;">'
        f'{logo}{name_html}'
        f'</td></tr></table>'
    )


def _build_footer(footer: str, brand: dict[str, str]) -> str:
    sig = ""
    if brand["signature"]:
        sig = f'<p style="margin:0 0 5px;">{brand["signature"]}</p>'
    company = ""
    if brand["company_name"]:
        company = brand["company_name"]
        if brand["website"]:
            company += (
                f'<br><a href="{brand["website"]}" '
                f'style="color:{brand["primary_color"]};text-decoration:none;">'
                f'{brand["website"]}</a>'
            )
    powered = ""
    if footer:
        powered = (
            f'<p style="margin:15px 0 0;font-size:12px;color:#999999;">'
            f'{footer}</p>'
        )
    return (
        f'<table role="presentation" width="100%" cellpadding="0" cellspacing="0">'
        f'<tr><td style="padding:20px;border-top:1px solid #eeeeee;'
        f'font-family:{brand["font_family"]};font-size:14px;color:#666666;">'
        f'{sig}'
        f'<p style="margin:0;">{company}</p>'
        f'{powered}'
        f'</td></tr></table>'
    )


def _base_html(
    body: str,
    brand: dict[str, str],
    footer: str = "",
    preview_text: str = "",
    extra_head: str = "",
) -> str:
    preview = _build_preview(preview_text)
    header = _build_header(brand)
    footer_html = _build_footer(footer, brand)
    return (
        '<!DOCTYPE html>\n'
        '<html lang="en" xmlns="http://www.w3.org/1999/xhtml">\n'
        '<head>\n'
        '<meta charset="utf-8">\n'
        '<meta name="viewport" content="width=device-width, initial-scale=1.0">\n'
        '<meta http-equiv="X-UA-Compatible" content="IE=edge">\n'
        f'{extra_head}'
        f'{preview}'
        '</head>\n'
        '<body style="margin:0;padding:0;background-color:#f4f4f4;'
        f'font-family:{brand["font_family"]};">\n'
        '<table role="presentation" width="100%" cellpadding="0" '
        'cellspacing="0" style="background-color:#f4f4f4;">\n'
        '<tr><td align="center" style="padding:20px 10px;">\n'
        '<table role="presentation" width="600" cellpadding="0" '
        'cellspacing="0" style="max-width:600px;width:100%;'
        'background-color:#ffffff;border-radius:8px;overflow:hidden;'
        'box-shadow:0 2px 8px rgba(0,0,0,0.05);">\n'
        f'{header}'
        '<tr>\n'
        '<td style="padding:30px 20px;'
        f'font-family:{brand["font_family"]};font-size:16px;'
        'line-height:1.6;color:#333333;">\n'
        f'{body}\n'
        '</td>\n'
        '</tr>\n'
        f'{footer_html}'
        '</table>\n'
        '</td></tr></table>\n'
        '</body>\n'
        '</html>'
    )


def _resolve_body_content(body_html: str, body_plain: str) -> str:
    if body_html:
        return body_html
    return "<p>" + body_plain.replace("\n", "<br>") + "</p>"


def plain_template(
    *,
    body_html: str = "",
    body_plain: str = "",
    preview_text: str = "",
    branding: BrandKit | None = None,
    footer: str = "",
) -> str:
    brand = _brand_style(branding)
    content = _resolve_body_content(body_html, body_plain)
    return _base_html(content, brand, footer, preview_text)


def professional_template(
    *,
    body_html: str = "",
    body_plain: str = "",
    preview_text: str = "",
    branding: BrandKit | None = None,
    footer: str = "",
) -> str:
    brand = _brand_style(branding)
    content = _resolve_body_content(body_html, body_plain)
    accent_bar = (
        f'<table role="presentation" width="100%" cellpadding="0" cellspacing="0">'
        f'<tr><td style="padding:0;height:4px;background-color:{brand["secondary_color"]};'
        f'font-size:1px;line-height:1px;">&nbsp;</td></tr></table>'
    )
    return _base_html(
        accent_bar + content,
        brand,
        footer,
        preview_text,
    )


def recruiting_template(
    *,
    body_html: str = "",
    body_plain: str = "",
    preview_text: str = "",
    branding: BrandKit | None = None,
    footer: str = "",
) -> str:
    brand = _brand_style(branding)
    content = _resolve_body_content(body_html, body_plain)
    cta_wrapper = (
        f'<div style="text-align:center;margin:20px 0;">'
        f'<table role="presentation" cellpadding="0" cellspacing="0" '
        f'style="display:inline-block;">'
        f'<tr><td style="background-color:{brand["primary_color"]};'
        f'border-radius:4px;text-align:center;">'
        f'<a href="#" style="display:inline-block;padding:12px 24px;'
        f'font-family:{brand["font_family"]};font-size:16px;'
        f'color:#ffffff;text-decoration:none;font-weight:600;">'
        f'Apply Now</a>'
        f'</td></tr></table></div>'
    )
    return _base_html(
        content + cta_wrapper,
        brand,
        footer,
        preview_text,
    )


def newsletter_template(
    *,
    body_html: str = "",
    body_plain: str = "",
    preview_text: str = "",
    branding: BrandKit | None = None,
    footer: str = "",
) -> str:
    brand = _brand_style(branding)
    content = _resolve_body_content(body_html, body_plain)
    divider = (
        f'<table role="presentation" width="100%" cellpadding="0" cellspacing="0" '
        f'style="margin:20px 0;">'
        f'<tr><td style="border-top:2px solid {brand["primary_color"]};'
        f'font-size:1px;line-height:1px;">&nbsp;</td></tr></table>'
    )
    return _base_html(
        divider + content + divider,
        brand,
        footer,
        preview_text,
    )


def proposal_template(
    *,
    body_html: str = "",
    body_plain: str = "",
    preview_text: str = "",
    branding: BrandKit | None = None,
    footer: str = "",
    proposal_title: str = "",
    proposal_date: str = "",
) -> str:
    brand = _brand_style(branding)
    content = _resolve_body_content(body_html, body_plain)
    meta = ""
    if proposal_title or proposal_date:
        meta_parts = []
        if proposal_title:
            meta_parts.append(f'<strong>{proposal_title}</strong>')
        if proposal_date:
            meta_parts.append(f'<span style="color:#999;">{proposal_date}</span>')
        meta = (
            f'<table role="presentation" width="100%" cellpadding="0" cellspacing="0" '
            f'style="margin-bottom:20px;padding:15px;background-color:#f9f9f9;'
            f'border-left:4px solid {brand["primary_color"]};">'
            f'<tr><td style="font-family:{brand["font_family"]};font-size:14px;">'
            + " | ".join(meta_parts) +
            f'</td></tr></table>'
        )
    return _base_html(
        meta + content,
        brand,
        footer,
        preview_text,
    )


def product_launch_template(
    *,
    body_html: str = "",
    body_plain: str = "",
    preview_text: str = "",
    branding: BrandKit | None = None,
    footer: str = "",
    product_name: str = "",
    cta_url: str = "",
    cta_text: str = "",
) -> str:
    brand = _brand_style(branding)
    content = _resolve_body_content(body_html, body_plain)

    hero = ""
    if product_name:
        hero = (
            f'<table role="presentation" width="100%" cellpadding="0" cellspacing="0" '
            f'style="background:{brand["primary_color"]};padding:30px 20px;">'
            f'<tr><td style="text-align:center;">'
            f'<h2 style="color:#ffffff;font-family:{brand["font_family"]};'
            f'font-size:28px;margin:0;font-weight:700;">{product_name}</h2>'
            f'</td></tr></table>'
        )

    cta = ""
    if cta_url and cta_text:
        cta = (
            f'<div style="text-align:center;margin:20px 0;">'
            f'<table role="presentation" cellpadding="0" cellspacing="0" '
            f'style="display:inline-block;">'
            f'<tr><td style="background-color:{brand["primary_color"]};'
            f'border-radius:4px;text-align:center;">'
            f'<a href="{cta_url}" style="display:inline-block;padding:12px 24px;'
            f'font-family:{brand["font_family"]};font-size:16px;'
            f'color:#ffffff;text-decoration:none;font-weight:600;">'
            f'{cta_text}</a>'
            f'</td></tr></table></div>'
        )

    return _base_html(
        hero + content + cta,
        brand,
        footer,
        preview_text,
    )


TEMPLATE_FUNCTIONS: dict[str, callable] = {
    "plain": plain_template,
    "professional": professional_template,
    "recruiting": recruiting_template,
    "newsletter": newsletter_template,
    "proposal": proposal_template,
    "product_launch": product_launch_template,
}


def render_template(
    name: str,
    *,
    body_html: str = "",
    body_plain: str = "",
    preview_text: str = "",
    branding: BrandKit | None = None,
    footer: str = "",
    **kwargs: str,
) -> str:
    fn = TEMPLATE_FUNCTIONS.get(name)
    if fn is None:
        msg = f"Unknown template: {name!r}. Available: {list(TEMPLATE_FUNCTIONS)}"
        raise ValueError(msg)
    return fn(
        body_html=body_html,
        body_plain=body_plain,
        preview_text=preview_text,
        branding=branding,
        footer=footer,
        **kwargs,
    )
