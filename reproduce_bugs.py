#!/usr/bin/env python3
"""Minimal input sequences that reproduce the known bugs in hero_journey.py.

Runs against the sibling hero_journey.py (buggy or fixed) and reports, for each
of the 5 defects, whether the bug is PRESENT or FIXED. Exits 0 only when every
bug is fixed, so the same script proves the before/after state.

Bug list:
  1. Minion attribute combination is 7x duplicated positional construction
     (fragile: any reorder silently miscombines attributes; nothing pins it).
  2. Speed/crit chance are ignored for turn order: the hero always acts first.
  3. Store charges money but potions do not increase (inventory cap math).
  4. After game over the village loop still accepts further operations.
  5. Re-spawning a run (second village() call) keeps stale boss_defeat state.
"""
import builtins
import contextlib
import io
import os
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))


def load_game():
    """Import hero_journey without auto-starting the game loop."""
    with open(os.path.join(HERE, "hero_journey.py")) as handle:
        src = handle.read()
    if 'if __name__ == "__main__":' not in src:
        stripped = src.rstrip()
        assert stripped.endswith("village()"), "unexpected module footer"
        src = stripped[: -len("village()")]
    namespace = {"__name__": "hero_journey_under_test"}
    exec(compile(src, "hero_journey.py", "exec"), namespace)
    return namespace


def quiet(game, func, *args, **kwargs):
    with contextlib.redirect_stdout(io.StringIO()):
        return func(*args, **kwargs)


def feed(inputs):
    iterator = iter(inputs)

    def fake_input(prompt=""):
        return next(iterator)

    return fake_input


results = {}


def report(bug, present, detail):
    results[bug] = not present
    status = "BUG PRESENT" if present else "fixed"
    print(f"[bug {bug}] {status}: {detail}")


def check_bug1(game):
    """Each hero attribute must land in the matching minion attribute."""
    import random as random_module

    def fake_randint(a, b):
        # Drive spawnminion deterministically: name index 0, scale 75%.
        return {(0, 6): 0, (75, 80): 75}[(a, b)]

    game["randint"] = fake_randint
    try:
        minion = quiet(game, game["spawnminion"], 20, 40, 60, 80, 100, 1)
    finally:
        game["randint"] = random_module.randint
    mapping_ok = (
        minion.attack == 15 and minion.defense == 30 and minion.speed == 45
        and minion.critchance == 60 and minion.health == 75
        and minion.maxhealth == 75 and minion.name == game["minion_list"][0]
    )
    # The bug is structural: 7 hand-written positional Minion(...) calls with no
    # single construction point. Detect the fix (dedicated keyword constructor).
    hardened = callable(game.get("create_scaled_minion"))
    report(
        1,
        not (mapping_ok and hardened),
        "attribute mapping pinned by single keyword constructor"
        if (mapping_ok and hardened) else
        "minion stats assembled by 7 duplicated positional Minion(...) calls; "
        "nothing guarantees attack/defense/speed/crit/health stay in their fields",
    )


def check_bug2(game):
    """A faster minion must act before a slower hero."""
    hero = game["Hero"]("Order", 5, 5, 0, 0, 0)  # speed 0
    hero.health = hero.maxhealth = 50
    minion = game["Minion"]("Fast", 1, 1, 10, 0, 10)  # speed 10
    events = []

    def hero_attack(self, enemy):
        events.append("hero")
        enemy.health = 0
        return False  # hero's attack finishes the minion

    def minion_attack(self, target):
        events.append("minion")
        return True  # hero survives; only record who acts first

    saved = (game["Hero"].attack_enemy, game["Minion"].attack_hero,
             game["spawnminion"])
    game["Hero"].attack_enemy = hero_attack
    game["Minion"].attack_hero = minion_attack
    game["spawnminion"] = lambda *a: minion  # train() spawns its own minion
    game["clear"] = lambda: None
    old_input = builtins.input
    builtins.input = feed(["1", "2", ""])  # attack, then leave training
    try:
        quiet(game, game["Hero"].train, hero)
    finally:
        (game["Hero"].attack_enemy, game["Minion"].attack_hero,
         game["spawnminion"]) = saved
        builtins.input = old_input
    hero_first = events[:1] == ["hero"] and events == ["hero"]
    report(
        2,
        hero_first,
        f"action order with hero speed 0 vs minion speed 10: {events} "
        + ("(speed ignored, hero always first)" if hero_first else "(faster minion acts first)"),
    )


