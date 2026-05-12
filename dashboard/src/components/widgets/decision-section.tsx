'use client'

import { Badge } from '@/components/ui/badge'
import { Skeleton } from '@/components/ui/skeleton'
import { SectionTitle } from '@/components/ui/section-title'
import { type Decision } from '@/hooks/use-pipeline'

// ── Outcome badge color mapping ───────────────────────────────────────────────

function outcomeBadge(outcome: Decision['outcome']): {
  className: string
  variant: 'destructive' | 'outline'
} {
  switch (outcome) {
    case 'APPROVED':
      return {
        className: 'bg-green-500/15 text-green-400 border-green-500/30',
        variant: 'outline',
      }
    case 'APPROVED_WITH_CONDITIONS':
      return {
        className: 'bg-blue-500/15 text-blue-400 border-blue-500/30',
        variant: 'outline',
      }
    case 'REJECTED':
      return { className: '', variant: 'destructive' }
    case 'BLOCKED':
      return {
        className: 'bg-orange-500/15 text-orange-400 border-orange-500/30',
        variant: 'outline',
      }
    case 'DEFERRED':
      return {
        className: 'bg-white/10 text-white/60 border-white/20',
        variant: 'outline',
      }
  }
}

// ── Agent list (consensus state) ──────────────────────────────────────────────

function AgentList({ label, agents }: { label: string; agents: string[] }) {
  if (agents.length === 0) return null
  return (
    <div className="text-xs">
      <span className="text-white/40 uppercase tracking-wide">{label}:</span>{' '}
      <span className="text-white/80 font-mono">{agents.join(', ')}</span>
    </div>
  )
}

// ── Main component ────────────────────────────────────────────────────────────

interface DecisionSectionProps {
  decision: Decision | null
}

export function DecisionSection({ decision }: DecisionSectionProps) {
  if (decision === null) {
    return (
      <div>
        <SectionTitle>Decision</SectionTitle>
        <Skeleton className="h-20 w-full" />
        <p className="mt-2 text-xs text-white/40 italic">
          Awaiting consensus decision...
        </p>
      </div>
    )
  }

  const { className: outcomeClass, variant: outcomeVariant } = outcomeBadge(decision.outcome)

  return (
    <div>
      <SectionTitle>Decision</SectionTitle>
      <div className="border border-white/10 rounded-md p-3 space-y-2 bg-white/[0.02]">

        {/* Outcome + consensus_type + contrarian flag */}
        <div className="flex items-center gap-2 flex-wrap">
          <Badge className={outcomeClass} variant={outcomeVariant}>
            {decision.outcome}
          </Badge>
          <span className="text-xs font-mono text-white/50">
            {decision.consensus_state.consensus_type}
          </span>
          {decision.contrarian_flag_raised && (
            <Badge
              className="bg-amber-500/15 text-amber-400 border-amber-500/30"
              variant="outline"
            >
              CONTRARIAN
            </Badge>
          )}
        </div>

        {/* Consensus state agent lists */}
        <div className="space-y-0.5">
          <AgentList label="Agree" agents={decision.consensus_state.agree} />
          <AgentList label="Disagree" agents={decision.consensus_state.disagree} />
          <AgentList label="Neutral" agents={decision.consensus_state.neutral} />
        </div>

        {/* Size modulation */}
        {decision.size_modulation !== null && (
          <div className="text-xs text-white/70">
            <span className="text-white/40 uppercase tracking-wide">Size reduced:</span>{' '}
            <span className="font-mono">
              {decision.size_modulation.original_size_pct}% → {decision.size_modulation.approved_size_pct}%
            </span>
            <div className="text-white/50 mt-0.5">
              Reason: {decision.size_modulation.reduction_reason}
            </div>
          </div>
        )}

        {/* Conditions */}
        {decision.conditions.length > 0 && (
          <div>
            <span className="text-xs text-white/40 uppercase tracking-wide">Conditions</span>
            <ul className="mt-1 list-disc list-inside space-y-0.5 text-xs text-white/80">
              {decision.conditions.map((c, i) => (
                <li key={i}>{c}</li>
              ))}
            </ul>
          </div>
        )}

      </div>
    </div>
  )
}
