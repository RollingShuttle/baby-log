# Baby Log as a native iOS app — needs and plan

Written 2 Nov 2026 at the owner's request: *record what the app must do, and how it would be
made into a real iPhone app — but do not build it.* **The build starts only when the owner says
they are at their MacBook and want to make the app.** Until then nothing here is scaffolded, and
the Windows PC cannot build iOS apps in any case.

Part 1 is the record of needs — everything the owner has asked for since the paper sheet, plus
what six weeks of use have shown. Part 2 is what the research found (November 2026 facts, with
sources). Part 3 is the recommended path and the build order. Part 4 lists what the owner has to
decide or do before the first build session.

---

## Part 1 — What the app must do

### 1.1 Who it is for

- Two parents — **Dad** and **Mom** — each with an iPhone, logging one baby: **Yisen**, born
  21 Sep 2026. A second child must not need a redesign (every entry already carries a child id).
- Both phones use the **owner's personal Microsoft account**; each phone carries a label saying
  who is holding it, stamped on every entry as *who did it*.
- A **Windows PC** remains the archive and print station: it reads the same journal, writes
  `Baby Log.xlsx` and printable day sheets into `OneDrive\文档\Yisen File`, and runs the Catch up
  and Reports screens on a big screen. The native app must not break that.

### 1.2 What gets logged (the record)

| Entry | Fields the parents actually use |
|---|---|
| **Feed** | Start time; one or more bottle portions, each with the amount in ml and the **formula name** (Similac / Enfamil today, more later); made / leftover; note. **No breast feeding** — removed on 27 Sep 2026; the old paper rows keep their minutes as a read-only line. |
| **Diaper** | Time; wet / dirty / both; colour, texture, size; rash, blowout; note. |
| **Sleep** | Start / end, where; a running timer. |
| **Pump** | Left / right ml, minutes. |
| **Growth** | Weight, length, head; change from birth weight. |
| **Health** | Temperature; medicine with dose (vitamin D is one); symptom; "last given 5 h ago". |
| **Note / milestone** | Text, flag. Photos later. |

Every entry also records who logged it, which device, when it was created and every later
revision. Times carry the local offset; days are grouped by the local date the writer saw.

### 1.3 Speed — the 3 a.m. rules

- A feed is **two taps**: an amount chip, Save. The amount chips are a **range** the parents set
  (from / to / step, e.g. 50 · 60 · 70 · 80 · 90 · 100) and move up as the baby grows; "Same as
  last" is always first. He is at roughly 60–90 ml per feed in early November.
- The **formula is remembered**: chips for the names used most recently, the last one already
  chosen; switching to plan B is one tap; "Other…" adds a new name.
- **Diapers are one tap** (Wet / Dirty / Both) with a six-second Undo · Edit; a second tap within
  two minutes opens the same diaper instead of making a new one.
- **Catch up**: when entries were written on paper (no phone to hand), one screen takes a date,
  then a time and a tap per line; each tap is already saved.
- **Night mode** by itself between 21:00 and 07:00: dim, red-shifted, large; the moon button
  overrides it.
- **Swipe**: left on any row deletes (Undo in the toast); right on a paper-import row with a
  `Check:` question says *Looks right*.

### 1.4 Changing things

Every surface that shows an entry opens its editor (tiles, lists, day-sheet cells); the editor
shows every field including date, time, who, and type; Delete is recoverable (Deleted list with
Restore); a running sleep can be stopped at a chosen earlier time; uncertain imports are listed
under **Needs check** until corrected.

### 1.5 Sync and ownership

- **The data is the owner's**: small immutable JSON files in `OneDrive/Apps/Baby Log`, one file
  per entry and per revision (`<id>-r<n>-<w>.json`, day folders by UTC write date). A correction
  is a new file; a deletion is a tombstone; nothing is ever edited in place. This format is
  shared with the PC app and must stay exactly as it is.
- **No server anywhere.** Phones talk to OneDrive through Microsoft Graph with the single scope
  `Files.ReadWrite.AppFolder`; the PC uses the synced folder.
