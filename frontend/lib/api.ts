import type { LoqiMessage, LoqiSessionSummary } from "./types";

const API_BASE =
  process.env.NEXT_PUBLIC_LOQI_API_BASE_URL || "http://127.0.0.1:10000";

async function parseJson<T>(response: Response): Promise<T> {
  if (!response.ok) {
    const text = await response.text();
    throw new Error(text || `Request failed with ${response.status}`);
  }
  return response.json() as Promise<T>;
}

export async function createSession(displayName?: string) {
  const response = await fetch(`${API_BASE}/api/web/session`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ display_name: displayName }),
  });
  return parseJson<{
    ok: boolean;
    session_token: string;
    gmail_connected: boolean;
  }>(response);
}

export async function getSession(sessionToken: string) {
  const response = await fetch(`${API_BASE}/api/web/session/${sessionToken}`, {
    cache: "no-store",
  });
  return parseJson<LoqiSessionSummary>(response);
}

export async function sendMessage(sessionToken: string, text: string) {
  const response = await fetch(
    `${API_BASE}/api/web/session/${sessionToken}/messages`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ text }),
    },
  );
  return parseJson<{ ok: boolean; messages: LoqiMessage[] }>(response);
}

export async function getGmailStatus(sessionToken: string) {
  const response = await fetch(`${API_BASE}/api/web/session/${sessionToken}/gmail`, {
    cache: "no-store",
  });
  return parseJson<{
    ok: boolean;
    gmail_connected: boolean;
    connect_url: string;
  }>(response);
}
