import { getOrders } from "@/lib/orders";
import { formatDate, formatPrice } from "@/lib/format";

export default async function OrdersPage() {
  // TODO: replace hard-coded guest email with the signed-in user
  const orders = await getOrders("guest@vibeshop.dev");
  return (
    <section>
      <h1>Orders</h1>
      {orders.map((o) => (
        <div key={o.id}>
          {formatDate(o.createdAt)} — {formatPrice(o.totalCents)} — {o.status}
        </div>
      ))}
    </section>
  );
}
