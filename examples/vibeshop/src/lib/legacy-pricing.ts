// Old discount logic from v0 — replaced by Stripe coupons.
// TODO: delete this once we're sure nothing uses it
export function applyDiscount(cents: number, percent: number) {
  return Math.round(cents * (1 - percent / 100));
}

export function bulkPrice(cents: number, qty: number) {
  return qty >= 10 ? applyDiscount(cents, 15) * qty : cents * qty;
}
