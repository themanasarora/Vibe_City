import { getProducts } from "@/lib/products";
import ProductGrid from "@/components/ProductGrid";

export default async function HomePage() {
  const products = await getProducts();
  return (
    <section>
      <h1>Fresh drops</h1>
      <ProductGrid products={products} />
    </section>
  );
}
