import contextlib
import io
import os
import tempfile
import unittest
from unittest.mock import patch

import hero_journey as game


class HeroJourneyTestCase(unittest.TestCase):
    def setUp(self):
        self.original_boss_defeat = game.boss_defeat.copy()
        self.addCleanup(self.restore_boss_defeat)

    def restore_boss_defeat(self):
        game.boss_defeat.clear()
        game.boss_defeat.update(self.original_boss_defeat)

    def make_hero(self, **overrides):
        hero = game.Hero("Test Hero", 5, 5, 5, 5, 0)
        for name, value in overrides.items():
            setattr(hero, name, value)
        return hero

    def run_quietly(self, function, *args, **kwargs):
        with contextlib.redirect_stdout(io.StringIO()):
            return function(*args, **kwargs)


class MinionSpawnTests(HeroJourneyTestCase):
    def test_spawn_maps_each_hero_attribute_to_the_matching_minion_attribute(self):
        with patch.object(game, "randint", side_effect=[0, 75]):
            minion = self.run_quietly(
                game.spawnminion, 20, 40, 60, 80, 100, 1
            )

        self.assertEqual(minion.name, game.minion_list[0])
        self.assertEqual(minion.attack, 15)
        self.assertEqual(minion.defense, 30)
        self.assertEqual(minion.speed, 45)
        self.assertEqual(minion.critchance, 60)
        self.assertEqual(minion.health, 75)
        self.assertEqual(minion.maxhealth, 75)

    def test_repeated_spawns_do_not_share_health_or_identity(self):
        with patch.object(game, "randint", side_effect=[0, 75, 1, 80]):
            first = self.run_quietly(game.spawnminion, 20, 40, 60, 80, 100, 1)
            second = self.run_quietly(game.spawnminion, 20, 40, 60, 80, 100, 1)

        self.assertIsNot(first, second)
        self.assertEqual(first.health, 75)
        self.assertEqual(second.health, 80)

        still_fighting = self.run_quietly(first.lose_health, first.health)

        self.assertFalse(still_fighting)
        self.assertEqual(first.health, 0)
        self.assertEqual(second.health, 80)
        self.assertEqual(second.maxhealth, 80)


class CombatStateTests(HeroJourneyTestCase):
    def test_speed_determines_who_acts_first(self):
        hero = self.make_hero(speed=1)
        minion = game.Minion("Fast Minion", 1, 1, 10, 0, 10)
        events = []

        def hero_attack(enemy):
            events.append("hero")
            return True

        def minion_attack(target):
            events.append("minion")
            return True

        with patch.object(game.Hero, "attack_enemy", side_effect=hero_attack), \
                patch.object(game.Minion, "attack_hero", side_effect=minion_attack), \
                patch.object(game, "clear"), \
                patch("builtins.input", return_value="1"):
            self.run_quietly(game.resolve_combat_round, hero, minion)

        self.assertEqual(events, ["minion", "hero"])

    def test_crit_chance_breaks_speed_ties_in_turn_order(self):
        hero = self.make_hero(speed=5, critchance=1)
        minion = game.Minion("Critical Minion", 1, 1, 5, 10, 10)
        events = []

        def hero_attack(enemy):
            events.append("hero")
            return True

        def minion_attack(target):
            events.append("minion")
            return True

        with patch.object(game.Hero, "attack_enemy", side_effect=hero_attack), \
                patch.object(game.Minion, "attack_hero", side_effect=minion_attack), \
                patch.object(game, "clear"), \
                patch("builtins.input", return_value="1"):
            self.run_quietly(game.resolve_combat_round, hero, minion)

        self.assertEqual(events, ["minion", "hero"])

    def test_critical_strike_still_doubles_damage_inside_the_round(self):
        hero = self.make_hero(attack=5, critchance=10)
        hero.maxhealth = 20
        hero.health = 20
        minion = game.Minion("Target", 0, 0, 0, 0, 10)

        with patch.object(game, "random", side_effect=[0.99, 0.0]):
            still_fighting = self.run_quietly(hero.attack_enemy, minion)

        self.assertFalse(still_fighting)
        self.assertEqual(minion.health, 0)

    def test_hero_death_settles_once_and_a_new_hero_starts_clean(self):
        hero = self.make_hero()
        hero.health = 5
        hero.money = 100
        hero.potions = 3
        hero.exp = 9
        hero.monsterskilled = 7

        with patch("builtins.input", return_value=""), \
                patch.object(game, "clear"):
            still_fighting = self.run_quietly(hero.lose_health, 10)

        self.assertFalse(still_fighting)
        self.assertEqual(hero.health, 0)
        self.assertEqual(hero.potions, 0)
        self.assertEqual(hero.money, 75)

        new_hero = self.make_hero()
        self.assertEqual(new_hero.health, 10)
        self.assertEqual(new_hero.maxhealth, 10)
        self.assertEqual(new_hero.money, 0)
        self.assertEqual(new_hero.potions, 0)
        self.assertEqual(new_hero.exp, 0)
        self.assertEqual(new_hero.monsterskilled, 0)

    def test_training_victory_moves_rewards_to_hero_and_leaves_minion_defeated(self):
        hero = self.make_hero()
        minion = game.Minion("Slime", 0, 0, 1, 0, 1)

        def resolve_combat(actual_hero, actual_minion):
            actual_minion.health = 0
            return False

        with patch.object(game, "spawnminion", return_value=minion), \
                patch.object(game, "resolve_combat_round", side_effect=resolve_combat), \
                patch.object(game, "randint", return_value=3), \
                patch.object(game, "random", return_value=0.99), \
                patch.object(game, "clear"), \
                patch("builtins.input", side_effect=["2", ""]):
            self.run_quietly(hero.train)

        self.assertEqual(hero.monsterskilled, 1)
        self.assertEqual(hero.exp, 5)
        self.assertEqual(hero.money, 3)
        self.assertEqual(hero.potions, 0)

    def test_boss_victory_moves_rewards_and_records_only_that_boss(self):
        hero = self.make_hero()
        hero.lvl = 10
        minion = game.Minion("Abadon", 0, 0, 1, 0, 1)

        def resolve_combat(actual_hero, actual_minion):
            actual_minion.health = 0
            return False

        with patch.object(game, "spawnminion", return_value=minion), \
                patch.object(game, "resolve_combat_round", side_effect=resolve_combat), \
                patch.object(game, "clear"), \
                patch("builtins.input", return_value=""):
            self.run_quietly(game.boss, hero)

        self.assertEqual(game.boss_defeat, {1: True, 2: False, 3: False, 4: False})
        self.assertEqual(hero.money, 10)
        self.assertEqual(hero.potions, 3)
        self.assertEqual(hero.exp, 1)
        self.assertEqual(hero.lvl, 11)


