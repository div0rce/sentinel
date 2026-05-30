import { Suspense, lazy } from "react";
import { NavLink, Route, Routes, useLocation } from "react-router-dom";
import { BarChart3, Moon, Search, ShieldCheck, Sun } from "lucide-react";
import { useTheme } from "./theme";
import { Query } from "./views/Query";
import { Review } from "./views/Review";

// Dashboard is the only Recharts consumer. Lazy-loading it splits the Recharts +
// d3 vendor bundle off the initial download path so visitors who never open
// /dashboard never pay for it. See issue #10.
const Dashboard = lazy(() =>
  import("./views/Dashboard").then((module) => ({ default: module.Dashboard })),
);

export function App(): JSX.Element {
  const location = useLocation();
  const { theme, toggleTheme } = useTheme();
  const queryTarget = { pathname: "/", search: location.search };
  const reviewTarget = { pathname: "/review", search: location.search };
  const dashboardTarget = { pathname: "/dashboard", search: location.search };
  const wordmark =
    theme === "light" ? "/brand/sentinel-wordmark-light.svg" : "/brand/sentinel-wordmark.svg";

  return (
    <div className="app">
      <header className="hdr">
        <span className="brand">
          <img src={wordmark} alt="Sentinel" />
        </span>
        <nav>
          <NavLink to={queryTarget} end className={({ isActive }) => "nav-link" + (isActive ? " active" : "")}>
            <Search size={15} aria-hidden />
            Query
          </NavLink>
          <NavLink to={reviewTarget} className={({ isActive }) => "nav-link" + (isActive ? " active" : "")}>
            <ShieldCheck size={15} aria-hidden />
            Review
          </NavLink>
          <NavLink to={dashboardTarget} className={({ isActive }) => "nav-link" + (isActive ? " active" : "")}>
            <BarChart3 size={15} aria-hidden />
            Dashboard
          </NavLink>
        </nav>
        <span className="tag">
          <span className="dot" />
          synthetic data only
        </span>
        <button
          type="button"
          className="theme-toggle"
          onClick={toggleTheme}
          title={theme === "light" ? "Switch to dark theme" : "Switch to light theme"}
          aria-label="Toggle theme"
        >
          {theme === "light" ? <Moon size={16} aria-hidden /> : <Sun size={16} aria-hidden />}
        </button>
      </header>
      <main className="main">
        <Suspense fallback={<p className="muted">Loading…</p>}>
          <Routes>
            <Route path="/" element={<Query />} />
            <Route path="/review" element={<Review />} />
            <Route path="/dashboard" element={<Dashboard />} />
            <Route
              path="*"
              element={<p className="muted">Not found. Try Query, Review, or Dashboard.</p>}
            />
          </Routes>
        </Suspense>
      </main>
    </div>
  );
}
