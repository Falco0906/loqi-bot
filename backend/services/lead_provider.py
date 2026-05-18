import os
import re


def _log(message: str) -> None:
    print(f"[lead_provider] {message}")


def _filter_and_rank_leads(leads: list, icp: dict) -> tuple[list, dict]:
    """
    Filter excluded leads and rank remaining by commercial qualification.
    Uses commercial_qualifier for multi-dimensional scoring.
    Returns (filtered_and_ranked_leads, filtering_stats)
    """
    from services.commercial_qualifier import qualify_and_rank_leads, log_ranking_breakdown

    qualified_leads, qual_stats = qualify_and_rank_leads(leads, icp)

    filter_stats = {
        "total_found": qual_stats["total"],
        "excluded_count": qual_stats["excluded_vendor"] + qual_stats["excluded_junk"],
        "excluded_reasons": qual_stats["rejected_reasons"],
        "scored_count": qual_stats["qualified"],
        "average_score": qual_stats["avg_score"],
        "drift_detected": qual_stats["drift_detected"],
    }

    _log(f"Commercial qualification: {filter_stats['excluded_count']} excluded (vendor={qual_stats['excluded_vendor']}, junk={qual_stats['excluded_junk']}), {filter_stats['scored_count']} qualified, {filter_stats['drift_detected']} drift flags, avg_score={filter_stats['average_score']:.1f}")

    return qualified_leads, filter_stats


def get_leads(service: str, target: str) -> dict:
    """Original deterministic lead search"""
    provider = os.getenv("LEAD_PROVIDER", "free").strip().lower()

    _log(f"using: {provider}")
    _log(f"input: {service}, {target}")

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
        _log(f"error: {error}")
        error_message = str(error)
        return {
            "ok": False,
            "source": provider,
            "leads": [],
            "error": error_message,
        }


def search_with_expansion(service: str, target: str) -> dict:
    """AI-enhanced lead search with buyer-intent expansion and filtering"""
    provider = os.getenv("LEAD_PROVIDER", "free").strip().lower()

    _log(f"BUYER-INTENT search: service='{service}', target='{target}'")

    combined_input = f"{service} {target}".strip() if target else service

    try:
        from services.icp_extractor import extract_structured_icp
        icp = extract_structured_icp(combined_input)

        _log(f"ICP extracted: mode={icp.get('mode')}, offer='{icp.get('offer')}")
        _log(f"buyer_industries: {icp.get('buyer_industries', [])}")
        _log(f"buyer_roles: {icp.get('buyer_roles', [])[:3]}...")
        _log(f"excluded_roles: {icp.get('excluded_roles', [])}")
    except Exception as e:
        _log(f"ICP extraction failed: {e}, using fallback")
        icp = None

    try:
        from services.search_expansion import expand_search_intent
        expansion = expand_search_intent(service, target, icp)

        _log(f"Expansion result: {len(expansion.get('search_queries', []))} queries")
        _log(f"buyer_roles: {expansion.get('roles', [])[:3]}...")
        _log(f"buyer_industries: {expansion.get('industries', [])}")
    except Exception as e:
        _log(f"Expansion failed: {e}, falling back to deterministic")
        expansion = None

    if provider != "free":
        _log(f"Provider {provider} doesn't support expansion, using deterministic")
        return get_leads(service, target)

    try:
        from services.free_leads import search_free_leads, SerpAPIError
        
        all_leads = []
        seen_urls = set()
        
        if expansion and expansion.get("search_queries"):
            search_queries = expansion["search_queries"]
            
            for query in search_queries:
                query_text = query.replace('site:linkedin.com/in "', '').replace('"', '')
                _log(f"Searching (buyer-focused): {query_text}")
                
                try:
                    leads = search_free_leads(query_text)
                    
                    for lead in leads:
                        if lead.get("linkedin_url") and lead["linkedin_url"] not in seen_urls:
                            seen_urls.add(lead["linkedin_url"])
                            all_leads.append(lead)
                            
                    _log(f"Found {len(leads)} leads for query, total unique: {len(all_leads)}")
                    
                except SerpAPIError as e:
                    _log(f"Query failed: {e}")
                    continue
                    
        else:
            _log("No expansion, using direct search")
            leads = search_free_leads(target or service)
            all_leads = leads

        if not all_leads:
            return {
                "ok": False,
                "source": "free",
                "leads": [],
                "error": "No leads found for expanded search",
                "icp": icp,
            }

        filtered_leads = all_leads
        filter_stats = {
            "total_found": len(all_leads),
            "excluded_count": 0,
            "scored_count": len(all_leads),
            "average_score": 0,
        }
        
        if icp and (icp.get("buyer_roles") or icp.get("excluded_roles")):
            _log("Applying buyer-intent filtering and ranking...")
            filtered_leads, filter_stats = _filter_and_rank_leads(all_leads, icp)

        _log(f"Final result: {len(filtered_leads)} leads after filtering (from {filter_stats['total_found']} found)")

        return {
            "ok": True,
            "source": "free",
            "leads": filtered_leads,
            "error": None,
            "expansion": expansion,
            "icp": icp,
            "filter_stats": filter_stats,
        }

    except Exception as error:
        _log(f"error: {error}")
        error_message = str(error)
        return {
            "ok": False,
            "source": provider,
            "leads": [],
            "error": error_message,
            "icp": icp,
        }