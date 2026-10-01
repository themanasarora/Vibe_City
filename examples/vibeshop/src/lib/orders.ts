import { supabase } from "./supabase";
import type { CartItem, Order } from "./types";
import { cartTotal } from "./cart";

export async function createOrder(email: string, items: CartItem[]): Promise<Order> {
  const { data, error } = await supabase
    .from("orders")
    .insert({ email, total_cents: cartTotal(items), status: "pending" })
    .select()
    .single();
  if (error) throw error;
  return data;
}

export async function markPaid(orderId: string) {
  await supabase.from("orders").update({ status: "paid" }).eq("id", orderId);
}

export async function getOrders(email: string): Promise<Order[]> {
  const { data } = await supabase.from("orders").select("*").eq("email", email);
  return data ?? [];
}
