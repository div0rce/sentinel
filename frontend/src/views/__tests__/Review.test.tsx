import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { Review } from "../Review";

interface ReviewItemFixture {
  id: number;
  extraction_id: number;
  status: "needs_review";
  reason: string | null;
  idempotency_key: string;
  created_at: string;
  updated_at: string;
}

function makeItem(id: number): ReviewItemFixture {
  return {
    id,
    extraction_id: id * 10,
    status: "needs_review",
    reason: "low_confidence",
    idempotency_key: "deadbeef" + String(id).padStart(8, "0"),
    created_at: "2026-05-29T01:00:00Z",
    updated_at: "2026-05-29T01:00:00Z",
  };
}

function makeFetchSequence(responses: Array<{ ok?: boolean; body: unknown; status?: number }>) {
  const fn = vi.fn();
  for (const { ok = true, status = 200, body } of responses) {
    fn.mockResolvedValueOnce({
      ok,
      status,
      json: vi.fn().mockResolvedValue(body),
    });
  }
  return fn;
}

describe("Review view", () => {
  beforeEach(() => {
    vi.unstubAllGlobals();
  });
  afterEach(() => {
    vi.unstubAllGlobals();
    vi.restoreAllMocks();
  });

  it("loads the queue and renders items", async () => {
    vi.stubGlobal(
      "fetch",
      makeFetchSequence([{ body: { items: [makeItem(1), makeItem(2)] } }]),
    );
    render(<Review />);
    await waitFor(() => {
      expect(screen.getByTestId("review-item-1")).toBeInTheDocument();
      expect(screen.getByTestId("review-item-2")).toBeInTheDocument();
    });
    expect(screen.getAllByText(/needs_review/i).length).toBeGreaterThanOrEqual(2);
  });

  it("approves an item and removes it from the queue", async () => {
    const fetchMock = makeFetchSequence([
      { body: { items: [makeItem(1), makeItem(2)] } }, // initial load
      {
        body: { id: 1, extraction_id: 10, status: "auto_approved", audit_event_id: 99 },
      }, // approve
    ]);
    vi.stubGlobal("fetch", fetchMock);

    const user = userEvent.setup();
    render(<Review />);

    await waitFor(() => screen.getByTestId("review-item-1"));

    const approveButtons = screen.getAllByRole("button", { name: /approve/i });
    await user.click(approveButtons[0]!);

    await waitFor(() => {
      expect(screen.queryByTestId("review-item-1")).not.toBeInTheDocument();
    });
    // Second item still there.
    expect(screen.getByTestId("review-item-2")).toBeInTheDocument();
    // Status flash visible, surfacing the real audit-event id from the decision response.
    expect(screen.getByRole("status")).toHaveTextContent(/Item #1 approved/i);
    expect(screen.getByRole("status")).toHaveTextContent(/audit event #99/i);

    // Verify the fetch payload was the approve endpoint with the actor body.
    const lastCall = fetchMock.mock.calls.at(-1);
    expect(lastCall?.[0]).toContain("/review/1/approve");
    const init = lastCall?.[1] as RequestInit | undefined;
    const sentBody = init?.body ? JSON.parse(String(init.body)) : null;
    expect(sentBody).toMatchObject({ actor: expect.any(String) });
  });

  it("renders the empty state when the queue is empty", async () => {
    vi.stubGlobal("fetch", makeFetchSequence([{ body: { items: [] } }]));
    render(<Review />);
    await waitFor(() => {
      expect(screen.getByText(/queue is empty/i)).toBeInTheDocument();
    });
  });
});
