# Running it — the PC app and the phone app

Written for someone who does not want to think about the technical details. `SETUP.md` covers the
one-time Microsoft and GitHub work; this covers everything after that.

---

## The idea in one picture

There are two halves and they never talk to each other directly.

```
   THE IPHONES                       ONEDRIVE                        YOUR PC
   ───────────                       ────────                        ───────
   a web app on each          <──>   one shared folder        <──>   the app you run
   home screen, labelled             Apps\Baby Log                   on your own machine
   Dad and Mom
                                     one small file per              reads that folder,
   log feeds, diapers,               feed, diaper, sleep…            writes Baby Log.xlsx
   sleeps, weights, notes;           never edited, only              and the day sheets
   works with no signal              added to                        into Yisen File
```

Every entry is one small file. A correction is a *new* file that says "revision 2 of that
entry"; a deletion is a new file that says "deleted". Nothing is ever overwritten, which is why
two phones and a PC can all write at once and never damage each other's work, and why anything
deleted can be brought back.

The phones reach the folder through Microsoft directly (that is what the sign-in is for). The PC
reaches it through the ordinary OneDrive client, the same way it reaches any other file. Neither
half needs the other to be running.

---

## Part 1 — The PC app

### Starting it

**Double-click the Baby Log icon** on the Desktop or in the Start menu. It opens in its own
window — no address bar, no tabs, and no black console window behind it.

- **Closing the window does not stop it.** The app keeps running in the notification area (the
  arrow at the right-hand end of the taskbar, next to the clock), so the next window opens at
  once and the phones' entries keep being turned into `Baby Log.xlsx` meanwhile. To bring the
  window back, double-click the Desktop icon again, or double-click the small icon by the clock.
- **To actually quit**, right-click that small icon → **Quit**.
- Double-clicking the icon twice does not open two copies; the second click brings the existing
  window to the front.
- If it fails to start it says so: a message box, and the same text in `error.log` in the
  project folder.

If you ever want a plain console and an address you open in a browser yourself, run
`python launch.py --no-window`, or `python app.py`, in the project folder. The address is
`http://127.0.0.1:8766` — "this computer, door 8766"; nothing outside the PC can reach it.
The whiskey app has door 8765; both can run at the same time.

### What the screens do

The top bar shows Yisen's name and age, a pill like `212 entries · newest 19:04` (how much is
in the journal and when the last file arrived — from either phone or this PC), and this PC's
label. The **Settings** tab carries a small number while anything is under Needs check.

| Screen | What it is for |
|---|---|
| **Today** | The entry screen. At the top, the *Now* panel: **Last feed** and **Last diaper** tiles with "45 m ago", a sleep that is running with a live clock and **Stop**, the usual gap ("Usually every 2 h 40 m · next around 14:20"), and today's totals against the pediatrician's targets when you have set them. Below it the day sheet in the hospital's layout — **Feeding** on the left, **Diapers** on the right, **Other** underneath for sleeps, pumps, weights, health and notes — with **‹ prev** / **next ›** to walk through the days. Then the log buttons: **Feed**, **Wet** / **Dirty** / **Both**, **Sleep**, **Pump**, **Weight**, **More ▾** (Health, Note), and **Catch up** for a paper slip. |
| **Trends** | **Last 14 days**: one row per day with feeds, bottle, breast minutes, wet, dirty, sleeps, pumps; a number under its target is marked. Clicking a row opens that day on Today. Below it the **24-hour rhythm** chart for the last 7 days: feeds as bars by start time (longer bar, longer breast feed), wet and dirty as dots, the night hours shaded. |
| **Growth** | Every weight, length and head measurement, with the change from birth weight and since the last one. **Add weight** at the top right. Birth weight comes from Settings → Child. |
| **Health** | Medicines and temperatures. Each medicine shows *last given 5 h ago*, which is the question you actually have at 2 a.m. Vitamin D is a medicine named `Vitamin D`. |
| **Reports** | **Print day sheet** for a chosen day, **Save day sheet** (writes it into Yisen File), **Print daily totals** for a date range, and **Rebuild Baby Log.xlsx**. It also shows where the journal and the output folder are. |
| **Settings** | This PC's label, units (ml or oz), the −/+ step, the quick amounts (a range, the last ten feeds, or your own list), night hours; Yisen's record (name, born, time of birth, birth weight, and the targets the pediatrician gave you); **Needs check**; **Deleted**. |

