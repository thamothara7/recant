// The guided walkthrough (beginner-first redesign). Each step is a full,
// deterministic description of what the board shows: going Back always lands on
// exactly the same picture. Steps drive state through useConsole.setStoryStep.
//
// Consolidated from 7 to 5 steps so judges reach the payoff faster.

export interface StoryStep {
  title: string;
  body: string;
  /** Optional one-line scenario context shown above the title on the first step. */
  scenario?: string;
  /** Keep the walkthrough focused so every card is readable in a 1280x720 recording. */
  visible: string[];
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
    title: "Three bots, one bad fact",
    scenario: "A customer-support system where 3 AI bots share memory",
    select: "bel_forum_claim",
    visible: ["bel_policy_window", "bel_handbook_flow", "bel_ops_status", "bel_forum_claim"],
    body:
      "Three AI bots work together and share what they learn. Each card is one memory a bot has saved. The Research bot just read a random forum post claiming refunds last 365 days. The real policy is 30 days. It is marked Looks wrong because it came from a place Recant does not trust.",
  },
  {
    title: "It spreads, with no paper trail",
    select: "bel_ops_action",
    visible: ["bel_policy_window", "bel_forum_claim", "bel_support_paraphrase", "bel_ops_action"],
    body:
      "The Support bot repeats the bad fact in its own words, and the Ops bot lines up a bogus 365-day refund for customer #4471. Neither memory links back to the forum post. The dotted arrows are Recant matching them by meaning instead.",
  },
  {
    title: "Take it back, everywhere, at once",
    select: "bel_forum_claim",
    cta: true,
    visible: ["bel_policy_window", "bel_forum_claim", "bel_support_paraphrase", "bel_ops_action"],
    body:
      "This is the point of Recant. One click finds every memory that grew from the forum post, even the reworded copies, and blocks them all at once across every bot in a single database transaction. Press the button to watch it happen.",
  },
  {
    title: "Disaster averted, with proof",
    select: "bel_ops_action",
    recanted: true,
    aost: -2,
    visible: ["bel_policy_window", "bel_forum_claim", "bel_support_paraphrase", "bel_ops_action"],
    body:
      "All three bad memories are now Blocked, and the Ops bot's $4,471 refund was stopped before the money left. Drag the Rewind time slider to see what the board looked like 2 hours ago: back then the bad memories were only flagged, not blocked yet. Nothing can be quietly edited or hidden.",
  },
  {
    title: "That's Recant",
    recanted: true,
    visible: ["bel_policy_window", "bel_forum_claim", "bel_support_paraphrase", "bel_ops_action"],
    body:
      "A bad fact got in, spread with no paper trail, and was taken back everywhere, with proof. Switch to Explore to click any memory card and trace exactly where it came from and where it spread.",
  },
];
