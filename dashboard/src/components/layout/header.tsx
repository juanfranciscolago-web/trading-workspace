'use client'

import { useState, useEffect } from 'react'
import { ModeBadge } from '@/components/ui/mode-badge'

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

const ET_FORMATTER = new Intl.DateTimeFormat('en-US', {
  timeZone: 'America/New_York',
  hour: '2-digit',
  minute: '2-digit',
  second: '2-digit',
  hour12: false,
})

function formatClock(d: Date): string {
  return `${ET_FORMATTER.format(d)} ET`
}

export function Header({
  mode = 'paper',
  sysStatus = 'ok',
  marketState = 'open',
  clockStr,
  updatedStr = 'updated 2s ago',
}: HeaderProps) {
  const [internalClock, setInternalClock] = useState<string>('')

  useEffect(() => {
    if (clockStr !== undefined) return

    setInternalClock(formatClock(new Date()))
    const id = setInterval(() => {
      setInternalClock(formatClock(new Date()))
    }, 1000)

    return () => clearInterval(id)
  }, [clockStr])

  const displayClock = clockStr ?? internalClock

  return (
    <header className="h-14 shrink-0 bg-[#0d0d0d] border-b border-white/[0.06] flex items-center px-6 gap-3">
      {/* Left: brand + mode badge */}
      <span className="text-base font-semibold text-white/80 tracking-wide">TW</span>
      <ModeBadge mode={mode} />

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

        <span className="font-mono text-white/60">{displayClock}</span>

        <span className="text-white/30">{updatedStr}</span>
      </div>
    </header>
  )
}
