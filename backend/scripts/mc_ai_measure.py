"""TMP-DIAG: measure the real AI calls (recs + brief) with the real context, warm DB."""

import sys
import time

sys.path.insert(0, ".")

TOKEN = sys.argv[1] if len(sys.argv) > 1 else "_5pbnHGls-9aDjIJJL2h0yCL"

from services.conversation_store import get_web_session
from services.workspace_state import load_workspace_state
from services.workspace_snapshot import build_snapshot
from services.recommendation_engine import generate_recommendations
from services.executive_brief import generate_brief

c = get_web_session(TOKEN)

print(f"[diag] token={TOKEN}")
t0 = time.monotonic()

web = get_web_session(TOKEN)
print(f"[diag] get_web_session: {(time.monotonic()-t0)*1000:.0f}ms -> {web}")

uid = web.get("id") if web else None
print(f"[diag] user_id={uid}")

st = load_workspace_state(uid)
print(f"[diag] load_workspace_state: {(time.monotonic()-t0)*1000:.0f}ms campaigns={len(st.get('campaigns', []))} drafts={len(st.get('drafts', []))}")

snap = build_snapshot(TOKEN, st.get("campaigns", []), st.get("drafts", []), user_id=uid)
print(f"[diag] build_snapshot: {(time.monotonic()-t0)*1000:.0f}ms")

t1 = time.monotonic()
recs = generate_recommendations(snap)
print(f"[diag] generate_recommendations: {(time.monotonic()-t1)*1000:.0f}ms n={len(recs)}")

t2 = time.monotonic()
brief = generate_brief(snap, recs)
print(f"[diag] generate_brief: {(time.monotonic()-t2)*1000:.0f}ms")

print(f"[diag] TOTAL: {(time.monotonic()-t0)*1000:.0f}ms")
