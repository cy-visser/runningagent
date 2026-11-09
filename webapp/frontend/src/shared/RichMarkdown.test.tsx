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

  it("default style uses the sparkle, not recommendation icons", () => {
    render(<RichMarkdown content={"- **Sub goal:** x"} />);
    expect(screen.queryByTestId("recommendation-icon")).toBeNull();
    expect(screen.getByTestId("bullet-icon")).toBeInTheDocument();
    expect(document.querySelector("ul")?.className).not.toContain("list-disc");
  });
});

describe("default bullet icons", () => {
  it("replaces every plain bullet with a gradient sparkle, smaller and outlined when nested", () => {
    render(<RichMarkdown content={"- Rep 1: 4:53/km\n- Rep 2: 4:53/km\n  - spread 1 s/km\n- Rep 3: 4:54/km"} />);
    const icons = screen.getAllByTestId("bullet-icon");
    expect(icons.map((i) => i.dataset.depth)).toEqual(["0", "0", "1", "0"]);
    expect(icons[0].querySelector("linearGradient")).not.toBeNull();
    expect(icons[2].querySelector("linearGradient")).toBeNull();
    expect(document.querySelector("ul")?.className).toContain("list-none");
    expect(screen.getByText("Rep 1: 4:53/km").closest("li")).toHaveClass("flex");
  });

  it("numbers ordered lists with badges and honours the start number", () => {
    render(<RichMarkdown content={"1. Warm up\n2. 3 x 2 km\n\ntext\n\n3. Cool down\n4. Stretch"} />);
    const badges = screen.getAllByTestId("number-badge").map((b) => b.textContent);
    expect(badges).toEqual(["1", "2", "3", "4"]);
    expect(screen.queryByTestId("bullet-icon")).toBeNull();
    expect(document.querySelector("ol")?.className).not.toContain("list-decimal");
  });

  it("status-emoji items keep only their status chip", () => {
    render(<RichMarkdown content={"- ✅ Hit\n- plain"} />);
    expect(screen.getAllByTestId("status-chip")).toHaveLength(1);
    expect(screen.getAllByTestId("bullet-icon")).toHaveLength(1);
  });

  it("loose list items with a status emoji get no extra sparkle", () => {
    render(<RichMarkdown content={"- ⚠️ Watch HRV\n\n- plain loose item"} />);
    expect(screen.getAllByTestId("status-chip")).toHaveLength(1);
    expect(screen.getAllByTestId("bullet-icon")).toHaveLength(1);
    expect(screen.getByText("plain loose item").closest("li")?.querySelector("[data-testid=bullet-icon]")).not.toBeNull();
  });

  it("task list items keep their checkbox", () => {
    render(<RichMarkdown content={"- [ ] book physio\n- [x] buy gels"} />);
    expect(screen.getAllByRole("checkbox")).toHaveLength(2);
    expect(screen.queryByTestId("bullet-icon")).toBeNull();
  });

  it("relaxed spacing gives sections more room and a hairline above all but the first", () => {
    render(<RichMarkdown spacing="relaxed" content={"### A\n\ntext\n\n### B\n\n#### Sub\n\nmore"} />);
    const [a, b] = screen.getAllByRole("heading", { level: 3 });
    expect(b).toHaveClass("mt-8", "border-t", "pt-6");
    expect(a).toHaveClass("first:border-t-0");
    expect(screen.getByRole("heading", { level: 4 })).toHaveClass("mt-5");
    expect(document.querySelector("[data-spacing=relaxed]")).toHaveClass("space-y-4");
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

describe("RichMarkdown model formatting drift", () => {
  it("renders LaTeX as plain text and <br> in table cells as a line break, keeping other HTML escaped", () => {
    // Trimmed from a real coach reply ("how does a 100k week look like for me").
    const content = [
      "Volume is capped to prioritize speed and $\\text{VO}_2\\text{max}$ without overload.",
      "Pace moved $4{:}37 \\rightarrow 4{:}32$/km; shoes cost $5 and $10. Code `$\\text{x}$` stays.",
      "",
      "| Day | Target Pace & HR |",
      "|---|---|",
      "| **Tuesday** | Quality: 4:45–5:00/km (HR 158–168)<br>Easy: 5:25–5:38/km |",
      "| **Friday** | MP: 4:55–5:05/km<br/>Easy <script>alert(1)</script> |",
    ].join("\n");
    const { container } = render(<RichMarkdown content={content} />);
    const text = container.textContent ?? "";

    expect(text).toContain("speed and VO₂max without");
    expect(text).toContain("4:37 → 4:32/km");
    expect(text).toContain("cost $5 and $10");
    expect(container.querySelector("code")).toHaveTextContent("$\\text{x}$");
    expect(text.replace(container.querySelector("code")!.textContent!, "")).not.toMatch(/\\text|\\rightarrow/);

    const cells = container.querySelectorAll("td");
    expect(text).not.toMatch(/<br\s*\/?>/i);
    expect(cells[1].querySelector("br")).not.toBeNull();
    expect(cells[1]).toHaveTextContent("(HR 158–168)Easy: 5:25–5:38/km");
    expect(cells[3].querySelector("br")).not.toBeNull();
    expect(container.querySelector("script")).toBeNull();
    expect(cells[3]).toHaveTextContent("<script>alert(1)</script>");
  });
});
