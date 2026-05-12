import { Badge } from '@/components/ui/badge'

interface StatusBadgeProps {
  status: string
}

interface BadgeStyle {
  className: string
  variant: 'destructive' | 'outline'
}

/**
 * Maps trades.proposals.status (free VARCHAR per the SQL schema comment) to
 * badge styling. The 5 expected statuses for Sprint 4 are pending →
 * under_critique → decided → atlas_validated, plus rejected as a terminal
 * failure path. 'expired' is in the schema comment but rare. Anything else
 * falls through to a neutral gray with the raw status string visible — a
 * deliberately visible signal that the backend produced an unexpected value.
 */
function statusStyle(status: string): BadgeStyle {
  switch (status) {
    case 'pending':
      return { className: 'bg-white/10 text-white/60 border-white/20', variant: 'outline' }
    case 'under_critique':
      return { className: 'bg-yellow-500/15 text-yellow-400 border-yellow-500/30', variant: 'outline' }
    case 'decided':
      return { className: 'bg-blue-500/15 text-blue-400 border-blue-500/30', variant: 'outline' }
    case 'atlas_validated':
      return { className: 'bg-green-500/15 text-green-400 border-green-500/30', variant: 'outline' }
    case 'rejected':
      return { className: '', variant: 'destructive' }
    case 'expired':
      return { className: 'bg-orange-500/15 text-orange-400 border-orange-500/30', variant: 'outline' }
    default:
      return { className: 'bg-white/10 text-white/60 border-white/20', variant: 'outline' }
  }
}

function statusLabel(status: string): string {
  // "under_critique" → "under critique"; CSS uppercase finishes the transform.
  return status.replace(/_/g, ' ')
}

export function StatusBadge({ status }: StatusBadgeProps) {
  const { className, variant } = statusStyle(status)
  return (
    <Badge className={`uppercase tracking-wide ${className}`} variant={variant}>
      {statusLabel(status)}
    </Badge>
  )
}
