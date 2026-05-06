import { Badge } from '@/components/ui/badge'

type Mode = 'paper' | 'real'

interface ModeBadgeProps {
  mode: Mode
  className?: string
}

const MODE_CLASS: Record<Mode, string> = {
  paper: 'bg-[#185FA5]/15 text-[#185FA5] border-[#185FA5]/40',
  real: 'bg-red-900/40 text-red-400 border-red-700/40',
}

export function ModeBadge({ mode, className }: ModeBadgeProps) {
  return (
    <Badge
      variant="outline"
      className={`tracking-widest uppercase font-bold ${MODE_CLASS[mode]} ${className ?? ''}`}
    >
      {mode}
    </Badge>
  )
}
