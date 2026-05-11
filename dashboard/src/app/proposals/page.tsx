'use client'

import { ProposalsTable } from '@/components/widgets/proposals-table'
import { TriggerAthenaButton } from '@/components/widgets/trigger-athena-button'

function formatDateLine(d: Date): string {
  const weekday = d.toLocaleDateString('en-US', { weekday: 'long' })
  const iso = d.toISOString().slice(0, 10)
  return `${weekday} · ${iso}`
}

export default function ProposalsPage() {
  return (
    <>
      <div className="mb-6 flex items-baseline justify-between">
        <h1 className="text-2xl font-semibold">Proposals</h1>
        <div className="flex items-center gap-4">
          <TriggerAthenaButton />
          <span className="font-mono text-sm text-white/40">{formatDateLine(new Date())}</span>
        </div>
      </div>
      <ProposalsTable />
    </>
  )
}
