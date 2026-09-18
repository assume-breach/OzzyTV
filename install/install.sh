#!/bin/sh
# install.sh — put Ozzy TV on a Raspberry Pi and make it the thing the Pi does.
#
# Safe to re-run: every step checks before it acts, so this doubles as the
# upgrade path.
#
#   sudo ./install/install.sh                 # install and enable
#   sudo ./install/install.sh --no-kiosk      # install only; start it yourself
#   sudo ./install/install.sh --no-share      # skip the network share
#   sudo ./install/install.sh --share-private # share, but ask for a login
#   sudo ./install/install.sh --uninstall
set -eu

# Every destination is overridable so the installer can be exercised against a
# temporary root (see tests/test_install.py). An installer that is only ever run
# for real is one nobody finds out is broken until a Pi is already wiped.
APP_DIR="${OZZYTV_APP_DIR:-/opt/ozzytv}"
BIN="${OZZYTV_BIN:-/usr/local/bin}"
UNIT_DIR="${OZZYTV_UNIT_DIR:-/etc/systemd/system}"
MEDIA_DEFAULT="${OZZYTV_MEDIA:-/media/ozzy}"
XWRAPPER="${OZZYTV_XWRAPPER:-/etc/X11/Xwrapper.config}"
HERE="$(cd "$(dirname "$0")/.." && pwd)"

say()  { printf '\n\033[1;32m==\033[0m %s\n' "$*"; }
warn() { printf '\033[1;33mWARNING:\033[0m %s\n' "$*" >&2; }
die()  { printf '\033[1;31mERROR:\033[0m %s\n' "$*" >&2; exit 1; }

[ "$(id -u)" -eq 0 ] || die "run this with sudo."

KIOSK=1
# On by default. Getting programmes onto the machine is not an optional extra —
# it is the second thing anybody needs after the menu appears, and the answer
# "now copy them onto a memory stick and walk them over" is not one.
SHARE=1
SHARE_PRIVATE="${OZZYTV_SHARE_PRIVATE:-0}"
UNINSTALL=0
for a in "$@"; do
  case "$a" in
    --no-kiosk)  KIOSK=0 ;;
    --no-share)  SHARE=0 ;;
    --share-private) SHARE_PRIVATE=1 ;;
    --uninstall) UNINSTALL=1 ;;
    *) die "unknown option '$a' (try --no-kiosk, --no-share, --share-private or --uninstall)" ;;
  esac
done

# Who owns the television. Not root: X, VLC and the settings file all belong to a
# person, and running a media player as root on a machine a child uses is the
# kind of thing that is fine until it is not.
OWNER="${SUDO_USER:-}"
[ -n "$OWNER" ] && [ "$OWNER" != root ] || OWNER="$(getent passwd 1000 | cut -d: -f1)"
[ -n "$OWNER" ] || die "could not work out which user to install for; run this with sudo as that user."

STATE="$APP_DIR/installed-state"

if [ "$UNINSTALL" -eq 1 ]; then
  say "removing Ozzy TV"
  [ -x "$HERE/install/share.sh" ] && sh "$HERE/install/share.sh" --disable || true
  systemctl disable --now "ozzytv@$OWNER.service" 2>/dev/null || true
  rm -f "$UNIT_DIR/ozzytv@.service" "$BIN/ozzytv-session" "$BIN/ozzytv"
  systemctl daemon-reload
  systemctl enable getty@tty1.service 2>/dev/null || true
  # Put back whatever we switched off to get the screen. Recorded at install
  # time: a desktop that does not come back is a worse surprise than one that
  # never went away.
  if [ -f "$STATE" ]; then
    _dm="$(sed -n 's/^display_manager=//p' "$STATE")"
    _tgt="$(sed -n 's/^default_target=//p' "$STATE")"
    [ -n "$_dm" ] && { systemctl enable "$_dm" 2>/dev/null || true
                       say "re-enabled $_dm"; }
    [ -n "$_tgt" ] && { systemctl set-default "$_tgt" 2>/dev/null || true
                        say "boot target back to $_tgt"; }
  fi
  rm -rf "$APP_DIR"
  echo "Removed. Your media and your choices in ~$OWNER/.local/share/ozzytv were left alone."
  exit 0
fi