class StoreTests(HeroJourneyTestCase):
    def test_store_caps_purchase_at_inventory_space_without_overcharging(self):
        hero = self.make_hero()
        hero.potions = 8
        hero.money = 50

        with patch("builtins.input", side_effect=["5", ""]), \
                patch.object(game, "clear"):
            self.run_quietly(game.store, hero)

        self.assertEqual(hero.potions, 10)
        self.assertEqual(hero.money, 40)

    def test_store_rejects_negative_purchase_without_changing_inventory(self):
        hero = self.make_hero()
        hero.potions = 4
        hero.money = 20

        with patch("builtins.input", side_effect=["-1", "", "0", ""]), \
                patch.object(game, "clear"):
            self.run_quietly(game.store, hero)

        self.assertEqual(hero.potions, 4)
        self.assertEqual(hero.money, 20)


class GameOverTests(HeroJourneyTestCase):
    def test_game_over_returns_a_terminal_state(self):
        hero = self.make_hero()
        game.boss_defeat[4] = True

        with tempfile.TemporaryDirectory() as directory:
            current_directory = os.getcwd()
            os.chdir(directory)
            self.addCleanup(os.chdir, current_directory)
            with patch("builtins.input", side_effect=["", "", ""]), \
                    patch.object(game, "clear"), \
                    patch.object(game, "sleep"), \
                    patch.object(game, "system"):
                finished = self.run_quietly(game.game_over, hero)
            self.assertTrue(os.path.exists(os.path.join(directory, "winner.txt")))

        self.assertTrue(finished)

    def test_village_returns_after_game_over_instead_of_accepting_more_input(self):
        hero = self.make_hero()
        inputs = iter([""])

        def fake_input(prompt=""):
            try:
                return next(inputs)
            except StopIteration as error:
                raise AssertionError("village accepted input after game over") from error

        with patch.object(game, "welcome_message"), \
                patch.object(game, "create_player", return_value=hero), \
                patch.object(game, "game_over", return_value=True), \
                patch.object(game, "clear"), \
                patch("builtins.input", side_effect=fake_input):
            self.run_quietly(game.village)

    def test_restart_resets_boss_progress(self):
        hero = self.make_hero()
        game.boss_defeat[1] = True

        with patch.object(game, "welcome_message"), \
                patch.object(game, "create_player", return_value=hero), \
                patch.object(game, "clear"), \
                patch.object(game, "exit", side_effect=SystemExit), \
                patch("builtins.input", side_effect=["", "5"]):
            with self.assertRaises(SystemExit):
                self.run_quietly(game.village)

        self.assertEqual(game.boss_defeat, {1: False, 2: False, 3: False, 4: False})


if __name__ == "__main__":
    unittest.main()
