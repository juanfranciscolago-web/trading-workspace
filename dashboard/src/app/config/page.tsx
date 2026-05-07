'use client'

import { useLimitsConfig, useBucketsConfig } from '@/hooks/use-config'
import { useSystemMode } from '@/hooks/use-system-mode'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Skeleton } from '@/components/ui/skeleton'
import { Alert, AlertDescription } from '@/components/ui/alert'
import { ModeBadge } from '@/components/ui/mode-badge'

interface ConfigSectionProps {
  title: string
  isLoading: boolean
  isError: boolean
  error: unknown
  data: unknown
}

function ConfigSection({ title, isLoading, isError, error, data }: ConfigSectionProps) {
  if (isLoading) {
    return (
      <Card>
        <CardHeader>
          <CardTitle className="text-sm font-medium text-white/60 uppercase tracking-wide">{title}</CardTitle>
        </CardHeader>
        <CardContent>
          <Skeleton className="h-32 w-full" />
        </CardContent>
      </Card>
    )
  }

  if (isError) {
    const message = error instanceof Error ? error.message : String(error)
    return (
      <Card>
        <CardHeader>
          <CardTitle className="text-sm font-medium text-white/60 uppercase tracking-wide">{title}</CardTitle>
        </CardHeader>
        <CardContent>
          <Alert variant="destructive">
            <AlertDescription>{message}</AlertDescription>
          </Alert>
        </CardContent>
      </Card>
    )
  }

  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-sm font-medium text-white/60 uppercase tracking-wide">{title}</CardTitle>
      </CardHeader>
      <CardContent>
        <pre className="font-mono text-xs text-white/70 whitespace-pre-wrap overflow-x-auto">
          {JSON.stringify(data, null, 2)}
        </pre>
      </CardContent>
    </Card>
  )
}

function TradingModeSection() {
  const { data, isLoading, isError, error } = useSystemMode()

  if (isLoading) {
    return (
      <Card>
        <CardHeader>
          <CardTitle className="text-sm font-medium text-white/60 uppercase tracking-wide">Trading Mode</CardTitle>
        </CardHeader>
        <CardContent>
          <Skeleton className="h-8 w-24" />
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

  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-sm font-medium text-white/60 uppercase tracking-wide">Trading Mode</CardTitle>
      </CardHeader>
      <CardContent className="flex flex-col gap-3">
        <ModeBadge mode={data.mode} className="self-start text-base" />
        <span className="text-xs text-white/40">
          Toggle disabled — coming Sprint 2B.5
        </span>
      </CardContent>
    </Card>
  )
}

export default function ConfigPage() {
  const limits = useLimitsConfig()
  const buckets = useBucketsConfig()

  return (
    <>
      <div className="mb-6 flex items-baseline justify-between">
        <h1 className="text-2xl font-semibold">Config</h1>
        <span className="font-mono text-sm text-white/40">read-only</span>
      </div>
      <div className="flex flex-col gap-4">
        <TradingModeSection />
        <ConfigSection
          title="Limits"
          isLoading={limits.isLoading}
          isError={limits.isError}
          error={limits.error}
          data={limits.data}
        />
        <ConfigSection
          title="Buckets"
          isLoading={buckets.isLoading}
          isError={buckets.isError}
          error={buckets.error}
          data={buckets.data}
        />
      </div>
    </>
  )
}
