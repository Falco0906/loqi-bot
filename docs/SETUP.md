# Loqi Setup Guide

Complete setup instructions for Mac, Windows, and WSL2.

---

## Prerequisites

### Required Accounts
1. **GitHub** - Repository access
2. **Supabase** - Database (free tier works)
3. **OpenAI** - API key (optional, fallback works without)
4. **SerpAPI** - Lead search (free tier available)
5. **Google Cloud** - Gmail OAuth (requires project setup)
6. **Render** - Backend hosting (free tier)
7. **Vercel** - Frontend hosting (free tier)

---

## Mac Setup

### 1. Clone Repository

```bash
cd ~/Downloads
git clone https://github.com/Falco0906/loqi-bot.git
cd loqi-bot
```

### 2. Python Setup

```bash
# Check Python version
python3 --version  # Should be 3.11+

# Create virtual environment
cd backend
python3 -m venv venv

# Activate (do this every time you work on backend)
source venv/bin/activate

# Install dependencies
pip install -r requirements.txt
```

### 3. Node Setup

```bash
# Check Node version
node --version  # Should be 18+

# Install frontend dependencies
cd ../frontend
npm install
```

### 4. Environment Variables

```bash
# Backend .env
cd ../backend
cp .env.example .env

# Edit .env with your values (see ENVIRONMENT.md)
nano .env
```

### 5. Run Backend

```bash
# With venv activated
uvicorn main:app --reload --port 10000
```

Backend runs at: http://localhost:10000

### 6. Run Frontend

```bash
# In a new terminal (venv not needed)
cd frontend
npm run dev
```

Frontend runs at: http://localhost:3000

---

## Windows Setup

### Option A: WSL2 (Recommended)

Follow the **WSL2 Setup** section below.

### Option B: Native Windows

```powershell
# Install Python from python.org (3.11+)
# Install Node from nodejs.org (18+)

# Clone repository
git clone https://github.com/Falco0906/loqi-bot.git
cd loqi-bot

# Create virtual environment
cd backend
python -m venv venv
.\venv\Scripts\Activate

# Install dependencies
pip install -r requirements.txt

# Frontend
cd ../frontend
npm install

# Run (in separate terminals)
# Backend:
.\venv\Scripts\python.exe -m uvicorn main:app --reload --port 10000
# Frontend:
npm run dev
```

---

## WSL2 Setup (Recommended for Windows)

### 1. Install WSL2

```powershell
# Run in PowerShell as Administrator
wsl --install -d Ubuntu
```

### 2. Setup Ubuntu

```bash
# Update system
sudo apt update && sudo apt upgrade -y

# Install Python
sudo apt install python3 python3-venv python3-pip -y

# Install Node.js
curl -fsSL https://deb.nodesource.com/setup_18.x | sudo -E bash -
sudo apt install nodejs -y

# Install Git
sudo apt install git -y
```

### 3. Clone and Setup

```bash
# Clone repository
cd ~
git clone https://github.com/Falco0906/loqi-bot.git
cd loqi-bot

# Backend setup
cd backend
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt

# Frontend setup (in new terminal or same)
cd ../frontend
npm install
```

### 4. Environment Variables

```bash
# Copy example env
cp .env.example .env
nano .env
```

### 5. Run Development

```bash
# Terminal 1: Backend
cd loqi-bot/backend
source venv/bin/activate
uvicorn main:app --reload --port 10000

# Terminal 2: Frontend
cd loqi-bot/frontend
npm run dev
```

---

## Supabase Setup

### 1. Create Project

1. Go to https://supabase.com
2. Click "New Project"
3. Name: loqi-bot
4. Database password: save for .env
5. Region: closest to you

### 2. Get Credentials

1. Project Settings → API
2. Copy `Project URL` → SUPABASE_URL
3. Copy `anon public` key → SUPABASE_KEY

### 3. Run Migrations

The schema is defined in `backend/supabase/multi_client_mvp.sql`. Run this in Supabase SQL editor:

```sql
-- Run the contents of backend/supabase/multi_client_mvp.sql
```

---

## OpenAI Setup (Optional)

1. Go to https://platform.openai.com
2. API Keys → Create new key
3. Copy to OPENAI_API_KEY in .env

**Note:** Fallback works without this, but AI extraction won't work.

---

## SerpAPI Setup

1. Go to https://serpapi.com
2. Sign up (free tier available)
3. Copy API key to SERPAPI_KEY in .env

---

## Gmail OAuth Setup

### 1. Google Cloud Console

1. Go to https://console.cloud.google.com
2. Create project: loqi-bot
3. Enable Gmail API
4. Credentials → OAuth Client ID
5. Application type: Web application
6. Authorized redirect URIs:
   - http://localhost:10000/google/callback
   - (production URL)/google/callback

### 2. Get Credentials

1. Credentials → OAuth Client
2. Copy Client ID → GMAIL_CLIENT_ID
3. Copy Client Secret → GMAIL_CLIENT_SECRET

### 3. Configure .env

```
GMAIL_CLIENT_ID=your-client-id
GMAIL_CLIENT_SECRET=your-client-secret
```

---

## Deployment

### Render (Backend)

1. Connect GitHub repo to Render
2. Create Web Service
3. Root directory: `backend`
4. Build command: (leave empty)
5. Start command: `uvicorn main:app --host 0.0.0.0 --port $PORT`
6. Add environment variables in Render settings

### Vercel (Frontend)

1. Connect GitHub repo to Vercel
2. Framework: Next.js
3. Root directory: `frontend`
4. Environment variables: NEXT_PUBLIC_API_URL = your-render-backend-url
5. Deploy

---

## Quick Start Verification

```bash
# 1. Backend health check
curl http://localhost:10000/
# Expected: "Loqi backend running"

# 2. Create session
curl -X POST http://localhost:10000/api/web/session \
  -H "Content-Type: application/json" \
  -d '{"message": "test"}'
# Expected: JSON with session_token

# 3. Frontend check
curl http://localhost:3000
# Expected: HTML page with "Loqi"
```

---

## Common Issues

### Python not found (Mac)
```bash
# Use python3 instead of python
python3 --version
```

### Permission denied (Mac)
```bash
# If pip install fails
sudo pip install -r requirements.txt
```

### Node modules issues
```bash
# Clean reinstall
rm -rf node_modules package-lock.json
npm install
```

### Port already in use
```bash
# Find and kill process
lsof -i :10000  # backend
lsof -i :3000  # frontend
kill -9 <PID>
```