'use client'

import Link from 'next/link'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Skeleton } from '@/components/ui/skeleton'
import { Alert, AlertDescription } from '@/components/ui/alert'
import { useProposals, type Proposal } from '@/hooks/use-proposals'

// ── Formatters ────────────────────────────────────────────────────────────────

function formatSize(pct: number | null, usd: number | null): string {
  if (pct == null && usd == null) return '—'
  const pctStr = pct != null ? `${pct.toFixed(1)}%` : '—'
  const usdStr = usd != null ? `$${Math.round(usd).toLocaleString()}` : '—'
  return `${pctStr} · ${usdStr}`
}

function formatHorizon(days: number | null): string {
  if (days == null) return '—'
  return `${days}d`
}

function formatCreatedAt(iso: string): string {
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return iso
  return d.toLocaleString('en-US', {
    year: 'numeric',
    month: 'short',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
  })
}

function convictionToneClass(score: number | null): string {
  if (score == null) return 'text-white/40'
  if (score >= 70) return 'text-green-400'
  if (score >= 50) return 'text-yellow-400'
  return 'text-orange-400'
}

// ── Row ───────────────────────────────────────────────────────────────────────

interface ProposalRowProps {
  proposal: Proposal
}

function ProposalRow({ proposal }: ProposalRowProps) {
  return (
    <li>
      <Link
        href={`/proposals/${proposal.correlation_id}`}
        className="grid grid-cols-[80px_80px_120px_80px_140px_60px_140px] gap-2 items-center px-3 py-2 text-sm rounded-sm hover:bg-white/5 transition-colors"
      >
        <span className="font-mono font-semibold text-white/90">
          {proposal.ticker}
        </span>
        <span className="font-mono text-xs text-white/60 uppercase tracking-wide">
          {proposal.proposing_agent}
        </span>
        <span className="font-mono text-xs text-white/70">
          {proposal.strategy_type}
        </span>
        <span className={`font-mono text-right ${convictionToneClass(proposal.conviction_score)}`}>
          {proposal.conviction_score ?? '—'}
        </span>
        <span className="font-mono text-xs text-white/60 text-right">
          {formatSize(proposal.proposed_size_pct, proposal.proposed_size_usd)}
        </span>
        <span className="font-mono text-xs text-white/60 text-right">
          {formatHorizon(proposal.time_horizon_days)}
        </span>
        <span className="font-mono text-xs text-white/40 text-right">
          {formatCreatedAt(proposal.created_at)}
        </span>
      </Link>
    </li>
  )
}

// ── Header ────────────────────────────────────────────────────────────────────

function ProposalsTableHeader() {
  return (
    <div className="grid grid-cols-[80px_80px_120px_80px_140px_60px_140px] gap-2 px-3 py-2 text-xs uppercase tracking-widest text-white/30 border-b border-white/5">
      <span>Ticker</span>
      <span>Agent</span>
      <span>Strategy</span>
      <span className="text-right">Conv.</span>
      <span className="text-right">Size</span>
      <span className="text-right">Horizon</span>
      <span className="text-right">Created</span>
    </div>
  )
}

// ── Main component ────────────────────────────────────────────────────────────

export function ProposalsTable() {
  const { data, isLoading, isError, error } = useProposals()

  if (isLoading) {
    return (
      <Card>
        <CardHeader>
          <CardTitle className="text-sm font-medium text-white/60 uppercase tracking-wide">
            Proposals
          </CardTitle>
        </CardHeader>
        <CardContent className="space-y-2">
          <Skeleton className="h-8 w-full" />
          <Skeleton className="h-8 w-full" />
          <Skeleton className="h-8 w-full" />
        </CardContent>
      </Card>
    )
  }

  if (isError) {
    return (
      <Card>
        <CardHeader>
          <CardTitle className="text-sm font-medium text-white/60 uppercase tracking-wide">
            Proposals
          </CardTitle>
        </CardHeader>
        <CardContent>
          <Alert variant="destructive">
            <AlertDescription>
              Failed to load proposals: {error instanceof Error ? error.message : 'unknown error'}
            </AlertDescription>
          </Alert>
        </CardContent>
      </Card>
    )
  }

  const items = data?.items ?? []

  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-sm font-medium text-white/60 uppercase tracking-wide">
          Proposals{' '}
          <span className="text-xs font-normal text-white/40 normal-case tracking-normal">
            ({data?.count ?? 0})
          </span>
        </CardTitle>
      </CardHeader>
      <CardContent>
        {items.length === 0 ? (
          <p className="text-sm text-white/40 py-8 text-center">No proposals yet.</p>
        ) : (
          <>
            <ProposalsTableHeader />
            <ul className="flex flex-col">
              {items.map((proposal) => (
                <ProposalRow key={proposal.correlation_id} proposal={proposal} />
              ))}
            </ul>
          </>
        )}
      </CardContent>
    </Card>
  )
}
