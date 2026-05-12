'use client'

import { Badge } from '@/components/ui/badge'
import { Skeleton } from '@/components/ui/skeleton'
import { SectionTitle } from '@/components/ui/section-title'
import { type AtlasValidation } from '@/hooks/use-pipeline'

// ── Risk mode badge color mapping ─────────────────────────────────────────────

function riskModeBadgeClass(mode: AtlasValidation['risk_mode']): string {
  switch (mode) {
    case 'GREEN':
      return 'bg-green-500/15 text-green-400 border-green-500/30'
    case 'YELLOW':
      return 'bg-yellow-500/15 text-yellow-400 border-yellow-500/30'
    case 'RED':
      return 'bg-red-500/15 text-red-400 border-red-500/30'
    case 'BLACK':
      return 'bg-red-700/30 text-red-200 border-red-700/50'
  }
}

// ── Approval badge ────────────────────────────────────────────────────────────

function approvalBadge(approved: boolean): {
  label: string
  className: string
  variant: 'destructive' | 'outline'
} {
  if (approved) {
    return {
      label: 'APPROVED',
      className: 'bg-green-500/15 text-green-400 border-green-500/30',
      variant: 'outline',
    }
  }
  return { label: 'BLOCKED', className: '', variant: 'destructive' }
}

// ── Size display helper ───────────────────────────────────────────────────────

function SizeDisplay({ executed, original }: { executed: string; original: string }) {
  // Pydantic Decimal serializes as string via mode='json'.
  // Parse to Number for comparison; show original as-is to preserve precision.
  const ex = Number(executed)
  const or = Number(original)
  if (!isFinite(ex) || !isFinite(or)) {
    return <span className="font-mono">{executed}% / {original}%</span>
  }
  if (ex === or) {
    return <span className="font-mono">{executed}% (full size)</span>
  }
  return (
    <span className="font-mono">
      {original}% → {executed}% <span className="text-white/40">(reduced)</span>
    </span>
  )
}

// ── Main component ────────────────────────────────────────────────────────────

interface AtlasValidationSectionProps {
  validation: AtlasValidation | null
}

export function AtlasValidationSection({ validation }: AtlasValidationSectionProps) {
  if (validation === null) {
    return (
      <div>
        <SectionTitle>ATLAS Validation</SectionTitle>
        <Skeleton className="h-20 w-full" />
        <p className="mt-2 text-xs text-white/40 italic">
          Awaiting ATLAS validation...
        </p>
      </div>
    )
  }

  const approval = approvalBadge(validation.approved)
  const snapshotShort = validation.portfolio_snapshot_id.slice(-8)

  return (
    <div>
      <SectionTitle>ATLAS Validation</SectionTitle>
      <div className="border border-white/10 rounded-md p-3 space-y-2 bg-white/[0.02]">

        {/* Approval + risk_mode */}
        <div className="flex items-center gap-2 flex-wrap">
          <Badge className={approval.className} variant={approval.variant}>
            {approval.label}
          </Badge>
          <Badge
            className={riskModeBadgeClass(validation.risk_mode)}
            variant="outline"
          >
            RISK: {validation.risk_mode}
          </Badge>
        </div>

        {/* Size + reason */}
        <div className="space-y-1">
          <div className="text-xs">
            <span className="text-white/40 uppercase tracking-wide">Size:</span>{' '}
            <SizeDisplay executed={validation.executed_size} original={validation.original_size} />
          </div>
          <div className="text-xs text-white/70">
            <span className="text-white/40 uppercase tracking-wide">Reason:</span>{' '}
            <span className="font-mono">{validation.reason}</span>
          </div>
        </div>

        {/* Checks failed (prominent if any) */}
        {validation.checks_failed.length > 0 && (
          <div>
            <span className="text-xs text-red-400 uppercase tracking-wide">
              Checks failed ({validation.checks_failed.length})
            </span>
            <ul className="mt-1 space-y-0.5 text-xs font-mono text-red-300">
              {validation.checks_failed.map((c, i) => (
                <li key={i}>• {c}</li>
              ))}
            </ul>
          </div>
        )}

        {/* Checks passed (subtle) */}
        {validation.checks_passed.length > 0 && (
          <div>
            <span className="text-xs text-white/40 uppercase tracking-wide">
              Checks passed ({validation.checks_passed.length})
            </span>
            <ul className="mt-1 space-y-0.5 text-xs font-mono text-white/50">
              {validation.checks_passed.map((c, i) => (
                <li key={i}>• {c}</li>
              ))}
            </ul>
          </div>
        )}

        {/* Metadata footer */}
        <div className="flex justify-between text-xs text-white/40 pt-1 border-t border-white/5">
          <span>Snapshot: <span className="font-mono">…{snapshotShort}</span></span>
          <span>Eval: <span className="font-mono">{validation.evaluation_time_ms.toFixed(1)}ms</span></span>
        </div>

      </div>
    </div>
  )
}
