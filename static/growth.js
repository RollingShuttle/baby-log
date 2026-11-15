/* Weight for age against China's growth standard for children under 7 (WS/T 423-2022).

   The table is static/growth_wfa.json; the arithmetic follows tools/growth_standard.py line for
   line, so the PC, the iPhone (Core/Growth.swift) and tests/fixtures/growth_cases.json agree to
   the last digit: same operations in the same order, not just the same formulas. Runs in the
   page (global Growth) and under Node (module.exports) for the tests. */
(function (root) {
  "use strict";
  const DAY = 86400000;
  const DAYS_PER_MONTH = 30.4375;   // 365.25 / 12: the standard's ages are whole months

  /** Date.UTC of a string's first ten characters ("YYYY-MM-DD..."), or null. */
  function utcDay(s) {
    const m = /^(\d{4})-(\d{2})-(\d{2})/.exec(String(s == null ? "" : s));
    return m ? Date.UTC(Number(m[1]), Number(m[2]) - 1, Number(m[3])) : null;
  }

  /** Months between two dates as whole days / 30.4375; null before birth. */
  function ageMonths(born, day) {
    const b = utcDay(born), t = utcDay(day);
    if (b === null || t === null) return null;
    const d = Math.round((t - b) / DAY);
    return d < 0 ? null : d / DAYS_PER_MONTH;
  }

  /** Whole calendar months since birth, anchored on the birth's day of the month, and the days
      left over: {m, d}; null before birth. An anniversary that has not come yet, or that rolled
      past a short month (born on the 31st), is not a month yet, as in Core.ageText. */
  function ageParts(born, day) {
    const b = utcDay(born), t = utcDay(day);
    if (b === null || t === null || t < b) return null;
    const bd = new Date(b), td = new Date(t);
    const by = bd.getUTCFullYear(), bm = bd.getUTCMonth(), bdd = bd.getUTCDate();
    let m = (td.getUTCFullYear() - by) * 12 + td.getUTCMonth() - bm;
    while (m > 0 && Date.UTC(by, bm + m, bdd) > t) m -= 1;
    return { m, d: Math.round((t - Date.UTC(by, bm + m, bdd)) / DAY) };
  }

  const table = (std, sex) => (std && (sex === "boy" || sex === "girl") ? std[sex] || null : null);

  /** The 7 values of "p" (P3..P97) or "sd" (-3..+3 SD) at a fractional age, linear between the
      two table rows around it; null for an unknown sex or an age outside 0..81 months. */
  function rowAt(std, sex, key, age) {
    const t = table(std, sex);
    if (!t || !t[key] || age == null || !(age >= 0)) return null;
    const ages = t.ages, rows = t[key];
    if (age > ages[ages.length - 1]) return null;
    let i = 0;
    while (i < ages.length - 2 && ages[i + 1] <= age) i += 1;
    const f = (age - ages[i]) / (ages[i + 1] - ages[i]);
    const a = rows[i], b = rows[i + 1];
    return a.map((v, k) => v + (b[k] - v) * f);
  }

  /** The weight's SD score: linear between the -3..+3 SD values at that age, and beyond them
      along the outermost step. */
  function zScore(std, sex, age, kg) {
    const s = rowAt(std, sex, "sd", age);
    if (s === null || kg == null || !Number.isFinite(kg)) return null;
    if (kg <= s[0]) return -3 - (s[0] - kg) / (s[1] - s[0]);
    if (kg >= s[6]) return 3 + (kg - s[6]) / (s[6] - s[5]);
    for (let i = 0; i < 6; i++) {
      if (kg <= s[i + 1]) return i - 3 + (kg - s[i]) / (s[i + 1] - s[i]);
    }
    return 3;
  }

  // JavaScript has no erf. This is the Chebyshev fit of Numerical Recipes (erfcc), relative error
  // under 1.2e-7 everywhere, so the percentile is good to 1e-5 of a percent in both tails.
  function erfc(x) {
    const z = Math.abs(x);
    const t = 1 / (1 + 0.5 * z);
    const r = t * Math.exp(-z * z - 1.26551223 + t * (1.00002368 + t * (0.37409196 + t * (0.09678418 +
      t * (-0.18628806 + t * (0.27886807 + t * (-1.13520398 + t * (1.48851587 +
      t * (-0.82215223 + t * 0.17087277)))))))));
    return x >= 0 ? r : 2 - r;
  }

  /** The share of children below this SD score, 0..100: 50 (1 + erf(z / sqrt 2)). */
  function percentile(z) {
    if (z == null || !Number.isFinite(z)) return null;
    return 50 * erfc(-z / Math.SQRT2);
  }

  /** The standard's Table 1 rating, read off the exact percentile (pctLabel truncates, so the
      number shown always falls in the band shown). */
  function band(pc) {
    if (pc == null) return null;
    if (pc >= 97) return "upper";
    if (pc >= 75) return "above";
    if (pc >= 25) return "average";
    if (pc >= 3) return "below";
    return "lower";
  }

  /** The percentile as shown: "<1", ">99", or the whole number below it. Truncated, not rounded:
      the band thresholds are whole numbers, so 2.6 shows as 2 beside "Lower" and 96.7 as 96
      beside "Above average", never as the next band's 3 or 97. */
  function pctLabel(pc) {
    if (pc == null) return null;
    if (pc < 1) return "<1";
    if (pc > 99) return ">99";
    return String(Math.floor(pc));
  }

  const api = { ageMonths, ageParts, rowAt, zScore, percentile, erfc, band, pctLabel, DAYS_PER_MONTH };
  if (typeof module !== "undefined" && module.exports) module.exports = api;
  else root.Growth = api;
})(typeof window !== "undefined" ? window : globalThis);
