import logging
import os
from typing import Any, Dict, Union

import sublime

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
        logging.basicConfig(level=logging.DEBUG)
        logger.setLevel(logging.DEBUG)
        logger.debug("Gemini AI Plugin logging enabled.")
    else:
        logging.basicConfig(level=logging.CRITICAL)
        logger.setLevel(logging.CRITICAL)  # Effectively disable logging


"""
$SELECTION  The text that was selected when the snippet was triggered.
$TM_CURRENT_LINE    Content of the cursor's line when the snippet was triggered.
$TM_CURRENT_WORD    Word under the cursor when the snippet was triggered.
$TM_DIRECTORY   Directory name of the file being edited. (since 3154)
$TM_FILENAME    Name of the file being edited, including extension.
$TM_FILEPATH    Path to the file being edited.
$TM_FULLNAME    User's user name.
$TM_LINE_INDEX  Column where the snippet is being inserted, 0 based.
$TM_LINE_NUMBER Row where the snippet is being inserted, 1 based.
$TM_SELECTED_TEXT   An alias for $SELECTION.
$TM_SCOPE   The scope of the beginning of each selected region. (since 3154)
$TM_SOFT_TABS   YES if translate_tabs_to_spaces is true, otherwise NO.
$TM_TAB_SIZE    Spaces per-tab (controlled by the tab_size option).
"""


def evaluate_completion_snippet(view: sublime.View, selected_code: str) -> str:
    window: Union[sublime.Window, None] = view.window()
    if not window:
        raise ValueError("No window found for evaluating prompt snippet.")

    shell_path = os.environ.get("COMSPEC", os.environ.get("SHELL", "Unknown"))

    variables = window.extract_variables()

    syntax_path: str = view.settings().get("syntax")
    syntax_name: str = syntax_path.split("/").pop().split(".")[0] if syntax_path else "plain text"

    completions_settings = get_setting(view, "completions")

    custom_variables = {
        "name": completions_settings.get(
            "prompt_snippet", "Packages/GeminiAI/snippets/completion_prompt.sublime-snippet"
        ),
        "OS": variables.get("platform"),
        "SHELL": os.path.basename(shell_path),
        "SYNTAX": syntax_name.lower(),
        "SOURCE_CODE": selected_code,
        "PROJECT_PATH": variables.get("project_path", "Not in a project context"),
        "FILE_NAME": variables.get("file", view.file_name()),
        # todo: add "always include" files
    }

    logger.debug("Custom instruct prompt vars: {}".format(custom_variables))

    # Create a new scratch view to insert the snippet into
    # This view will not be shown to the user.
    temp_view = window.new_file(flags=sublime.TRANSIENT)
    temp_view.set_scratch(True)

    # To ensure the snippet evaluates correctly with environment variables like $TM_FILENAME,
    # we need to set them in the temporary view's settings or pass them to insert_snippet.
    # For simplicity, we'll just insert it.
    # Note: Direct evaluation of all snippet features (like $TM_FILENAME) requires
    # the context of an actual view, so we use a temporary one.

    # The 'insert_snippet' command requires an 'edit' object. Since we are not within
    # a direct TextCommand's run method for the temp_view, we'll create a dummy edit.
    # In Sublime Text 3.x and 4.x, edit objects are managed by the API.
    # The 'insert_snippet' command handles this internally when called via run_command.

    # Insert the snippet into the temporary view
    temp_view.run_command(
        "insert_snippet",
        custom_variables,
    )

    # Get the content of the temporary view
    evaluated_content = temp_view.substr(sublime.Region(0, temp_view.size()))

    # Close the temporary view
    temp_view.close()

    return evaluated_content


def evaluate_instruction_snippet(view: sublime.View, user_instruction: str, selected_code: str) -> str:
    window: Union[sublime.Window, None] = view.window()
    if not window:
        raise ValueError("No window found for evaluating prompt snippet.")

    shell_path = os.environ.get("COMSPEC", os.environ.get("SHELL", "Unknown"))

    variables = window.extract_variables()

    syntax_path: str = view.settings().get("syntax")
    syntax_name: str = syntax_path.split("/").pop().split(".")[0] if syntax_path else "plain text"

    instruct_settings = get_setting(view, "instruct")

    custom_variables = {
        "name": instruct_settings.get("prompt_snippet", "Packages/GeminiAI/snippets/instruct_prompt.sublime-snippet"),
        "OS": variables.get("platform"),
        "SHELL": os.path.basename(shell_path),
        "SYNTAX": syntax_name.lower(),
        "INSTRUCTIONS": user_instruction,
        "SOURCE_CODE": selected_code,
        "PROJECT_PATH": variables.get("project_path", "Not in a project context"),
        "FILE_NAME": variables.get("file", view.file_name()),
    }

    logger.debug("Custom instruct prompt vars: {}".format(custom_variables))

    # Create a new scratch view to insert the snippet into
    # This view will not be shown to the user.
    temp_view = window.new_file(flags=sublime.TRANSIENT)
    temp_view.set_scratch(True)

    # To ensure the snippet evaluates correctly with environment variables like $TM_FILENAME,
    # we need to set them in the temporary view's settings or pass them to insert_snippet.
    # For simplicity, we'll just insert it.
    # Note: Direct evaluation of all snippet features (like $TM_FILENAME) requires
    # the context of an actual view, so we use a temporary one.

    # The 'insert_snippet' command requires an 'edit' object. Since we are not within
    # a direct TextCommand's run method for the temp_view, we'll create a dummy edit.
    # In Sublime Text 3.x and 4.x, edit objects are managed by the API.
    # The 'insert_snippet' command handles this internally when called via run_command.

    # Insert the snippet into the temporary view
    temp_view.run_command(
        "insert_snippet",
        custom_variables,
    )

    # Get the content of the temporary view
    evaluated_content = temp_view.substr(sublime.Region(0, temp_view.size()))

    # Close the temporary view
    temp_view.close()

    return evaluated_content
