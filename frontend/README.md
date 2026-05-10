# Loqi Web MVP

This is the first ChatGPT-style web client for Loqi.

## Local development

1. Install dependencies:
   `npm install`
2. Set:
   `NEXT_PUBLIC_LOQI_API_BASE_URL=http://127.0.0.1:10000`
3. Run:
   `npm run dev`

The app bootstraps a lightweight backend-issued session token and stores it in `localStorage`.
