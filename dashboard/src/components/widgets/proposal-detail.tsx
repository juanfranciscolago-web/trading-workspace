'use client'

import Link from 'next/link'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Skeleton } from '@/components/ui/skeleton'
import { Alert, AlertDescription } from '@/components/ui/alert'
import { useProposal, type ProposalDetail } from '@/hooks/use-proposals'

// ── Formatters ────────────────────────────────────────────────────────────────

function formatTimestamp(iso: string): string {
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return iso
  return d.toLocaleString('en-US', {
    year: 'numeric',
    month: 'short',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
    timeZoneName: 'short',
  })
}

function convictionToneClass(score: number): string {
  if (score >= 70) return 'text-green-400'
  if (score >= 50) return 'text-yellow-400'
  return 'text-orange-400'
}

// ── Helpers for narrowing nested unknowns ─────────────────────────────────────

function asString(v: unknown): string {
  return typeof v === 'string' ? v : v == null ? '—' : String(v)
}

function asStringArray(v: unknown): string[] {
  return Array.isArray(v) ? v.map(asString) : []
}

// ── Sub-sections ──────────────────────────────────────────────────────────────

interface SectionProps {
  title: string
  children: React.ReactNode
}

function Section({ title, children }: SectionProps) {
  return (
    <div>
      <h3 className="text-xs font-semibold tracking-widest text-white/40 uppercase mb-2">
        {title}
      </h3>
      <div className="space-y-1 text-sm">{children}</div>
    </div>
  )
}

interface FieldProps {
  label: string
  value: React.ReactNode
}

function Field({ label, value }: FieldProps) {
  return (
    <div className="flex gap-3">
      <span className="text-white/40 w-44 shrink-0">{label}</span>
      <span className="text-white/80 font-mono break-words">{value}</span>
    </div>
  )
}

// ── Trade legs ────────────────────────────────────────────────────────────────

function TradeLegs({ structure }: { structure: Record<string, unknown> }) {
  const legs = Array.isArray(structure.legs) ? structure.legs : []
  if (legs.length === 0) return <span className="text-white/40">—</span>
  return (
    <ul className="flex flex-col gap-1 font-mono text-xs">
      {legs.map((leg: unknown, i: number) => {
        const l = leg as Record<string, unknown>
        return (
          <li key={i} className="text-white/80">
            {asString(l.action).toUpperCase()} {typeof l.quantity === 'number' ? l.quantity : '?'}× {asString(l.instrument_type).toUpperCase()} @ {asString(l.strike)} ({asString(l.expiration)})
          </li>
        )
      })}
    </ul>
  )
}

// ── Main component ────────────────────────────────────────────────────────────

interface ProposalDetailWidgetProps {
  corrId: string | undefined
}

export function ProposalDetailWidget({ corrId }: ProposalDetailWidgetProps) {
  const { data, isLoading, isError, error } = useProposal(corrId)

  if (!corrId) {
    return (
      <Alert variant="destructive">
        <AlertDescription>Missing proposal ID.</AlertDescription>
      </Alert>
    )
  }

  if (isLoading) {
    return (
      <div className="space-y-4">
        <Skeleton className="h-32 w-full" />
        <Skeleton className="h-48 w-full" />
        <Skeleton className="h-32 w-full" />
      </div>
    )
  }

  if (isError) {
    const msg = error instanceof Error ? error.message : 'unknown error'
    // Backend returns detail="proposal not found" on 404 (per routes/trades.py).
    // Fallback to substring match if a future error path uses different wording.
    const is404 = msg === 'proposal not found' || msg.toLowerCase().includes('not found')
    return (
      <Alert variant="destructive">
        <AlertDescription>
          {is404 ? 'Proposal not found.' : `Failed to load proposal: ${msg}`}
          <div className="mt-2">
            <Link href="/proposals" className="text-blue-400 hover:underline">
              ← Back to Proposals
            </Link>
          </div>
        </AlertDescription>
      </Alert>
    )
  }

  if (!data) return null

  return <ProposalDetailContent proposal={data} />
}

