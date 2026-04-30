import { PnLCard } from '@/components/widgets/pnl-card'
import { LLMCostCard } from '@/components/widgets/llm-cost-card'

export default function HomePage() {
  return (
    <main className="min-h-screen bg-background text-foreground p-8">
      <header className="mb-8">
        <h1 className="text-2xl font-semibold">Trading Dashboard — Phase 0</h1>
        <p className="text-sm text-muted-foreground mt-1">Prototype build</p>
      </header>
      <div className="grid grid-cols-1 md:grid-cols-2 gap-6 max-w-4xl">
        <PnLCard />
        <LLMCostCard />
      </div>
    </main>
  )
}
