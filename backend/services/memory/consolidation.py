from __future__ import annotations

from services.memory.models import (
    AccountMemory,
    ContactMemory,
    ConversationMemory,
    Memory,
    MemorySearch,
    MemoryType,
    PreferenceMemory,
)
from services.memory.memory_store import MemoryProvider


async def consolidate_memories(provider: MemoryProvider) -> dict[str, int]:
    result: dict[str, int] = {}

    result["account"] = await _consolidate_accounts(provider)
    result["contact"] = await _consolidate_contacts(provider)
    result["conversation"] = await _consolidate_conversations(provider)

    return result


async def _consolidate_accounts(provider: MemoryProvider) -> int:
    search = MemorySearch(memory_type=MemoryType.ACCOUNT, limit=500)
    result = await provider.search(search)
    accounts: dict[str, list[AccountMemory]] = {}

    for mem in result.memories:
        if not isinstance(mem, AccountMemory):
            continue
        key = mem.company_id or mem.company_name
        if key:
            accounts.setdefault(key, []).append(mem)

    consolidated = 0
    for key, mems in accounts.items():
        if len(mems) < 2:
            continue
        latest = max(mems, key=lambda m: m.timestamp)
        tier_counts: dict[str, int] = {}
        intent_counts: dict[str, int] = {}
        all_contacts: set[str] = set()

        for m in mems:
            if m.account_tier:
                tier_counts[m.account_tier] = tier_counts.get(m.account_tier, 0) + 1
            if m.buying_intent:
                intent_counts[m.buying_intent] = intent_counts.get(m.buying_intent, 0) + 1
            all_contacts.update(m.key_contacts)

        latest.metadata["consolidated_from"] = len(mems)
        if tier_counts:
            latest.account_tier = max(tier_counts, key=tier_counts.get)
        if intent_counts:
            latest.buying_intent = max(intent_counts, key=intent_counts.get)
        latest.key_contacts = list(all_contacts)
        latest.tags = list(set(latest.tags + ["consolidated"]))
        await provider.update(latest.id, {
            "account_tier": latest.account_tier,
            "buying_intent": latest.buying_intent,
            "key_contacts": latest.key_contacts,
            "tags": latest.tags,
            "metadata": latest.metadata,
        })
        consolidated += 1

    return consolidated


async def _consolidate_contacts(provider: MemoryProvider) -> int:
    search = MemorySearch(memory_type=MemoryType.CONTACT, limit=500)
    result = await provider.search(search)
    contacts: dict[str, list[ContactMemory]] = {}

    for mem in result.memories:
        if not isinstance(mem, ContactMemory):
            continue
        key = mem.contact_id or mem.email
        if key:
            contacts.setdefault(key, []).append(mem)

    consolidated = 0
    for key, mems in contacts.items():
        if len(mems) < 2:
            continue
        latest = max(mems, key=lambda m: m.timestamp)
        all_comm: list[str] = []
        seen_comm: set[str] = set()
        for m in mems:
            for c in m.communication_history:
                if c not in seen_comm:
                    seen_comm.add(c)
                    all_comm.append(c)

        latest.communication_history = all_comm
        latest.tags = list(set(latest.tags + ["consolidated"]))
        await provider.update(latest.id, {
            "communication_history": latest.communication_history,
            "tags": latest.tags,
        })
        consolidated += 1

    return consolidated


async def _consolidate_conversations(provider: MemoryProvider) -> int:
    search = MemorySearch(memory_type=MemoryType.CONVERSATION, limit=500)
    result = await provider.search(search)
    conversations: dict[str, list[ConversationMemory]] = {}

    for mem in result.memories:
        if not isinstance(mem, ConversationMemory):
            continue
        key = mem.conversation_id
        if key:
            conversations.setdefault(key, []).append(mem)

    consolidated = 0
    for key, mems in conversations.items():
        if len(mems) < 2:
            continue
        latest = max(mems, key=lambda m: m.timestamp)
        all_intents: list[str] = []
        all_objections: list[str] = []
        seen_intents: set[str] = set()
        seen_objections: set[str] = set()

        for m in mems:
            for intent in m.intents:
                if intent not in seen_intents:
                    seen_intents.add(intent)
                    all_intents.append(intent)
            for obj in m.objections:
                if obj not in seen_objections:
                    seen_objections.add(obj)
                    all_objections.append(obj)

        latest.intents = all_intents
        latest.objections = all_objections
        latest.tags = list(set(latest.tags + ["consolidated"]))
        await provider.update(latest.id, {
            "intents": latest.intents,
            "objections": latest.objections,
            "tags": latest.tags,
        })
        consolidated += 1

    return consolidated
