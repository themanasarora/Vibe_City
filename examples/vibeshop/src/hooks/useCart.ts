"use client";
import { useEffect, useState } from "react";
import type { CartItem } from "@/lib/types";

export function useCart() {
  const [items, setItems] = useState<CartItem[]>([]);

  async function refresh() {
    const res = await fetch("/api/cart");
    setItems(await res.json());
  }

  async function addItem(productId: string) {
    await fetch("/api/cart", { method: "POST", body: JSON.stringify({ productId }) });
    await refresh();
  }

  async function removeItem(productId: string) {
    await fetch(`/api/cart?productId=${productId}`, { method: "DELETE" });
    await refresh();
  }

  useEffect(() => {
    refresh();
  }, []);

  return { items, addItem, removeItem, count: items.reduce((n, i) => n + i.qty, 0) };
}
