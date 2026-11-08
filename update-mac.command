#!/bin/bash
# Baby Log on the Mac: get the latest code. Double-click this file in Finder (or keep it in the
# Dock). It throws away what Xcode wrote into ios/ during builds, pulls, and leaves Xcode to
# reload the project by itself. The team ID in ios/Local.xcconfig is untracked and untouched.
cd "$(dirname "$0")" || exit 1
echo "Baby Log - updating from GitHub..."
echo ""
git checkout -- ios 2>/dev/null
if git pull --ff-only; then
    echo ""
    echo "Done. Xcode reloads on its own; then Product > Archive to ship it."
else
    echo ""
    echo "The pull failed - send a screenshot of this window to Claude."
fi
echo ""
read -n 1 -s -r -p "Press any key to close this window."
echo ""
