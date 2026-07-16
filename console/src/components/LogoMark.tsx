// The product mark: a memory dot with a custody thread arcing back around it,
// the recant gesture (take the fact back) drawn as one stroke. Flat, geometric,
// M3-disciplined: primary tile, on-primary glyph, no gradients or effects.
// The favicon (public/favicon.svg) mirrors this geometry; keep them in sync.
export function LogoMark({ size = 32 }: { size?: number }) {
  return (
    <div
      aria-hidden
      className="grid shrink-0 place-items-center rounded-md3-sm bg-primary text-on-primary"
      style={{ width: size, height: size }}
    >
      <svg
        width={size * 0.62}
        height={size * 0.62}
        viewBox="0 0 24 24"
        fill="none"
      >
        {/* the belief: one memory */}
        <circle cx="12" cy="12" r="2.5" fill="currentColor" />
        {/* the thread pulling it back: 270deg arc, arrow rising into the gap */}
        <path
          d="M 12 5 A 7 7 0 1 0 19 12"
          stroke="currentColor"
          strokeWidth="2.4"
          strokeLinecap="round"
        />
        <path d="M 16.4 12.6 L 21.6 12.6 L 19 8.4 Z" fill="currentColor" />
      </svg>
    </div>
  );
}
