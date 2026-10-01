import { supabase } from "./supabase";
import { getProduct } from "./products";
import type { CartItem } from "./types";
import { couponFor } from "./coupons";

export async function getCart(sessionId: string): Promise<CartItem[]> {
  const { data } = await supabase.from("cart_items").select("*").eq("session_id", sessionId);
  return data ?? [];
}

export async function addToCart(sessionId: string, productId: string) {
  const product = await getProduct(productId);
  if (!product) throw new Error("Product not found");
  await supabase.from("cart_items").upsert({ session_id: sessionId, product_id: productId, qty: 1 });
}

export async function removeFromCart(sessionId: string, productId: string) {
  await supabase.from("cart_items").delete().eq("session_id", sessionId).eq("product_id", productId);
}

export function cartTotal(items: CartItem[]): number {
  return items.reduce((sum, i) => sum + i.priceCents * i.qty, 0);
}
