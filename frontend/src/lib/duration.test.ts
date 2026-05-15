import { describe, expect, it } from "vitest";

import { durationMinutesTitle, formatDurationMinutes } from "./duration";

describe("duration formatting", () => {
  it("formats unset values", () => {
    expect(formatDurationMinutes(null)).toBe("Not set");
    expect(formatDurationMinutes(undefined)).toBe("Not set");
  });

  it("formats minutes below an hour", () => {
    expect(formatDurationMinutes(0)).toBe("0m");
    expect(formatDurationMinutes(45)).toBe("45m");
  });

  it("formats hour and minute totals", () => {
    expect(formatDurationMinutes(60)).toBe("1h");
    expect(formatDurationMinutes(157)).toBe("2h 37m");
    expect(formatDurationMinutes(1530)).toBe("25h 30m");
  });

  it("keeps exact minute totals in title text", () => {
    expect(durationMinutesTitle(1)).toBe("1 minute");
    expect(durationMinutesTitle(1530)).toBe("1530 minutes");
    expect(durationMinutesTitle(null)).toBeUndefined();
  });
});
