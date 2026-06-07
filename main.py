"""Entry point.

    python main.py            launch the desktop window
    python main.py --console  quick text demo (no window needed)
"""
from __future__ import annotations
import sys


def run_console_demo():
    from engine import DraftAssistant, load_sample_data
    a = DraftAssistant()
    player, map_name = load_sample_data(a)
    prof = a.player_profile("EnemyOTP#5555")
    print(f"{prof.battletag}: {prof.letter}  OTP={prof.is_otp}  hero={prof.otp_hero}")
    recs = a.recommendations(player, map_name)
    print("\nBans:")
    for b in recs["bans"]:
        print(f"  {b.hero} — {b.reason}")
    print("\nPicks:")
    for p in recs["picks"]:
        print(f"  {p.hero}: {p.score:.3f} ({p.reason})")
    a.close()


def run_window():
    try:
        from app import run
        run()
    except ImportError:
        print("PyQt5 not found. Install with:\n    pip install PyQt5")
        sys.exit(1)


if __name__ == "__main__":
    if "--console" in sys.argv:
        run_console_demo()
    else:
        run_window()
