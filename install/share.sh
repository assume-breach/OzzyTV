#!/bin/sh
# share.sh — put the media folder on the network, so films arrive over wifi
# instead of on a memory stick.
#
#   sudo ./install/share.sh              # set it up and start it — open, no login
#   sudo ./install/share.sh --private    # require a username and password
#   sudo ./install/share.sh --disable    # stop sharing, put smb.conf back
#   sudo ./install/share.sh --password   # set/change the password (implies --private)
#
# Open by default: no username, no password. Dropping a film on a Pi should not
# involve a credential. What keeps that reasonable is everything AROUND it —
# ONE folder is shared, the one the television reads, never the home directory,
# the app or the root of the disk, and only ever to the local network. Anyone on
# the wifi can read and write that folder; on a home network that is the point.
# `--private` requires a login instead.
set -eu

MEDIA="${OZZYTV_MEDIA:-/media/ozzy}"
SMB_CONF="${OZZYTV_SMB_CONF:-/etc/samba/smb.conf}"
BACKUP="$SMB_CONF.before-ozzytv"
SHARE_NAME="${OZZYTV_SHARE_NAME:-ozzytv}"

say()  { printf '\n\033[1;32m==\033[0m %s\n' "$*"; }
warn() { printf '\033[1;33mWARNING:\033[0m %s\n' "$*" >&2; }
die()  { printf '\033[1;31mERROR:\033[0m %s\n' "$*" >&2; exit 1; }

[ "$(id -u)" -eq 0 ] || die "run this with sudo."

OWNER="${SUDO_USER:-}"
[ -n "$OWNER" ] && [ "$OWNER" != root ] || OWNER="$(getent passwd 1000 | cut -d: -f1)"
[ -n "$OWNER" ] || die "could not work out which user owns the media folder."

MODE=enable
# Also settable from the environment, so install.sh --share-private can pass it
# straight through rather than re-implementing the flag.
PRIVATE="${OZZYTV_SHARE_PRIVATE:-0}"
NEEDS_PASSWORD=
for a in "$@"; do
  case "$a" in
    --disable)  MODE=disable ;;
    --private)  PRIVATE=1 ;;
    --password) MODE=password ;;
    *) die "unknown option '$a' (try --private, --disable or --password)" ;;
  esac
done

if [ "$MODE" = disable ]; then
  say "turning the share off"
  systemctl disable --now smbd nmbd wsdd 2>/dev/null || true
  if [ -f "$BACKUP" ]; then
    mv "$BACKUP" "$SMB_CONF"
    say "put back the smb.conf that was there before"
  elif [ -f "$SMB_CONF" ] && grep -q "Written by Ozzy TV" "$SMB_CONF"; then
    # No backup because there was nothing here before we wrote it — a machine
    # with no Samba config of its own. Restoring "what was there" means removing
    # ours, not leaving it behind switched off.
    rm -f "$SMB_CONF"
    rmdir "$(dirname "$SMB_CONF")" 2>/dev/null || true
    say "removed the smb.conf this wrote; there was none here before"
  fi
  systemctl restart smbd 2>/dev/null || true
  echo
  echo "The folder is no longer on the network. Nothing in $MEDIA was touched."
  exit 0
fi

PRIVATE_FLAG="$(dirname "$SMB_CONF")/ozzytv-private"

if [ "$MODE" = password ]; then
  smbpasswd -a "$OWNER"
  # Remember it, so a later plain `share.sh` does not silently reopen a share
  # somebody deliberately locked. Turning it back off is explicit: --disable
  # then a plain run.
  mkdir -p "$(dirname "$PRIVATE_FLAG")" && : > "$PRIVATE_FLAG"
  echo
  echo "The share now needs a login. Username: $OWNER"
  exit 0
fi

# A share somebody made private stays private across re-runs and upgrades.
[ -f "$PRIVATE_FLAG" ] && PRIVATE=1
[ "$PRIVATE" -eq 1 ] && { mkdir -p "$(dirname "$PRIVATE_FLAG")"; : > "$PRIVATE_FLAG"; } \
                     || rm -f "$PRIVATE_FLAG" 2>/dev/null || true

