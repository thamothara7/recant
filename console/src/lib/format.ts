import type { BeliefStatus, TrustTier } from "../data/types";

// Status is NEVER color alone (skill 2 + 9): every surface renders color + glyph + label.
// Labels are plain English (beginner-first redesign); the enum values still mirror
// the database schema so the fixture layer swaps cleanly for the real API.
export const STATUS_META: Record<
  BeliefStatus,
  { label: string; glyph: string; token: string }
> = {
  active: { label: "Healthy", glyph: "✓", token: "var(--attested)" },
  suspect: { label: "Looks wrong", glyph: "⚠", token: "var(--suspect)" },
  quarantined: { label: "Blocked", glyph: "⛔", token: "var(--quarantined)" },
  retracted: { label: "Withdrawn", glyph: "∅", token: "var(--retracted)" },
};

// One-sentence explanation per status, shown in the details panel.
export const STATUS_EXPLAIN: Record<BeliefStatus, string> = {
  active: "Nothing suspicious about this memory.",
  suspect: "This memory traces back to an untrusted place. It hasn't been blocked yet.",
  quarantined: "This memory was taken back. Bots can no longer act on it.",
  retracted: "The bot that wrote this memory withdrew it.",
};

export const TRUST_META: Record<TrustTier, { label: string; token: string }> = {
  verified: { label: "trusted", token: "var(--attested)" },
  partner: { label: "partner", token: "var(--bond-dim)" },
  public: { label: "public", token: "var(--bond-dim)" },
  untrusted: { label: "not trusted", token: "var(--quarantined)" },
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
