'use client'

import Link from 'next/link'
import { usePathname } from 'next/navigation'

interface NavItem {
  label: string
  href: string
  soon?: boolean
  sprint?: string
}

const SECTIONS: { title: string; items: NavItem[] }[] = [
  {
    title: 'VIEWS',
    items: [
      { label: 'Home', href: '/' },
      { label: 'Portfolio', href: '/portfolio' },
      { label: 'Risk', href: '/risk' },
    ],
  },
  {
    title: 'CONTROL',
    items: [
      { label: 'Agents', href: '/agents', soon: true, sprint: '2B.4' },
      { label: 'Config', href: '/config', soon: true, sprint: '2B.4' },
      { label: 'Backtesting', href: '/backtesting', soon: true, sprint: 'S5' },
    ],
  },
  {
    title: 'DATA',
    items: [
      { label: 'Market', href: '/market', soon: true, sprint: 'S4' },
    ],
  },
]

export function Sidebar() {
  const pathname = usePathname()

  return (
    <aside className="w-[180px] shrink-0 bg-[#0d0d0d] border-r border-white/5 flex flex-col py-4 overflow-y-auto">
      <div className="px-4 mb-6">
        <span className="text-[10px] font-bold tracking-widest text-white/30 uppercase">TW</span>
      </div>
      <nav className="flex flex-col gap-5 flex-1 px-2">
        {SECTIONS.map((section) => (
          <div key={section.title}>
            <p className="px-2 mb-1 text-xs font-semibold tracking-widest text-white/25 uppercase">
              {section.title}
            </p>
            <ul className="flex flex-col gap-0.5">
              {section.items.map((item) => {
                if (item.soon) {
                  return (
                    <li key={item.href}>
                      <span className="flex items-center h-8 px-2 text-base text-white/50 cursor-default select-none">
                        <span className="flex-1">{item.label}</span>
                        {item.sprint && (
                          <span className="text-xs text-white/25 font-mono">{item.sprint}</span>
                        )}
                      </span>
                    </li>
                  )
                }
                const isActive = pathname === item.href
                return (
                  <li key={item.href}>
                    <Link
                      href={item.href}
                      className={`flex items-center h-8 px-2 rounded-sm text-base transition-colors ${
                        isActive
                          ? 'bg-[#1a1a1a] text-white'
                          : 'text-white/70 hover:text-white hover:bg-white/5'
                      }`}
                      style={isActive ? { borderLeft: '2px solid #185FA5', paddingLeft: 6 } : undefined}
                    >
                      {item.label}
                    </Link>
                  </li>
                )
              })}
            </ul>
          </div>
        ))}
      </nav>
    </aside>
  )
}