- Each phone sees the other's entries within about a minute while open; a collision (both edited
  the same entry) is **named**, not hidden; sync is a button that **shows its work** (sending 2 of
  5 · checking 4 days · reading 12 new · Synced · 5 sent · 12 new).
- Works with **no signal**: entries save on the phone first and queue; "Signed out never blocks
  logging".

### 1.6 Reliability — what the web app got wrong and the native app must get right

Six weeks of use show the installed web app never became the every-feed tool: **11 live entries
between 21 Sep and 2 Nov 2026**, most from the paper import (the real feeds were logged
elsewhere or not at all). The friction is known:

1. **A sign-in tap about once a day** — browser refresh tokens are capped at 24 h and Safari
   blocks silent renewal. A native app with Microsoft's native sign-in library keeps a session
   for months (Part 2.2).
2. **Nothing happens while the app is closed** — no "3 h since the last feed", no "the sleep timer
   is still running", no glance at the lock screen.
3. **Updates needed a ritual** (close twice, wait for GitHub's cache) until v8; a native app
   updates through TestFlight/the App Store like any other app.
4. **Must open instantly and never lose a half-typed entry** (drafts survive the app being
   killed today; keep that).

The success criterion for the native app is simple: **every feed and every diaper gets logged,
by whichever parent is holding the baby, without thinking about the app.**

### 1.7 Native-only wishes (the reason to build it)

Ranked by value for two tired parents (details and limits in Part 2.4):

1. **Reminders while closed**: "It has been 3 h since the last feed", "Sleep timer still running
   since 02:15" — local notifications scheduled from the last entry, no server needed.
2. **Lock-screen / Home-screen widget**: last feed 45 m ago · last diaper 1 h 10 m ago · today's
   totals.
3. **No sign-in prompts** for months at a time.
4. **Live Activity** for a running sleep (and on the Dynamic Island).
5. **Siri / Shortcuts**: "Log a wet diaper", "Log a 70 ml feed".
6. Later: Apple Watch glance and one-tap logging; a read-only view for grandparents.

### 1.8 Constraints

- A **private app for two people** — never a public product; no App Store listing wanted unless
  that is the cheapest way to put it on the wife's phone.
- The owner builds it **on a MacBook with an AI assistant, in sessions**, saving each step as it
  is finished with its tests before the next (the working style of the whole project).
- **No command line for routine use** — installing on the wife's phone and updating must be a
  tap (TestFlight) or a double-click.
- Keep the **PC app and the journal format unchanged**; the Windows side keeps working
  throughout and after.
- Budget-conscious: say plainly what costs money (Apple Developer Program) and what is free.

### 1.9 Out of scope for the first native version

Photos and milestones with pictures, WHO percentile charts, vaccines, solids, milk stash,
grandparents' view, Apple Watch — all listed as "Next" in RUNNING.md; the data model already
leaves room for them.

---

## Part 2 — What the research found (November 2026)

Four research passes, each against official sources (Apple, Microsoft) with the links kept in
the session record; confidence noted where it matters.

### 2.1 Apple: the tools, the cost, and how two people get a private app

- **Xcode 27.2 / iOS 27.2** are current (Oct 2026). Xcode 27 needs **macOS Tahoe 26.6+ on an
  Apple-silicon Mac** (M1 or later; it does not run on Intel). An Intel MacBook tops out at
  Xcode 26.6 and cannot meet the iOS 27 SDK rule that App Store/TestFlight uploads get in
  April 2027. *First question for the owner: which MacBook?*
- **Free Apple account**: can install on your own phone from Xcode, but the install expires
  after **7 days**, 3 devices, 3 apps — fine for the first prototype week, useless for daily use
  and for the wife's phone (weekly cable reinstall).
- **Apple Developer Program: US$99/year.** Identity verification can take days to weeks —
  enrol early. It unlocks TestFlight, Ad Hoc, push, App Groups (widgets), background modes.
- **How the wife's phone gets the app, ranked**: (1) **TestFlight internal testing** — add her
  as an App Store Connect user on the team; she installs from the TestFlight app; updates arrive
  by themselves; **no App Review**; the only chore is uploading a new build at least every
  **90 days** (any build, no code change needed). (2) Ad Hoc — install an .ipa by cable, profile
  lasts a year, no review; fallback. (3) Unlisted App Store / Apple Business custom apps — both
  need full App Review and Apple's own guidelines say a family app does not belong there. Skip.
- **What needs what**: local notifications need nothing (no paid account, no entitlement);
  widgets realistically need the paid program (App Groups); Live Activities started by the app
  itself need no push; push from a server needs the paid program *and a server*.
- **Xcode 27 has Claude built in** (agentic coding through the Xcode MCP server, Apple silicon
  only) — Claude Code can drive the Xcode project directly, which fits the way this project is
  built. Swift 6.4, SwiftUI, Liquid Glass by default.

### 2.2 Microsoft: the daily sign-in is fixable, and the journal needs no change

- **The 24-hour sign-in is a rule for web apps only.** Microsoft caps refresh tokens at 24 h
  for redirect URIs registered as *single-page application*; for an app registered under the
  **iOS/macOS platform** the default is **90 days, sliding** — a phone that syncs at least once
  in 90 days never sees a sign-in prompt. Not configurable for personal accounts; it is what the
  platform does. [high confidence, Microsoft's own token-lifetime docs]
- **Same registration, same client ID, same single scope.** The existing `Baby Log` Entra
  registration takes an *iOS/macOS* platform entry beside the web one (bundle ID →
  `msauth.<bundle-id>://auth`). Reusing it also sidesteps the open Aug-2026 personal-OneDrive
  provisioning bug (`serviceReadOnly` on brand-new app+user consents), because the owner's
  consent already exists.
- **MSAL for iOS 2.17** (Oct 2026, iOS 17+, Swift Package Manager): keychain group
  `com.microsoft.adalcache`, URL scheme `msauth.<bundle-id>`, `LSApplicationQueriesSchemes`
  msauthv2/msauthv3, authority `/consumers`; the Authenticator broker is optional for a personal
  account. Share the keychain group with the widget extension so a widget button can upload.
- **Graph from Swift**: there is no Microsoft Graph SDK for Swift (the ObjC one was archived in
  2023); a ~150-line URLSession client over the same five endpoints the web app uses
  (`special/approot` children / content / upload, plus delta) is the right size. Honour
  `Retry-After` on 429/503 exactly as `sync.js` does; send a `NONISV|RollingShuttle|BabyLog/<ver>`
  User-Agent.
- **Delta** (`/me/drive/items/<approot-id>/delta`) is the cheapest way to pull changes and is
  Microsoft-confirmed on folder ids, but untested on the app folder with the AppFolder-only
  scope: try it in the first spike; the three-day folder listing the web app does today is the
  fallback.
- Nothing announced for 2026–27 threatens personal-account auth or consumer OneDrive on Graph
  v1.0. The journal format and the PC side stay exactly as they are.

### 2.3 What a native app can do that the installed web app cannot

Ranked by value for two tired parents (API · catch):

1. **Reminders while closed** — "3 h since the last feed", "sleep timer still running".
   `UNUserNotificationCenter` with a time-interval trigger, rescheduled on every save;
   `timeSensitive` so it breaks through Sleep Focus; **no server**. Catch: a feed logged on the
   *other* phone only cancels this phone's reminder after the next pull (see 6).
2. **No sign-in prompts** — native MSAL, 90-day sliding tokens (2.2).
3. **Lock-screen / Home-screen / StandBy widget** — "last feed 45 m ago" ticks by itself
   (`Text(date, style: .relative)` needs no refresh); reload only when a new entry is known
   (free when the app or a widget button caused it; otherwise a 40–70/day budget). **Buttons on
   the widget** (iOS 17+) log Wet / Dirty / a feed without opening the app (device unlocked).
4. **Running sleep as a Live Activity** — Dynamic Island, Lock Screen, StandBy, and the Apple
   Watch Smart Stack with no watch app; a Stop button on it. Catch: 8-hour cap per activity;
   only the phone that started it owns it.
5. **Siri, Shortcuts, Control Center, the Action button** — one `AppIntent` each (log diaper,
   log feed with an amount, start/stop sleep) serves all of them. Siri phrases are fixed per
   build and **must include the app name**: "Hey Siri, log a wet diaper **in Baby Log**",
   "log a 70 millilitre feed in Baby Log" (up to 10 phrases; Apple Intelligence has no
   baby-logging domain, so free-form "the baby just ate" is not available). Control Center and
   Lock Screen buttons and the Action button fire the same intents with one press, no unlock
   required if you choose — for a 3 a.m. diaper that beats talking.
6. **Background refresh** (`BGAppRefreshTask`, 30 s, system-timed, never guaranteed, stops if
   the app is force-quit) — makes the other parent's entries arrive *eventually* while closed.
7. **Instant cross-phone push** honestly needs a server: Apple's push service only accepts
   requests from something holding your key. Two no-ops options if it ever matters: a free-tier
   relay (Graph webhook on the app folder → silent push), or a shared iCloud "doorbell" record
   whose subscription push (sent by Apple) triggers the OneDrive pull — data stays in OneDrive.
   Not needed for v1: both parents open the app many times a day.
8. **Apple Watch app** — skip for v1; the Live Activity and notifications mirror to a watch
   already.

### 2.4 How to build it — the four paths

| Path | Reuse of today's code | Effort to parity (AI-assisted, on the Mac) | What it unlocks | Verdict |
|---|---|---|---|---|
| **A. Native SwiftUI** | Logic re-implemented in Swift, checked against the same fixture (`tests/fixtures/data_cases.json`); UI rebuilt | ~15–23 working days | Everything in 2.3; no WebView quirks; one app for the next years | **Recommended** (reasons below) |
| **B. Capacitor** wrapping `docs/` | ~95 % of the JS as is; native MSAL behind the same `Graph.token()` | ~6–9 days | Sign-in fix, reminders, update quirks gone | Fast — but Siri, widgets, controls and Live Activities are Swift extensions *anyway*, and they need Swift code that writes the journal, so the JS saves little once those are wanted |
| C. Flutter / React Native | Little (RN could keep `core.js`/`sync.js`) | 14–28 days | Cross-platform the family does not need | No |
| D. Stay a web app, add web push from the PC | All | 2–4 days | Pushes and badges, with the PC switched on | Cannot remove the daily sign-in; no Siri, widgets, scheduled reminders. No |

**Why A, given what the owner asked for on 2 Nov 2026.** The wants that matter most — Siri and
one-press logging for heavy daily use, reminders, a glanceable widget — all live in Swift
extensions that must read and write the journal themselves. Build them once, natively, and the
app is that same Swift code with a SwiftUI front. The web app stays alive as the fallback and
the zero-install option, and the PC app does not change at all. The fixture makes the third
implementation of validate/resolve mechanically safe.

## Part 3 — The recommended path and the build order

**Target**: a native SwiftUI iPhone app, `Baby Log`, Swift 6 / Xcode 27, iOS 17 or later (MSAL's
floor), same OneDrive journal, same Entra registration, distributed to both phones through
TestFlight internal testing. Built in sessions on the MacBook with Claude Code driving Xcode;
each step saved and tested before the next, exactly as the rest of this project.

**Non-negotiables carried over** (the ones in CLAUDE.md, now for a third implementation):
immutable journal files and the one filename rule with a fresh `<w>` per write; the single
resolve rule; both validators (now three) run against `tests/fixtures/data_cases.json` — the
Swift tests load the same file; the day folder is the UTC date of the write; the phone never
creates a child; the one scope `Files.ReadWrite.AppFolder`; no personal data in the tree.

**Stage 0 — before the first session** (Part 4 has the owner's list): Apple-silicon Mac on
Tahoe 26.6+, Xcode 27 installed, Developer Program enrolled, the iOS platform added to the Entra
registration, a bundle ID chosen (e.g. `com.rollingshuttle.babylog`).

**Stage 1 — the spine (about a week): daily use without the sign-in tap.**
1. `BabyLogCore` Swift package: the record types, `validate`, `resolve`/`live`, the filename
   regex, the amounts/formula helpers — ported from `core.js` function for function, with XCTest
   cases generated from `data_cases.json`. *Green before anything else.*
2. Journal store: an App Group container holding the mirror of revision files plus an outbox;
   an in-memory index (rebuildable; SwiftData only as a cache if at all, never iCloud-synced).
3. Sign-in and transport: MSAL for iOS, the 150-line Graph client, `pull` (delta first, the
   three-day listing as fallback) and `flush`, the same backoff and collision rules as
   `sync.js`, the same status texts.
4. Screens: Now (tiles, log bar, recent), the feed editor (two taps: amount chip → Save; formula
   chips; range control), one-tap diapers with Undo, the other editors, night mode. Swipe
   actions come free with `.swipeActions`.
5. Run on the owner's phone from Xcode (free account is enough here). Use it for a few days
   beside the web app — both write the same journal.

**Stage 2 — the native wins (about a week).**
6. Local reminders (next feed due; sleep still running), rescheduled on every save and every
   pull; `timeSensitive`.
7. App Intents: log diaper (wet/dirty/both), log feed (amount, last formula), start/stop sleep;
   App Shortcuts phrases ("… in Baby Log"); Control Center / Lock Screen / Action-button
   controls on the same intents.
8. WidgetKit: Lock Screen and Home widget "last feed · last diaper · today", with Wet / Dirty /
   Feed buttons; StandBy at night.
9. Live Activity for a running sleep, with Stop.
10. Background App Refresh: one pull, then reschedule reminders and reload widgets.

**Stage 3 — the rest and the hand-over (a few days).**
11. Day sheet with prev/next, Trends, Settings (label, units, range, night hours, child,
    targets), Catch up, Needs check, Deleted/Restore.
12. TestFlight: upload, add the wife as an App Store Connect user, install on her phone;
    a reminder (or a `push.bat`-style script on the Mac) to re-upload every 90 days.
13. Guides: a RUNNING section for the iOS app; CLAUDE.md notes for the Swift package.

**Later, if ever**: the iCloud "doorbell" push for instant cross-phone updates; an Apple Watch
app for wrist logging; photos and milestones.

## Part 4 — What the owner decides or does before the first build session

Decisions (answer these in the chat when the time comes):
1. **Which MacBook?** Apple silicon (M1 or later) on macOS Tahoe 26.6+ is required for Xcode 27.
   An Intel MacBook changes the plan (Xcode 26.6 at most, and a deadline of April 2027).
2. **Pay the US$99/year Apple Developer Program?** Yes is assumed — it is the only sane way to put
   the app on the wife's phone and keep it updated. Enrol a few weeks ahead; verification can
   be slow.
3. **Bundle ID** (suggest `com.rollingshuttle.babylog`) and the Siri phrases wanted (up to 10;
   each ends "in Baby Log").
4. **Reminder rules**: minutes since the last feed before a reminder (3 h?), hours for a running
   sleep (6?), whether reminders may break through Sleep Focus at night.
5. **Instant vs eventual** cross-phone updates while closed: eventual (free, v1) or the iCloud
   doorbell later.
6. **Keep the web app alive** as the fallback (recommended: yes; it costs nothing).

Preparation (can be done any time before the first session):
- Enrol in the Apple Developer Program and, once accepted, add the wife as a user in App Store
  Connect (role: Developer is enough for TestFlight internal testing).
- Entra: open the `Baby Log` registration → Authentication → *Add a platform* → **iOS / macOS**
  → bundle ID. (The web platform stays; nothing else changes.)
- Both iPhones on iOS 17 or later.
- Install Xcode 27 from the Mac App Store (large download) and sign in to it with the Apple
  Account.
- Clone the repository on the Mac (`git clone https://github.com/RollingShuttle/baby-log.git`);
  the Swift package will live beside the other folders (`ios/`), and `push.bat` gets a Mac twin
  (`push.command`).

Then say: **"I'm on my MacBook — let's make the app."**
