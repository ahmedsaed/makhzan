/**
 * Opening hours in plain English: schema.org's machine strings rewritten for
 * a buyer whose week starts on Saturday, and anything else left exactly as
 * written.
 */
import { describe, expect, it } from "vitest";

import { daysText, formatOpeningHours, openingHoursLine, parseOpeningHoursLine } from "@/lib/hours";

describe("schema.org openingHours", () => {
  it.each([
    // The shape that started this: six days listed by code, Friday apart.
    [["Sa,Su,Mo,Tu,We,Th 10:00-20:30", "Fr 14:00-20:00"], "Sat–Thu 10:00–20:30 · Fri 14:00–20:00"],
    // A working week: the weekend is closed, and is said to be.
    [["Mo-Fr 09:00-17:00"], "Mon–Fri 09:00–17:00 · Sat, Sun closed"],
    // All seven alike.
    [["Mo-Su 10:00-22:00"], "Daily 10:00–22:00"],
    [["Mo,Tu,We,Th,Fr,Sa,Su 10:00-22:00"], "Daily 10:00–22:00"],
    // Round the clock, however it is written.
    [["Mo-Su 00:00-23:59"], "Open 24 hours"],
    [["Mo-Su 00:00-24:00"], "Open 24 hours"],
    [["Mo-Su"], "Open 24 hours"],
    [["Mo-Fr 00:00-23:59", "Sa 10:00-14:00"], "Sat 10:00–14:00 · Mon–Fri 24 hours · Sun closed"],
    // A range that wraps past the end of the week.
    [["Sa-Th 10:00-22:00"], "Sat–Thu 10:00–22:00 · Fri closed"],
    // Same hours on separate lines merge; different ones stay apart.
    [
      ["Sa 10:00-22:00", "Su 10:00-22:00", "Mo 10:00-22:00"],
      "Sat–Mon 10:00–22:00 · Tue–Fri closed",
    ],
    [["Sa-We 10:00-22:00", "Th 10:00-16:00"], "Sat–Wed 10:00–22:00 · Thu 10:00–16:00 · Fri closed"],
    // Two days are listed, not ranged.
    [["Fr,Sa 12:00-23:00", "Su-Th 10:00-22:00"], "Fri, Sat 12:00–23:00 · Sun–Thu 10:00–22:00"],
    // Days apart from each other with the same hours.
    [["Sa,Mo,We 09:00-13:00"], "Sat, Mon, Wed 09:00–13:00 · Sun, Tue, Thu, Fri closed"],
    // A split shift, on one line or two.
    [
      ["Sa-Th 10:00-14:00,17:00-22:00", "Fr 17:00-22:00"],
      "Sat–Thu 10:00–14:00, 17:00–22:00 · Fri 17:00–22:00",
    ],
    [
      ["Sa-Th 10:00-14:00", "Sa-Th 17:00-22:00", "Fr 17:00-22:00"],
      "Sat–Thu 10:00–14:00, 17:00–22:00 · Fri 17:00–22:00",
    ],
    // Hours padded, seconds dropped, spaces and dashes tolerated.
    [["Mo-Fr 9:00-17:00:00"], "Mon–Fri 09:00–17:00 · Sat, Sun closed"],
    [["Mo - Fr 09:00 – 17:00"], "Mon–Fri 09:00–17:00 · Sat, Sun closed"],
    [["Sa, Su, Mo 10:00-20:00"], "Sat–Mon 10:00–20:00 · Tue–Fri closed"],
    // Midnight to midnight is schema.org's "closed".
    [["Sa-Th 10:00-22:00", "Fr 00:00-00:00"], "Sat–Thu 10:00–22:00 · Fri closed"],
    // A day said to be closed in words.
    [["Sa-Th 10:00-22:00", "Fr closed"], "Sat–Thu 10:00–22:00 · Fri closed"],
  ])("%j reads %s", (lines, text) => {
    expect(openingHoursLine(lines)).toBe(text);
  });

  it("reads full and short English day names, in any case", () => {
    expect(openingHoursLine(["Saturday-Thursday 10:00-22:00", "Friday 14:00-22:00"])).toBe(
      "Sat–Thu 10:00–22:00 · Fri 14:00–22:00",
    );
    expect(openingHoursLine(["MON-FRI 09:00-17:00"])).toBe("Mon–Fri 09:00–17:00 · Sat, Sun closed");
    expect(openingHoursLine(["Sat-Thu 10:00-22:00", "Fri 14:00-22:00"])).toBe(
      "Sat–Thu 10:00–22:00 · Fri 14:00–22:00",
    );
  });

  it("reads Arabic day names", () => {
    expect(openingHoursLine(["السبت-الخميس 10:00-22:00", "الجمعة 14:00-22:00"])).toBe(
      "Sat–Thu 10:00–22:00 · Fri 14:00–22:00",
    );
    expect(openingHoursLine(["السبت،الأحد،الاثنين 10:00-20:00"])).toBe(
      "Sat–Mon 10:00–20:00 · Tue–Fri closed",
    );
  });

  it("orders days from Saturday, the Egyptian week, whatever order they came in", () => {
    expect(openingHoursLine(["Fr 14:00-20:00", "Th,We,Tu,Mo,Su,Sa 10:00-20:30"])).toBe(
      "Sat–Thu 10:00–20:30 · Fri 14:00–20:00",
    );
  });

  it("returns one phrase a group, for joining or listing", () => {
    expect(formatOpeningHours(["Sa,Su,Mo,Tu,We,Th 10:00-20:30", "Fr 14:00-20:00"])).toEqual([
      "Sat–Thu 10:00–20:30",
      "Fri 14:00–20:00",
    ]);
  });
});

