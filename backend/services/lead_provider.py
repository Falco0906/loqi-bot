import os


def get_leads(service: str, target: str) -> dict:
    provider = os.getenv("LEAD_PROVIDER", "free").strip().lower()

    print("[lead_provider] using:", provider)
    print("[lead_provider] input:", service, target)

    try:
        if provider == "apollo":
            from services.apollo import search_leads
            return search_leads(target)

        if provider == "free":
            from services.free_leads import search_free_leads, SerpAPIError
            leads = search_free_leads(target)
            return {
                "ok": True,
                "source": "free",
                "leads": leads,
                "error": None,
            }

        raise Exception(f"Invalid LEAD_PROVIDER: {provider}")
    except Exception as error:
        print(f"[lead_provider] error: {error}")
        error_message = str(error)
        return {
            "ok": False,
            "source": provider,
            "leads": [],
            "error": error_message,
        }