# ---- packages -------------------------------------------------------------
# vlc          the engine
# python3-vlc  the bindings this talks to it through
# python3-tk   the menus (stdlib, but Debian splits it out)
# xserver/xinit  a screen to draw on, with no desktop
# unclutter    hides the mouse pointer
# x11-utils    xmessage, so a failure to start appears ON THE TELEVISION rather
#              than only in the journal — a black screen tells nobody anything
# ffmpeg       OPTIONAL: lets the parent screen warn about files this Pi cannot play
# cec-utils    OPTIONAL: the TV's own remote
say "installing packages"
export DEBIAN_FRONTEND=noninteractive
apt-get update -qq || warn "apt-get update failed — carrying on with what is cached"
apt-get install -y --no-install-recommends \
    vlc python3-vlc python3-tk xserver-xorg xinit x11-xserver-utils x11-utils unclutter \
    fonts-dejavu-core \
  || die "could not install the packages Ozzy TV needs. Fix the errors above and re-run."
# DVDs. libdvdnav/libdvdread are what VLC uses to read the disc structure and
# the menus. They do NOT decrypt: most commercial DVDs are CSS scrambled, and
# Debian ships the decryptor as a source package you build yourself
# (libdvd-pkg) for licensing reasons. Home-made and unencrypted discs play with
# what is here; for the rest, run:
#     sudo apt install libdvd-pkg && sudo dpkg-reconfigure libdvd-pkg
apt-get install -y --no-install-recommends libdvdnav4 libdvdread8 \
  || apt-get install -y --no-install-recommends libdvdnav4 libdvdread7 \
  || warn "the DVD libraries did not install; discs will not play."

apt-get install -y --no-install-recommends ffmpeg cec-utils \
  || warn "ffmpeg/cec-utils did not install. Ozzy TV works without them; you lose
         the 'may not play on this Pi' warning and the TV-remote option."

# ---- the app --------------------------------------------------------------
say "installing Ozzy TV to $APP_DIR"
mkdir -p "$APP_DIR" "$BIN"
rm -rf "$APP_DIR/ozzytv"
cp -r "$HERE/ozzytv" "$APP_DIR/ozzytv"
# Leave no stale .pyc behind from a previous version — a half-updated package
# is the one failure mode that looks like a code bug.
find "$APP_DIR" -name __pycache__ -type d -prune -exec rm -rf {} + 2>/dev/null || true
# Stamp WHAT was installed. Twice a fix has been reported as "still broken"
# because the installer was re-run against an older checkout — a second copy of
# the repo, or a re-downloaded archive that landed beside the first — and
# nothing on the Pi could tell the two apart. `ozzytv --doctor` reads this back.
_rev="$(cd "$HERE" && git rev-parse --short HEAD 2>/dev/null || echo 'no git checkout')"
_when="$(date -u '+%Y-%m-%d %H:%M UTC')"
printf '%s  installed %s  from %s\n' "$_rev" "$_when" "$HERE" > "$APP_DIR/BUILD"
install -m 0755 "$HERE/install/ozzytv-session" "$BIN/ozzytv-session"
# Bake the install location into the session script for the same reason.
sed -i "s#^OZZYTV_APP_DIR=.*#OZZYTV_APP_DIR=$APP_DIR#" "$BIN/ozzytv-session"
cat > "$BIN/ozzytv" <<SH
#!/bin/sh
# PYTHONPATH as well as the .pth. Either alone is enough; together, a .pth that
# lands somewhere this Python does not read is not a black screen.
PYTHONPATH="$APP_DIR\${PYTHONPATH:+:\$PYTHONPATH}" export PYTHONPATH
exec python3 -m ozzytv "\$@"
SH
chmod 0755 "$BIN/ozzytv"
# A .pth rather than pip or a virtualenv: the Pi's python3-vlc and python3-tk are
# system packages, so a venv would need --system-site-packages to see them at all
# and would buy nothing in return.
# Write it into EVERY site directory this Python reads, not just the first.
# getsitepackages()[0] is /usr/lib/python3/dist-packages on one image and
# /usr/local/lib/pythonX/dist-packages on another, and picking the wrong one
# leaves a .pth that nothing ever loads.
if [ -n "${OZZYTV_SITE:-}" ]; then
  SITES="$OZZYTV_SITE"
else
  SITES="$(python3 -c 'import site; print("\n".join(site.getsitepackages()))' 2>/dev/null)"
fi
[ -n "$SITES" ] || die "could not find Python's site-packages directory to register $APP_DIR in."
WROTE=0
for d in $SITES; do
  [ -d "$d" ] || continue
  echo "$APP_DIR" > "$d/ozzytv.pth" 2>/dev/null && WROTE=1