### Logging on the PC

- **Wet**, **Dirty** or **Both** is one click: the diaper is saved at the current time and a
  small notice appears for six seconds — `Wet + dirty · 03:12` with **Undo** and **Edit**. Undo
  removes it (it goes to Deleted, so even that is recoverable); Edit opens it to add colour,
  texture, rash and so on. Click the same button again inside two minutes and instead of a
  second diaper the first one opens with the line *Same as the 03:12 one? Save adds to it ·
  Log another adds a new one* — because it usually is the same diaper.
- **Feed** opens the feed editor: a bottle, nothing else (breast feeding was taken out on
  27 Sep 2026; the paper rows that had breast minutes still show them as a grey line). Tap an
  amount chip or type one, pick the formula, Save. The chips are **Same as last · 70 ml** and then
  the range — **50 · 60 · 70 · 80 · 90 · 100** to begin with — and the small **range** control
  right beside them (from / to / step) moves the whole row up the week his feeds grow; it is saved
  the moment you change it, on that device. **Another portion** adds a second bottle; **Made** /
  **leftover** — fill in those two and the amount fills itself in. If an amount is more than
  twice his biggest recent feed, Save asks once — **Save anyway** — in case a zero slipped in.
- **The formula is remembered.** Under each portion are chips for the formulas you have used,
  newest first (**Similac** and **Enfamil** until you have logged one), with the last one already
  chosen — so a feed is two taps, and switching to plan B is one more. **Other…** takes a new
  name, which becomes the first chip from then on. The name goes into the entry and into the
  `formula` column of `Baby Log.xlsx`.
- **Sleep** starts a sleep clock at once (with the same Undo / Edit notice); the button then
  reads **Sleeping…** and opens it so you can **Stop now**. A sleep nobody stopped is *not*
  stopped for you: after six hours the card says *forgot to stop it?* with **Set end time**.
- **Weight**, **Pump**, **More ▾ → Health / Note** open the plain editor for that type.
- **Catch up** (beside the log buttons) is for the paper slips written when no phone was to hand.
  Pick the date, then work down the slip: type a time, tap an amount (a feed) or **Wet · Dirty ·
  Both** (a diaper) — each tap saves that entry straight away and lists it underneath, and only
  the time clears, ready for the next line. The date stays until you change it. Every entry
  saved this way is an ordinary entry: tap it in the list to correct it.

---

## Part 2 — The phone app

### Logging on the phone

The tabs are **Now · Day · Trends · Settings**. The log buttons on Now are **Feed**,
**Wet · Dirty · Both**, then **Sleep · Pump · Weight · More**; health and notes are under **More**.

- **Now** is the whole point: since the last feed and the last diaper, any running feed or
  sleep with its clock, the next-feed guess, today's counts, and the last ten entries. The one-tap
  diaper buttons and **Feed** are right there.
- **Diapers are one tap**, exactly as on the PC: a six-second `Wet · 03:12 · Undo · Edit` toast
  above the tab bar, and the same two-minute "same diaper?" check.
- **Feeds are the same two taps as on the PC**: an amount chip, the formula chip (the last one is
  already chosen), Save; the **range** control beside the chips moves the amounts up as he grows.
  **Catch up** is under **More** for entering a paper slip line by line.
- **Sync shows its work.** Tap the pill at the top to sync right now: it reads *Syncing… sending
  2 of 5*, then *Syncing… checking 4 days*, *Syncing… reading 12 new*, and for a few seconds
  afterwards *Synced · 5 sent · 12 new* (or *Synced · nothing new*), so you can see it was pressed
  and when it is done. The phone also syncs by itself every 45 seconds while it is open. If the
  other phone changed an entry you have open, the screen says *Updated from Mom's phone* and shows
  the new state before it lets you act — one of you can never silently undo the other.
