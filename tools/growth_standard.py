"""The weight-for-age standard behind the growth charts, and the arithmetic every chart follows.

The numbers are WS/T 423-2022 "7岁以下儿童生长标准" (National Health Commission of China, issued
2022-09-19, in force 2023-03-01), tables A.1/A.2 (percentiles) and B.1/B.2 (standard deviations)
for boys and girls under 7. The standard's data are the 2015 nine-city survey (Beijing, Harbin,
Xi'an, Shanghai, Nanjing, Wuhan, Guangzhou, Fuzhou, Kunming; Zong et al., Chin J Pediatr
2023;61(12):1103-1108). `static/growth_wfa.json` is the one copy of record; the iPhone bundles
`ios/BabyLog/Resources/growth_wfa.json`, byte for byte the same.

    python tools/growth_standard.py <text of the PDF>   # rebuild both JSON copies from the standard
    python tools/growth_standard.py --fixture           # rewrite tests/fixtures/growth_cases.json

The text is what any PDF-to-text tool gives for the official PDF (the URL is in the JSON); the
parser only needs each table's title line and its rows. The functions below are the reference
for `static/growth.js` and `ios/BabyLog/Core/Growth.swift`, which must agree with the fixture.
"""
import datetime
import json
import math
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
JSON_PATH = ROOT / "static" / "growth_wfa.json"
IOS_PATH = ROOT / "ios" / "BabyLog" / "Resources" / "growth_wfa.json"
FIXTURE = ROOT / "tests" / "fixtures" / "growth_cases.json"
URL = "https://www.nhc.gov.cn/cms-search/downFiles/e38068f0a62d4a1eb1bd451414444ec1.pdf"

TITLES = {
    ("boy", "p"): "表 A.1 7 岁以下男童年龄别体重的百分位数值",
    ("girl", "p"): "表 A.2 7 岁以下女童年龄别体重的百分位数值",
    ("boy", "sd"): "表 B.1 7 岁以下男童年龄别体重的标准差数值",
    ("girl", "sd"): "表 B.2 7 岁以下女童年龄别体重的标准差数值",
}
PERCENTILES = [3, 10, 25, 50, 75, 90, 97]
SDS = [-3, -2, -1, 0, 1, 2, 3]
DAYS_PER_MONTH = 30.4375   # 365.25 / 12: the standard's ages are whole months


# -- reading the standard ------------------------------------------------------------------

def parse_table(lines, title):
    """{age in months: [7 values]} for one table, its continuation pages included."""
    start = next(i for i, line in enumerate(lines) if line.strip().startswith(title))
    rows = {}
    for line in lines[start + 1:]:
        if line.strip().startswith("表 ") and "（续）" not in line and "(续)" not in line:
            break                       # the next table
        toks = line.split()
        if len(toks) < 8:
            continue
        try:
            nums = [float(t) for t in toks[-7:]]
        except ValueError:
            continue
        m = re.fullmatch(r"(?:(\d+)岁)?(?:(\d+)月)?", "".join(toks[:-7]))
        if not m or not (m.group(1) or m.group(2)):
            continue
        rows[int(m.group(1) or 0) * 12 + int(m.group(2) or 0)] = nums
    return rows


def build(text):
    lines = text.splitlines()
    out = {
        "source": "WS/T 423—2022 7岁以下儿童生长标准（中华人民共和国国家卫生健康委员会，2022-09-19 发布，"
                  "2023-03-01 实施），表 A.1、A.2（百分位数值）和表 B.1、B.2（标准差数值），年龄别体重",
        "url": URL,
        "unit": "kg",
        "ages": "months; whole months to 2 years, then every 3 months",
        "percentiles": PERCENTILES,
        "sds": SDS,
    }
    for sex in ("boy", "girl"):
        p = parse_table(lines, TITLES[(sex, "p")])
        sd = parse_table(lines, TITLES[(sex, "sd")])
        if sorted(p) != sorted(sd):
            raise ValueError(f"{sex}: the percentile and SD tables list different ages")
        ages = sorted(p)
        out[sex] = {"ages": ages, "p": [p[a] for a in ages], "sd": [sd[a] for a in ages]}
    check(out)
    return out


