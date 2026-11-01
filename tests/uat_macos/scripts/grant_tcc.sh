#!/bin/bash
# Grant the permissions real input needs on a GitHub-hosted macOS runner (eyewall S4 recipe).
# Relies on SIP being off and passwordless sudo, as on the hosted images. Usage: grant_tcc.sh PYTHON_PATH
set -u
PY="$(readlink -f "${1:-$(command -v python3)}")"
CLICK="$(command -v cliclick)"
paths=(/opt/hca/hosted-compute-agent /usr/bin/osascript /bin/bash /bin/sh /usr/bin/python3 "$PY" "$CLICK" /usr/sbin/screencapture
  /System/Applications/Utilities/Terminal.app/Contents/MacOS/Terminal /Applications/iTerm.app/Contents/MacOS/iTerm2)
bundles=(com.apple.Terminal com.googlecode.iterm2 com.apple.systemevents)
for db in "/Library/Application Support/com.apple.TCC/TCC.db" "$HOME/Library/Application Support/com.apple.TCC/TCC.db"; do
  echo "== $db"
  for svc in kTCCServiceAccessibility kTCCServiceScreenCapture kTCCServicePostEvent kTCCServiceListenEvent; do
    for c in "${paths[@]}"; do
      sudo sqlite3 "$db" "INSERT OR REPLACE INTO access (service,client,client_type,auth_value,auth_reason,auth_version,flags,last_modified) VALUES ('$svc','$c',1,2,4,1,0,strftime('%s','now'));" 2>&1 | head -2
    done
    for c in "${bundles[@]}"; do
      sudo sqlite3 "$db" "INSERT OR REPLACE INTO access (service,client,client_type,auth_value,auth_reason,auth_version,flags,last_modified) VALUES ('$svc','$c',0,2,4,1,0,strftime('%s','now'));" 2>&1 | head -2
    done
  done
  for c in "${paths[@]}"; do for tgt in com.apple.systemevents com.apple.Terminal com.googlecode.iterm2; do
    sudo sqlite3 "$db" "INSERT OR REPLACE INTO access (service,client,client_type,auth_value,auth_reason,auth_version,indirect_object_identifier_type,indirect_object_identifier,flags,last_modified) VALUES ('kTCCServiceAppleEvents','$c',1,2,4,1,0,'$tgt',0,strftime('%s','now'));" 2>&1 | head -2
  done; done
done
sudo killall tccd 2>/dev/null
sleep 3
# Preflight: a System Events key press must succeed, or Apple Events are still blocked.
osascript -e 'tell application "System Events" to key code 0'
