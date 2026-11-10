/**
 * Opening hours in plain English.
 *
 * Hours reach the API in two shapes. The crawler reads a shop's schema.org
 * markup, whose `openingHours` strings are written for machines:
 * "Sa,Su,Mo,Tu,We,Th 10:00-20:30", "Fr 14:00-20:00", "Mo-Su 00:00-23:59".
 * A person listing a shop by hand writes words instead: "Monday to Saturday
 * 10:00 to 20:00", "Sunday closed".
 *
 * The first are rewritten for a buyer in Egypt, whose week starts on
 * Saturday: "Sat–Thu 10:00–20:30 · Fri 14:00–20:00". Days with the same
 * hours are merged, consecutive days collapse into a range, and all seven
 * read "Daily". When any line does not parse, hand-written lines included,
 * every line is shown exactly as written: an unfamiliar line is never dropped
 * or guessed at, and the lines are never half-rewritten and reordered around
 * it ("Sunday closed" beside "Monday to Saturday 10:00 to 20:00" means what it
 * says only as a pair).
 */

/** The Egyptian week, Saturday first: the order days are named in. */
const WEEK = ["Sat", "Sun", "Mon", "Tue", "Wed", "Thu", "Fri"] as const;

/** Every spelling of a day we accept, folded to lower case, to its index in WEEK. */
const DAY_NAMES: Record<string, number> = {};
for (const [index, names] of [
  ["sa", "sat", "saturday", "السبت", "سبت"],
  ["su", "sun", "sunday", "الأحد", "الاحد", "أحد", "احد"],
  ["mo", "mon", "monday", "الاثنين", "الإثنين", "الأثنين", "اثنين"],
  ["tu", "tue", "tues", "tuesday", "الثلاثاء", "ثلاثاء"],
  ["we", "wed", "wednesday", "الأربعاء", "الاربعاء", "أربعاء", "اربعاء"],
  ["th", "thu", "thur", "thurs", "thursday", "الخميس", "خميس"],
  ["fr", "fri", "friday", "الجمعة", "الجمعه", "جمعة"],
].entries()) {
  for (const name of names) DAY_NAMES[name] = index;
}

const DASH = /\s*[-–—]\s*/;
const TIME = /^(\d{1,2})[:.](\d{2})(?::\d{2})?$/;

function day(name: string): number | null {
  const index = DAY_NAMES[name.trim().toLowerCase().replace(/\.$/, "")];
  return index ?? null;
}

/** "Mo-Fr" or "Sa,Su,Mo" or "Mo-We,Fr" to indices in WEEK; null if any part is not a day. */
function parseDays(text: string): number[] | null {
  const days = new Set<number>();
  for (const part of text.split(/\s*[,،]\s*/)) {
    if (!part) return null;
    const ends = part.split(DASH);
    if (ends.length === 1) {
      const one = day(ends[0]);
      if (one === null) return null;
      days.add(one);
    } else if (ends.length === 2) {
      const from = day(ends[0]);
      const to = day(ends[1]);
      if (from === null || to === null) return null;
      // A range runs forward through the week and may wrap: "Sa-Th", "Fr-Su".
      for (let d = from; ; d = (d + 1) % 7) {
        days.add(d);
        if (d === to) break;
      }
    } else {
      return null;
    }
  }
  return days.size > 0 ? [...days] : null;
}

function time(text: string): string | null {
  const match = TIME.exec(text.trim());
  if (!match) return null;
  const hours = Number(match[1]);
  const minutes = Number(match[2]);
  if (hours > 24 || minutes > 59 || (hours === 24 && minutes > 0)) return null;
  return `${String(hours).padStart(2, "0")}:${match[2]}`;
}

/** What a day's hours say: open between times, all day, or closed. */
type Hours = { kind: "open"; spans: string[] } | { kind: "allDay" } | { kind: "closed" };

/** "10:00-20:30" or "10:00-14:00,16:00-20:00"; "closed"/"off"; null when unreadable. */
function parseHours(text: string): Hours | null {
  const words = text.trim().toLowerCase();
  if (words === "closed" || words === "off") return { kind: "closed" };
  const spans: string[] = [];
  for (const span of text.split(/\s*[,،]\s*|\s+(?=\d)/)) {
    const ends = span.split(DASH);
    if (ends.length !== 2) return null;
    const open = time(ends[0]);
    const close = time(ends[1]);
    if (!open || !close) return null;
    // schema.org writes "closed all day" as opening and closing at midnight.
    if (open === "00:00" && close === "00:00") return { kind: "closed" };
    if (open === "00:00" && (close === "23:59" || close === "24:00")) return { kind: "allDay" };
    spans.push(`${open}–${close}`);
  }
  return spans.length > 0 ? { kind: "open", spans } : null;
}

