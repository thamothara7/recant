// Live mode is opt-in via build-time env. With no env set (the Vercel judge
// URL), the console runs entirely on deterministic fixtures, so the demo needs
// no backend. Point VITE_FORENSICS_URL at a running forensics service to drive
// the Explore board from live seed data, and VITE_QUARANTINE_URL at the
// quarantine service to make the recant action hit the real transaction.
//
// Story mode stays scripted regardless (it is the recorded video and must be
// reproducible frame for frame). If forensics is live but quarantine is not,
// reads are live and the recant action falls back to the local simulation.

const forensics = import.meta.env.VITE_FORENSICS_URL?.replace(/\/$/, "");
const quarantine = import.meta.env.VITE_QUARANTINE_URL?.replace(/\/$/, "");

export const CONFIG = {
  /** Explore reads come from the live board when forensics is configured. */
  live: Boolean(forensics),
  forensicsUrl: forensics ?? "",
  /** The recant action posts here only when it is set; else it simulates. */
  quarantineUrl: quarantine ?? "",
  liveRecant: Boolean(forensics && quarantine),
};
