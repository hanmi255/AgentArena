import { useEffect, useRef, useState } from "react";
import { Link, NavLink, Route, Routes, useLocation } from "react-router-dom";
import {
  ArrowUpRight,
  BookOpen,
  ChevronRight,
  Command,
  FlaskConical,
  LayoutGrid,
  Menu,
  Settings2,
  Swords,
  X,
  Zap,
} from "lucide-react";
import { useResource } from "./api";
import type { Catalog } from "./types";
import { ErrorState, Loading, ToastProvider } from "./components/ui";
import { Dashboard } from "./pages/Dashboard";
import { ArenaPage } from "./pages/ArenaPage";
import { StrategiesPage } from "./pages/StrategiesPage";
import { ExperimentsPage } from "./pages/ExperimentsPage";
import { SettingsPage } from "./pages/SettingsPage";

const NAVIGATION = [
  { to: "/", name: "竞技场", en: "ARENA", icon: LayoutGrid },
  { to: "/strategies", name: "策略库", en: "STRATEGIES", icon: Zap },
  { to: "/experiments", name: "实验室", en: "LABORATORY", icon: FlaskConical },
];

export default function App() {
  const { data: catalog, error, reload } = useResource<Catalog>("/catalog");
  const [mobileOpen, setMobileOpen] = useState(false);
  const mobileDialog = useRef<HTMLDialogElement>(null);
  useEffect(() => {
    if (mobileOpen) mobileDialog.current?.showModal();
    else mobileDialog.current?.close();
  }, [mobileOpen]);
  const location = useLocation();
  const arenaView = location.pathname.startsWith("/arenas/");
  const pageName = arenaView
    ? "对局实况"
    : location.pathname === "/settings"
      ? "运行设置"
      : NAVIGATION.find((item) => item.to === location.pathname)?.name ||
        "竞技场";
  const nav = (
    <>
      <Link to="/" className="brand" onClick={() => setMobileOpen(false)}>
        <span className="brand-mark">
          <span>A</span>
          <i />
        </span>
        <span>
          Agent<span>Arena</span>
          <small>THE AGENT ECONOMY</small>
        </span>
      </Link>
      <div className="nav-section-label">WORKSPACE</div>
      <nav className="main-navigation" aria-label="主导航">
        {NAVIGATION.map((item) => (
          <NavLink
            key={item.to}
            to={item.to}
            end={item.to === "/"}
            className={({ isActive }) =>
              `nav-item ${isActive || (item.to === "/" && arenaView) ? "active" : ""}`
            }
            onClick={() => setMobileOpen(false)}
          >
            <item.icon size={19} strokeWidth={1.7} />
            <span>
              {item.name}
              <small>{item.en}</small>
            </span>
            <ChevronRight size={14} />
          </NavLink>
        ))}
      </nav>
      <div className="sidebar-bottom">
        <div className="sidebar-rule" />
        <NavLink
          to="/settings"
          className={({ isActive }) =>
            `nav-item settings-nav ${isActive ? "active" : ""}`
          }
          onClick={() => setMobileOpen(false)}
        >
          <Settings2 size={18} />
          <span>运行设置</span>
        </NavLink>
        <a
          className="sidebar-docs"
          href="/api/docs"
          target="_blank"
          rel="noreferrer"
        >
          <BookOpen size={15} />
          API 文档
          <ArrowUpRight size={14} />
        </a>
        <div className="sidebar-version">
          <span>
            <i />
            SYSTEM ONLINE
          </span>
          <small>v1.0</small>
        </div>
      </div>
    </>
  );
  return (
    <ToastProvider>
      <div className="app-shell">
        <a className="skip-link" href="#main-content">
          跳到主内容
        </a>
        <aside className="sidebar">{nav}</aside>
        <dialog
          ref={mobileDialog}
          className="mobile-nav-dialog"
          aria-label="工作台导航"
          onCancel={() => setMobileOpen(false)}
          onClick={(event) => {
            if (event.target === mobileDialog.current) setMobileOpen(false);
          }}
        >
          <aside className="mobile-nav">
            <button
              className="mobile-close icon-button"
              aria-label="关闭导航"
              onClick={() => setMobileOpen(false)}
            >
              <X size={20} />
            </button>
            {nav}
          </aside>
        </dialog>
        <div className="app-body">
          <header className="topbar">
            <button
              className="mobile-toggle icon-button"
              aria-label="打开导航"
              onClick={() => setMobileOpen(true)}
            >
              <Menu size={22} />
            </button>
            <div className="breadcrumbs">
              <span>工作空间</span>
              <ChevronRight size={13} />
              <strong>{pageName}</strong>
            </div>
            <div className="topbar-right">
              <span className="environment-label">
                <i />
                LOCAL WORKSPACE
              </span>
              <span className="topbar-avatar">AA</span>
            </div>
          </header>
          <main
            id="main-content"
            className={`main-content ${arenaView ? "arena-content" : ""}`}
          >
            {error ? (
              <ErrorState message={error} retry={reload} />
            ) : !catalog ? (
              <Loading />
            ) : (
              <Routes>
                <Route path="/" element={<Dashboard catalog={catalog} />} />
                <Route path="/arenas/:id" element={<ArenaPage />} />
                <Route path="/strategies" element={<StrategiesPage />} />
                <Route
                  path="/experiments"
                  element={<ExperimentsPage catalog={catalog} />}
                />
                <Route path="/settings" element={<SettingsPage />} />
                <Route
                  path="*"
                  element={
                    <div className="not-found">
                      <h1>找不到这个页面</h1>
                      <Link to="/">返回竞技场</Link>
                    </div>
                  }
                />
              </Routes>
            )}
          </main>
        </div>
      </div>
    </ToastProvider>
  );
}
