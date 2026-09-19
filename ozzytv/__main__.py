"""Starting Ozzy TV.

    ozzytv                      the television
    ozzytv --windowed           same, in a window, for setting up over VNC/SSH -X
    ozzytv --fake-player        no VLC at all: navigate the menus on a laptop
    ozzytv --scan               print what the library looks like, and stop
    ozzytv --doctor             why it is not on the screen, and what to type
    ozzytv --selftest           draw every screen headless; what a Pi cannot show
"""
from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

from . import library, probe
from .app import OzzyApp
from .config import load_settings, save_settings, settings_path
from .playback import FakePlayer, VlcPlayer, VlcUnavailable
from .security import PinGate, WeakPin, check_pin_strength
from .store import Store


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="ozzytv", description="Ozzy TV")
    ap.add_argument("--windowed", action="store_true",
                    help="run in a window instead of filling the screen")
    ap.add_argument("--fake-player", action="store_true",
                    help="do not use VLC — for trying the menus without media")
    ap.add_argument("--scan", action="store_true",
                    help="print the library as the app sees it, then exit")
    ap.add_argument("--check", action="store_true",
                    help="with --scan, also say what this hardware can play")
    ap.add_argument("--show-everything", action="store_true",
                    help="clear every hide/show mark: back to what is on the drive")
    ap.add_argument("--doctor", action="store_true",
                    help="say why it is not on the screen, and what to type")
    ap.add_argument("--selftest", action="store_true",
                    help="draw every screen with no display, and report what broke")
    # Choosing from a terminal as well as from the television: a Pi is usually
    # set up over SSH before it is ever plugged into a TV, and a parent with a
    # keyboard should not have to wait for the sofa to curate a library.
    ap.add_argument("--allow", action="append", metavar="PATH", default=[],
                    help="let the child see this file or folder (repeatable)")
    ap.add_argument("--block", action="append", metavar="PATH", default=[],
                    help="hide this file or folder, even inside an allowed one")
    ap.add_argument("--forget", action="append", metavar="PATH", default=[],
                    help="remove a choice, so it inherits from its folder again")
    ap.add_argument("--media", action="append", metavar="DIR",
                    help="use this folder as the library (repeatable, overrides settings)")
    ap.add_argument("-v", "--verbose", action="store_true")
    args = ap.parse_args(argv)

    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.INFO,
                        format="%(levelname)s %(name)s: %(message)s")

    # Before anything reads or writes settings. The installer runs this under
    # sudo, and a self-test that leaves a settings file and a database in /root
    # is a self-test that changed the machine it was checking.
    if args.selftest:
        from . import selftest
        return selftest.report(selftest.run())

    settings = load_settings()
    if args.media:
        settings.media_roots = [str(Path(m).expanduser()) for m in args.media]
    if not settings_path().exists():
        save_settings(settings)         # so there is a file to edit next time
        print(f"Wrote starting settings to {settings_path()}", file=sys.stderr)

    store = Store()
    try:
        if args.doctor:
            from . import doctor
            return doctor.report(doctor.run(settings, store))
        if args.show_everything:
            return _show_everything(settings, store)
        if args.allow or args.block or args.forget:
            rc = _mark(settings, store, args)
            if rc or not args.scan:
                return rc
        if args.scan:
            return _scan(settings, store, check=args.check)
        return _run(settings, store, args)
    finally:
        store.close()


def _show_everything(settings, store) -> int:
    """Forget every mark.

    Ozzy TV used to hide everything until a grown-up allowed it, one thing at a
    time, so a library set up under that rule is carrying marks that now do the
    opposite of what anybody wants. This is the one command that undoes the lot.
    """
    n = 0
    for root in settings.roots:
        n += len(store.rules_for(root).marks)
        store.clear_marks(root)
    print(f"Cleared {n} hide/show mark(s).")
    print("Everything on the drive is visible. Hide something with:")
    print('    ozzytv --block "/media/ozzy/<what>"')
    return 0


def _set_pin(store: Store) -> int:
    import getpass
    gate = PinGate(store)
    first = getpass.getpass("New parent PIN: ")
    try:
        check_pin_strength(first)
    except WeakPin as e:
        print(e, file=sys.stderr)
        return 2
    if first != getpass.getpass("Again: "):
        print("Those did not match.", file=sys.stderr)
        return 2
    gate.set_pin(first)
    print("PIN saved.")
    return 0


def _mark(settings, store, args) -> int:
    """Apply --allow / --block / --forget.

    A path is refused unless it is inside one of the media roots — the same
    confinement the child's side applies. Without it a typo could write a rule
    keyed on a path no root will ever produce, which then silently does nothing.
    """
    from .picks import Mark, relkey
    roots = settings.roots
    for paths, mark in ((args.allow, Mark.ALLOW), (args.block, Mark.BLOCK),
                        (args.forget, None)):
        for raw in paths:
            target = Path(raw).expanduser()
            for root in roots:
                rel = relkey(root, target)
                if rel is not None:
                    store.set_mark(root, rel, mark)
                    verb = {Mark.ALLOW: "allowed", Mark.BLOCK: "blocked"}.get(mark, "forgotten")
                    print(f"{verb}: {rel}   (in {root})")
                    break
            else:
                print(f"'{raw}' is not inside any media folder. Roots are:",
                      file=sys.stderr)
                for root in roots:
                    print(f"  {root}", file=sys.stderr)
                return 2
    return 0


def _scan(settings, store, check: bool) -> int:
    roots = library.scan(settings.roots)
    if not roots:
        print("No media folders found. Looked in:", file=sys.stderr)
        for r in settings.roots:
            print(f"  {r}", file=sys.stderr)
        return 1
    for root in roots:
        rules = store.rules_for(root.root)
        print(f"\n{root.root}")
        for node in library.prune_empty_folders(root).walk():
            if node is root:
                continue
            from . import picks
            mark = rules.marks.get(node.rel)
            seen = picks.decide_rel(rules, node.rel).visible
            flag = {"allow": "A", "block": "B"}.get(mark.value if mark else "", " ")
            note = ""
            if check and node.is_playable:
                p = probe.probe(node.path, store)
                note = f"   [{p.verdict}: {p.detail}]" if p.verdict != "unknown" else ""
            depth = node.rel.count("/")
            print(f"  {flag} {'  ' * depth}{'[+] ' if not node.is_playable else ''}"
                  f"{node.title}{'' if seen else '   (hidden)'}{note}")
    print("\n  A = allowed   B = blocked   (blank = inherits from its folder)")
    return 0


def _run(settings, store, args) -> int:
    if args.fake_player:
        player = FakePlayer()
    else:
        try:
            player = VlcPlayer(settings.vlc_args)
        except VlcUnavailable as e:
            print(e, file=sys.stderr)
            return 3
    app = OzzyApp(settings, store, player)

    try:
        from .tkview import TkView
    except ImportError as e:
        print("Tk is not available — on Raspberry Pi OS:\n"
              "    sudo apt install python3-tk\n"
              f"(the import said: {e})", file=sys.stderr)
        return 4

    view = TkView(app, fullscreen=not args.windowed)

    remote = None
    if settings.cec:
        from .cec import CecRemote
        remote = CecRemote()
        if remote.start():
            def pump():
                if remote.drain(app):
                    view.render()
                view.root.after(100, pump)
            view.root.after(100, pump)

    try:
        view.run()
    finally:
        if remote:
            remote.stop()
        player.release()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
