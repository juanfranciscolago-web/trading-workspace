'use client'

import { LLMCostCard } from '@/components/widgets/llm-cost-card'

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
      <div className="grid grid-cols-1 md:grid-cols-2 gap-6 max-w-4xl">
        <LLMCostCard />
      </div>
    </>
  )
}
