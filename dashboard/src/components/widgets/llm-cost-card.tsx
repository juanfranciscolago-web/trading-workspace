'use client'

import { useCostsDaily } from '@/hooks/use-costs'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Skeleton } from '@/components/ui/skeleton'
import { Alert, AlertDescription } from '@/components/ui/alert'

const usd = new Intl.NumberFormat('en-US', {
  style: 'currency',
  currency: 'USD',
  minimumFractionDigits: 4,
})

export function LLMCostCard() {
  const { data, isLoading, isError, error } = useCostsDaily()

  if (isLoading) {
    return (
      <Card>
        <CardHeader><CardTitle>LLM Cost</CardTitle></CardHeader>
        <CardContent className="flex flex-col gap-3">
          <Skeleton className="h-10 w-32" />
          <Skeleton className="h-6 w-24" />
        </CardContent>
      </Card>
    )
  }

  if (isError) {
    const message = error instanceof Error ? error.message : String(error)
    return (
      <Alert variant="destructive">
        <AlertDescription>{message}</AlertDescription>
      </Alert>
    )
  }

  if (!data) return null

  // HACK PHASE 0: backend /costs/daily has rows: list[dict] (untyped on the Python side).
  // This cast assumes specific fields verified manually via curl.
  // Sprint 2B.3 must type this properly via Pydantic model on backend (CostRow).
  // See Sprint 2B.2 retro: "Cost responses tienen list[dict] sin tipar".
  type CostRow = { date: string; calls: number; cost_usd: number; total_tokens: number }
  const today = data.rows[0] as CostRow | undefined

  return (
    <Card>
      <CardHeader>
        <CardTitle>LLM Cost</CardTitle>
      </CardHeader>
      <CardContent className="flex flex-col gap-2">
        <span className="font-mono text-4xl font-semibold">
          {today ? usd.format(today.cost_usd) : '—'}
        </span>
        <span className="font-mono text-sm text-muted-foreground">
          {today ? `${today.calls} calls · ${today.date}` : 'no data today'}
        </span>
      </CardContent>
    </Card>
  )
}