/**
 * One schema.org `openingHours` line: "<days> <hours>". The days may be
 * listed ("Sa,Su,Mo") or ranged ("Mo-Fr"), in two-letter codes, short or full
 * English names or Arabic; the hours are 24-hour times. A line of days alone
 * ("Mo-Su") is open all day, as schema.org defines it. Null for anything else.
 */
export function parseOpeningHoursLine(line: string): { days: number[]; hours: Hours } | null {
  const text = line
    .trim()
    .replace(/\s+/g, " ")
    .replace(/\s*[-–—]\s*/g, "-");
  // The days run up to the first digit, or to a trailing "closed"/"off".
  const match = /^(.*?)(?:\s+(\d.*|closed|off))?$/i.exec(text);
  if (!match) return null;
  const days = parseDays(match[1].replace(/\s*:\s*$/, ""));
  if (!days) return null;
  if (match[2] === undefined) return { days, hours: { kind: "allDay" } };
  const hours = parseHours(match[2]);
  return hours ? { days, hours } : null;
}

function hoursText(hours: Hours): string {
  if (hours.kind === "closed") return "closed";
  if (hours.kind === "allDay") return "24 hours";
  return hours.spans.join(", ");
}

/**
 * Days as a reader names them: "Sat–Thu", "Fri", "Sat, Sun", "Mon–Wed, Fri",
 * "Daily". A run may wrap past Friday ("Thu–Sat") but starts where a gap ends,
 * so it is never split in two.
 */
export function daysText(days: number[]): string {
  const set = new Set(days);
  if (set.size === 7) return "Daily";
  // Start the walk just after a day that is not in the set, so no run is cut.
  const start = (WEEK.findIndex((_, d) => !set.has(d)) + 1) % 7;
  const runs: number[][] = [];
  for (let step = 0; step < 7; step++) {
    const d = (start + step) % 7;
    if (!set.has(d)) continue;
    const last = runs[runs.length - 1];
    if (last && (last[last.length - 1] + 1) % 7 === d) last.push(d);
    else runs.push([d]);
  }
  // Runs in week order (Saturday first) by where each begins.
  runs.sort((a, b) => a[0] - b[0]);
  return runs
    .map((run) =>
      run.length === 1
        ? WEEK[run[0]]
        : run.length === 2
          ? `${WEEK[run[0]]}, ${WEEK[run[1]]}`
          : `${WEEK[run[0]]}–${WEEK[run[run.length - 1]]}`,
    )
    .join(", ");
}

/**
 * A shop's opening hours as short phrases, to be joined with " · ":
 *
 *   ["Sa,Su,Mo,Tu,We,Th 10:00-20:30", "Fr 14:00-20:00"]
 *     → ["Sat–Thu 10:00–20:30", "Fri 14:00–20:00"]
 *   ["Mo-Su 00:00-23:59"]                 → ["Open 24 hours"]
 *   ["Mo-Fr 09:00-17:00"]                 → ["Mon–Fri 09:00–17:00", "Sat, Sun closed"]
 *   ["Monday to Saturday 10:00 to 20:00"] → as written
 *
 * The days none of the lines names are closed (schema.org's own reading) and
 * are said to be. When any line does not parse, every line is returned as
 * written, in its order.
 */
export function formatOpeningHours(lines: string[]): string[] {
  const cleaned = lines.map((line) => line.trim()).filter(Boolean);
  const parsed = cleaned.map(parseOpeningHoursLine);
  if (parsed.length === 0 || parsed.some((line) => line === null)) return cleaned;
  const byDay = new Map<number, Hours>();
  for (const line of parsed as NonNullable<(typeof parsed)[number]>[]) {
    for (const d of line.days) {
      const before = byDay.get(d);
      // Two lines for one day are a split shift: both spans apply.
      if (before?.kind === "open" && line.hours.kind === "open") {
        byDay.set(d, { kind: "open", spans: [...before.spans, ...line.hours.spans] });
      } else {
        byDay.set(d, line.hours);
      }
    }
  }
  for (let d = 0; d < 7; d++) if (!byDay.has(d)) byDay.set(d, { kind: "closed" });

  // Days with the same hours together, in the week order of their first day.
  const groups = new Map<string, number[]>();
  for (let d = 0; d < 7; d++) {
    const hours = byDay.get(d);
    if (!hours) continue;
    const key = hoursText(hours);
    groups.set(key, [...(groups.get(key) ?? []), d]);
  }
  const phrases = [...groups.entries()]
    // Open days first, then the closed ones.
    .sort(([a], [b]) => Number(a === "closed") - Number(b === "closed"))
    .map(([hours, days]) =>
      days.length === 7 && hours === "24 hours" ? "Open 24 hours" : `${daysText(days)} ${hours}`,
    );
  return phrases;
}

/** The same, as one line: "Sat–Thu 10:00–20:30 · Fri 14:00–20:00". Empty when there are none. */
export function openingHoursLine(lines: string[]): string {
  return formatOpeningHours(lines).join(" · ");
}
