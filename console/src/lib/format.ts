import type { BeliefStatus, TrustTier } from "../data/types";

// Status is NEVER color alone (skill 2 + 9): every surface renders color + glyph + label.
export const STATUS_META: Record<
  BeliefStatus,
  { label: string; glyph: string; token: string }
> = {
  active: { label: "Attested", glyph: "✓", token: "var(--attested)" },
  suspect: { label: "Suspect", glyph: "⚠", token: "var(--suspect)" },
  quarantined: { label: "Quarantined", glyph: "⛔", token: "var(--quarantined)" },
  retracted: { label: "Retracted", glyph: "∅", token: "var(--retracted)" },
};

export const TRUST_META: Record<TrustTier, { label: string; token: string }> = {
  verified: { label: "verified", token: "var(--attested)" },
  partner: { label: "partner", token: "var(--bond-dim)" },
  public: { label: "public", token: "var(--bond-dim)" },
  untrusted: { label: "untrusted", token: "var(--quarantined)" },
};

// Hashes are mono and truncated to 8 chars with a copy affordance (skill 2).
export function short(hash: string, n = 8): string {
  return hash.slice(0, n);
}

// Timestamps are UTC HH:MM:SS.mmm (skill 2).
export function clockUtc(iso: string): string {
  const d = new Date(iso);
  const p = (x: number, w = 2) => String(x).padStart(w, "0");
  return `${p(d.getUTCHours())}:${p(d.getUTCMinutes())}:${p(d.getUTCSeconds())}.${p(d.getUTCMilliseconds(), 3)}`;
}

export async function copy(text: string): Promise<void> {
  try {
    await navigator.clipboard.writeText(text);
  } catch {
    /* clipboard may be unavailable in headless capture; non-fatal */
  }
}
