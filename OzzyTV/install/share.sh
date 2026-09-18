#!/bin/sh
# share.sh — put the media folder on the network, so films arrive over wifi
# instead of on a memory stick.
#
#   sudo ./install/share.sh              # set it up and start it
#   sudo ./install/share.sh --disable    # stop sharing, put smb.conf back
#   sudo ./install/share.sh --password   # change the password only
#
# ONE folder is shared — the one the television reads. Not the home directory,
# not the app, not the root of the disk. A machine a child uses unattended is
# not a machine to put a wide-open file server on.
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
for a in "$@"; do
  case "$a" in
    --disable)  MODE=disable ;;
    --password) MODE=password ;;
    *) die "unknown option '$a' (try --disable or --password)" ;;
  esac
done

if [ "$MODE" = disable ]; then
  say "turning the share off"
  systemctl disable --now smbd nmbd wsdd 2>/dev/null || true
  if [ -f "$BACKUP" ]; then
    mv "$BACKUP" "$SMB_CONF"
    say "put back the smb.conf that was there before"
  fi
  systemctl restart smbd 2>/dev/null || true
  echo
  echo "The folder is no longer on the network. Nothing in $MEDIA was touched."
  exit 0
fi

if [ "$MODE" = password ]; then
  smbpasswd -a "$OWNER"
  echo
  echo "Done. Use it with the username: $OWNER"
  exit 0
fi

# ---- packages -------------------------------------------------------------
say "installing Samba"
export DEBIAN_FRONTEND=noninteractive
apt-get update -qq || warn "apt-get update failed — carrying on with what is cached"
apt-get install -y --no-install-recommends samba samba-common-bin \
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

   # Everyone who connects is a real user with a real password. 'map to guest =
   # never' matters as much as the rest: without it a wrong password silently
   # becomes an anonymous login rather than a refusal.
   security = user
   map to guest = never
   restrict anonymous = 2
   null passwords = no

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
   guest ok = no
   valid users = $OWNER
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
if pdbedit -L 2>/dev/null | cut -d: -f1 | grep -qx "$OWNER"; then
  say "'$OWNER' already has a share password; leaving it alone"
  say "  (change it with: sudo ./install/share.sh --password)"
else
  say "set a password for connecting to the share, as user '$OWNER'"
  echo "  This is separate from the Pi's login password."
  smbpasswd -a "$OWNER"
fi

# ---- start it -------------------------------------------------------------
systemctl enable --now smbd
systemctl enable --now avahi-daemon 2>/dev/null || true
systemctl enable --now wsdd 2>/dev/null || true
systemctl restart smbd

IP="$(hostname -I 2>/dev/null | awk '{print $1}')"
HOST="$(hostname -s)"

say "done"
cat <<TXT

$MEDIA is on the network as \\\\$HOST\\$SHARE_NAME

  From a Mac      Finder, Cmd-K:   smb://$IP/$SHARE_NAME
  From Windows    Explorer:        \\\\$IP\\$SHARE_NAME
  From Linux      Files, Ctrl-L:   smb://$IP/$SHARE_NAME

  Username: $OWNER
  Password: the one you just set (not the Pi's login password)

Copy programmes in, then allow them for your child — over ssh:

    ozzytv --scan
    ozzytv --allow "$MEDIA/Bluey"

or on the television itself: press P, enter the PIN.

The television notices new files on its own within a few seconds; there is
nothing to restart.

TXT
