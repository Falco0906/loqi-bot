# Loqi - AI-Native Outbound Operating System

Loqi is an AI-powered outbound operating system for lead sourcing, personalized outreach, and conversational workflow management.

---

## Quick Links

- **[Architecture](docs/ARCHITECTURE.md)** - System design and philosophy
- **[Current State](docs/CURRENT_STATE.md)** - What's working right now (MOST IMPORTANT)
- **[Setup](docs/SETUP.md)** - Complete setup instructions
- **[Workflows](docs/WORKFLOWS.md)** - Detailed workflow documentation
- **[Lead Pipeline](docs/LEAD_PIPELINE.md)** - Complete lead architecture
- **[Deployment](docs/DEPLOYMENT.md)** - Deploy to Render + Vercel
- **[Migration](docs/MIGRATION.md)** - Move to a new machine
- **[Debugging](docs/DEBUGGING.md)** - Common issues and fixes
- **[Known Issues](docs/KNOWN_ISSUES.md)** - Current limitations

---

## Quick Start

### Local Development

```bash
# Backend
cd backend
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
cp .env.example .env  # Fill in your credentials
uvicorn main:app --reload --port 10000

# Frontend (new terminal)
cd frontend
npm install
npm run dev
```

Visit http://localhost:3000

---

## What Loqi Does

1. **Lead Search** - Find leads via SerpAPI (LinkedIn profiles)
2. **ICP Extraction** - Extract customer profiles (AI or fallback)
3. **Semantic Expansion** - Expand queries for better results
4. **Draft Generation** - AI-powered personalized emails
5. **Gmail Send** - Send directly from the app

---

## Current Capabilities

✅ Working:
- Web chat UI
- Session management
- ICP extraction (AI + deterministic fallback)
- Semantic search expansion
- Lead search via SerpAPI
- Lead storage in Supabase
- Email drafting
- Gmail integration (OAuth + send)

⚠️ Partial:
- Gmail inbox sync
- Lead ranking
- Enrichment

❌ Not Implemented:
- Reply detection
- Personalization memory
- Analytics
- Stripe payments
- Full authentication

---

## Tech Stack

- **Backend:** FastAPI, Python
- **Frontend:** Next.js, Tailwind
- **Database:** Supabase (PostgreSQL)
- **AI:** OpenAI (GPT-4o-mini)
- **Leads:** SerpAPI
- **Email:** Gmail API
- **Hosting:** Render (backend), Vercel (frontend)

---

## Documentation Structure

```
docs/
├── ARCHITECTURE.md      # System design
├── STACK.md            # Technology choices
├── ROADMAP.md          # Future plans
├── CURRENT_STATE.md    # What's working (IMPORTANT)
├── NEXT_STEPS.md       # Engineering priorities
├── SETUP.md            # Setup instructions
├── ENVIRONMENT.md      # Environment variables
├── DATABASE.md         # Schema documentation
├── WORKFLOWS.md        # Detailed workflows
├── LEAD_PIPELINE.md    # Lead architecture
├── AI_SYSTEM.md        # AI usage + fallback philosophy
├── DEPLOYMENT.md       # Deploy instructions
├── MIGRATION.md        # Move to new machine
├── DEBUGGING.md        # Common fixes
└── KNOWN_ISSUES.md     # Current limitations
```

---

## Support

- Check `docs/CURRENT_STATE.md` for what's working
- Check `docs/DEBUGGING.md` for issues
- Check `docs/KNOWN_ISSUES.md` for limitations