import { NavLink } from 'react-router-dom'
import { BookOpen, CalendarDays, ChartNoAxesCombined, CircleHelp, Database, FolderInput, Home, LayoutGrid, Receipt, Tag, Wallet } from 'lucide-react'
import { useT } from '@beecount/ui'
import { useLedgers } from '../context/LedgersContext'

const items = [
  { path: 'overview', label: 'nav.overview', Icon: Home },
  { path: 'transactions', label: 'nav.transactions', Icon: Receipt },
  { path: 'finance', label: 'finance.title', Icon: ChartNoAxesCombined },
  { path: 'accounts', label: 'nav.accounts', Icon: Wallet },
  { path: 'data-sources', label: 'nav.dataSources', Icon: Database },
  { path: 'calendar', label: 'nav.calendar', Icon: CalendarDays },
  { path: 'budgets', label: 'nav.budgets', Icon: ChartNoAxesCombined },
  { path: 'categories', label: 'nav.categories', Icon: LayoutGrid },
  { path: 'tags', label: 'nav.tags', Icon: Tag },
  { path: 'ledgers', label: 'nav.ledgers', Icon: BookOpen },
  { path: 'import', label: 'import.pageTitle', Icon: FolderInput },
]

export function AppSidebar() {
  const t = useT()
  const { currentLedger } = useLedgers()
  return <aside className="bc-sidebar hidden lg:flex" aria-label={t('shell.appName')}>
    <div className="px-3 pb-5">
      <p className="text-xs font-medium text-muted-foreground">{t('shell.ledger')}</p>
      <p className="mt-1 truncate text-sm font-semibold">{currentLedger?.ledger_name || t('shell.appName')}</p>
    </div>
    <nav className="space-y-1">
      {items.map(({ path, label, Icon }) => <NavLink key={path} to={`/app/${path}`} className={({ isActive }) => `bc-sidebar-link ${isActive ? 'is-active' : ''}`}>
        <Icon size={18} strokeWidth={1.7} aria-hidden="true" /><span>{t(label)}</span>
      </NavLink>)}
    </nav>
    <NavLink to="/app/settings-profile" className="bc-sidebar-link mt-auto"><CircleHelp size={18} aria-hidden="true" />{t('nav.profile')}</NavLink>
  </aside>
}
