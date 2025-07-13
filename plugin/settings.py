import sublime
import logging
from typing import Any, Dict, Union

SETTINGS_FILE = "gemini-ai.sublime-settings"
logger = logging.getLogger("GeminiAIPlugin")

def plugin_settings() -> sublime.Settings:
    """Loads and returns the plugin's settings."""
    return sublime.load_settings(SETTINGS_FILE)

def view_settings(view: sublime.View) -> Dict[str, Any]:
    """Returns a dictionary representation of the GeminiAI settings specific to the view."""
    return view.settings().get("GeminiAI", {})

def get_setting(view: sublime.View, key: str, default: Any = None) -> Any:
    """
    Retrieves a setting, prioritizing view-specific settings over global plugin settings.
    """
    try:
        view_specific_setting: Union[Any, None] = view_settings(view).get(key)
        if view_specific_setting is not None:
            return view_specific_setting

        return plugin_settings().get(key, default)
    except KeyError:
        # Fallback in case of unexpected KeyError, though .get() should prevent this.
        return plugin_settings().get(key, default)

def whole_file_as_context(view: sublime.View) -> str:
    """Reads the entire content of the view and returns it as a string."""
    file_size: int = view.size()
    full_region: sublime.Region = sublime.Region(0, file_size)
    return view.substr(full_region)

def _update_logging_level() -> None:
    """
    Updates the logger's level based on the 'debug_logging' setting.
    """
    settings = plugin_settings()
    debug_logging: bool = settings.get("debug_logging", False)

    if debug_logging:
        logger.setLevel(logging.DEBUG)
        logger.debug("Gemini AI Plugin logging enabled.")
    else:
        logger.setLevel(logging.CRITICAL) # Effectively disable logging