def check(std):
    """The shape every reader relies on: rising ages, rising columns, 0..81 months."""
    for sex in ("boy", "girl"):
        t = std[sex]
        ages = t["ages"]
        if ages[0] != 0 or ages[-1] != 81 or ages[:25] != list(range(25)):
            raise ValueError(f"{sex}: unexpected ages {ages[:3]}…{ages[-3:]}")
        if any(b <= a for a, b in zip(ages, ages[1:])):
            raise ValueError(f"{sex}: ages not rising")
        for key in ("p", "sd"):
            if len(t[key]) != len(ages):
                raise ValueError(f"{sex}.{key}: {len(t[key])} rows for {len(ages)} ages")
            for a, row in zip(ages, t[key]):
                if len(row) != 7 or any(b <= x for x, b in zip(row, row[1:])):
                    raise ValueError(f"{sex}.{key} at {a} months: {row}")
        for a, p, sd in zip(ages, t["p"], t["sd"]):
            if p[3] != sd[3]:
                raise ValueError(f"{sex} at {a} months: median {p[3]} vs {sd[3]}")


def dumps(std):
    """One table row per line, so a diff of the file reads like the standard."""
    head = {k: v for k, v in std.items() if k not in ("boy", "girl")}
    parts = ["{"]
    for k, v in head.items():
        parts.append(f"  {json.dumps(k)}: {json.dumps(v, ensure_ascii=False)},")
    for i, sex in enumerate(("boy", "girl")):
        t = std[sex]
        parts.append(f"  {json.dumps(sex)}: {{")
        parts.append(f"    \"ages\": {json.dumps(t['ages'])},")
        for j, key in enumerate(("p", "sd")):
            rows = ",\n".join("      " + json.dumps(r) for r in t[key])
            parts.append(f"    {json.dumps(key)}: [\n{rows}\n    ]{',' if j == 0 else ''}")
        parts.append("  }" + ("," if i == 0 else ""))
    parts.append("}")
    return "\n".join(parts) + "\n"


def load(path=JSON_PATH):
    return json.loads(Path(path).read_text(encoding="utf-8"))


# -- the arithmetic (static/growth.js and Growth.swift follow this) ---------------------------

def age_months(born, day):
    """Months between two YYYY-MM-DD dates as days / 30.4375; None before birth."""
    d = (datetime.date.fromisoformat(day[:10]) - datetime.date.fromisoformat(born[:10])).days
    return None if d < 0 else d / DAYS_PER_MONTH


def row_at(table, ages, age):
    """The 7 values at a fractional age, linear between the two table rows around it; None
    outside 0..81 months."""
    if age is None or age < 0 or age > ages[-1]:
        return None
    i = 0
    while i < len(ages) - 2 and ages[i + 1] <= age:
        i += 1
    f = (age - ages[i]) / (ages[i + 1] - ages[i])
    return [a + (b - a) * f for a, b in zip(table[i], table[i + 1])]


def z_score(std, sex, age, kg):
    """The weight's SD score: linear between the -3..+3 SD values at that age, and beyond them
    along the outermost step. None for an unknown sex or an age outside the table."""
    t = std.get(sex) if sex in ("boy", "girl") else None
    s = row_at(t["sd"], t["ages"], age) if t else None
    if s is None or kg is None:
        return None
    if kg <= s[0]:
        return -3 - (s[0] - kg) / (s[1] - s[0])
    if kg >= s[6]:
        return 3 + (kg - s[6]) / (s[6] - s[5])
    for i in range(6):
        if kg <= s[i + 1]:
            return i - 3 + (kg - s[i]) / (s[i + 1] - s[i])
    return 3.0


def percentile(z):
    """The share of children below this SD score, 0..100."""
    return None if z is None else 50 * (1 + math.erf(z / math.sqrt(2)))


def band(pc):
    """The standard's Table 1 rating: upper (≥P97), above (P75–P97), average (P25–P75), below
    (P3–P25), lower (<P3). Read off the exact percentile, not the 0.1 kg percentile table, so a
    weight at the 22nd percentile is never rated "average"; pct_label truncates, so the number
    shown always falls in the band shown."""
    if pc is None:
        return None
    if pc >= 97:
        return "upper"
    if pc >= 75:
        return "above"
    if pc >= 25:
        return "average"
    if pc >= 3:
        return "below"
    return "lower"


