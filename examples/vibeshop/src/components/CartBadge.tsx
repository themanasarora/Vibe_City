"use client";
import Link from "next/link";
import { useCart } from "@/hooks/useCart";

export default function CartBadge() {
  const { count } = useCart();
  return <Link href="/cart">Cart ({count})</Link>;
}
