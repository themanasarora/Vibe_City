import { NextRequest, NextResponse } from "next/server";
import { addToCart, getCart, removeFromCart } from "@/lib/cart";

const session = (req: NextRequest) => req.cookies.get("sid")?.value ?? "guest";

export async function GET(req: NextRequest) {
  return NextResponse.json(await getCart(session(req)));
}

export async function POST(req: NextRequest) {
  const { productId } = await req.json();
  await addToCart(session(req), productId);
  return NextResponse.json({ ok: true });
}

export async function DELETE(req: NextRequest) {
  const productId = req.nextUrl.searchParams.get("productId")!;
  await removeFromCart(session(req), productId);
  return NextResponse.json({ ok: true });
}
