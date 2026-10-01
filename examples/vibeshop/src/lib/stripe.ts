import Stripe from "stripe";
import type { CartItem } from "./types";

export const stripe = new Stripe(process.env.STRIPE_SECRET_KEY!);

export async function createCheckoutSession(orderId: string, items: CartItem[]) {
  return stripe.checkout.sessions.create({
    mode: "payment",
    metadata: { orderId },
    line_items: items.map((i) => ({
      quantity: i.qty,
      price_data: { currency: "usd", unit_amount: i.priceCents, product_data: { name: i.name } },
    })),
    success_url: `${process.env.APP_URL}/orders?paid=1`,
    cancel_url: `${process.env.APP_URL}/cart`,
  });
}