def pct_label(pc):
    """The percentile as shown: "<1", ">99", or the whole number below it. Truncated, not rounded:
    the band thresholds are whole numbers, so 2.6 shows as 2 beside "lower" and 96.7 as 96
    beside "above average", never as the next band's 3 or 97."""
    if pc is None:
        return None
    if pc < 1:
        return "<1"
    if pc > 99:
        return ">99"
    return str(int(math.floor(pc)))


# -- the shared fixture --------------------------------------------------------------------

CASES = [
    # (sex, born, day, kg) — births, row ages, between rows, past both ends, the 3-month steps
    ("boy", "2026-09-21", "2026-09-21", 3.125),
    ("boy", "2026-09-21", "2026-11-01", 5.0),
    ("boy", "2026-09-21", "2026-11-07", 5.2),
    ("boy", "2026-09-21", "2026-11-14", 5.6),
    ("boy", "2026-09-21", "2027-03-21", 8.4),
    ("boy", "2026-09-21", "2027-09-21", 10.1),
    ("boy", "2026-09-21", "2028-11-03", 13.4),
    ("boy", "2026-09-21", "2026-12-01", 3.0),
    ("boy", "2026-09-21", "2026-12-01", 12.5),
    ("boy", "2026-09-21", "2026-10-21", 4.2),
    ("boy", "2026-09-21", "2026-10-21", 3.7),
    ("boy", "2026-09-21", "2026-10-21", 5.6),
    ("boy", "2026-09-21", "2033-06-21", 23.0),
    ("boy", "2026-09-21", "2033-06-22", 23.0),
    # just under each band threshold (P2.6, P24.9, P74.9, P96.7): the number shown stays in its band
    ("boy", "2026-09-21", "2027-01-21", 6.044),
    ("girl", "2026-09-21", "2027-06-02", 7.938),
    ("boy", "2026-09-21", "2028-03-10", 12.028),
    ("girl", "2026-09-21", "2026-11-30", 6.882),
    ("boy", "2026-09-21", "2026-09-20", 3.1),
    ("girl", "2026-09-21", "2026-09-21", 3.2),
    ("girl", "2026-09-21", "2026-12-15", 5.9),
    ("girl", "2026-09-21", "2029-02-01", 14.0),
    ("", "2026-09-21", "2026-11-14", 5.6),
    ("other", "2026-09-21", "2026-11-14", 5.6),
]


def cases(std):
    out = []
    for sex, born, day, kg in CASES:
        age = age_months(born, day)
        z = z_score(std, sex, age, kg)
        pc = percentile(z)
        med = None
        t = std.get(sex) if sex in ("boy", "girl") else None
        if t:
            r = row_at(t["p"], t["ages"], age)
            med = None if r is None else round(r[3], 9)
        out.append({"sex": sex, "born": born, "day": day, "kg": kg,
                    "age_months": None if age is None else round(age, 9),
                    "z": None if z is None else round(z, 9),
                    "percentile": None if pc is None else round(pc, 6),
                    "label": pct_label(pc), "band": band(pc), "median": med})
    return out


def main(argv):
    if argv[:1] == ["--fixture"]:
        body = {"_about": "Weight-for-age cases from tools/growth_standard.py; static/growth.js and "
                          "ios/BabyLog/Core/Growth.swift must give the same results "
                          "(z to 1e-9, percentile to 1e-3).",
                "cases": cases(load())}
        FIXTURE.write_text(json.dumps(body, ensure_ascii=False, indent=1) + "\n", encoding="utf-8", newline="\n")
        print(f"wrote {FIXTURE.relative_to(ROOT)} ({len(body['cases'])} cases)")
        return 0
    if len(argv) != 1:
        print(__doc__)
        return 2
    std = build(Path(argv[0]).read_text(encoding="utf-8"))
    text = dumps(std)
    if json.loads(text) != std:
        raise SystemExit("the writer lost something")
    for path in (JSON_PATH, IOS_PATH):
        path.write_text(text, encoding="utf-8", newline="\n")
        print(f"wrote {path.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
