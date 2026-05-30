import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, useLocation } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { App } from "../App";

function LocationProbe(): JSX.Element {
  const location = useLocation();
  return (
    <output aria-label="current location">
      {location.pathname}
      {location.search}
    </output>
  );
}

function renderAppAt(path: string): void {
  render(
    <MemoryRouter initialEntries={[path]}>
      <App />
      <LocationProbe />
    </MemoryRouter>,
  );
}

describe("App navigation", () => {
  beforeEach(() => {
    class ResizeObserverStub {
      observe(): void {}
      unobserve(): void {}
      disconnect(): void {}
    }

    vi.stubGlobal("ResizeObserver", ResizeObserverStub);
    vi.stubGlobal(
      "fetch",
      vi.fn(async (input: RequestInfo | URL) => {
        const url = String(input);
        let body: unknown;
        if (url.includes("/review")) {
          body = { items: [] };
        } else if (url.includes("/dashboard/kpis")) {
          body = { kpis: [], threshold_hours: 24, generated_at: "2026-05-29T00:00:00Z" };
        } else if (url.includes("/dashboard/volume")) {
          body = { days: 30, points: [] };
        } else if (url.includes("/dashboard/categories")) {
          body = { points: [] };
        } else if (url.includes("/dashboard/confidence")) {
          body = { buckets: [], total_fields: 0 };
        } else if (url.includes("/dashboard/sla")) {
          body = { threshold_hours: 24, total_needs_review: 0, over_sla: 0, buckets: [] };
        } else {
          body = {};
        }
        return {
          ok: true,
          status: 200,
          json: vi.fn().mockResolvedValue(body),
        };
      }),
    );
  });

  afterEach(() => {
    vi.unstubAllGlobals();
    vi.restoreAllMocks();
  });

  it("preserves existing query parameters when navigating", async () => {
    const user = userEvent.setup();
    renderAppAt("/?api=http://localhost:8000");

    await user.click(screen.getByRole("link", { name: /^review$/i }));
    expect(screen.getByLabelText("current location")).toHaveTextContent(
      "/review?api=http://localhost:8000",
    );

    await user.click(screen.getByRole("link", { name: /^dashboard$/i }));
    expect(screen.getByLabelText("current location")).toHaveTextContent(
      "/dashboard?api=http://localhost:8000",
    );
  });
});
