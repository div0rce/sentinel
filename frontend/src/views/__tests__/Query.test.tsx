import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { Query } from "../Query";

interface FetchMockBody {
  status: "answered" | "refused";
  answer: string;
  citations: { chunk_id: number; document_id: number; score: number; text: string }[];
  reason: string | null;
}

function mockFetchOnce(body: FetchMockBody, init: { ok?: boolean; status?: number } = {}): void {
  const ok = init.ok ?? true;
  const status = init.status ?? (ok ? 200 : 500);
  vi.stubGlobal(
    "fetch",
    vi.fn().mockResolvedValue({
      ok,
      status,
      json: vi.fn().mockResolvedValue(body),
    }),
  );
}

describe("Query view", () => {
  beforeEach(() => {
    vi.unstubAllGlobals();
  });
  afterEach(() => {
    vi.unstubAllGlobals();
    vi.restoreAllMocks();
  });

  it("renders the input and the disabled-by-default Ask button", () => {
    render(<Query />);
    expect(screen.getByRole("textbox")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /^ask$/i })).toBeDisabled();
  });

  it("submits a question, renders the answer and a citation", async () => {
    mockFetchOnce({
      status: "answered",
      answer: "The synthetic vendor is Acme [chunk:7].",
      citations: [
        { chunk_id: 7, document_id: 3, score: 0.91, text: "Vendor: Acme Synthetic Co." },
      ],
      reason: null,
    });

    const user = userEvent.setup();
    render(<Query />);

    await user.type(screen.getByRole("textbox"), "Who is the vendor?");
    expect(screen.getByRole("button", { name: /^ask$/i })).toBeEnabled();

    await user.click(screen.getByRole("button", { name: /^ask$/i }));

    await waitFor(() => {
      // The answer heading now leads with a `cited` status badge, so the accessible
      // name is "cited Answer" — match on the substring rather than the whole string.
      expect(screen.getByRole("heading", { name: /answer/i })).toBeInTheDocument();
    });
    expect(screen.getByText(/Acme Synthetic Co\./)).toBeInTheDocument();
    expect(screen.getByText(/Citations \(1\)/)).toBeInTheDocument();
    expect(screen.getByText(/chunk #7/)).toBeInTheDocument();
  });

  it("shows the deliberate refusal when the API returns refused", async () => {
    mockFetchOnce({
      status: "refused",
      answer: "I cannot answer based on the provided context.",
      citations: [],
      reason: "no_support",
    });
    const user = userEvent.setup();
    render(<Query />);
    await user.type(screen.getByRole("textbox"), "Anything?");
    await user.click(screen.getByRole("button", { name: /^ask$/i }));
    await waitFor(() => {
      // Heading leads with a `refused` badge: accessible name is "refused Refused".
      expect(screen.getByRole("heading", { name: /refused/i })).toBeInTheDocument();
    });
    expect(screen.getByText(/no_support/)).toBeInTheDocument();
  });
});
