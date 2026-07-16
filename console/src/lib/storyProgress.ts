// Remember that this browser finished the walkthrough, so return visits open
// straight into Explore instead of replaying "Meet your bots". localStorage,
// not cookies: the console is a static site with no server to read a cookie,
// and the flag has no business riding along on network requests.
// Guarded: storage can throw in private browsing; the story simply replays.
const KEY = "recant.storyDone";

export function isStoryDone(): boolean {
  try {
    return window.localStorage.getItem(KEY) === "1";
  } catch {
    return false;
  }
}

export function markStoryDone(): void {
  try {
    window.localStorage.setItem(KEY, "1");
  } catch {
    // Nothing to do: the walkthrough will show again next visit.
  }
}
