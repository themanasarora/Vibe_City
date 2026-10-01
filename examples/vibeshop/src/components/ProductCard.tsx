import type { Product } from "@/lib/types";
import { formatPrice } from "@/lib/format";
import AddToCartButton from "./AddToCartButton";

export default function ProductCard({ product }: { product: Product }) {
  return (
    <div className="rounded-xl border p-4">
      <img src={product.image} alt={product.name} />
      <h3>{product.name}</h3>
      <p>{formatPrice(product.priceCents)}</p>
      <AddToCartButton productId={product.id} />
    </div>
  );
}
