"use client";
import type { CartItem } from "@/lib/types";
import { formatPrice } from "@/lib/format";

export default function CartItemRow({ item, onRemove }: { item: CartItem; onRemove: (id: string) => void }) {
  return (
    <li className="flex justify-between">
      <span>{item.name} × {item.qty}</span>
      <span>{formatPrice(item.priceCents * item.qty)}</span>
      <button onClick={() => onRemove(item.productId)}>Remove</button>
    </li>
  );
}
