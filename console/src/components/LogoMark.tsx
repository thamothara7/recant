// The product mark: an R monogram whose leg is the custody thread, ending in
// a memory bead it has caught. One letterform, one idea (the thread holds the
// memory), no effects. M3-disciplined: primary tile, on-primary glyph.
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
        {/* stem and bowl of the R */}
        <path
          d="M 8.2 19.2 V 5.2 H 12.9 A 4.1 4.1 0 0 1 12.9 13.4 H 8.2"
          stroke="currentColor"
          strokeWidth="2.5"
          strokeLinecap="round"
          strokeLinejoin="round"
        />
        {/* the leg is the custody thread... */}
        <path
          d="M 11.9 13.4 L 15.1 17.4"
          stroke="currentColor"
          strokeWidth="2.5"
          strokeLinecap="round"
        />
        {/* ...ending in the memory bead it caught */}
        <circle cx="16.6" cy="19.2" r="1.9" fill="currentColor" />
      </svg>
    </div>
  );
}
