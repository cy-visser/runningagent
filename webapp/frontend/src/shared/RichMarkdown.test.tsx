import { describe, expect, it } from "vitest";
import "@testing-library/jest-dom/vitest";
import { render, screen } from "@testing-library/react";
import { TrendingDown } from "lucide-react";
import { RichMarkdown, StatusBadge, StatusPill, directionFromArrow } from "./RichMarkdown";

describe("status badges", () => {
  it("StatusPill renders an outline chip with an svg icon instead of a dot", () => {
    const { container } = render(<StatusPill tone="emerald" label="Safe Ramp" />);
    const badge = screen.getByTestId("status-badge");
    expect(badge).toHaveTextContent("Safe Ramp");
    expect(badge.className).toContain("border-emerald-300");
    expect(badge.className).toContain("bg-white");
    expect(badge.querySelector("svg")).not.toBeNull();
    expect(container.querySelector(".rounded-full")).toBeNull();
  });

  it("direction-aware badge uses the arrow for the icon and the tone for the colour", () => {
    expect(directionFromArrow("↓")).toBe("down");
    expect(directionFromArrow("↑")).toBe("up");
    expect(directionFromArrow("→")).toBe("flat");
    expect(directionFromArrow(undefined)).toBeUndefined();
    render(<StatusBadge tone="emerald" label="improving" direction="down" />);
    const svg = screen.getByTestId("status-badge").querySelector("svg");
    expect(svg?.getAttribute("class")).toContain("lucide-trending-down");
    expect(svg?.getAttribute("class")).toContain("text-emerald-600");
  });

  it("accepts an explicit lucide icon", () => {
    render(<StatusBadge tone="rose" label="Falling" icon={TrendingDown} />);
    expect(
      screen.getByTestId("status-badge").querySelector("svg")?.getAttribute("class"),
    ).toContain("lucide-trending-down");
  });
});

describe("RichMarkdown status emoji", () => {
  it("replaces a leading ✅ in a list item with an icon chip and keeps nested markup", () => {
    render(<RichMarkdown content={"- ✅ **Long run** done at 4:30/km\n- plain item"} />);
    const chips = screen.getAllByTestId("status-chip");
    expect(chips).toHaveLength(1);
    expect(chips[0].dataset.tone).toBe("emerald");
    expect(chips[0].querySelector("svg")).not.toBeNull();
    const li = chips[0].closest("li")!;
    expect(li.textContent).not.toContain("✅");
    expect(li.querySelector("strong")).toHaveTextContent("Long run");
    expect(li).toHaveTextContent("Long run done at 4:30/km");
  });

  it("handles ⚠️ with variation selector and emoji inside bold", () => {
    render(<RichMarkdown content={"- ⚠️ Watch HRV\n- **🔴 Missed:** tempo"} />);
    const chips = screen.getAllByTestId("status-chip");
    expect(chips.map((c) => c.dataset.tone)).toEqual(["amber", "rose"]);
    expect(document.body.textContent).not.toMatch(/[⚠🔴\uFE0F]/u);
    expect(screen.getByText("Missed:").tagName).toBe("STRONG");
  });

  it("renders a leading paragraph verdict as a hero badge", () => {
    render(<RichMarkdown content={"🟢 On Track. CTL has climbed to **61.4**."} />);
    const badge = screen.getByTestId("status-badge");
    expect(badge).toHaveTextContent("On Track");
    expect(screen.getByText("61.4").tagName).toBe("STRONG");
    expect(document.body.textContent).not.toContain("🟢");
  });

  it("renders a paragraph that is only a verdict as a hero badge", () => {
    render(<RichMarkdown content={"🟡 At Risk"} />);
    expect(screen.getByTestId("status-badge")).toHaveTextContent("At Risk");
  });

  it("table cells with a leading status use the badge", () => {
    render(<RichMarkdown content={"| a | b |\n|---|---|\n| x | ✅ Hit — 4:05/km |"} />);
    expect(screen.getByTestId("status-badge")).toHaveTextContent("Hit");
    expect(screen.getByText("4:05/km")).toBeInTheDocument();
  });
});

describe("solid status chip", () => {
  it("fills the chip with the tone colour and a white icon", () => {
    render(<RichMarkdown content={"- 🟢 Good spacing\n- 🟡 Watch ramp\n- 🔴 Missed taper"} />);
    const chips = screen.getAllByTestId("status-chip");
    expect(chips[0].className).toContain("bg-emerald-600");
    expect(chips[1].className).toContain("bg-amber-500");
    expect(chips[2].className).toContain("bg-rose-600");
    expect(chips[0].className).not.toContain("bg-white");
    expect(chips[0].querySelector("svg")?.getAttribute("class")).toContain("text-white");
  });
});

describe("recommendation bullet style", () => {
  it("replaces bullets with Flag / Star / Lightbulb icons", () => {
    render(
      <RichMarkdown
        bulletStyle="recommendation"
        content={
          "- **Sub goal (HM):** cap tempo at LTHR\n" +
          "- **North star:** hold 24 km\n" +
          "- Add a strides session"
        }
      />,
    );
    const icons = screen.getAllByTestId("recommendation-icon");
    expect(icons.map((i) => i.dataset.icon)).toEqual(["subgoal", "northstar", "tip"]);
    expect(icons[0].querySelector("svg")?.getAttribute("class")).toContain("lucide-flag");
    expect(icons[1].querySelector("svg")?.getAttribute("class")).toContain("lucide-star");
    expect(icons[2].querySelector("svg")?.getAttribute("class")).toContain("lucide-lightbulb");
    expect(document.querySelector("ul")?.className).not.toContain("list-disc");
  });

  it("uses a non-status indigo fill so recommendations don't read as problems", () => {
    render(<RichMarkdown bulletStyle="recommendation" content={"- Add a strides session"} />);
    const icon = screen.getByTestId("recommendation-icon");
    expect(icon.className).toContain("bg-indigo-600");
    expect(icon.className).not.toMatch(/sunset|rose|red/);
  });

  it("nested items inherit the parent's goal icon", () => {
    render(
      <RichMarkdown
        bulletStyle="recommendation"
        content={"- **North star**\n  - hold 24 km\n  - step to 26 km\n- **Sub goal**\n  - cap tempo"}
      />,
    );
    const icons = screen.getAllByTestId("recommendation-icon").map((i) => i.dataset.icon);
    expect(icons).toEqual(["northstar", "northstar", "northstar", "subgoal", "subgoal"]);
  });

  it("default style keeps plain bullets", () => {
    render(<RichMarkdown content={"- **Sub goal:** x"} />);
    expect(screen.queryByTestId("recommendation-icon")).toBeNull();
    expect(document.querySelector("ul")?.className).toContain("list-disc");
  });
});


describe("RichMarkdown sub-headings", () => {
  it("styles #### to ###### headings and thematic breaks instead of leaving them as body text", () => {
    const { container } = render(
      <RichMarkdown content={"### Execution\n\n#### Pacing & Quality Execution\ntext\n\n---\n\n##### Detail\n\n###### Note"} />,
    );
    const h4 = screen.getByRole("heading", { level: 4, name: "Pacing & Quality Execution" });
    expect(h4).toHaveClass("font-display", "font-semibold");
    expect(screen.getByRole("heading", { level: 5, name: "Detail" })).toHaveClass("font-semibold");
    expect(screen.getByRole("heading", { level: 6, name: "Note" })).toHaveClass("font-semibold");
    expect(container.querySelector("hr")).toHaveClass("border-slate-200");
  });
});
