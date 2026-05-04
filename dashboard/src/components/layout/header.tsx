'use client'

interface HeaderProps {
  mode?: 'paper' | 'real'
  sysStatus?: 'ok' | 'error' | 'degraded'
  marketState?: 'open' | 'closed' | 'pre' | 'after'
  clockStr?: string
  updatedStr?: string
}

const SYS_DOT: Record<string, string> = {
  ok: 'bg-green-500',
  error: 'bg-red-500',
  degraded: 'bg-yellow-400',
}

const MARKET_LABEL: Record<string, string> = {
  open: 'MARKET OPEN',
  closed: 'MARKET CLOSED',
  pre: 'PRE-MARKET',
  after: 'AFTER-HOURS',
}

const MARKET_COLOR: Record<string, string> = {
  open: 'text-green-400',
  closed: 'text-white/30',
  pre: 'text-amber-400',
  after: 'text-amber-400',
}

export function Header({
  mode = 'paper',
  sysStatus = 'ok',
  marketState = 'open',
  clockStr = '14:32:05 ET',
  updatedStr = 'updated 2s ago',
}: HeaderProps) {
  return (
    <header className="h-14 shrink-0 bg-[#0d0d0d] border-b border-white/[0.06] flex items-center px-6 gap-3">
      {/* Left: brand + mode badge */}
      <span className="text-base font-semibold text-white/80 tracking-wide">TW</span>
      <span
        className={`text-xs font-bold px-1.5 py-0.5 rounded tracking-widest uppercase border ${
          mode === 'paper'
            ? 'bg-[#185FA5]/15 text-[#185FA5] border-[#185FA5]/40'
            : 'bg-red-900/40 text-red-400 border-red-700/40'
        }`}
      >
        {mode}
      </span>

      {/* Spacer */}
      <div className="flex-1" />

      {/* Right cluster */}
      <div className="flex items-center gap-5 text-sm">
        <span className="flex items-center gap-1.5">
          <span className={`w-1.5 h-1.5 rounded-full shrink-0 ${SYS_DOT[sysStatus] ?? 'bg-gray-500'}`} />
          <span className="text-white/60 uppercase tracking-wide">SYS {sysStatus}</span>
        </span>

        <span className={MARKET_COLOR[marketState] ?? 'text-white/30'}>
          {MARKET_LABEL[marketState] ?? 'MARKET ?'}
        </span>

        <span className="font-mono text-white/60">{clockStr}</span>

        <span className="text-white/30">{updatedStr}</span>
      </div>
    </header>
  )
}
