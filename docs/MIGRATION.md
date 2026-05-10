# Loqi Migration Guide

Complete guide for moving Loqi to a completely new machine.

---

## Quick Recovery (5 Minutes)

If you just need to get running again:

```bash
# 1. Clone
git clone https://github.com/Falco0906/loqi-bot.git

# 2. Setup
cd loqi-bot/backend
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
cp .env.example .env

# 3. Get credentials from docs/ENVIRONMENT.md
# Fill in your .env file

# 4. Run
uvicorn main:app --reload --port 10000

# 5. Frontend (new terminal)
cd ../frontend
npm install
npm run dev
```

---

## Full Migration Steps

### 1. System Preparation

#### Mac
```bash
# Install Xcode Command Line Tools
xcode-select --install

# Install Homebrew (if not present)
/bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
```

#### Windows
```bash
# Install WSL2 (recommended)
wsl --install -d Ubuntu
```

#### Linux (WSL2/Ubuntu)
```bash
sudo apt update
sudo apt upgrade -y
sudo apt install python3 python3-venv python3-pip nodejs git -y
```

### 2. Repository Clone

```bash
cd ~/Downloads
git clone https://github.com/Falco0906/loqi-bot.git
cd loqi-bot
```

### 3. Python Setup

```bash
cd backend

# Create virtual environment
python3 -m venv venv

# Activate
source venv/bin/activate  # Mac/Linux
# or: .\venv\Scripts\Activate  # Windows

# Install dependencies
pip install -r requirements.txt
```

### 4. Node Setup

```bash
cd ../frontend

# Install Node if needed (v18+)
# Mac: brew install node
# Windows: Download from nodejs.org
# Linux: sudo apt install nodejs

npm install
```

### 5. Environment Setup

From `docs/ENVIRONMENT.md`, get all required variables:

```bash
cd ../backend
cp .env.example .env
nano .env
```

Fill in:
- SUPABASE_URL
- SUPABASE_KEY
- SESSION_SECRET
- GMAIL_CLIENT_ID
- GMAIL_CLIENT_SECRET
- SERPAPI_KEY
- OPENAI_API_KEY (optional)

### 6. Supabase Access

If you have Supabase access:
1. Go to https://supabase.com
2. Project Settings → API
3. Copy credentials

If NEW Supabase needed:
1. Create new project
2. Run migrations from `backend/supabase/multi_client_mvp.sql`

### 7. Test Locally

```bash
# Terminal 1: Backend
cd backend
source venv/bin/activate
uvicorn main:app --reload --port 10000

# Terminal 2: Frontend
cd frontend
npm run dev

# Verify
curl http://localhost:10000/
curl http://localhost:3000
```

---

## AI Context Recovery

To restore AI understanding of the project:

### Read These Files (in order):
1. `docs/ARCHITECTURE.md` - System design
2. `docs/CURRENT_STATE.md` - What's working
3. `docs/LEAD_PIPELINE.md` - Lead flow
4. `docs/WORKFLOWS.md` - Detailed workflows
5. `docs/AI_SYSTEM.md` - AI philosophy and fallback

### Key Implementation Files:
```
backend/
├── main.py                     # Entry point
├── workflows.py                # Orchestration
├── services/
│   ├── conversation_engine.py  # Core runtime
│   ├── icp_extractor.py        # ICP extraction
│   ├── search_expansion.py     # Query expansion
│   ├── lead_provider.py       # Lead search
│   ├── free_leads.py           # SerpAPI
│   ├── ai.py                   # Draft generation
│   ├── gmail.py                # Email sending
│   └── supabase.py             # Database

frontend/
├── app/page.tsx                # Main UI
└── components/chat/            # Chat components
```

---

## OpenCode Setup

If using OpenCode:

```bash
# Install
npm install -g opencode

# Run
opencode
```

OpenCode will read this directory and understand:
- Project structure
- Architecture
- Current state
- Implementation details

---

## Restoring Credentials

### From Memory/Last Machine
Check these in order:
1. Last project's `.env` file
2. Password manager (1Password, Bitwarden)
3. Supabase dashboard
4. Google Cloud Console
5. OpenAI Platform
6. SerpAPI dashboard

### From Documentation
- `docs/ENVIRONMENT.md` has variable names
- Not actual values (for security)

---

## Known External Dependencies

| Service | Purpose | Sign Up |
|---------|---------|---------|
| Supabase | Database | supabase.com |
| OpenAI | AI | platform.openai.com |
| SerpAPI | Lead search | serpapi.com |
| Google Cloud | Gmail OAuth | console.cloud.google.com |
| Render | Backend hosting | render.com |
| Vercel | Frontend hosting | vercel.com |

---

## Troubleshooting New Machine

### "Python not found"
```bash
# Mac
brew install python3

# Linux
sudo apt install python3
```

### "Node not found"
```bash
# Mac
brew install node

# Linux
curl -fsSL https://deb.nodesource.com/setup_18.x | sudo -E bash -
sudo apt install nodejs
```

### "pip command not found"
```bash
# Ensure venv is activated
source venv/bin/activate
```

### "npm command not found"
```bash
# Install Node first
```

---

## Post-Migration Verification

Run these to confirm everything works:

```bash
# 1. Backend health
curl http://localhost:10000/
# Expected: "Loqi backend running"

# 2. Create session
curl -X POST http://127.0.0.1:10000/api/web/session \
  -H "Content-Type: application/json" \
  -d '{"message": "test"}'
# Expected: JSON with session_token

# 3. Frontend
curl http://localhost:3000
# Expected: HTML page

# 4. Test lead search (through browser)
# 1. Go to localhost:3000
# 2. Create session
# 3. Enter service: "CRM"
# 4. Enter target: "startups"
# 5. Should see leads
```

---

## Emergency Recovery

If nothing works:

1. Check `docs/CURRENT_STATE.md` for what's known to work
2. Check `docs/DEBUGGING.md` for common fixes
3. Check `docs/KNOWN_ISSUES.md` for limitations
4. Review `backend/server.log` for errors