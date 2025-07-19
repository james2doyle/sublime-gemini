import sys

# clear modules cache if package is reloaded (after update?)
prefix = __package__ + ".plugin"  # type: ignore # don't clear the base package
for module_name in [module_name for module_name in sys.modules if module_name.startswith(prefix)]:
    del sys.modules[module_name]
del prefix

from .plugin.api_client import AsyncGemini  # noqa: E402, F401
from .plugin.commands import (  # noqa: E402, F401
    CompletionGeminiCommand,
    InstructGeminiCommand,
    OpenNewTabWithContentCommand,
    ReplaceTextCommand,
)
from .plugin.listeners import GeminiAiSettingsListener  # noqa: E402, F401
from .plugin.settings import (  # noqa: E402, F401
    _update_logging_level,
    get_setting,
    plugin_settings,
    view_settings,
    whole_file_as_context,
)


# Ensure the logging level is set up when the plugin is loaded
# This is called once on plugin initialization.
def plugin_loaded():
    _update_logging_level()
    # Add a listener for settings changes to update logging dynamically.
    plugin_settings().add_on_change("gemini_ai_debug_logging", _update_logging_level)


# Clean up the settings listener when the plugin is unloaded.
def plugin_unloaded():
    plugin_settings().clear_on_change("gemini_ai_debug_logging")