// ── Content (rendered when data is loaded) ────────────────────────────────────

function ProposalDetailContent({ proposal }: { proposal: ProposalDetail }) {
  const structure = proposal.trade.structure
  const thesis = proposal.thesis
  const sizing = proposal.sizing
  const sig = proposal.data_signature

  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-sm font-medium text-white/60 uppercase tracking-wide">
          <span className="font-mono">{proposal.trade.ticker}</span>
          <span className="text-white/30 mx-2">·</span>
          <span>{proposal.trade.strategy_type}</span>
          <span className="text-white/30 mx-2">·</span>
          <span className={convictionToneClass(proposal.conviction_score)}>
            Conviction {proposal.conviction_score}
          </span>
        </CardTitle>
      </CardHeader>
      <CardContent className="space-y-6">

        <Section title="Trade">
          <Field label="Ticker" value={proposal.trade.ticker} />
          <Field label="Asset class" value={proposal.trade.asset_class} />
          <Field label="Strategy" value={proposal.trade.strategy_type} />
          <Field label="Legs" value={<TradeLegs structure={structure} />} />
          <Field label="Estimated credit" value={asString(structure.estimated_credit)} />
          <Field label="Estimated debit" value={asString(structure.estimated_debit)} />
          <Field label="Max profit" value={asString(structure.max_profit)} />
          <Field label="Max loss" value={asString(structure.max_loss)} />
          <Field label="Breakeven" value={asString(structure.breakeven)} />
          <Field label="Buying power" value={`$${asString(structure.buying_power_required)}`} />
        </Section>

        <Section title="Thesis">
          <Field label="Premise" value={<span className="font-sans whitespace-pre-wrap">{asString(thesis.premise)}</span>} />
          <Field label="Mechanism" value={<span className="font-sans whitespace-pre-wrap">{asString(thesis.mechanism)}</span>} />
          <Field label="Key data points" value={
            <ul className="list-disc list-inside space-y-0.5 font-sans">
              {asStringArray(thesis.key_data_points).map((p, i) => <li key={i}>{p}</li>)}
            </ul>
          } />
          <Field label="Invalidation" value={<span className="font-sans">{asString(thesis.invalidation)}</span>} />
          <Field label="Target" value={<span className="font-sans">{asString(thesis.target)}</span>} />
          <Field label="Time horizon" value={`${asString(thesis.time_horizon_days)}d`} />
          <Field label="Expected holding" value={`${asString(thesis.expected_holding_period_days)}d`} />
        </Section>

        <Section title="Sizing">
          <Field label="Size % portfolio" value={`${asString(sizing.proposed_size_pct_portfolio)}%`} />
          <Field label="Size USD" value={`$${asString(sizing.proposed_size_usd)}`} />
          <Field label="Kelly suggested" value={asString(sizing.kelly_suggested)} />
          <Field label="Kelly fraction applied" value={asString(sizing.kelly_fraction_applied)} />
        </Section>

        {proposal.self_acknowledged_biases.length > 0 && (
          <Section title="Acknowledged biases">
            <ul className="list-disc list-inside space-y-0.5 font-sans">
              {proposal.self_acknowledged_biases.map((b, i) => <li key={i}>{b}</li>)}
            </ul>
          </Section>
        )}

        <Section title="Data signature">
          <Field label="Model version" value={asString(sig.model_version)} />
          <Field label="Data timestamp" value={formatTimestamp(asString(sig.data_timestamp))} />
          <Field label="Data sources" value={asStringArray(sig.data_sources).join(', ')} />
        </Section>

        <Section title="Metadata">
          <Field label="Correlation ID" value={proposal.correlation_id} />
          <Field label="Message ID" value={proposal.message_id} />
          <Field label="Agent" value={proposal.agent_id} />
          <Field label="Schema version" value={proposal.schema_version} />
          <Field label="Created" value={formatTimestamp(proposal.timestamp)} />
        </Section>

      </CardContent>
    </Card>
  )
}
