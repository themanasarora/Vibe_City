import { Resend } from "resend";
import { formatPrice } from "./format";
import type { Order } from "./types";

const resend = new Resend(process.env.RESEND_API_KEY);

export async function sendReceipt(order: Order) {
  await resend.emails.send({
    from: "VibeShop <shop@vibeshop.dev>",
    to: order.email,
    subject: `Your receipt — ${formatPrice(order.totalCents)}`,
    html: `<p>Thanks! We received ${formatPrice(order.totalCents)}.</p>`,
  });
}
