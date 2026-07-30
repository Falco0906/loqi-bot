const API_BASE =
  process.env.NEXT_PUBLIC_LOQI_API_BASE_URL || "http://127.0.0.1:10000";

export interface Plan {
  id: string;
  code: string;
  name: string;
  description: string;
  price: number;
  display_price: string;
  billing_interval: "monthly" | "yearly";
}

export async function getPlans(): Promise<{ plans: Plan[] }> {
  const res = await fetch(`${API_BASE}/api/v1/billing/plans`);
  if (!res.ok) throw new Error("Failed to fetch plans");
  return res.json();
}

export async function createCheckoutSession(
  organization_id: string,
  plan_id: string,
  email: string,
  success_url: string,
  cancel_url: string,
): Promise<{ url: string }> {
  const res = await fetch(`${API_BASE}/api/v1/billing/checkout`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ organization_id, plan_id, email, success_url, cancel_url }),
  });
  if (!res.ok) throw new Error("Failed to create checkout session");
  return res.json();
}
