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

describe("RichMarkdown status emoji stripping, generic pills & issue callouts", () => {
  it("strips positive/neutral emojis (✅/🟢/⚪) and renders plain sparkle BulletIcons", () => {
    render(<RichMarkdown content={"- ✅ **Long run** done at 4:30/km\n- ⚪ Neutral note\n- plain item"} />);
    expect(screen.queryByTestId("status-chip")).toBeNull();
    expect(screen.queryByTestId("issue-item")).toBeNull();
    const icons = screen.getAllByTestId("bullet-icon");
    expect(icons).toHaveLength(3);
    expect(document.body.textContent).not.toMatch(/[✅⚪]/u);
    expect(screen.getByText("Long run").tagName).toBe("STRONG");
    expect(screen.getByText("Long run").closest("li")).toHaveTextContent("Long run done at 4:30/km");
  });

  it("renders ⚠️/🟡 and 🔴/❌ bullets (including nested inside bold) as amber/rose issue callout rows", () => {
    render(<RichMarkdown content={"- ⚠️ Watch HRV\n- **🔴 Missed:** tempo"} />);
    expect(screen.queryByTestId("bullet-icon")).toBeNull();
    const items = screen.getAllByTestId("issue-item");
    expect(items).toHaveLength(2);
    expect(items.map((el) => el.dataset.tone)).toEqual(["amber", "rose"]);
    expect(items[0].className).toContain("bg-amber-50/75");
    expect(items[1].className).toContain("bg-rose-50/75");
    const icons = screen.getAllByTestId("issue-icon");
    expect(icons.map((el) => el.dataset.tone)).toEqual(["amber", "rose"]);
    expect(document.body.textContent).not.toMatch(/[⚠🔴\uFE0F]/u);
    expect(screen.getByText("Missed:").tagName).toBe("STRONG");
  });

  it("renders standalone ⚠️/🔴 paragraphs as issue callout rows while keeping headings and table cells clean", () => {
    render(
      <RichMarkdown
        content={
          "### 🟢 Assessment\n\n🟢 On Track. CTL has climbed to **61.4**.\n\n⚠️ **Spacing watch:** Keep 48h between quality runs.\n\n| a | b |\n|---|---|\n| x | ✅ Hit — 4:05/km |"
        }
      />,
    );
    expect(screen.queryByTestId("status-badge")).toBeNull();
    const callout = screen.getByTestId("issue-callout");
    expect(callout).toHaveAttribute("data-tone", "amber");
    expect(callout).toHaveTextContent("Spacing watch: Keep 48h between quality runs.");
    expect(screen.getByRole("heading", { level: 3, name: "Assessment" })).toBeInTheDocument();
    expect(screen.getByText("61.4").tagName).toBe("STRONG");
    expect(screen.getByText("Hit — 4:05/km")).toBeInTheDocument();
    expect(document.body.textContent).not.toMatch(/[🟢✅⚠]/u);
  });
});

describe("default bullet icons and number badges", () => {
  it("replaces every plain bullet with a gradient sparkle, smaller and outlined when nested", () => {
    render(<RichMarkdown content={"- Rep 1: 4:53/km\n- Rep 2: 4:53/km\n  - spread 1 s/km\n- Rep 3: 4:54/km"} />);
    const icons = screen.getAllByTestId("bullet-icon");
    expect(icons.map((i) => i.dataset.depth)).toEqual(["0", "0", "1", "0"]);
    expect(icons[0].querySelector("linearGradient")).not.toBeNull();
    expect(icons[2].querySelector("linearGradient")).toBeNull();
    expect(document.querySelector("ul")?.className).toContain("list-none");
    expect(screen.getByText("Rep 1: 4:53/km").closest("li")).toHaveClass("flex");
  });

  it("numbers ordered lists with badges, honours start numbers, and highlights ordered issue items", () => {
    render(<RichMarkdown content={"1. ✅ Warm up\n2. 🔴 Back-to-back quality conflict\n\ntext\n\n3. Cool down\n4. Stretch"} />);
    const badges = screen.getAllByTestId("number-badge").map((b) => b.textContent);
    expect(badges).toEqual(["1", "2", "3", "4"]);
    expect(screen.queryByTestId("bullet-icon")).toBeNull();
    expect(screen.getByTestId("issue-item")).toHaveAttribute("data-tone", "rose");
    expect(document.body.textContent).not.toMatch(/[✅🔴]/u);
    expect(document.querySelector("ol")?.className).not.toContain("list-decimal");
  });

  it("loose list items style ⚠️ items as issue rows without nested callout boxes and keep plain items as sparkles", () => {
    render(<RichMarkdown content={"- ⚠️ Watch HRV\n\n- plain loose item"} />);
    expect(screen.getAllByTestId("issue-item")).toHaveLength(1);
    expect(screen.queryByTestId("issue-callout")).toBeNull();
    expect(screen.getAllByTestId("bullet-icon")).toHaveLength(1);
    expect(document.body.textContent).not.toMatch(/⚠/u);
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
