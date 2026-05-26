import * as React from 'react'
import { cn } from '@/lib/utils'

const TabsContext = React.createContext(null)

const Tabs = React.forwardRef(({ className, value, onValueChange, defaultValue, ...props }, ref) => {
  const [internalValue, setInternalValue] = React.useState(defaultValue ?? value ?? '')
  const currentValue = value !== undefined ? value : internalValue
  return (
    <TabsContext.Provider value={{ value: currentValue, onValueChange: onValueChange ?? setInternalValue }}>
      <div ref={ref} className={cn('w-full', className)} {...props} />
    </TabsContext.Provider>
  )
})
Tabs.displayName = 'Tabs'

const TabsList = React.forwardRef(({ className, ...props }, ref) => (
  <div ref={ref} className={cn('inline-flex h-9 items-center justify-center rounded-lg bg-muted p-1 text-muted-foreground', className)} {...props} />
))
TabsList.displayName = 'TabsList'

const TabsTrigger = React.forwardRef(({ className, value, ...props }, ref) => {
  const ctx = React.useContext(TabsContext)
  const isActive = ctx?.value === value
  return (
    <button
      ref={ref}
      className={cn(
        'inline-flex items-center justify-center whitespace-nowrap rounded-md px-3 py-1 text-sm font-medium ring-offset-background transition-all focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 disabled:pointer-events-none disabled:opacity-50',
        isActive ? 'bg-background text-foreground shadow' : 'hover:bg-background/50 hover:text-foreground',
        className
      )}
      onClick={() => ctx?.onValueChange?.(value)}
      {...props}
    />
  )
})
TabsTrigger.displayName = 'TabsTrigger'

const TabsContent = React.forwardRef(({ className, value, ...props }, ref) => {
  const ctx = React.useContext(TabsContext)
  const isActive = ctx?.value === value
  return (
    <div
      ref={ref}
      className={cn(
        'mt-2 ring-offset-background focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2',
        isActive ? 'block' : 'hidden',
        className
      )}
      {...props}
    />
  )
})
TabsContent.displayName = 'TabsContent'

export { Tabs, TabsList, TabsTrigger, TabsContent }