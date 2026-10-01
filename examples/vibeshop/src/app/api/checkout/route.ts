import { NextRequest, NextResponse } from "next/server";
import { getCart } from "@/lib/cart";
import { createOrder } from "@/lib/orders";
import { createCheckoutSession } from "@/lib/stripe";

export async function POST(req: NextRequest) {
  const { email } = await req.json();
  const items = await getCart(req.cookies.get("sid")?.value ?? "guest");
  if (items.length === 0) return NextResponse.json({ error: "Cart is empty" }, { status: 400 });

  const order = await createOrder(email, items);
  const session = await createCheckoutSession(order.id, items);
  return NextResponse.json({ url: session.url });
}
