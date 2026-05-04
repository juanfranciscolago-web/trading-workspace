'use client'

import { LLMCostCard } from '@/components/widgets/llm-cost-card'
import { SystemStatusCard } from '@/components/widgets/system-status-card'
import { TradingModeCard } from '@/components/widgets/trading-mode-card'
import { RiskModeCard } from '@/components/widgets/risk-mode-card'

function formatDateLine(d: Date): string {
  const weekday = d.toLocaleDateString('en-US', { weekday: 'long' })
  const iso = d.toISOString().slice(0, 10)
  return `${weekday} · ${iso}`
}

export default function HomePage() {
  return (
    <>
      <div className="mb-6 flex items-baseline justify-between">
        <h1 className="text-2xl font-semibold">Home</h1>
        <span className="font-mono text-sm text-white/40">{formatDateLine(new Date())}</span>
      </div>
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
        <SystemStatusCard />
        <TradingModeCard />
        <RiskModeCard />
        <LLMCostCard />
      </div>
    </>
  )
}
