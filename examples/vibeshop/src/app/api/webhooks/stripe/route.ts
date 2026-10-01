import { NextRequest, NextResponse } from "next/server";
import { stripe } from "@/lib/stripe";
import { markPaid, getOrders } from "@/lib/orders";
import { sendReceipt } from "@/lib/email";

export async function POST(req: NextRequest) {
  const sig = req.headers.get("stripe-signature")!;
  const event = stripe.webhooks.constructEvent(await req.text(), sig, process.env.STRIPE_WEBHOOK_SECRET!);

  if (event.type === "checkout.session.completed") {
    const orderId = event.data.object.metadata!.orderId;
    await markPaid(orderId);
    const [order] = await getOrders(event.data.object.customer_email!);
    if (order) await sendReceipt(order);
  }
  return NextResponse.json({ received: true });
}
