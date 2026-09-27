# Setup — the one-time steps

Roughly 45 minutes across your PC and both iPhones, in the order below. Nothing here installs a
server or costs money. `RUNNING.md` covers day-to-day use; this is only what has to happen once.

---

## The idea in one picture

```
   DAD'S IPHONE            ONEDRIVE                 MOM'S IPHONE
   ────────────            ────────                 ────────────
   a web app on     <──>   one shared folder  <──>  the same web app,
   the home screen         Apps\Baby Log            labelled "Mom"

                              ^
                              |  the OneDrive client on the PC syncs it
                              v
                           YOUR PC
                           the Baby Log app: reads the folder, writes
                           Baby Log.xlsx and the day sheets into Yisen File
```

Every feed, diaper, sleep, weight or note is one small file in `OneDrive\Apps\Baby Log`. Both
phones and the PC write there and read from there; nobody talks to anybody directly, so nothing
has to be switched on at the same time. The PC turns that folder into the readable
`Baby Log.xlsx` and the printable day sheets in `Yisen File`.

Two things have to exist before any of that works: a Microsoft *app registration* (what lets the
phones reach the folder, and nothing else in your OneDrive) and a web address for the phone app
(GitHub Pages). Parts 1 and 2 make those. Part 3 sets up the PC, Part 4 the phones.

> **The two-accounts trap, again.** You have more than one Microsoft account, and the Baby Log
> folder lives on the **personal** one — the same OneDrive that holds the Whiskey File folder.
> entra.microsoft.com signs you in with whichever account the browser already has a session for,
> often the wrong one. Before every step in Part 1, look at the avatar in the top right and make
> sure it is the personal account. If it is not, sign out or use a private window. A registration
> made under the work account cannot reach the personal OneDrive at all, and the error it gives
> does not say so.

---

## Part 1 — Register the app with Microsoft (15 min)

1. Go to **https://entra.microsoft.com** and sign in with your **personal** Microsoft account.
   If the site bounces a personal account, use https://portal.azure.com → search
   "Microsoft Entra ID" → **App registrations**. Same screens.
2. Left menu → **Applications** → **App registrations** → **New registration**.
3. **Name:** `Baby Log` — exactly that, capital B, capital L, one space.
   > This name becomes the OneDrive folder name: `OneDrive\Apps\Baby Log`. The PC's setup
   > script writes that same path into its settings. Renaming the registration later would
   > point the phones at a different, empty folder.
4. **Supported account types:** **Personal accounts only** (the last of the four options).
   With two accounts in play, this makes signing in with the wrong one impossible.
5. **Redirect URI:** leave it **empty** for now. It is added in Part 2, once the web address
   exists. Nothing is registered for localhost.
6. Click **Register**.
7. On the overview page, copy the **Application (client) ID** — a GUID like `3f9a2c14-…`.
   Keep it; Part 2 step 5 needs it. **It is not a secret**: every browser app of this kind ships
   it in plain view, and on its own it is useless.
8. Left menu of the registration → **API permissions** → **Add a permission** →
   **Microsoft Graph** → **Delegated permissions** → tick **`Files.ReadWrite.AppFolder`** →
   **Add permissions**. `User.Read` may already be there; leave it.
9. **Do not create a client secret.** A single-page app must not have one; adding one breaks the
   sign-in flow.

### Sanity check

Under **API permissions** you should see `Files.ReadWrite.AppFolder` (and possibly `User.Read`)
and nothing else. If `Files.ReadWrite` or `Files.ReadWrite.All` is there, remove it — those reach
your whole drive. The one exception is the troubleshooting step at the end of this guide, and
there it is removed again the same day.

`OneDrive\Apps\Baby Log` **will not exist yet.** The folder appears the first time something
writes to it — the PC's setup script in Part 3 creates it, and the phones would too. Nothing is
wrong if you look and it is not there.

---

## Part 2 — Put the phone app on the web (15 min)

The phone app is a web page, so it needs an address. GitHub Pages hosts it for free; nothing runs
between visits and there is no server to patch. The repository does not exist yet, so this part
creates it. Your GitHub account is `RollingShuttle`, the one the whiskey app uses.

### Step A — the repository

1. Go to https://github.com/new. **Repository name:** `baby-log`. Public (Pages on a free
   account needs that; the tree carries no personal data beyond the child's first name — see
   `CLAUDE.md`). Do not tick "Add a README". **Create repository**.
