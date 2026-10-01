"use client";
import { useCart } from "@/hooks/useCart";
import { formatPrice } from "@/lib/format";
import CartItemRow from "@/components/CartItemRow";
import CheckoutButton from "@/components/CheckoutButton";

export default function CartPage() {
  const { items, removeItem } = useCart();
  const total = items.reduce((sum, i) => sum + i.priceCents * i.qty, 0);

  return (
    <section>
      <h1>Your cart</h1>
      <ul>
        {items.map((item) => (
          <CartItemRow key={item.productId} item={item} onRemove={removeItem} />
        ))}
      </ul>
      <p>Total: {formatPrice(total)}</p>
      <CheckoutButton email="guest@vibeshop.dev" />
    </section>
  );
}
