import unittest

from codex_token_widget import context_menu_css, system_prefers_dark


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

    def test_context_menu_css_matches_the_selected_appearance(self) -> None:
        dark_css = context_menu_css(True)
        light_css = context_menu_css(False)
        self.assertIn("background-color: #242424", dark_css)
        self.assertIn("color: #F7F9FC", dark_css)
        self.assertIn("background-color: #ECEEEC", light_css)
        self.assertIn("color: #202124", light_css)


if __name__ == "__main__":
    unittest.main()
