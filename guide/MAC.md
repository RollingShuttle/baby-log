# Baby Log on the Mac — building and installing the iPhone app

The iPhone app lives in `ios/` (an Xcode project, Swift, no packages to download). It was
written on the PC, where nothing can compile Swift, so the first build in Xcode is the first
compile: expect a few red lines, paste them into a Claude Code session and have them fixed.
After that, every update is *pull, then Run*.

## Once, on the Mac

1. **Your own macOS user** (System Settings → Users & Groups → Add User), so your Apple ID,
   Xcode and the repository stay separate from the Mac owner's. Sign in to that user for all
   of this.
2. **Xcode** from the App Store, opened once (it installs its tools). Xcode → Settings →
   Accounts → add the Apple ID that is enrolled in the Developer Program.
3. **The code**: Xcode's welcome window → *Clone Git Repository…* →
   `https://github.com/RollingShuttle/baby-log.git` → choose a folder such as
   `~/Developer/baby-log`. (Or in Terminal: `git clone https://github.com/RollingShuttle/baby-log.git`.)
4. **Open `ios/BabyLog.xcodeproj`.** Select the *BabyLog* target → *Signing & Capabilities* →
   tick *Automatically manage signing* → pick your *Team*. The bundle ID is
   `com.rollingshuttle.babylog`; if Apple says it is taken, change it there **and** in
   `ios/BabyLog/Config.swift` (`bundleId`, `callbackScheme`, `redirectUri`) **and** in the Entra
   step below — the three must match.
5. **Entra, the iOS platform** (once, on any computer): portal.azure.com → *App registrations*
   → *Baby Log* → *Authentication* → *Add a platform* → *iOS / macOS* → Bundle ID
   `com.rollingshuttle.babylog` → *Configure*. That registers the redirect
   `msauth.com.rollingshuttle.babylog://auth` the app signs in through. The existing web
   platform stays; nothing else changes (same client ID, same one scope).

## Putting it on a phone

6. On the iPhone: *Settings → Privacy & Security → Developer Mode* → on (it restarts).
7. Plug the phone into the Mac (or have both on the same Wi-Fi after the first cable run),
   choose it in Xcode's run destination (top bar, next to *BabyLog*), press **Run** (⌘R).
   The first time, the phone asks you to trust the developer: *Settings → General → VPN &
   Device Management* → your team → *Trust*.
8. In the app: tap the sync pill → *Sign in with Microsoft* → the same Microsoft account the PC
   and the web app use. The first sync pulls the whole journal (a few pages of listing, then
   six downloads at a time: seconds, not minutes). Then *Settings* (gear) → *Who is holding
   this phone?* → **Dad** or **Mom**.
9. The other phone: the same steps 6–7 with that phone plugged in, or, once Stage 3 is built,
   TestFlight. A build from a paid team runs for a year before it needs another Run.

## Updating

Xcode → *Integrate → Pull* (or `git pull` in the folder), then **Run** again with the phone
connected. Nothing on the phone needs to be removed first; the journal mirror and the sign-in
stay.

## What is in this first version (Stage 1 of guide/IOS-APP-PLAN.md)

Today: the Now panel (child and age, last feed, last diaper, today's totals), the day list with
*‹ ›* days, **Feed** (amount chips from the range in Settings, formula chips from the latest
portions, note) and one-tap **Wet · Dirty · Both**, a **Note**, tap a row to edit, swipe to
delete. Settings: sign-in, sync, who, the quick-amount range, language (follow the phone,
English, 简体中文). Sync runs when the app opens, two seconds after every save, and on
pull-to-refresh or a tap on the pill.

Not yet: sleep and pump timers, growth, health, the bath type, photos, the outing checklist,
reminders, Siri, widgets, TestFlight. The plan's Stages 2–5 list them in order.

## How sync works now (and why it is fast)

The phone keeps a mirror of the OneDrive app folder (the same `children/` and
`events/<day>/` files) and an outbox. A sync uploads the outbox, then asks Graph for the
folder's **delta** — everything that changed since the last sync, in pages of a few hundred —
and downloads only the files it does not have, six at a time through pre-authorised download
links that do not count against Graph's request budget. The first sync of a thousand files is
seconds; a later sync usually finds a handful. The web app listed day folders one by one and
fetched files one by one, which is why 200 entries took twenty minutes there.

The PC has no sync of its own and needs none: the OneDrive desktop client keeps
`OneDrive\Apps\Baby Log` on disk, and the app scans that folder every 60 seconds (guide/RUNNING.md).
What the phones upload appears on the PC as soon as the OneDrive client has fetched it,
usually within a minute.
