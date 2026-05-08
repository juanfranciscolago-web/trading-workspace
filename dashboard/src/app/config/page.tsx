'use client'

import { useState } from 'react'
import { toast } from 'sonner'

import { useLimitsConfig, useBucketsConfig } from '@/hooks/use-config'
import { useSystemMode, useToggleMode } from '@/hooks/use-system-mode'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Skeleton } from '@/components/ui/skeleton'
import { Alert, AlertDescription } from '@/components/ui/alert'
import { ModeBadge } from '@/components/ui/mode-badge'
import { Button } from '@/components/ui/button'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'

const REAL_MODE_TOKEN = 'CAUTION_GOING_LIVE_STOPPING_PAPER_GOING_REAL_TRADING'
const ACTIVATE_PHRASE = 'ACTIVATE REAL TRADING'
const DEACTIVATE_PHRASE = 'DEACTIVATE'

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
  const toggle = useToggleMode()
  const [open, setOpen] = useState(false)
  const [confirmText, setConfirmText] = useState('')
  const [tokenInput, setTokenInput] = useState('')

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

  const isPaper = data.mode === 'paper'
  const targetMode: 'paper' | 'real' = isPaper ? 'real' : 'paper'
  const expectedPhrase = isPaper ? ACTIVATE_PHRASE : DEACTIVATE_PHRASE
  const isFormValid = isPaper
    ? confirmText === ACTIVATE_PHRASE && tokenInput === REAL_MODE_TOKEN
    : confirmText === DEACTIVATE_PHRASE

  function reset() {
    setConfirmText('')
    setTokenInput('')
  }

  function handleOpenChange(next: boolean) {
    if (!next) reset()
    setOpen(next)
  }

  function handleSubmit() {
    toggle.mutate(
      {
        mode: targetMode,
        confirmation_token: isPaper ? tokenInput : undefined,
      },
      {
        onSuccess: (resp) => {
          toast.success(`Trading mode changed to ${resp.mode.toUpperCase()}`)
          setOpen(false)
          reset()
        },
        onError: (err) => {
          const message = err instanceof Error ? err.message : String(err)
          toast.error(message)
        },
      },
    )
  }

  return (
    <>
      <Card>
        <CardHeader>
          <CardTitle className="text-sm font-medium text-white/60 uppercase tracking-wide">Trading Mode</CardTitle>
        </CardHeader>
        <CardContent className="flex flex-col gap-3">
          <ModeBadge mode={data.mode} className="self-start text-base" />
          <div>
            <Button
              variant={isPaper ? 'destructive' : 'outline'}
              size="sm"
              onClick={() => setOpen(true)}
            >
              {isPaper ? 'Switch to REAL' : 'Switch back to PAPER'}
            </Button>
          </div>
        </CardContent>
      </Card>

      <Dialog open={open} onOpenChange={handleOpenChange}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>
              {isPaper ? 'Switch to REAL trading mode' : 'Switch back to PAPER mode'}
            </DialogTitle>
            <DialogDescription>
              {isPaper
                ? 'This will enable REAL TRADING. The system will execute orders against the live broker. Real money is at stake.'
                : 'This will disable real trading and return to paper trading. Live broker calls will stop.'}
            </DialogDescription>
          </DialogHeader>

          <div className="flex flex-col gap-4">
            <div className="flex flex-col gap-1">
              <label className="text-xs text-white/60">
                Type <code className="font-mono text-white/80">{expectedPhrase}</code> to confirm
              </label>
              <input
                type="text"
                value={confirmText}
                onChange={(e) => setConfirmText(e.target.value)}
                placeholder={expectedPhrase}
                autoComplete="off"
                spellCheck={false}
                className="rounded border border-white/20 bg-transparent px-3 py-2 font-mono text-sm focus:outline-none focus:border-white/50"
              />
            </div>

            {isPaper && (
              <div className="flex flex-col gap-1">
                <label className="text-xs text-white/60">Confirmation token</label>
                <input
                  type="text"
                  value={tokenInput}
                  onChange={(e) => setTokenInput(e.target.value)}
                  placeholder="Paste REAL_MODE_TOKEN"
                  autoComplete="off"
                  spellCheck={false}
                  className="rounded border border-white/20 bg-transparent px-3 py-2 font-mono text-xs focus:outline-none focus:border-white/50"
                />
                <span className="font-mono text-[10px] text-white/40 break-all">
                  {REAL_MODE_TOKEN}
                </span>
              </div>
            )}
          </div>

          <DialogFooter>
            <Button
              variant="outline"
              onClick={() => handleOpenChange(false)}
              disabled={toggle.isPending}
            >
              Cancel
            </Button>
            <Button
              variant={isPaper ? 'destructive' : 'default'}
              onClick={handleSubmit}
              disabled={!isFormValid || toggle.isPending}
            >
              {toggle.isPending ? 'Working…' : isPaper ? 'Activate REAL' : 'Deactivate'}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </>
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
