import { describe, expect, it, vi } from "vitest";
import "@testing-library/jest-dom/vitest";
import { render, screen } from "@testing-library/react";
import { DEMO_AUDIT_DATA, DEMO_AUDIT_MARKDOWN } from "../../demo/fixtures";
import { AuditReport } from "./AuditReport";

vi.mock("./AuditCharts", () => ({
  default: () => <div data-testid="audit-charts" />,
}));

describe("schedule audit feature", () => {
  it("renders AuditReport with weekly volume totals and schedule evaluation markdown", () => {
    render(
      <AuditReport data={DEMO_AUDIT_DATA} markdown={DEMO_AUDIT_MARKDOWN} />,
    );
    expect(screen.getByText("Schedule Audit")).toBeInTheDocument();
    expect(screen.getByText("279.0 km total")).toBeInTheDocument();
    expect(screen.getByText("Schedule Evaluation")).toBeInTheDocument();
    expect(screen.getByText("Recommended Adjustments")).toBeInTheDocument();
  });
});
