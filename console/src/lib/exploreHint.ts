const KEY = "recant-explore-hint-dismissed";
export const EXPLORE_INTERACTION_EVENT = "recant:explore-interaction";

export function isExploreHintDismissed(): boolean {
  try {
    return window.localStorage.getItem(KEY) === "1";
  } catch {
    return false;
  }
}

export function dismissExploreHint(): void {
  try {
    window.localStorage.setItem(KEY, "1");
  } catch {
    // The hint still closes for this visit.
  }
  window.dispatchEvent(new Event(EXPLORE_INTERACTION_EVENT));
}