done
[ "$WROTE" = 1 ] || die "could not write ozzytv.pth into any of: $SITES"

# Prove it the way the app is actually STARTED — with no PYTHONPATH. Checking it
# with PYTHONPATH set (which is what this used to do) proves only that the files
# were copied; it says nothing about whether python3 can find them on its own,
# and that is exactly the failure that ends in a Pi booting to a black screen
# with a white X cursor and nothing in front of you to explain it.
env -u PYTHONPATH python3 -c 'import ozzytv' \
  || die "python3 cannot import ozzytv without PYTHONPATH, which is how it is
         started. The .pth in $SITES is not being read. Nothing would start."

# And now DRAW every screen, here, with no display. Importing proves the files
# arrived; it says nothing about whether the menus paint. The one bug that has
# cost two reboots was a TclError on the third-to-last line of TkView.__init__,
# which no import check could ever have seen and this catches in half a second.
say "checking that every screen draws"
env -u PYTHONPATH python3 -m ozzytv --selftest \
  || die "the installed code cannot draw its own screens — see above. This is
         what a black screen on the television looks like from here. Nothing
         has been enabled at boot; fix this first."

# ---- somewhere to put the films ------------------------------------------
if [ ! -d "$MEDIA_DEFAULT" ]; then
  say "creating $MEDIA_DEFAULT"
  mkdir -p "$MEDIA_DEFAULT"
  chown "$OWNER":"$OWNER" "$MEDIA_DEFAULT"
fi
HOME_DIR="$(getent passwd "$OWNER" | cut -d: -f6)"
CONF_DIR="$HOME_DIR/.local/share/ozzytv"
mkdir -p "$CONF_DIR"
chown -R "$OWNER":"$OWNER" "$CONF_DIR"
if [ ! -f "$CONF_DIR/settings.json" ]; then
  cat > "$CONF_DIR/settings.json" <<JSON
{
  "media_roots": ["$MEDIA_DEFAULT"],
  "vlc_args": [],
  "columns": 3,
  "rows": 2,
  "resume": true,
  "cec": false
}
JSON
  chown "$OWNER":"$OWNER" "$CONF_DIR/settings.json"
fi

# ---- and a way to get programmes onto it ----------------------------------
if [ "$SHARE" -eq 1 ]; then
  # Every destination share.sh writes to is forwarded, not just the media
  # folder. Without this the test harness — which overrides everything else —
  # would still write the REAL /etc/samba/smb.conf of whatever machine it ran
  # on, which is exactly the kind of thing an installer test exists to avoid.
  OZZYTV_MEDIA="$MEDIA_DEFAULT" \
  OZZYTV_SMB_CONF="${OZZYTV_SMB_CONF:-/etc/samba/smb.conf}" \
  OZZYTV_SHARE_NAME="${OZZYTV_SHARE_NAME:-ozzytv}" \
  OZZYTV_SHARE_PRIVATE="$SHARE_PRIVATE" \
    sh "$HERE/install/share.sh" \
    || warn "the network share did not set up. Ozzy TV works without it — you
         will be copying films over on a memory stick. Try it on its own with:
         sudo ./install/share.sh"
fi