- **Night mode** turns on by itself between 21:00 and 07:00 (Settings changes the hours) and
  the moon button forces it on or off until the next boundary. It is dim red on black, and Delete
  is a plain outlined word, never an icon, so a half-asleep thumb cannot hit it by accident.
- The phone shows the last **120 days**; the PC shows everything. Older entries are still in
  OneDrive and in `Baby Log.xlsx`; the phone simply stops carrying them around.
- **Signed out never blocks logging; entries queue and upload after the next sign-in.** Every
  entry is saved on the phone before the app says Saved. The pill at the top says what is going
  on: `Synced 1 min ago` · `Syncing…` · `Offline · 2 waiting` · `Signed out · 3 waiting · tap to
  sign in` · `Signed out · showing data from 14:02` (nothing waiting, just not refreshed). It
  turns amber when something has waited more than a day, which usually means nobody has tapped
  it — tap it.
- **Drafts.** iOS closes a home-screen app whenever it feels like it. If that happens with an
  editor open, the app reopens it with everything you had typed and a *Draft restored* line.

### Settings on the phone

Your label, units, step and quick amounts, night hours; Yisen's record (the phone can change it
but not create it — that is the PC's job); **Sign in** / **Sign out** with *Signed in as …*; the
sync details (last sync, how many entries are waiting, **Sync now** — which re-reads every day
folder of the last 120 days, the thing to press if an entry from the PC seems missing —
*Changed on two devices*, which lists entries both a phone and the PC changed at once so you can
look at the one that won, anything OneDrive refused with **Retry** /
**Discard**, storage used); **Deleted**; **Needs check (n)**.

**Swiping a row.** On the phone, any entry in the Now list, the Day sheet's Other section or
Needs check slides sideways: drag it **left** to reveal **Delete** (no question asked — the
toast offers **Undo** for six seconds, and Settings → Deleted has Restore after that). A row still
carrying a `Check:` question from the paper sheet also slides **right** to reveal **Looks
right**, which keeps the entry as read and drops the question, so it leaves Needs check without
opening anything. Tapping a row still opens its editor.

---

## Part 3 — Changing or deleting an entry

The rule you asked for: **every entry can be changed or deleted from every device, and it is
obvious how.** Anything that shows an entry opens it.

**On the PC**, click any of these and the entry opens in its editor: the **Last feed** / **Last
diaper** tiles, a running feed or sleep card, any cell of the day sheet (feeding or diapers side,
the By column, the note), any row under **Other**, a row in **Growth** or **Health**, a bar or dot
in the rhythm chart, a row under Settings → **Needs check** or **Deleted**, and **Edit** on the
notice that follows a one-click diaper.

**On the phone**, tap any of these: the since-last tiles, a running card, an entry in Now's
recent list, any cell of the Day sheet, any row of its Other section, the Deleted and Needs check
lists in Settings, and **Edit** on the toast.

**The editor** is the same on both, one dialog for every type. Every field is there and can be
changed: **Start** (a date-and-time box, plus `−5 · −15 · −30 min` chips that shift it, with the
result shown beside them — for "he actually started fifteen minutes ago"), **End** where it
applies, **Who** (chips for every label the journal has seen, plus **Other…**), the type's own
fields, the note, and **Change type…** (a feed logged as a diaper by mistake becomes a diaper,
keeping its time, note and who). The PC's editor also shows the entry's **History** — every
revision, when, and by whom.

**Save** writes a new revision. Save refuses a few things and says so in the dialog rather than
in a pop-up: a start before Yisen was born, a start more than ten minutes in the future, an end
before its start, made less than leftover.

**Delete** is at the foot of the editor for an existing entry. It asks once, in the dialog —
`Delete feed 02:10?` with **Keep** / **Delete** — then shows `Deleted · Undo` for six seconds.
Undo puts it straight back.

**Deleted** (Settings, on both) lists everything that has ever been deleted, newest first, with
who deleted it and why (an Undo says `undo`; merging two running feeds says `merged into …`),
and a **Restore** button. Restore brings the entry back exactly as it last was. Nothing is ever
really gone.

