import type { BeliefStatus, TrustTier } from "../data/types";

// Status is NEVER color alone: every surface renders icon + label + color.
// Colors are M3 roles; icons are Material Symbols names. `container` and
// `onContainer` style tonal chips; `color` is for icons/text on plain surfaces.
// Labels are plain English; the enum values still mirror the database schema
// so the fixture layer swaps cleanly for the real API.
export const STATUS_META: Record<
  BeliefStatus,
  { label: string; icon: string; color: string; container: string; onContainer: string }
> = {
  active: {
    label: "Healthy",
    icon: "check_circle",
    color: "var(--md-success)",
    container: "var(--md-success-container)",
    onContainer: "var(--md-on-success-container)",
  },
  suspect: {
    label: "Looks wrong",
    icon: "warning",
    color: "var(--md-warning)",
    container: "var(--md-warning-container)",
    onContainer: "var(--md-on-warning-container)",
  },
  quarantined: {
    label: "Blocked",
    icon: "block",
    color: "var(--md-error)",
    container: "var(--md-error-container)",
    onContainer: "var(--md-on-error-container)",
  },
  retracted: {
    label: "Withdrawn",
    icon: "do_not_disturb_on",
    color: "var(--md-outline)",
    container: "var(--md-surface-container-highest)",
    onContainer: "var(--md-on-surface-variant)",
  },
};

// One-sentence explanation per status, shown in the details panel.
export const STATUS_EXPLAIN: Record<BeliefStatus, string> = {
  active: "Nothing suspicious about this memory.",
  suspect: "This memory traces back to an untrusted place. It hasn't been blocked yet.",
  quarantined: "This memory was taken back. Bots can no longer act on it.",
  retracted: "The bot that wrote this memory withdrew it.",
};

export const TRUST_META: Record<TrustTier, { label: string; color: string }> = {
  verified: { label: "trusted", color: "var(--md-success)" },
  partner: { label: "partner", color: "var(--md-on-surface-variant)" },
  public: { label: "public", color: "var(--md-on-surface-variant)" },
  untrusted: { label: "not trusted", color: "var(--md-error)" },
};

// Hashes are mono and truncated to 8 chars with a copy affordance.
export function short(hash: string, n = 8): string {
  return hash.slice(0, n);
}

// Timestamps are UTC HH:MM:SS.mmm, always mono.
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
