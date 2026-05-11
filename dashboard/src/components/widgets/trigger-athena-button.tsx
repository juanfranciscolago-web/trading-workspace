'use client'

import { useRouter } from 'next/navigation'
import { toast } from 'sonner'
import { Button } from '@/components/ui/button'
import { useTriggerAthena } from '@/hooks/use-trigger-athena'

export function TriggerAthenaButton() {
  const router = useRouter()
  const mutation = useTriggerAthena()

  const handleClick = () => {
    mutation.mutate(undefined, {
      onSuccess: (data) => {
        if (data.no_setup) {
          toast.info('ATHENA found no setup', {
            description: 'No proposal generated this run.',
          })
          return
        }
        if (data.proposal) {
          const ticker = data.proposal.trade.ticker
          const strategy = data.proposal.trade.strategy_type
          toast.success(`${ticker} ${strategy} proposal generated`, {
            description: `Conviction ${data.proposal.conviction_score}`,
            action: {
              label: 'View',
              onClick: () => router.push(`/proposals/${data.correlation_id}`),
            },
          })
        }
      },
      onError: (error) => {
        toast.error('Trigger failed', {
          description: error instanceof Error ? error.message : 'Unknown error',
        })
      },
    })
  }

  return (
    <Button
      onClick={handleClick}
      disabled={mutation.isPending}
      variant="outline"
    >
      {mutation.isPending ? 'Triggering...' : 'Trigger ATHENA'}
    </Button>
  )
}
