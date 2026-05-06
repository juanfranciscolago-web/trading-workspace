import { Badge } from '@/components/ui/badge'

type RiskLevel = 'GREEN' | 'YELLOW' | 'RED' | 'BLACK'

interface RiskBadgeProps {
  level: RiskLevel
  className?: string
}

const RISK_CLASS: Record<RiskLevel, string> = {
  GREEN: 'bg-green-500/15 text-green-400 border-green-500/40',
  YELLOW: 'bg-amber-500/15 text-amber-400 border-amber-500/40',
  RED: 'bg-red-500/15 text-red-400 border-red-500/40',
  BLACK: 'bg-white/5 text-white/40 border-white/20',
}

export function RiskBadge({ level, className }: RiskBadgeProps) {
  return (
    <Badge
      variant="outline"
      className={`tracking-widest uppercase font-bold ${RISK_CLASS[level]} ${className ?? ''}`}
    >
      {level}
    </Badge>
  )
}
