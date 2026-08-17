import unittest

from codex_token_widget import system_prefers_dark


class SystemThemeTests(unittest.TestCase):
    def test_explicit_color_scheme_wins_over_gtk_hints(self) -> None:
        self.assertFalse(system_prefers_dark("prefer-light", "Adwaita-dark", True))
        self.assertTrue(system_prefers_dark("prefer-dark", "Adwaita", False))

    def test_gtk_theme_is_used_when_color_scheme_is_default(self) -> None:
        self.assertTrue(system_prefers_dark("default", "Adwaita-dark"))
        self.assertFalse(system_prefers_dark("default", "Adwaita"))

    def test_gtk_preference_is_used_without_a_theme_hint(self) -> None:
        self.assertTrue(system_prefers_dark("default", "", True))
        self.assertFalse(system_prefers_dark("default", "", False))

if __name__ == "__main__":
    unittest.main()
