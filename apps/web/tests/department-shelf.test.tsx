/**
 * The department page's category controls: chips inside a group, carrying an
 * icon only where the department's set is drawn (plain chips elsewhere), and
 * the light "Biggest in" shortcut pills that name their group.
 */
import { render } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { CategoryChip, ShortcutPill } from "@/app/(site)/departments/_components/browse-tile";

describe("category chips and shortcut pills", () => {
  it("a chip carries its icon when the department is drawn", () => {
    const { container } = render(
      <CategoryChip
        href="/departments/electronics/resistors"
        iconRef="electronics:resistors"
        label="Resistors"
        count={2704}
        withIcon
      />,
    );
    expect(container.querySelector("svg[data-icon='electronics:resistors']")).not.toBeNull();
    expect(container.textContent).toBe("Resistors 2,704");
  });

  it("a chip is plain in a department without icons", () => {
    const { container } = render(
      <CategoryChip
        href="/departments/seals-bearings/o-rings"
        iconRef="seals-bearings:o-rings"
        label="O-Rings"
        count={400}
        current
        withIcon={false}
      />,
    );
    expect(container.querySelector("svg")).toBeNull();
    expect(container.querySelector("a")?.getAttribute("aria-current")).toBe("page");
  });

  it("a shortcut names its group and count", () => {
    const { container } = render(
      <ShortcutPill
        href="/departments/electronics/measurement"
        iconRef="electronics:measurement"
        label="Measurement & Test"
        group="Tools & Equipment"
        count={1143}
        withIcon
      />,
    );
    expect(container.textContent).toBe("Measurement & Test · Tools & Equipment 1,143");
    expect(container.querySelector("svg[data-icon='electronics:measurement']")).not.toBeNull();
  });
});
