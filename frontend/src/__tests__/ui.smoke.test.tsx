import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import { KpiCard } from "@prosper/ui";
import { Badge } from "@prosper/ui";
import { StatusDot } from "@prosper/ui";

describe("Phase 0 — UI smoke", () => {
  it("KpiCard renders label and value", () => {
    render(<KpiCard label="AUM" value="$42.3M" delta={0.025} />);
    expect(screen.getByText("AUM")).toBeInTheDocument();
    expect(screen.getByText("$42.3M")).toBeInTheDocument();
    expect(screen.getByText(/2.50%/)).toBeInTheDocument();
  });

  it("Badge picks tone automatically from status string", () => {
    const { getByText } = render(<Badge tone="auto">approved</Badge>);
    expect(getByText("approved")).toBeInTheDocument();
  });

  it("StatusDot renders without crashing", () => {
    render(<StatusDot color="green" label="Healthy" />);
    expect(screen.getByText("Healthy")).toBeInTheDocument();
  });
});
