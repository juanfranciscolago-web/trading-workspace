/**
 * Section title primitive — the h3 used across detail widgets for
 * consistent typography (uppercase, tracking-widest, white/40 color).
 *
 * Pure presentational, no client-side requirement (no hooks, no state).
 */
export function SectionTitle({ children }: { children: React.ReactNode }) {
  return (
    <h3 className="text-xs font-semibold tracking-widest text-white/40 uppercase mb-2">
      {children}
    </h3>
  )
}
