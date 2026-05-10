import os


def get_leads(service: str, target: str) -> dict:
    """Original deterministic lead search"""
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


def search_with_expansion(service: str, target: str) -> dict:
    """AI-enhanced lead search with semantic expansion"""
    provider = os.getenv("LEAD_PROVIDER", "free").strip().lower()

    print(f"[lead_provider] AI-enhanced search: service='{service}', target='{target}'")

    try:
        from services.search_expansion import expand_search_intent
        expansion = expand_search_intent(service, target)
        
        print(f"[lead_provider] expansion result: {len(expansion.get('search_queries', []))} queries")
        print(f"[lead_provider] roles: {expansion.get('roles', [])}")
        print(f"[lead_provider] industries: {expansion.get('industries', [])}")
    except Exception as e:
        print(f"[lead_provider] Expansion failed: {e}, falling back to deterministic")
        expansion = None

    if provider != "free":
        print(f"[lead_provider] Provider {provider} doesn't support expansion, using deterministic")
        return get_leads(service, target)

    try:
        from services.free_leads import search_free_leads, SerpAPIError
        
        all_leads = []
        seen_urls = set()
        
        if expansion and expansion.get("search_queries"):
            search_queries = expansion["search_queries"]
            
            for query in search_queries:
                query_text = query.replace('site:linkedin.com/in "', '').replace('"', '')
                print(f"[lead_provider] Searching: {query_text}")
                
                try:
                    leads = search_free_leads(query_text)
                    
                    for lead in leads:
                        if lead.get("linkedin_url") and lead["linkedin_url"] not in seen_urls:
                            seen_urls.add(lead["linkedin_url"])
                            all_leads.append(lead)
                            
                    print(f"[lead_provider] Found {len(leads)} leads for query, total unique: {len(all_leads)}")
                    
                except SerpAPIError as e:
                    print(f"[lead_provider] Query failed: {e}")
                    continue
                    
        else:
            print("[lead_provider] No expansion, using direct search")
            leads = search_free_leads(target or service)
            all_leads = leads

        if not all_leads:
            return {
                "ok": False,
                "source": "free",
                "leads": [],
                "error": "No leads found for expanded search",
            }

        print(f"[lead_provider] Final result: {len(all_leads)} unique leads")
        
        return {
            "ok": True,
            "source": "free",
            "leads": all_leads,
            "error": None,
            "expansion": expansion,
        }
        
    except Exception as error:
        print(f"[lead_provider] error: {error}")
        error_message = str(error)
        return {
            "ok": False,
            "source": provider,
            "leads": [],
            "error": error_message,
        }