import sublime
import sublime_plugin
import sys
from os.path import dirname

# --- Module Reloading for Development ---
# This block ensures that when the plugin is reloaded (e.g., during development),
# any sub-modules within the 'plugin' directory are re-imported fresh.
# This prevents issues where old versions of modules might persist in sys.modules.
prefix = __package__ + '.plugin'
for module_name in [module_name for module_name in sys.modules if module_name.startswith(prefix)]:
    del sys.modules[module_name]
# --- End Module Reloading ---

# Add the 'plugin' directory to the Python path so its modules can be imported
# This is crucial for Sublime Text to find your refactored classes.
if dirname(__file__) not in sys.path:
    sys.path.append(dirname(__file__))

# Import all necessary classes from the new 'plugin' sub-package
# This makes them discoverable by Sublime Text's plugin loader.
from plugin.settings import plugin_settings, view_settings, get_setting, _update_logging_level, whole_file_as_context
from plugin.api_client import AsyncGemini
from plugin.commands import CompletionGeminiCommand, InstructGeminiCommand, ReplaceTextCommand, OpenNewTabWithContentCommand
from plugin.listeners import GeminiAiSettingsListener

# Ensure the logging level is set up when the plugin is loaded
# This is called once on plugin initialization.
def plugin_loaded():
    _update_logging_level()
    # Add a listener for settings changes to update logging dynamically.
    plugin_settings().add_on_change("gemini_ai_debug_logging", _update_logging_level)

# Clean up the settings listener when the plugin is unloaded.
def plugin_unloaded():
    plugin_settings().clear_on_change("gemini_ai_debug_logging")