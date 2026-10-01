import Link from "next/link";
import CartBadge from "./CartBadge";

export default function Navbar() {
  return (
    <nav className="flex justify-between p-4">
      <Link href="/">VibeShop</Link>
      <div className="flex gap-4">
        <Link href="/orders">Orders</Link>
        <CartBadge />
      </div>
    </nav>
  );
}