# ---- make it the thing the Pi does ---------------------------------------
if [ "$KIOSK" -eq 1 ]; then
  say "starting Ozzy TV at boot, as $OWNER"

  # Raspberry Pi OS DESKTOP boots a display manager, which owns the screen and
  # the virtual terminal Ozzy TV wants. Left alone the two fight over tty1 and
  # the Pi comes up to a desktop, a black screen, or a flickering alternation of
  # the two. Switch it off — and write down what was switched off, so
  # --uninstall gives the desktop back rather than leaving someone with a Pi
  # that will not boot to anything they recognise.
  : > "$STATE"
  DM=""
  if [ -L /etc/systemd/system/display-manager.service ]; then
    DM="$(basename "$(readlink /etc/systemd/system/display-manager.service)")"
  fi
  if [ -n "$DM" ]; then
    warn "this looks like Raspberry Pi OS Desktop ($DM is running the screen)."
    say  "  Disabling it so Ozzy TV can have the display. 'install.sh --uninstall'"
    say  "  puts it back."
    printf 'display_manager=%s\n' "$DM" >> "$STATE"
    systemctl disable "$DM" 2>/dev/null || true
  fi
  OLD_TARGET="$(systemctl get-default 2>/dev/null || echo '')"
  if [ "$OLD_TARGET" = "graphical.target" ]; then
    printf 'default_target=%s\n' "$OLD_TARGET" >> "$STATE"
    systemctl set-default multi-user.target 2>/dev/null || true
    say "boot target set to multi-user (console); Ozzy TV takes the screen from there."
  fi
  mkdir -p "$UNIT_DIR"
  install -m 0644 "$HERE/install/ozzytv.service" "$UNIT_DIR/ozzytv@.service"
  systemctl daemon-reload
  # The console login on tty1 goes away: the whole point is that this machine has
  # one job. It comes back with --uninstall.
  systemctl disable getty@tty1.service 2>/dev/null || true
  systemctl enable "ozzytv@$OWNER.service"
  # Let this user start X. Debian ships needs_root_rights=auto, which refuses
  # from a systemd service.
  mkdir -p "$(dirname "$XWRAPPER")"
  if [ -f "$XWRAPPER" ]; then
    sed -i 's/^allowed_users=.*/allowed_users=anybody/' "$XWRAPPER"
    grep -q '^allowed_users=' "$XWRAPPER" || echo 'allowed_users=anybody' >> "$XWRAPPER"
    grep -q '^needs_root_rights' "$XWRAPPER" \
      || echo 'needs_root_rights=yes' >> "$XWRAPPER"
  else
    printf 'allowed_users=anybody\nneeds_root_rights=yes\n' > "$XWRAPPER"
  fi
  # The video group is what gets you the GPU; without it VLC decodes on the CPU.
  usermod -aG video,audio,render "$OWNER" 2>/dev/null || true
fi

# ---- did it actually work? -----------------------------------------------
# Check the things that decide whether the next boot lands on the menu, and say
# which one did not. "Installed successfully" followed by a black screen is the
# outcome this exists to prevent.
PROBLEMS=""
[ -x "$BIN/ozzytv" ] || PROBLEMS="$PROBLEMS\n  - $BIN/ozzytv was not created"
[ -d "$APP_DIR/ozzytv" ] || PROBLEMS="$PROBLEMS\n  - the app was not copied to $APP_DIR"
env -u PYTHONPATH python3 -c 'import ozzytv.app, ozzytv.skin' 2>/dev/null \
  || PROBLEMS="$PROBLEMS\n  - python3 cannot import ozzytv the way the service starts it"
env -u PYTHONPATH python3 -c 'import tkinter' 2>/dev/null \
  || PROBLEMS="$PROBLEMS\n  - python3-tk is missing; the menus cannot be drawn"
env -u PYTHONPATH python3 -c 'import vlc' 2>/dev/null \
  || PROBLEMS="$PROBLEMS\n  - python3-vlc is missing; nothing can be played"
if [ "$KIOSK" -eq 1 ]; then
  [ -f "$UNIT_DIR/ozzytv@.service" ] || PROBLEMS="$PROBLEMS\n  - the startup service was not installed"
  systemctl is-enabled "ozzytv@$OWNER.service" >/dev/null 2>&1 \
    || PROBLEMS="$PROBLEMS\n  - the startup service is not enabled; it will NOT start at boot"
fi
if [ -n "$PROBLEMS" ]; then
  printf '\n\033[1;31mInstalled, but the next boot will not reach the menu:\033[0m'
  printf "$PROBLEMS\n\n"
  exit 1
fi

say "done"
cat <<TXT

Ozzy TV is installed.   [$(cat "$APP_DIR/BUILD")]

  1. Put films and programmes in $MEDIA_DEFAULT
        (or edit media_roots in $CONF_DIR/settings.json)

  2. Set the parent PIN — do this before anyone else does:
        sudo -u $OWNER ozzytv --set-pin

  3. Choose what your child can watch. Either on the television (press P and
     enter the PIN), or from here:
        sudo -u $OWNER ozzytv --scan
        sudo -u $OWNER ozzytv --allow "$MEDIA_DEFAULT/Bluey"

     Nothing is visible until you allow it. That is deliberate.

TXT
if [ "$KIOSK" -eq 1 ]; then
  echo "  4. Reboot. The Pi will come up into Ozzy TV and nothing else."
  echo
  echo "     To get back to a console: Ctrl-Alt-F2, or ssh in."
else
  echo "  4. Start it with:  ozzytv"
fi
echo