**Needs check** (Settings, on both; the count sits on the PC's Settings tab) is the eight
readings from the hospital sheet that were hard to make out on the photo — an amount written
over another number, a `>=10 ml`, a time that might be 15:00. Each carries a note beginning
`Check:` saying what was unclear. Open it, put the right value in, delete the `Check:` part of
the note, Save, and it drops off the list. When the list is empty the count disappears.

A change made on one phone reaches the other on its next pull (within a minute while the app is
open), and the PC on the OneDrive client's next sync (usually seconds; `Baby Log.xlsx` follows a
minute or so later).

---

## Part 4 — Where the data goes

- **The journal** → `C:\Users\<you>\OneDrive\Apps\Baby Log\`. One small file per entry, under
  `events\<date>\` (the date is the day the file was *written*, not the day of the entry, so
  a correction to last week lands in today's folder — that is deliberate) and `children\`.
  Never edited, only added to. Leave it alone; there is nothing in it to read by hand.
- **The readable spreadsheet** → `C:\Users\<you>\OneDrive\文档\Yisen File\Baby Log.xlsx`, rebuilt
  from the journal by the PC: sheets **Feeds**, **Diapers**, **Sleep**, **Pumping**, **Growth**,
  **Health**, **Notes**, **Daily** (one row per day, every day from the first entry to today)
  and **About**. The PC rebuilds it when it starts, twenty seconds after anything you change on
  the PC, and within a minute of a phone's entries arriving through OneDrive.

  **Do not type into `Baby Log.xlsx`.** It is regenerated whole, and your typing would be lost
  the next time. Correct entries in the app instead. The last thirty versions are kept in
  `data\backups\` in the project folder. If the file is open in Excel the rebuild waits and says
  so in the log; close Excel and it catches up.
- **Day sheets** → `Yisen File\Day sheets\<date>.html` when you press **Save day sheet**: a
  printable copy of one day in the hospital's layout. Open it in any browser, from any device
  that can see OneDrive.
- **Settings** → `data\settings.json` in the project folder (the PC's label, units and so on).
  The phones keep theirs on the phone.

### Printing a day sheet

Reports → pick the day → **Print day sheet**. It opens in a new window laid out for Letter
paper, black on white, feeding on the left and diapers on the right with a totals line at the
foot (`8 feeds · 135 ml bottle · 57 min breast · 6 wet · 4 dirty`, with the targets beside the
counts when set). Print it from that window. **Print daily totals** does the same for a date
range — one row per day — which is the thing to take to the pediatrician.

---

## Part 5 — A second computer

The app is not tied to one machine. A laptop can run the same thing and the two stay in step,
because both read and write the same OneDrive folder — the same way the phones do. There is no
"main" computer.

On the laptop, once: install Python (https://www.python.org/downloads/, tick *Add Python to
PATH*), make sure OneDrive is signed in with the personal account and has finished syncing, then

```
git clone https://github.com/RollingShuttle/baby-log.git
cd baby-log
python tools/setup_machine.py
pip install -r requirements.txt
build_exe.bat
python tools/make_shortcut.py
```

Give it its own label in Settings. Do **not** run `python paper.py` again — it would find the
child and the entries already there and write nothing, but there is no reason to.

Both computers rebuild `Baby Log.xlsx` from the same journal, so it is the same file whichever
one wrote it last. OneDrive copes with two writers of a small file well enough; if it ever makes
a *conflicted copy* of `Baby Log.xlsx`, delete the copy — the file is regenerated, nothing in it
is original.

**Keeping a machine up to date:** double-click `update.bat` in the project folder. It fetches
the latest version, reinstalls anything new, closes the app if it is running, rebuilds it and
refreshes the icon. If there is nothing new it says so and stops.

**Sending a change out (no command line):** double-click `push.bat`. It asks in one line what
changed (or just press Enter), runs the tests, and puts the change on GitHub — which is where
the phones and the other computers get it from. It refuses to push while any test fails, bumps
the phone app's version by itself when anything under `docs/` changed, and says so when there is
nothing to push. The phones pick a change up on their own within a minute or two; other PCs get
it with `update.bat`.

---

## Part 6 — Things that are normal, not faults

- **After a push, the phone says *New version ready* with a Reload button** — within about ten
  minutes of the push (GitHub keeps files that long), the next time the app is opened. Tap Reload
  when you are not in the middle of an entry. Settings → Sync shows *Phone app vN* so you can
  tell which version is running.

- **The app is still by the clock after you close its window.** Deliberate. It is what keeps
  `Baby Log.xlsx` current while you are not looking. Quit it from that icon if you want it gone.
- **The phone asks you to sign in about once a day.** Microsoft's limit, not adjustable. It
  never stops you logging — only uploading. Tap the pill, tap Continue.
- **A phone shows `Signed out · showing data from 14:02`.** It is telling you the truth: nothing
  is waiting to go up, and what it shows is as of the last refresh. Log normally.
- **An entry from one phone takes a minute to show on the other.** The phone looks every 45
  seconds while it is open, and immediately when you open it. Open the app and it is there.
- **`Baby Log.xlsx` lags the app by a minute.** The PC checks the folder once a minute and
  rebuilds when something new has arrived.
- **A feed shows as running on the sheet with a `▸`.** Someone started the clock and nobody
  stopped it. After an hour the card offers **Set end time**.
- **The paper entries say "paper" in the By column.** They came from the hospital sheet, not
  from either of you. Editing one changes the By to whoever fixes it only if you change the Who
  chip; otherwise it stays "paper" and the history records who edited it.
- **The phone's Day view stops at 120 days back.** By design; the PC and the spreadsheet have
  everything.
- **`OneDrive\Apps\Baby Log` has hundreds of tiny files.** One per entry and per correction.
  That is the whole design, and OneDrive is fine with it.

---

## Part 7 — If something looks wrong

| What you see | What to do |
|---|---|
| The PC window closes at once, or never appears | Read `error.log` in the project folder. |
| A window saying *The app has been closed* | A leftover window from a copy you quit. Close it and open the app again. |
| The top-bar pill says `journal?` or is amber | The app cannot read the journal folder, or some files in it are unreadable. Check OneDrive is signed in and not paused; hover the pill for the count. Files mid-download are skipped and retried on their own. |
| Today shows *Who is this log for?* | The journal has no child. Run `python paper.py` (SETUP Part 3) — or, if the folder is genuinely empty and OneDrive is fine, add the child in that card. |
| *Rebuild Baby Log.xlsx* says the workbook is open in Excel | Close `Baby Log.xlsx` in Excel and press it again. Writing while Excel holds it would make OneDrive keep two copies. |
| Phone pill: `Sync failed · 19:03 · tap for details` | Tap it. A network blip clears itself on the next try. `accessDenied` / `serviceReadOnly` on a new setup is the Microsoft provisioning problem in SETUP's troubleshooting. Anything else, tell me the code it shows. |
| Phone pill: `1 stuck · tap` | OneDrive refused one upload for good (not a signal problem). Settings shows it with **Retry** and **Discard**. Retry first. |
| Phone pill amber for a day or more | Something has been waiting to upload for over 24 hours — almost always "nobody has tapped sign in". Tap it. |
| Phone says *Not saved — storage full* | The phone would not let the app write. Free some space on the phone and press Save again; what you typed is still in the editor. |
| Phone: *Updated on Dad's phone — look again* | You tried to switch or stop a feed the other phone had just changed. The screen now shows the current state; do it again. |
| Two feeds are running at once | Both were started, one on each device, and both are real. Today's Now panel offers **Merge into one** (keeps the earlier start, adds the sides together, the later one goes to Deleted). |
| Sign-in fails on the phone | Personal account, not work; and the address in SETUP Part 2 step C must match exactly, trailing slash included. |
| An entry looks wrong and you do not know who changed it | Open it on the PC; **History** at the foot lists every revision with the device label. |

---

## Next — not in version 1

These were set aside so version 1 could be finished. None of them is started.

- Sleep pattern charts beyond the PC's rhythm chart
- The milk stash (pumped bottles in the fridge and freezer, with dates)
- WHO growth percentile charts
- Vaccines
- Solids
- Milestones with photos
- Monthly archive bundles, so a phone's first catch-up after a long absence is faster
- A read-only view for grandparents and the pediatrician
- Microsoft's "delta" sync, which would let the phone ask OneDrive "what changed?" instead of
  listing folders
