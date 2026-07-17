# Changelog

## Milestone Complete — Production Outbound Infrastructure

- GmailOutboundProvider instantiation and registration fix
- OAuth callback + connect endpoint provider wiring
- Provider fallback in all execution paths
- Send Now / Schedule / Cancel buttons (DraftReviewWorkspace)
- Campaign launch progress polling
- Provider credential persistence and startup restoration
- Connected Accounts section (Settings page)
- OAuth scope upgrade detection
- Workspace Navigation Architecture

## Milestone Complete — Conversation Management & Autonomous Follow-up Engine

- Conversation domain models (Conversation, Thread, Message, Participant, Status, Summary)
- Conversation state machine with explicit transitions (14 states)
- Timeline events (17 event types)
- Reply classification architecture (rule-based + AI fallback)
- Follow-up planner architecture (rule-based + AI fallback)
- In-memory conversation store with indexed lookups
- Integration hooks: send creates conversation, campaign dispatch creates conversations
- Conversations workspace page with list view
- Conversation detail page with timeline, messages, summary, suggested actions
- Sidebar integration
- API endpoints (list, detail, timeline, messages)
- Full documentation (conversation-lifecycle.md with state diagram, extension points)

### Future AI Features
- AI Reply Generation
- AI-Powered Follow-up Planning
- CRM Syncing
- Meeting Scheduling
- Conversation Memory
- Multi-Provider Conversations (LinkedIn, WhatsApp, Slack)

### Future UI Polish
- Workspace Navigation
- Scroll Snap
- Motion System
