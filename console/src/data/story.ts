// The guided walkthrough (beginner-first redesign). Each step is a full,
// deterministic description of what the board shows: going Back always lands on
// exactly the same picture. Steps drive state through useConsole.setStoryStep.

export interface StoryStep {
  title: string;
  body: string;
  /** belief to select (lights its thread on the board) */
  select?: string;
  /** hours back for the time rewind, negative; defaults to 0 (now) */
  aost?: number;
  /** at this step the bad fact has already been taken back */
  recanted?: boolean;
  /** show the big "Take it back" button on this step */
  cta?: boolean;
}

export const POISONED_SOURCE = "src_forum";

export const STORY: StoryStep[] = [
  {
    title: "Meet your bots",
    body:
      "Three AI bots work together and share what they learn. Every card on this board is one memory a bot has saved. An arrow means one memory was built from another. Memories marked Healthy are fine.",
  },
  {
    title: "A bad fact gets in",
    select: "bel_forum_claim",
    body:
      "The Research bot reads a random forum post claiming refunds last 365 days. The real policy is 30 days. The bot saves the bad fact anyway. It's marked Looks wrong because it came from a place Recant doesn't trust.",
  },
  {
    title: "It spreads, with no paper trail",
    select: "bel_ops_action",
    body:
      "The Support bot repeats the bad fact in its own words, and the Ops bot lines up a bogus 365-day refund. Neither memory links back to the forum post. The dotted arrows are Recant matching them by meaning instead.",
  },
  {
    title: "Take it back in one click",
    select: "bel_forum_claim",
    cta: true,
    body:
      "This is the point of Recant. One click finds every memory that grew from the forum post, even the reworded copies, and blocks them all at once, across every bot. Press the button to watch it happen.",
  },
  {
    title: "Disaster averted",
    select: "bel_ops_action",
    recanted: true,
    body:
      "All three bad memories are now Blocked, and the Ops bot's refund was stopped just before the money left. The Live activity strip below shows the receipt.",
  },
  {
    title: "Rewind time to prove it",
    aost: -2,
    recanted: true,
    body:
      "Recant keeps a tamper-proof history. This is the board 2 hours ago. Back then the bad memories were only flagged, not blocked yet. Drag the Rewind time slider to scrub through time, like security-camera footage for AI memory. Nothing can be quietly edited or hidden.",
  },
  {
    title: "That's Recant",
    recanted: true,
    body:
      "A bad fact got in, spread with no paper trail, and was taken back everywhere, with proof. Switch to Explore and click any memory card to see where it came from and where it spread.",
  },
];