def check_bug3(game):
    """Buying past the potion cap must cap at 10 and charge only for those."""
    hero = game["Hero"]("Shop", 0, 0, 0, 0, 0)
    hero.money = 50
    hero.potions = 8
    old_input = builtins.input
    builtins.input = feed(["5", ""])  # buy 5 with 8 in inventory
    game["clear"] = lambda: None
    try:
        quiet(game, game["store"], hero)
    finally:
        builtins.input = old_input
    bug = not (hero.potions == 10 and hero.money == 40)
    report(
        3,
        bug,
        f"8 potions + buy 5 -> potions={hero.potions}, money={hero.money} "
        f"(expected potions=10, money=40)",
    )


def check_bug4(game):
    """Game over must produce a terminal signal the village loop obeys."""
    hero = game["Hero"]("End", 1, 1, 1, 1, 0)
    game["sleep"] = lambda *a: None
    game["system"] = lambda *a: 0
    game["clear"] = lambda: None
    game["welcome_message"] = lambda: None
    game["create_player"] = lambda: hero
    old_input = builtins.input

    # Part 1: game_over() must report the terminal state (not rely on exit()).
    game["boss_defeat"][4] = True
    builtins.input = feed(["", "", ""])
    cwd = os.getcwd()
    try:
        with tempfile.TemporaryDirectory() as tmp:
            os.chdir(tmp)
            try:
                terminal = quiet(game, game["game_over"], hero)
            finally:
                os.chdir(cwd)
    finally:
        builtins.input = old_input
    game["boss_defeat"][4] = False
    not_terminal = quiet(game, game["game_over"], hero)

    # Part 2: with the terminal signal set, village() must stop asking for input.
    consumed = []

    def counting_input(prompt=""):
        consumed.append(prompt)
        if len(consumed) > 6:
            raise StopIteration
        return ""

    def terminal_game_over(h):
        return True

    saved_game_over = game["game_over"]
    game["game_over"] = terminal_game_over
    builtins.input = counting_input
    try:
        try:
            quiet(game, game["village"])
        except StopIteration:
            pass
    finally:
        game["game_over"] = saved_game_over
        builtins.input = old_input
    menu_prompts = sum("Where do you want to go" in p for p in consumed)

    bug = (not terminal) or (not_terminal is not False) or menu_prompts > 0
    details = []
    details.append("game_over() returns a terminal value" if terminal
                   else "game_over() returns None; termination relies on the "
                        "interactive-only exit() helper (absent under python -S "
                        "or in frozen builds), so the village loop keeps "
                        "accepting operations after the ending")
    if terminal:
        details.append("village stops without prompting the menu again"
                       if menu_prompts == 0 else
                       f"village still prompted the menu {menu_prompts} time(s)")
    report(4, bug, "; ".join(details))


def check_bug5(game):
    """Restarting a run must not inherit the previous run's boss progress."""
    hero = game["Hero"]("Again", 1, 1, 1, 1, 0)
    for key in game["boss_defeat"]:
        game["boss_defeat"][key] = False
    game["boss_defeat"][1] = True  # previous run defeated the first general
    game["welcome_message"] = lambda: None
    game["create_player"] = lambda: hero
    game["clear"] = lambda: None
    game["sleep"] = lambda *a: None
    old_input, old_exit = builtins.input, builtins.exit
    builtins.input = feed(["", "5"])  # skip intro, leave via menu
    builtins.exit = lambda *a: (_ for _ in ()).throw(SystemExit)
    try:
        try:
            quiet(game, game["village"])
        except SystemExit:
            pass
    finally:
        builtins.input, builtins.exit = old_input, old_exit
    residue = any(game["boss_defeat"].values())
    report(
        5,
        residue,
        f"boss_defeat after restarting a run: {game['boss_defeat']}"
        + (" (stale progress leaks into the new run)" if residue else " (clean slate)"),
    )
    for key in game["boss_defeat"]:
        game["boss_defeat"][key] = False


def main():
    game = load_game()
    game["clear"] = lambda: None
    check_bug1(game)
    check_bug2(game)
    check_bug3(game)
    check_bug4(game)
    check_bug5(game)
    print()
    if all(results.values()):
        print("All 5 bugs are fixed.")
        return 0
    print(f"{sum(1 for ok in results.values() if not ok)} bug(s) still present.")
    return 1


if __name__ == "__main__":
    sys.exit(main())
