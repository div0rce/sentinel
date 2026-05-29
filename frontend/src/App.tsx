import { NavLink, Route, Routes, useLocation } from "react-router-dom";
import { Query } from "./views/Query";
import { Review } from "./views/Review";
import { Dashboard } from "./views/Dashboard";

export function App(): JSX.Element {
  const location = useLocation();
  const queryTarget = { pathname: "/", search: location.search };
  const reviewTarget = { pathname: "/review", search: location.search };
  const dashboardTarget = { pathname: "/dashboard", search: location.search };

  return (
    <div className="app">
      <header className="app-header">
        <h1>Sentinel</h1>
        <nav>
          <NavLink to={queryTarget} end className={({ isActive }) => (isActive ? "active" : "")}>
            Query
          </NavLink>
          <NavLink to={reviewTarget} className={({ isActive }) => (isActive ? "active" : "")}>
            Review
          </NavLink>
          <NavLink to={dashboardTarget} className={({ isActive }) => (isActive ? "active" : "")}>
            Dashboard
          </NavLink>
        </nav>
        <span className="muted" style={{ marginLeft: "auto" }}>
          synthetic data only
        </span>
      </header>
      <main className="app-main">
        <Routes>
          <Route path="/" element={<Query />} />
          <Route path="/review" element={<Review />} />
          <Route path="/dashboard" element={<Dashboard />} />
          <Route
            path="*"
            element={<p className="muted">Not found. Try Query, Review, or Dashboard.</p>}
          />
        </Routes>
      </main>
    </div>
  );
}