# ---- packages -------------------------------------------------------------
say "installing Samba"
export DEBIAN_FRONTEND=noninteractive
apt-get update -qq || warn "apt-get update failed — carrying on with what is cached"
apt-get install -y --no-install-recommends samba samba-common-bin smbclient \
  || die "could not install Samba. Fix the errors above and re-run."
# So the Pi turns up by itself in Finder and in Windows' Network list. Neither
# is required to USE the share, so neither is fatal.
apt-get install -y --no-install-recommends avahi-daemon wsdd \
  || warn "avahi/wsdd did not install — the share works, you will just have to
         type the address instead of finding it in a list."

# ---- the folder -----------------------------------------------------------
[ -d "$MEDIA" ] || { say "creating $MEDIA"; mkdir -p "$MEDIA"; }
chown "$OWNER":"$OWNER" "$MEDIA"
chmod 0775 "$MEDIA"

# ---- open, or asking for a login? -----------------------------------------
if [ "$PRIVATE" -eq 1 ]; then
  # Everyone who connects is a real user with a real password. 'map to guest =
  # never' matters as much as the rest: without it a wrong password silently
  # becomes an anonymous login rather than a refusal.
  GLOBAL_GUEST='   map to guest = never
   restrict anonymous = 2
   null passwords = no'
  SHARE_GUEST="   guest ok = no
   valid users = $OWNER"
else
  # Open. 'map to guest = bad user' sends an unknown username to the guest
  # account rather than refusing it, and 'guest only' means nothing ever gets
  # asked for a password. The guest account IS the television's user, so files
  # arrive owned by the thing that has to read them.
  GLOBAL_GUEST="   map to guest = bad user
   guest account = $OWNER"
  SHARE_GUEST='   guest ok = yes
   guest only = yes'
fi

# ---- the configuration ----------------------------------------------------
# Written whole rather than appended to. This Pi has one job, so a small file
# that can be read in one go beats a stock config with edits threaded through
# it — and --disable can then put the original back exactly.
[ -f "$SMB_CONF" ] && [ ! -f "$BACKUP" ] && cp "$SMB_CONF" "$BACKUP"
mkdir -p "$(dirname "$SMB_CONF")"
cat > "$SMB_CONF" <<CONF
# Written by Ozzy TV's share.sh. The previous file is at
# $BACKUP and 'share.sh --disable' puts it back.
[global]
   workgroup = WORKGROUP
   server string = Ozzy TV
   netbios name = $(hostname -s)
   server role = standalone server

   security = user
$GLOBAL_GUEST

   # SMB1 is off. It is how most of the well-known file-sharing worms travel,
   # and nothing made this decade needs it.
   server min protocol = SMB2_10
   client min protocol = SMB2_10

   # The house, and nothing else. If this Pi is ever put on a network it does
   # not own, this line is what stops the folder going with it.
   hosts allow = 127.0.0.1 10. 172.16. 172.17. 172.18. 172.19. 172.20. 172.21. 172.22. 172.23. 172.24. 172.25. 172.26. 172.27. 172.28. 172.29. 172.30. 172.31. 192.168. 169.254.
   hosts deny = 0.0.0.0/0

   # No printers, and no letting a logged-in user invent new shares.
   load printers = no
   printing = bsd
   printcap name = /dev/null
   disable spoolss = yes
   usershare max shares = 0

   log file = /var/log/samba/log.%m
   max log size = 1000
   logging = file

[$SHARE_NAME]
   comment = Ozzy TV media
   path = $MEDIA
   browseable = yes
   read only = no
$SHARE_GUEST
   # Whatever a laptop calls itself, files land owned by the user the television
   # runs as — otherwise they arrive unreadable and the menu stays empty.
   force user = $OWNER
   force group = $OWNER
   create mask = 0664
   directory mask = 0775
   # The debris a Mac and a Windows box leave in every folder they touch.
   veto files = /._*/.DS_Store/Thumbs.db/desktop.ini/.Spotlight-V100/.Trashes/
   delete veto files = yes
CONF

