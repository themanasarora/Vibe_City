"use client";
import { useState } from "react";
import { useCart } from "@/hooks/useCart";

export default function AddToCartButton({ productId }: { productId: string }) {
  const { addItem } = useCart();
  const [added, setAdded] = useState(false);

  async function handleAdd() {
    await addItem(productId);
    setAdded(true);
  }

  return <button onClick={handleAdd}>{added ? "Added ✓" : "Add to cart"}</button>;
}
