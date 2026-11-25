import {
  ArrowLeftRight,
  BookOpen,
  ChefHat,
  KeyRound,
  ClipboardCheck,
  LayoutDashboard,
  LogOut,
  Menu,
  Package,
  PackageMinus,
  PackagePlus,
  Receipt,
  Settings,
  Users,
  Warehouse,
  Boxes,
  X,
  type LucideIcon,
} from "lucide-react";
import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { NavLink, Outlet, useLocation } from "react-router-dom";
import { useAuth } from "@/auth/AuthContext";
import { loadQueue } from "@/lib/countQueue";
import type { Permission } from "@/lib/types";
import { ChangePasswordDialog } from "./ChangePassword";
import { Modal } from "./Modal";
import { Button, cn } from "./ui";

interface NavItem {
  to: string;
  key: string;
  icon: LucideIcon;
  perm?: Permission;
}

const sections: { key: string; items: NavItem[] }[] = [
  {
    key: "",
    items: [
      { to: "/", key: "dashboard", icon: LayoutDashboard },
      { to: "/stock", key: "stock", icon: Boxes },
    ],
  },
  {
    key: "operations",
    items: [
      { to: "/receipts", key: "receipts", icon: PackagePlus },
      { to: "/write-offs", key: "writeOffs", icon: PackageMinus },
      { to: "/transfers", key: "transfers", icon: ArrowLeftRight },
      { to: "/inventory", key: "inventory", icon: ClipboardCheck },
      { to: "/sales", key: "sales", icon: Receipt },
      { to: "/journal", key: "journal", icon: BookOpen },
    ],
  },
  {
    key: "catalog",
    items: [
      { to: "/products", key: "products", icon: Package },
      { to: "/locations", key: "locations", icon: Warehouse },
      { to: "/pos-items", key: "posItems", icon: ChefHat },
    ],
  },
  {
    key: "admin",
    items: [
      { to: "/users", key: "users", icon: Users, perm: "manage_users" },
      { to: "/settings", key: "settings", icon: Settings, perm: "manage_settings" },
    ],
  },
];

function Sidebar({ onNavigate }: { onNavigate?: () => void }) {
  const { t } = useTranslation();
  const { user, can, logout } = useAuth();
  const [unsent, setUnsent] = useState(0);
  const [changing, setChanging] = useState(false);
  const signOut = () => {
    const n = user ? loadQueue(user.id).length : 0;
    if (n > 0) setUnsent(n);
    else void logout();
  };

  return (
    <div className="flex h-full flex-col">
      <div className="flex h-16 items-center px-5 text-base font-semibold tracking-tight">{t("app.name")}</div>
      <nav className="flex-1 space-y-5 overflow-y-auto px-3 pb-4">
        {sections.map((s) => {
          const items = s.items.filter((i) => !i.perm || can(i.perm));
          if (!items.length) return null;
          return (
            <div key={s.key || "main"}>
              {s.key && <div className="px-2 pb-1 text-xs font-medium uppercase tracking-wide text-zinc-400">{t(`nav.${s.key}`)}</div>}
              {items.map((i) => (
                <NavLink
                  key={i.to}
                  to={i.to}
                  end={i.to === "/"}
                  onClick={onNavigate}
                  className={({ isActive }) =>
                    cn(
                      "flex min-h-10 items-center gap-3 rounded-lg px-2 text-sm",
                      isActive ? "bg-zinc-900 text-white" : "text-zinc-700 hover:bg-zinc-100",
                    )
                  }
                >
                  <i.icon className="h-4 w-4 shrink-0" aria-hidden />
                  {t(`nav.${i.key}`)}
                </NavLink>
              ))}
            </div>
          );
        })}
      </nav>
      <div className="border-t border-zinc-200 p-3">
        <div className="px-2 pb-2">
          <div className="truncate text-sm font-medium">{user?.full_name || user?.username}</div>
          <div className="text-xs text-zinc-500">{user && t(`role.${user.role}`)}</div>
        </div>
        <button
          type="button"
          onClick={() => setChanging(true)}
          className="flex min-h-10 w-full items-center gap-3 rounded-lg px-2 text-sm text-zinc-700 hover:bg-zinc-100"
        >
          <KeyRound className="h-4 w-4" aria-hidden />
          {t("auth.changePassword")}
        </button>
        <button
          type="button"
          onClick={signOut}
          className="flex min-h-10 w-full items-center gap-3 rounded-lg px-2 text-sm text-zinc-700 hover:bg-zinc-100"
        >
          <LogOut className="h-4 w-4" aria-hidden />
          {t("auth.signOut")}
        </button>
      </div>
      {changing && <ChangePasswordDialog onClose={() => setChanging(false)} />}
      {unsent > 0 && (
        <Modal title={t("auth.unsentTitle")} onClose={() => setUnsent(0)}>
          <p className="text-sm">{t("auth.unsentExplain", { count: unsent })}</p>
          <div className="mt-4 flex flex-wrap gap-2">
            <Button variant="secondary" onClick={() => setUnsent(0)}>
              {t("auth.stayIn")}
            </Button>
            <Button variant="danger" onClick={() => void logout()}>
              {t("auth.signOutAnyway")}
            </Button>
          </div>
        </Modal>
      )}
    </div>
  );
}

export function Layout() {
  const { t } = useTranslation();
  const [open, setOpen] = useState(false);
  const location = useLocation();

  useEffect(() => setOpen(false), [location.pathname]);

  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && setOpen(false);
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open]);

  return (
    <div className="min-h-screen lg:flex">
      <aside className="hidden w-64 shrink-0 border-r border-zinc-200 bg-white lg:fixed lg:inset-y-0 lg:block">
        <Sidebar />
      </aside>

      <header className="sticky top-0 z-20 flex h-14 items-center gap-3 border-b border-zinc-200 bg-white px-4 lg:hidden">
        <button type="button" aria-label="Open menu" onClick={() => setOpen(true)} className="-ml-2 rounded-lg p-2 hover:bg-zinc-100">
          <Menu className="h-5 w-5" />
        </button>
        <span className="font-semibold">{t("app.name")}</span>
      </header>

      {open && (
        <div className="fixed inset-0 z-30 lg:hidden" role="dialog" aria-modal="true">
          <div className="absolute inset-0 bg-zinc-900/40" onClick={() => setOpen(false)} />
          <aside className="absolute inset-y-0 left-0 w-72 max-w-[85vw] bg-white shadow-xl">
            <button
              type="button"
              aria-label="Close menu"
              onClick={() => setOpen(false)}
              className="absolute right-3 top-3 rounded-lg p-2 hover:bg-zinc-100"
            >
              <X className="h-5 w-5" />
            </button>
            <Sidebar onNavigate={() => setOpen(false)} />
          </aside>
        </div>
      )}

      <main className="min-w-0 flex-1 px-4 py-6 sm:px-6 lg:ml-64 lg:px-8">
        <Outlet />
      </main>
    </div>
  );
}
