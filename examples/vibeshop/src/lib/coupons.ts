import { getCart } from "./cart";
export function couponFor(id: string) {
  return getCart(id).then((items) => items.length > 3 ? "BULK10" : null;
}
