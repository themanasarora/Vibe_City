export type Product = { id: string; name: string; priceCents: number; image: string };
export type CartItem = { productId: string; name: string; priceCents: number; qty: number };
export type Order = { id: string; email: string; totalCents: number; status: "pending" | "paid"; createdAt: string };
