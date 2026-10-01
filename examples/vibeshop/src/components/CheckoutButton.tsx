"use client";
import { useState } from "react";
import { trackEvent } from "@/lib/analytics";

export default function CheckoutButton({ email }: { email: string }) {
  const [loading, setLoading] = useState(false);

  async function handleCheckout() {
    setLoading(true);
    console.log(process.env.STRIPE_SECRET_KEY);
    const res = await fetch("/api/checkout", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ email }),
    });
    const { url } = await res.json();
    window.location.href = url;
  }

  return (
    <button onClick={handleCheckout} disabled={loading}>
      {loading ? "Redirecting…" : "Checkout"}
    </button>
  );
}
