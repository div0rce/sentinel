import { NavLink, Route, Routes } from "react-router-dom";
import { Query } from "./views/Query";
import { Review } from "./views/Review";
import { Dashboard } from "./views/Dashboard";

export function App(): JSX.Element {
  return (
    <div className="app">
      <header className="app-header">
        <h1>Sentinel</h1>
        <nav>
          <NavLink to="/" end className={({ isActive }) => (isActive ? "active" : "")}>
            Query
          </NavLink>
          <NavLink to="/review" className={({ isActive }) => (isActive ? "active" : "")}>
            Review
          </NavLink>
          <NavLink to="/dashboard" className={({ isActive }) => (isActive ? "active" : "")}>
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
