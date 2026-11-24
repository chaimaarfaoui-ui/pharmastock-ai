import { BarChart3, Bell, Bot, CalendarClock, ClipboardList, FileText, FlaskConical, LayoutDashboard, LineChart, Package, Pill, Settings, ShoppingCart, ShieldAlert, Truck, Upload, Users, Warehouse, type LucideIcon } from "lucide-react";
import type { Role } from "./api";

export interface NavItem { href: string; label: string; icon: LucideIcon; roles: Role[] }
const ALL: Role[] = ["admin", "manager", "employee"];
const MGR: Role[] = ["admin", "manager"];

// Every entry is a working page. The API enforces permissions; this list is only a UX convenience.
export const NAV: NavItem[] = [
  { href: "/dashboard", label: "Dashboard", icon: LayoutDashboard, roles: ALL },
  { href: "/inventory", label: "Inventory", icon: Warehouse, roles: ALL },
  { href: "/medicines", label: "Medicines", icon: Pill, roles: ALL },
  { href: "/batches", label: "Batches", icon: Package, roles: ALL },
  { href: "/forecasting", label: "Demand Forecasting", icon: LineChart, roles: MGR },
  { href: "/shortage", label: "Shortage Alerts", icon: ShieldAlert, roles: MGR },
  { href: "/expiration", label: "Expiration Management", icon: CalendarClock, roles: MGR },
  { href: "/reorder", label: "Reorder Recommendations", icon: ClipboardList, roles: MGR },
  { href: "/suppliers", label: "Suppliers", icon: Truck, roles: ALL },
  { href: "/purchase-orders", label: "Purchase Orders", icon: ShoppingCart, roles: ALL },
  { href: "/analytics", label: "Analytics", icon: BarChart3, roles: MGR },
  { href: "/simulation", label: "Scenario Simulation", icon: FlaskConical, roles: MGR },
  { href: "/assistant", label: "AI Assistant", icon: Bot, roles: ALL },
  { href: "/import", label: "Import Data", icon: Upload, roles: MGR },
  { href: "/reports", label: "Reports", icon: FileText, roles: MGR },
  { href: "/notifications", label: "Notifications", icon: Bell, roles: ALL },
  { href: "/settings", label: "Settings", icon: Settings, roles: MGR },
  { href: "/users", label: "Users", icon: Users, roles: ["admin"] },
];