2. In a terminal in the project folder (`E:\Claude Code\baby-logging`):

   ```
   git remote add origin https://github.com/RollingShuttle/baby-log.git
   git push -u origin main
   ```

   If you name the repository something other than `baby-log`, tell me: `tools/update.py`
   carries that clone address as a placeholder and it has to match.

### Step B — Pages

1. On the repository page → **Settings** → **Pages** (left menu).
2. Under "Build and deployment": **Source** = *Deploy from a branch*; **Branch** = `main`,
   folder = **`/docs`**; **Save**.
3. Wait a minute or two, reload the page, and it shows the address. With the names above it is

   ```
   https://rollingshuttle.github.io/baby-log/
   ```

   Open it on the PC to check it loads. It will ask "Who is holding this phone?" — that is fine,
   close it; it is the phones that matter.

### Step C — the redirect URI

Back in the Entra portal, on the `Baby Log` registration:

1. Left menu → **Authentication** → **Add a platform** → **Single-page application** (not
   "Web" — SPA is what allows sign-in without a secret).
2. Redirect URI: the Pages address **exactly, with the trailing slash**:

   ```
   https://rollingshuttle.github.io/baby-log/
   ```

3. **Configure** (or **Save**). This is the only redirect URI the registration needs. Nothing
   for localhost, nothing for the PC — the PC never signs in to anything; it reads the synced
   folder as ordinary files.

### Step D — the client ID

1. In the project folder, open `docs/config.js` in any text editor. Near the top:

   ```
   CLIENT_ID: "",
   ```

   Paste the ID from Part 1 step 7 between the quotes.
2. Double-click `push.bat`. It bumps the phone app's version, runs the tests, commits and
   pushes. (Done on 26 Sep 2026: the ID is in, and the two tests that used to insist it was
   blank now check that it looks like one. If the ID ever changes, this step is the whole job.)

Pages picks the change up within a minute or two.

---

## Part 3 — The PC, first (10 min)

The PC goes first so that Yisen and the hospital's first three days are in the folder before
either phone signs in. Open a terminal in the project folder and run these in order:

```
python tools/setup_machine.py
pip install -r requirements.txt
python paper.py
build_exe.bat
python tools/make_shortcut.py
```

What each one does:

1. **`setup_machine.py`** finds your OneDrive and writes `config.yaml` with the two folders:
   `OneDrive\Apps\Baby Log` (the journal) and `OneDrive\文档\Yisen File` (the readable files).
   It creates both if they are missing and pins the journal folder to *Always keep on this
   device*, so OneDrive never leaves a file as a cloud placeholder the app cannot read.
   `config.yaml` is not in the repository because those paths contain your username.
2. **`pip install`** — the four small libraries the app needs.
3. **`paper.py`** reads the transcribed hospital sheet (`tools/paper_sheet.json`) and writes it
   into the journal: Yisen, born 21 Sep 2026, and the 18 feeds and 19 diapers from the first
   three days. Eight readings were hard to make out on the photo; those carry a `Check: …` note
   and show up under **Needs check** in the app so you can correct them (`RUNNING.md` says how).
   It prints every row it writes. Running it twice is safe — the second run says
   `0 written, 37 skipped`. `python paper.py --dry-run` shows the plan without writing.
4. **`build_exe.bat`** packages the app as `Baby Log.exe` (no console window). It takes about
   twenty seconds and is not in the repository.
5. **`make_shortcut.py`** puts a **Baby Log** icon on the Desktop and in the Start menu.

Then double-click the icon. The window opens on **Today** with Yisen's name and age in the top
bar and the first three days behind **‹ prev**. Go to **Settings** and fill in **Label (who logs
from here)** — whoever mostly sits at this PC — and **Save settings**. The label is what an entry
shows as its "By".

If **Today** instead shows a card headed **Who is this log for?**, the paper import did not run
(or ran into an empty folder). Close the app, run `python paper.py` again, and read what it
prints. Adding the child by hand in that card also works, but then run the import *afterwards*
and it will attach the paper entries to the child that exists rather than making a second one.

---

## Part 4 — Both iPhones (5 min each)

Do this on Dad's phone, then on Mom's. Same steps, different answer to the first question.

1. Check **Settings → Apps → Safari → Block All Cookies** is **off**. It breaks Microsoft
   sign-in. *Prevent Cross-Site Tracking* can stay on.
