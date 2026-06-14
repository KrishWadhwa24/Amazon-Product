"use client";

import type { CartItem } from "@/lib/catalog";

export const CLAIMED_DEAL_DISCOUNT = 100;
export const LOCAL_ORDER_EVENT = "amazon-edge-local-order";

export interface PlacedOrderItem {
  id: number;
  asin: string;
  name: string;
  price: number;
  image_url: string;
  uploaded_image_path: string | null;
  is_claimed_deal: boolean;
}

export interface PlacedOrder {
  id: string;
  placed_at: string;
  address: string;
  payment_method: string;
  subtotal: number;
  discount: number;
  total: number;
  items: PlacedOrderItem[];
}

function claimedDealsKey(userId: number): string {
  return `amazon-edge:claimed-deals:${userId}`;
}

function placedOrdersKey(userId: number): string {
  return `amazon-edge:placed-orders:${userId}`;
}

function readJson<T>(key: string, fallback: T): T {
  if (typeof window === "undefined") return fallback;
  try {
    const raw = window.localStorage.getItem(key);
    return raw ? (JSON.parse(raw) as T) : fallback;
  } catch {
    return fallback;
  }
}

function writeJson<T>(key: string, value: T): void {
  if (typeof window === "undefined") return;
  window.localStorage.setItem(key, JSON.stringify(value));
  window.dispatchEvent(new Event(LOCAL_ORDER_EVENT));
}

export function getClaimedDealAsins(userId: number): Set<string> {
  return new Set(readJson<string[]>(claimedDealsKey(userId), []));
}

export function claimLocalDeal(userId: number, asin: string): void {
  const asins = getClaimedDealAsins(userId);
  asins.add(asin);
  writeJson(claimedDealsKey(userId), Array.from(asins));
}

export function isClaimedDeal(userId: number, asin: string): boolean {
  return getClaimedDealAsins(userId).has(asin);
}

export function countClaimedDealsInCart(
  userId: number,
  items: CartItem[],
): number {
  const claimed = getClaimedDealAsins(userId);
  const counted = new Set<string>();
  for (const item of items) {
    const asin = item.product.asin;
    if (claimed.has(asin)) counted.add(asin);
  }
  return counted.size;
}

export function getPlacedOrders(userId: number): PlacedOrder[] {
  return readJson<PlacedOrder[]>(placedOrdersKey(userId), []);
}

export function savePlacedOrder(userId: number, order: PlacedOrder): void {
  writeJson(placedOrdersKey(userId), [order, ...getPlacedOrders(userId)]);
}
