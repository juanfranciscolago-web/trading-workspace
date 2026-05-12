'use client'

import { Badge } from '@/components/ui/badge'
import { Skeleton } from '@/components/ui/skeleton'
import { SectionTitle } from '@/components/ui/section-title'
import { type Critique } from '@/hooks/use-pipeline'

// ── Stance badge color mapping ────────────────────────────────────────────────

function stanceBadgeClass(stance: Critique['stance']): string {
  switch (stance) {
    case 'AGREE':
      return 'bg-green-500/15 text-green-400 border-green-500/30'
    case 'AGREE_WITH_CONDITIONS':
      return 'bg-blue-500/15 text-blue-400 border-blue-500/30'
    case 'DISAGREE':
      return 'bg-orange-500/15 text-orange-400 border-orange-500/30'
    case 'NEUTRAL':
      return 'bg-white/10 text-white/60 border-white/20'
  }
}

// ── One critique entry ────────────────────────────────────────────────────────

function CritiqueItem({ critique }: { critique: Critique }) {
  return (
    <div className="border border-white/10 rounded-md p-3 space-y-2 bg-white/[0.02]">
      <div className="flex items-center gap-2 flex-wrap">
        <span className="text-xs font-mono uppercase text-white/60">
          {critique.agent_id}
        </span>
        <Badge className={stanceBadgeClass(critique.stance)} variant="outline">
          {critique.stance}
        </Badge>
        {critique.veto_request && (
          <Badge variant="destructive">VETO</Badge>
        )}
        {critique.contrarian_flag_raised && (
          <Badge
            className="bg-amber-500/15 text-amber-400 border-amber-500/30"
            variant="outline"
          >
            CONTRARIAN
          </Badge>
        )}
      </div>

      <p className="text-sm text-white/80">{critique.argument.summary}</p>

      {critique.argument.evidence.length > 0 && (
        <div>
          <span className="text-xs text-white/40 uppercase tracking-wide">Evidence</span>
          <ul className="mt-1 space-y-0.5 text-xs font-mono text-white/70">
            {critique.argument.evidence.map((ev, i) => (
              <li key={i}>
                <span className="text-white/50">{ev.data_source}:</span>{' '}
                {ev.claim} = <span className="text-white/90">{String(ev.value)}</span>
              </li>
            ))}
          </ul>
        </div>
      )}

      <div className="text-xs text-white/60">
        <span className="text-white/40">Concern:</span> {critique.argument.concern}
      </div>

      <div className="text-xs text-white/40">
        Would change my mind: {critique.argument.data_that_would_change_my_mind}
      </div>
    </div>
  )
}

// ── Main component ────────────────────────────────────────────────────────────

interface CritiqueSectionProps {
  critiques: Critique[]
}

export function CritiqueSection({ critiques }: CritiqueSectionProps) {
  if (critiques.length === 0) {
    return (
      <div>
        <SectionTitle>Critiques</SectionTitle>
        <Skeleton className="h-20 w-full" />
        <p className="mt-2 text-xs text-white/40 italic">
          Awaiting APOLLO critique...
        </p>
      </div>
    )
  }

  return (
    <div>
      <SectionTitle>
        Critiques <span className="text-white/30">({critiques.length})</span>
      </SectionTitle>
      <div className="space-y-3">
        {critiques.map((c) => (
          <CritiqueItem key={c.message_id} critique={c} />
        ))}
      </div>
    </div>
  )
}
