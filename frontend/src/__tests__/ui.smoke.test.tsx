import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import { KpiCard, Badge, StatusDot, PageHeader } from "@prosper/ui";

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

  it("PageHeader renders title, subtitle, breadcrumbs and right-side actions", () => {
    render(
      <PageHeader
        breadcrumbs={[
          { label: "Admin", href: "/admin" },
          { label: "Compliance Reviews" },
        ]}
        kicker="Admin · Phase 0"
        title="KYB Queue"
        subtitle="KYB / KYC, sanciones, PEP."
        actions={<button data-testid="hdr-act">Refresh</button>}
      />,
    );
    expect(screen.getByText("KYB Queue")).toBeInTheDocument();
    expect(screen.getByText("KYB / KYC, sanciones, PEP.")).toBeInTheDocument();
    const adminLink = screen.getByText("Admin");
    expect(adminLink.getAttribute("href")).toBe("/admin");
    // last crumb is not linked
    const lastCrumb = screen.getByText("Compliance Reviews");
    expect(lastCrumb.tagName.toLowerCase()).toBe("span");
    expect(screen.getByTestId("page-header-actions")).toBeInTheDocument();
    expect(screen.getByTestId("hdr-act")).toBeInTheDocument();
    expect(screen.getByTestId("page-breadcrumbs")).toBeInTheDocument();
    expect(screen.getByTestId("page-header")).toBeInTheDocument();
  });
});
