'use client'

import { useParams } from 'next/navigation'
import Link from 'next/link'
import { ProposalDetailWidget } from '@/components/widgets/proposal-detail'

export default function ProposalDetailPage() {
  const params = useParams<{ corrId: string }>()
  const corrId = params?.corrId

  return (
    <>
      <div className="mb-6 flex items-baseline justify-between">
        <div className="flex items-baseline gap-3">
          <Link
            href="/proposals"
            className="text-sm text-white/40 hover:text-white/70 transition-colors"
          >
            ← Proposals
          </Link>
          <span className="text-white/30">/</span>
          <h1 className="text-2xl font-semibold">Detail</h1>
        </div>
      </div>
      <ProposalDetailWidget corrId={corrId} />
    </>
  )
}
