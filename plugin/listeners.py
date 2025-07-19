import logging
from typing import List

import sublime
import sublime_plugin

# Import _update_logging_level from the new settings module
from .settings import _update_logging_level

logger = logging.getLogger("GeminiAIPlugin")
logging.basicConfig(level=logging.DEBUG)


class GeminiAiSettingsListener(sublime_plugin.EventListener):
    """
    Listens for changes in the plugin settings to update the logger level.
    """

    def on_init(self, views: List[sublime.View]) -> None:
        # Called once when the plugin is loaded.
        _update_logging_level()
        # Add a listener for settings changes to update logging dynamically.
        sublime.load_settings("gemini-ai.sublime-settings").add_on_change(
            "gemini_ai_debug_logging", _update_logging_level
        )

    def on_exit(self) -> None:
        # Remove the settings listener when the plugin is unloaded.
        sublime.load_settings("gemini-ai.sublime-settings").clear_on_change("gemini_ai_debug_logging")
