from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class EmailConfig:
    provider: str = "console"
    api_key: str = ""
    from_email: str = "noreply@loqi.ai"
    from_name: str = "Loqi"
    reply_to: str = ""
    app_url: str = "http://localhost:3000"
    company_name: str = "Loqi"
    company_website: str = "https://loqi.ai"
    template_vars: dict[str, str] = field(default_factory=dict)
