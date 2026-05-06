'use client'

import { useAgents, useToggleAgent, type Agent } from '@/hooks/use-agents'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Skeleton } from '@/components/ui/skeleton'
import { Alert, AlertDescription } from '@/components/ui/alert'
import { Switch } from '@/components/ui/switch'

const STATUS_DOT: Record<string, string> = {
  idle: 'bg-green-500',
  running: 'bg-blue-500',
  error: 'bg-red-500',
  stopped: 'bg-gray-500',
}

function formatCost(value: string | null): string {
  if (value == null) return '$0.0000'
  const n = Number(value)
  if (Number.isNaN(n)) return '$—'
  return `$${n.toFixed(4)}`
}

function statusDotClass(status: string | null | undefined): string {
  if (!status) return 'bg-gray-500'
  return STATUS_DOT[status] ?? 'bg-gray-500'
}

interface AgentRowProps {
  agent: Agent
  onToggle: (agentId: string, nextActive: boolean) => void
  isPending: boolean
  pendingAgentId: string | null
}

function AgentRow({ agent, onToggle, isPending, pendingAgentId }: AgentRowProps) {
  const thisAgentPending = isPending && pendingAgentId === agent.agent_id

  return (
    <li className="flex items-center gap-3 text-sm">
      <span className={`w-2 h-2 rounded-full shrink-0 ${statusDotClass(agent.status)}`} />
      <span className="flex-1 font-mono text-white/80 uppercase tracking-wide">
        {agent.display_name}
      </span>
      <span className="font-mono text-xs text-white/40 w-20 text-right">
        {formatCost(agent.llm_cost_today_usd)}
      </span>
      <Switch
        checked={agent.is_active}
        disabled={thisAgentPending}
        onCheckedChange={(next) => onToggle(agent.agent_id, next)}
      />
    </li>
  )
}

export function AgentsCard() {
  const { data, isLoading, isError, error } = useAgents()
  const toggleMutation = useToggleAgent()

  if (isLoading) {
    return (
      <Card>
        <CardHeader><CardTitle>Agents</CardTitle></CardHeader>
        <CardContent><Skeleton className="h-32 w-full" /></CardContent>
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

  const items = data?.items ?? []
  const pendingAgentId = toggleMutation.isPending ? toggleMutation.variables?.agentId ?? null : null

  const handleToggle = (agentId: string, nextActive: boolean) => {
    toggleMutation.mutate({ agentId, isActive: nextActive })
  }

  return (
    <Card style={{ borderLeft: '2px solid #444' }}>
      <CardHeader>
        <CardTitle className="text-sm font-medium text-white/60 uppercase tracking-wide">Agents</CardTitle>
      </CardHeader>
      <CardContent>
        {items.length === 0 ? (
          <span className="text-sm text-white/40">No agents registered</span>
        ) : (
          <ul className="flex flex-col gap-2">
            {items.map((agent) => (
              <AgentRow
                key={agent.agent_id}
                agent={agent}
                onToggle={handleToggle}
                isPending={toggleMutation.isPending}
                pendingAgentId={pendingAgentId}
              />
            ))}
          </ul>
        )}
      </CardContent>
    </Card>
  )
}