describe("anything else is shown as written", () => {
  it("leaves hand-written hours alone", () => {
    expect(formatOpeningHours(["Monday to Saturday 10:00 to 20:00", "Sunday closed"])).toEqual([
      "Monday to Saturday 10:00 to 20:00",
      "Sunday closed",
    ]);
    expect(openingHoursLine(["Daily 10:00 to 20:00"])).toBe("Daily 10:00 to 20:00");
  });

  it("never rewrites half the lines and reorders them round the rest", () => {
    // "Sunday closed" parses alone; beside an unreadable line it must not
    // be rewritten, moved first, or used to infer the rest of the week.
    expect(formatOpeningHours(["Monday to Saturday 10:00 to 20:00", "Su closed"])).toEqual([
      "Monday to Saturday 10:00 to 20:00",
      "Su closed",
    ]);
  });

  it.each([
    "Mo-Fr 9am-5pm",
    "Mo-Fr 25:00-26:00",
    "Mo-Fr 10:00",
    "Xy 10:00-20:00",
    "By appointment",
    "Mo-Fr 10:00-20:00-22:00",
    "Mo--Fr 10:00-20:00",
    "Ramadan 12:00-17:00",
  ])("keeps %s", (line) => {
    expect(formatOpeningHours([line])).toEqual([line]);
  });

  it("drops only blank lines, and nothing for no hours", () => {
    expect(formatOpeningHours([" ", "Mo-Su 10:00-20:00"])).toEqual(["Daily 10:00–20:00"]);
    expect(formatOpeningHours([])).toEqual([]);
    expect(openingHoursLine([])).toBe("");
  });
});

describe("the parts", () => {
  it("parses one line into days (Saturday = 0) and hours", () => {
    expect(parseOpeningHoursLine("Mo-We 09:00-17:00")).toEqual({
      days: [2, 3, 4],
      hours: { kind: "open", spans: ["09:00–17:00"] },
    });
    expect(parseOpeningHoursLine("Fr")).toEqual({ days: [6], hours: { kind: "allDay" } });
    expect(parseOpeningHoursLine("nonsense")).toBeNull();
  });

  it("names days in runs, wrapping past Friday without splitting a run", () => {
    expect(daysText([0, 1, 2, 3, 4, 5])).toBe("Sat–Thu");
    expect(daysText([5, 6, 0])).toBe("Thu–Sat");
    expect(daysText([6, 0])).toBe("Fri, Sat");
    expect(daysText([2, 3, 4, 6])).toBe("Mon–Wed, Fri");
    expect(daysText([0, 1, 2, 3, 4, 5, 6])).toBe("Daily");
  });
});
