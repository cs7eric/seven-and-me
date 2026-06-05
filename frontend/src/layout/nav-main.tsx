import * as React from "react"
import { Link, useLocation, useNavigate } from "react-router-dom"
import { ChevronRight, type LucideIcon } from "lucide-react"

import {
  Collapsible,
  CollapsibleContent,
  CollapsibleTrigger,
} from "@/components/ui/collapsible"
import {
  SidebarGroup,
  SidebarGroupLabel,
  SidebarMenu,
  SidebarMenuButton,
  SidebarMenuItem,
  SidebarMenuSub,
  SidebarMenuSubButton,
  SidebarMenuSubItem,
  useSidebar,
} from "@/components/ui/sidebar"

const STORAGE_KEY = "app-sidebar-open-groups"

export function NavMain({
  items,
}: {
  items: {
    title: string
    url: string
    icon?: LucideIcon
    isActive?: boolean
    items?: {
      title: string
      url: string
    }[]
  }[]
}) {
  const { state } = useSidebar()
  const location = useLocation()
  const navigate = useNavigate()

  const getInitialOpenState = React.useCallback(() => {
    if (typeof window === "undefined") {
      return Object.fromEntries(items.map((item) => [item.title, Boolean(item.isActive)]))
    }
    try {
      const raw = window.localStorage.getItem(STORAGE_KEY)
      if (raw) {
        return {
          ...Object.fromEntries(items.map((item) => [item.title, Boolean(item.isActive)])),
          ...JSON.parse(raw),
        }
      }
    } catch {
      return Object.fromEntries(items.map((item) => [item.title, Boolean(item.isActive)]))
    }
    return Object.fromEntries(items.map((item) => [item.title, Boolean(item.isActive)]))
  }, [items])

  const [openItems, setOpenItems] = React.useState<Record<string, boolean>>(getInitialOpenState)

  React.useEffect(() => {
    window.localStorage.setItem(STORAGE_KEY, JSON.stringify(openItems))
  }, [openItems])

  return (
    <SidebarGroup>
      <SidebarGroupLabel>Applications</SidebarGroupLabel>
      <SidebarMenu>
        {items.map((item) => {
          const hasSubItems = Array.isArray(item.items) && item.items.length > 0
          const isActive =
            location.pathname === item.url ||
            item.items?.some((subItem) => subItem.url === location.pathname)

          if (!hasSubItems) {
            return (
              <SidebarMenuItem key={item.title}>
                <SidebarMenuButton
                  tooltip={item.title}
                  isActive={isActive}
                  onClick={() => navigate(item.url)}
                >
                  {item.icon ? <item.icon /> : null}
                  <span>{item.title}</span>
                </SidebarMenuButton>
              </SidebarMenuItem>
            )
          }

          const isOpen = (openItems[item.title] ?? false) || isActive
          const showChevron = (
            <ChevronRight className="ml-auto transition-transform duration-200 group-data-[state=open]/collapsible:rotate-90 group-data-[collapsible=icon]:hidden" />
          )

          if (state === "collapsed") {
            return (
              <SidebarMenuItem key={item.title}>
                <SidebarMenuButton
                  tooltip={item.title}
                  isActive={isActive}
                  onClick={() => navigate(item.url)}
                >
                  {item.icon ? <item.icon /> : null}
                  <span>{item.title}</span>
                  {showChevron}
                </SidebarMenuButton>
              </SidebarMenuItem>
            )
          }

          return (
            <Collapsible
              key={item.title}
              asChild
              open={isOpen}
              onOpenChange={(open) => {
                setOpenItems((prev) => ({ ...prev, [item.title]: open }))
              }}
              className="group/collapsible"
            >
              <SidebarMenuItem>
                <CollapsibleTrigger asChild>
                  <SidebarMenuButton tooltip={item.title} isActive={isActive}>
                    {item.icon ? <item.icon /> : null}
                    <span>{item.title}</span>
                    {showChevron}
                  </SidebarMenuButton>
                </CollapsibleTrigger>
                <CollapsibleContent>
                  <SidebarMenuSub>
                    {item.items?.map((subItem) => (
                      <SidebarMenuSubItem key={subItem.title}>
                        <SidebarMenuSubButton asChild isActive={location.pathname === subItem.url}>
                          <Link to={subItem.url}>
                            <span>{subItem.title}</span>
                          </Link>
                        </SidebarMenuSubButton>
                      </SidebarMenuSubItem>
                    ))}
                  </SidebarMenuSub>
                </CollapsibleContent>
              </SidebarMenuItem>
            </Collapsible>
          )
        })}
      </SidebarMenu>
    </SidebarGroup>
  )
}