2. Open **Safari** — it has to be Safari; installing from Chrome does not give you a real app —
   and go to `https://rollingshuttle.github.io/baby-log/`.
3. Tap **Share** (the square with the arrow) → **Add to Home Screen** → **Add**.
4. Open it from the new icon. It asks **Who is holding this phone?** — tap **Dad** or **Mom**
   (or **Other…** and type). This is the label stamped on everything logged from this phone; it
   can be changed later in Settings.
5. **Settings** tab → **Sign in**. Sign in with the **personal** Microsoft account — the same one
   on both phones; the device label is what tells them apart, not the account.
6. When Microsoft asks **"Stay signed in?"**, answer **Yes**. That is what lets the app keep its
   sign-in after iOS closes it in the background; answer No and you will be signing in every
   time you open it.
7. Back in the app, the pill at the top goes from `Signed out · tap to sign in` to `Syncing…`
   and then `Synced just now`, and the **Now** tab shows the last feed and diaper from the paper
   sheet. Done.

Until the first successful sign-in the Now screen says "Waiting for the first sync" and the log
buttons are off — the phone has no child to log against yet. After it, everything works with no
signal at all.

---

## Living with the daily "Continue" tap

Microsoft caps a browser app's sign-in at **24 hours** and it is not adjustable. So about once a
day the pill on the phone turns to `Signed out · 3 waiting · tap to sign in`. Tap it, tap
**Continue as <you>** — one tap, no password, because the session cookie lives inside the
installed app — and it carries on.

The important part: **signed out never blocks logging.** Every entry is saved on the phone the
instant you tap Save, and only the *upload* waits. Log at 3 a.m. signed out and everything goes
up after the next sign-in. The number in the pill is how many entries are waiting.

---

## Troubleshooting

| What you see | What it means and what to do |
|---|---|
| Sign-in fails with a "redirect URI" message | The address in Part 2 step C does not match the page exactly — check the trailing slash and the capitalisation. |
| Sign-in works but the pill says `Sync failed · … · tap for details` and the details say **`accessDenied`** or **`serviceReadOnly`** | See below — a known Microsoft problem on brand-new AppFolder-only registrations. |
| Settings → Sync says `Sign-in is not configured yet` and the pill leads to Settings | `docs/config.js` still has a blank `CLIENT_ID`, or the push has not reached Pages yet. |
| The phone still shows an old version after a push | Wait ten minutes — GitHub keeps every file that long — then open the app: it says *New version ready* with **Reload**. Settings → Sync shows *Phone app vN*, the number in `docs/sw.js`, so you can check. (Before v8 the phone had to be closed and reopened twice instead.) |
| The PC says `Who is this log for?` | The journal has no child. Run `python paper.py` (Part 3). |
| The PC window never appears | Read `error.log` in the project folder; the reason is written there. |
| `OneDrive\Apps\Baby Log` is not in File Explorer | Normal until something writes to it. Run `python tools/setup_machine.py`, which creates it. |
| A phone signed in with the work account by mistake | Settings → **Sign out**, then sign in again and watch which account the Microsoft page offers. Nothing from that session was written anywhere reachable. |

### The first-sign-in problem on new AppFolder-only apps

Since about August 2026, a freshly registered app whose *only* permission is
`Files.ReadWrite.AppFolder` sometimes cannot create its own folder on the first sign-in.
Microsoft's side has not provisioned the app folder yet, and every call comes back
`accessDenied` or `serviceReadOnly`, which the pill shows as `Sync failed`. Signing out and in
again does not help, and nothing is wrong with your setup.

The one-time escape hatch, on the PC:

1. Entra → the `Baby Log` registration → **API permissions** → **Add a permission** →
   **Microsoft Graph** → **Delegated** → tick **`Files.ReadWrite`** (the plain one) → **Add**.
2. On one phone: Settings → **Sign out**, then **Sign in** again. Microsoft asks you to consent
   to the wider permission; accept. Wait for the pill to say `Synced`. The folder now exists.
3. Back in Entra → **API permissions** → the `…` beside `Files.ReadWrite` → **Remove
   permission**. Do this the same day.
4. On both phones, sign out and sign in once more so the phones hold a token with only the
   narrow permission again.

Because the PC's setup script created `OneDrive\Apps\Baby Log` locally in Part 3 and the OneDrive
client uploaded it, you may never hit this at all. It is here in case you do.