testparm -s "$SMB_CONF" >/dev/null 2>&1 \
  || { [ -f "$BACKUP" ] && cp "$BACKUP" "$SMB_CONF"
       die "the Samba configuration this wrote is not valid; put the old one back."; }

# ---- who may connect ------------------------------------------------------
# Samba keeps its own password database. This is NOT the Pi's login password,
# and deliberately so: the thing that can write to a child's media folder over
# the network should not also be the thing that can log into the machine.
if [ "$PRIVATE" -eq 0 ]; then
  say "open share — no username, no password"
elif pdbedit -L 2>/dev/null | cut -d: -f1 | grep -qx "$OWNER"; then
  say "'$OWNER' already has a share password; leaving it alone"
  say "  (change it with: sudo ./install/share.sh --password)"
elif [ -t 0 ]; then
  say "set a password for connecting to the share, as user '$OWNER'"
  echo "  This is separate from the Pi's login password."
  smbpasswd -a "$OWNER"
else
  # Nobody at the keyboard — a piped install, or a script. Leave the share set
  # up but with no password, which refuses every connection rather than
  # accepting anonymous ones. An unattended install must not quietly end with a
  # child's media folder open to the network.
  NEEDS_PASSWORD=1
  warn "no terminal to ask for a password on, so the share has none yet and
         will refuse connections. Set one with:
             sudo ./install/share.sh --password"
fi

# ---- start it -------------------------------------------------------------
systemctl enable --now smbd
systemctl enable --now avahi-daemon 2>/dev/null || true
systemctl enable --now wsdd 2>/dev/null || true
systemctl restart smbd

if [ "$PRIVATE" -eq 1 ]; then
  CREDS="  Username: $OWNER
  Password: ${NEEDS_PASSWORD:+NOT SET YET — run: sudo ./install/share.sh --password}${NEEDS_PASSWORD:-the one you set}"
else
  CREDS="  No username, no password. Connect as a guest.

  Windows 10 and 11 refuse guest shares out of the box. Either run
      sudo ./install/share.sh --private
  and use a login, or turn on 'Insecure guest logons' in Windows.
  Macs and Linux connect as guest without complaining."
fi

# ---- did it actually work? ------------------------------------------------
# "systemctl enable" returning 0 means systemd accepted the unit, not that a
# laptop can see the folder. Ask Samba itself, the way a client would.
PROBLEMS=""
systemctl is-active smbd >/dev/null 2>&1 \
  || PROBLEMS="$PROBLEMS\n  - smbd is not running (systemctl status smbd)"
if command -v smbclient >/dev/null 2>&1; then
  if [ "$PRIVATE" -eq 0 ]; then
    smbclient -N -L localhost 2>/dev/null | grep -q "$SHARE_NAME" \
      || PROBLEMS="$PROBLEMS\n  - Samba is running but does not offer '$SHARE_NAME'"
    smbclient -N "//localhost/$SHARE_NAME" -c 'ls' >/dev/null 2>&1 \
      || PROBLEMS="$PROBLEMS\n  - the share exists but refuses a guest connection"
  fi
else
  warn "smbclient is not installed, so this could not test the share from the
         outside. Install it with: sudo apt install smbclient"
fi
if [ -n "$PROBLEMS" ]; then
  printf '\n\033[1;31mThe share is configured but not working:\033[0m'
  printf "$PROBLEMS\n\n"
  printf 'Look at:  sudo testparm -s ; journalctl -u smbd -n 30 --no-pager\n\n'
  exit 1
fi

IP="$(hostname -I 2>/dev/null | awk '{print $1}')"
HOST="$(hostname -s)"

say "done"
cat <<TXT

$MEDIA is on the network as \\\\$HOST\\$SHARE_NAME

  From a Mac      Finder, Cmd-K:   smb://$IP/$SHARE_NAME
  From Windows    Explorer:        \\\\$IP\\$SHARE_NAME
  From Linux      Files, Ctrl-L:   smb://$IP/$SHARE_NAME

$CREDS

Copy shows in, then allow them for your child — over ssh:

    ozzytv --scan

Everything you copy in shows up on its own. To hide something:

    ozzytv --block "$MEDIA/<what>"

The television notices new files on its own within a few seconds; there is
nothing to restart.

TXT
