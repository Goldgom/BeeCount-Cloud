import type { ReactNode } from 'react'
import { AppSidebar } from '../app/AppSidebar'

type AppLayoutProps = {
  header: ReactNode
  children: ReactNode
}

export function AppLayout({ header, children }: AppLayoutProps) {
  return (
    <div className="min-h-screen bg-background text-foreground">
      {header}
      <a href="#main-content" className="bc-skip-link">Skip to content</a>
      <AppSidebar />
      <main id="main-content" tabIndex={-1} className="bc-main">{children}</main>
    </div>
  )
}
