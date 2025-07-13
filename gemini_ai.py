import http.client
import json
import logging
import threading

from typing import Any, Dict, Union

import sublime
import sublime_plugin

# --- Configuration ---
SETTINGS_FILE = "gemini-ai.sublime-settings"

# Configure logging to be toggled by settings later
# For now, keep it as DEBUG for development
logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger("GeminiAIPlugin")


# --- Helper Functions ---
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


class AsyncGemini(threading.Thread):
    """
    A simple async thread class for accessing the Gemini API and waiting for a response.
    """

    def __init__(self, view: sublime.View, region: sublime.Region, data: Dict[str, Any], preText: str):
        """
        Initializes the AsyncGemini thread.

        Args:
            view: The Sublime Text view associated with the command.
            region: The sublime.Region object representing the highlighted text.
            data: The payload data for the API request.
            preText: Text to prepend to the result (e.g., original prompt text).
        """
        super().__init__()
        self.view: sublime.View = view
        self.region: sublime.Region = region
        self.data: Dict[str, Any] = data
        self.preText: str = preText
        self.running: bool = False
        self.result: Union[str, None] = None
        self.error: Union[str, None] = None # New attribute to store error messages

    def run(self):
        """
        Overrides the threading.Thread run method.
        Performs the API call and handles potential errors.
        """
        self.running = True
        self.result = None # Reset result
        self.error = None  # Reset error
        try:
            self.result = self.get_gemini_response()
        except Exception as e:
            self.error = str(e)
            logger.error("Error in AsyncGemini thread: {}".format(self.error))
        finally:
            self.running = False

    def get_gemini_response(self) -> str:
        """
        Passes the given data to Gemini API, returning the response.
        Raises ValueError if API token is missing or if the API returns an error.
        """
        token: Union[str, None] = get_setting(self.view, "api_token", None)
        hostname: str = get_setting(self.view, "hostname", "generativelanguage.googleapis.com")
        model_name: str = self.data.get("model", "gemini-2.5-flash") # Model name from data
        # The endpoint is always 'generateContent' for these commands
        api_endpoint: str = "generateContent"

        # Ensure token is not None before proceeding
        if token is None:
            raise ValueError("API token is missing.")

        # Using http.client for HTTPS connection
        conn: http.client.HTTPSConnection = http.client.HTTPSConnection(hostname)

        headers: Dict[str, str] = {
            "Content-Type": "application/json"
        }

        # Prepare the data payload as a JSON string
        # Remove 'model' from payload_for_body as it's used in the URL
        payload_for_body = self.data.copy()
        if "model" in payload_for_body:
            del payload_for_body["model"]

        data_payload: str = json.dumps(payload_for_body)
        logger.debug("API request data: {}".format(data_payload))

        # Construct the native Gemini API endpoint path
        # Example: POST /v1beta/models/gemini-2.5-flash:generateContent?key=YOUR_API_KEY
        path = "/v1beta/models/{}:{}?key={}".format(model_name, api_endpoint, token)
        logger.debug("API request path: {}".format(path))

        conn.request("POST", path, data_payload, headers)

        response: http.client.HTTPResponse = conn.getresponse()

        # Decode the response and load the JSON
        response_body: str = response.read().decode('utf-8')
        response_dict: Dict[str, Any] = json.loads(response_body)
        logger.debug("API response data: {}".format(response_dict))

        if response_dict.get("error", None):
            # If the API returns an error, raise it
            error_details = response_dict["error"].get("message", "Unknown API error")
            raise ValueError("API Error: {}".format(error_details))
        else:
            # Check for prompt feedback (e.g., safety issues with the input)
            prompt_feedback = response_dict.get("promptFeedback", {})
            safety_ratings = prompt_feedback.get("safetyRatings", [])
            for rating in safety_ratings:
                if rating.get("blocked"):
                    raise ValueError("Prompt blocked by safety filters: {}".format(rating.get("reason", "Unknown reason")))

            # Check for candidates and their finish reasons first
            candidates: list[Dict[str, Any]] = response_dict.get("candidates", [])
            if not candidates:
                # If no candidates and no prompt feedback, it's an unexpected empty response
                raise ValueError("Gemini did not return any candidates. The model might have generated no response or encountered an internal issue.")

            first_candidate: Dict[str, Any] = candidates[0]
            finish_reason = first_candidate.get("finishReason", None) # Changed from 'finish_reason' to 'finishReason' as per log

            if finish_reason:
                # Provide more specific messages for different finish reasons
                if finish_reason == "STOP":
                    # This means the model finished normally, but might not have content if output was short
                    pass # Will proceed to check content_parts
                elif finish_reason == "MAX_TOKENS":
                    # Get the total token count from usageMetadata
                    usage_metadata = response_dict.get("usageMetadata", {})
                    total_token_count = usage_metadata.get("totalTokenCount", 0)
                    raise ValueError("Gemini finished early due to max tokens limit. Used {} tokens. Try increasing 'max_tokens' in settings.".format(total_token_count))
                elif finish_reason == "SAFETY":
                    raise ValueError("Gemini response blocked by safety filters.")
                elif finish_reason == "RECITATION":
                    raise ValueError("Gemini response blocked due to recitation policy.")
                else:
                    raise ValueError("Gemini finished early with reason: {}".format(finish_reason))

            content_parts: list[Dict[str, Any]] = first_candidate.get("content", {}).get("parts", [])

            if not content_parts:
                # This error is now more specific as finish_reason would have been handled
                raise ValueError("No content parts found in AI response. This could be due to an empty model response even after successful generation.")

            ai_text: str = content_parts[0].get("text", "")

            if not ai_text:
                raise ValueError("No text content found in AI response part.")

            return ai_text


class GeminiCommand(sublime_plugin.TextCommand):
    """
    Base class for Gemini AI commands, providing common setup and thread handling.
    """
    def check_setup(self):
        """
        Performs checks to ensure Gemini AI can run, such as API key presence
        and selection validity.
        Raises ValueError if setup is incomplete or invalid.
        """
        key: Union[str, None] = get_setting(self.view, "api_token")

        if key is None:
            msg: str = "Please put an 'api_token' in the GeminiAI package settings"
            sublime.error_message(msg) # Use error_message for critical setup issues
            raise ValueError(msg)

        no_empty_selection: bool = get_setting(self.view, "no_empty_selection", True)

        # Ensure a selection exists before accessing it
        if not self.view.sel():
            if no_empty_selection:
                msg = "Please highlight a section of code."
                sublime.status_message(msg)
                raise ValueError(msg)
            # If no_empty_selection is False and there is no selection,
            # we can proceed, assuming the command can handle an empty region.
            # For commands like 'completions', an empty selection might still be an issue.
            # This check is primarily for commands that require a specific region.

        # Check if the primary selection is empty when it's not allowed
        if self.view.sel() and self.view.sel()[0].empty() and no_empty_selection:
            msg = "Please highlight a section of code."
            sublime.status_message(msg)
            raise ValueError(msg)

    def handle_thread(self, thread: 'AsyncGemini', label: str, on_success_callback, seconds: int = 0):
        """
        Recursively checks the status of the AsyncGemini thread and updates the UI
        or shows feedback. Dispatches UI updates to the main thread.

        Args:
            thread: The AsyncGemini thread instance.
            label: A string label for the command (e.g., "completions", "edits").
            on_success_callback: A callable function to execute when the thread finishes successfully.
                                 It will receive the thread instance as an argument.
            seconds: Current elapsed time for the timeout.
        """
        max_seconds: int = get_setting(self.view, "max_seconds", 60)

        # If we ran out of time, let user know, stop checking on the thread
        if seconds > max_seconds:
            logger.debug("Thread for {} is maxed out".format(label))
            msg: str = "Gemini ran out of time! {}s".format(max_seconds)
            sublime.status_message(msg)
            return

        # While the thread is running, show them some feedback,
        # and keep checking on the thread
        if thread.running:
            logger.debug("Thread for {} is running".format(label))
            msg: str = "Gemini is thinking, one moment... ({}/{}s)".format(seconds, max_seconds)
            sublime.status_message(msg)
            # Wait a second, then check on it again
            sublime.set_timeout(lambda: self.handle_thread(thread, label, on_success_callback, seconds + 1), 1000)
            return

        # If the thread finished but encountered an error
        if thread.error:
            logger.error("Thread for {} finished with error: {}".format(label, thread.error))
            sublime.error_message("Gemini AI Error: {}".format(thread.error))
            return

        # If we finished with no result (and no explicit error), something is wrong
        if not thread.result:
            logger.debug("Thread for {} is done, but no result found.".format(label))
            sublime.status_message("Something is wrong with Gemini - aborting (no result)")
            return

        # If the thread finished successfully and has a result, call the success callback
        logger.debug("Thread for {} finished successfully. Calling on_success_callback.".format(label))
        sublime.set_timeout(lambda: on_success_callback(thread), 0)


class GeminiBaseAiCommand(GeminiCommand):
    """
    Abstract base class for Gemini AI commands, providing common logic for
    preparing data and handling successful API responses.
    """

    def get_settings_key(self) -> str:
        """
        Returns the key used to retrieve command-specific settings (e.g., "completions", "edits").
        Must be implemented by subclasses.
        """
        raise NotImplementedError("Subclasses must implement get_settings_key()")

    def get_command_label(self) -> str:
        """
        Returns a label for the command, used in status messages and logging.
        Must be implemented by subclasses.
        """
        raise NotImplementedError("Subclasses must implement get_command_label()")

    def get_prompt_data(self, content: str, syntax_name: str, user_input: str = None) -> Dict[str, Any]:
        """
        Constructs the data payload for the Gemini API request.
        Must be implemented by subclasses.

        Args:
            content: The selected text or whole file content.
            syntax_name: The name of the current file's syntax.
            user_input: Optional user input for commands like 'edit'.
        """
        raise NotImplementedError("Subclasses must implement get_prompt_data()")

    def on_api_success(self, thread: 'AsyncGemini'):
        """
        Callback executed when the AsyncGemini thread finishes successfully.
        Contains the logic for handling the API response (e.g., inserting text,
        opening new tab). Must be implemented by subclasses.
        """
        raise NotImplementedError("Subclasses must implement on_api_success()")

    def _prepare_and_run_gemini_thread(self, content: str, user_input: str = None):
        """
        Internal method to prepare the data, create the thread, and start monitoring it.
        """
        settings_key = self.get_settings_key()
        command_label = self.get_command_label()
        command_settings: Dict[str, Any] = get_setting(self.view, settings_key)

        syntax_path: str = self.view.settings().get('syntax')
        syntax_name: str = syntax_path.split('/').pop().split('.')[0] if syntax_path else "plain text"
        logger.debug("Current syntax name: {}".format(syntax_name))

        # Get prompt data from subclass
        data: Dict[str, Any] = self.get_prompt_data(content, syntax_name, user_input)

        # Handle 'preText' which is passed to the AsyncGemini thread
        # This 'preText' is used by the success callback (e.g., for open_new_tab_with_content)
        preText: str = ""
        if settings_key == "completions" and command_settings.get("keep_prompt_text", False):
            preText = content
        elif settings_key == "edits":
             # For edits, preText is the instruction + original content for the new tab
            preText = "{} Code:\n\n```{}\n{}\n```\n\nInstruction:\n\n{}".format(syntax_name, syntax_name.lower(), content, user_input)

        # Use the current selection region for the thread, or an empty region if none
        region: sublime.Region = self.view.sel()[0] if self.view.sel() else sublime.Region(0, 0)

        # Initialize and start the async thread
        thread: AsyncGemini = AsyncGemini(self.view, region, data, preText)
        thread.start()
        self.handle_thread(thread, command_label, self.on_api_success)


class CompletionGeminiCommand(GeminiBaseAiCommand):
    """
    Provides a prompt of text/code for Gemini to complete.
    """
    def get_settings_key(self) -> str:
        return "completions"

    def get_command_label(self) -> str:
        return "completions"

    def get_prompt_data(self, content: str, syntax_name: str, user_input: str = None) -> Dict[str, Any]:
        """
        Constructs the data payload for the Gemini API completion request.
        """
        settingsc: Dict[str, Any] = get_setting(self.view, self.get_settings_key())
        return {
            "model": settingsc.get("model", "gemini-2.5-flash"),
            "contents": [
                {
                    "role": "user",
                    "parts": [{"text": "You are a helpful {} coding assistant. Complete code to the best of your ability when given some. Do not wrap the output with backticks\n{}".format(syntax_name, content)}]
                }
            ],
            "generationConfig": {
                "temperature": settingsc.get("temperature", 0),
                "top_p": settingsc.get("top_p", 1),
                "max_output_tokens": settingsc.get("max_tokens", 100),
            }
        }

    def on_api_success(self, thread: 'AsyncGemini'):
        """
        Inserts the completion text into the view.
        """
        logger.debug("Running command for `completions` with content: {}".format(thread.result))
        # Ensure UI updates are done on the main thread
        sublime.set_timeout(
            lambda: self.view.run_command(
                "replace_text",
                {
                    "region": [thread.region.begin(), thread.region.end()],
                    "text": "{}{}".format(thread.preText, thread.result)
                },
            ),
            0
        )
        sublime.status_message("Gemini AI completion inserted.")

    def run(self, edit: sublime.Edit):
        try:
            self.check_setup()
        except ValueError:
            return

        no_empty_selection: bool = get_setting(self.view, "no_empty_selection", True)

        # Check if there are selections and if no_empty_selection is enabled
        if len(self.view.sel()) == 0 and no_empty_selection:
            msg: str = "Please highlight only 1 chunk of code."
            sublime.status_message(msg)
            return

        region: sublime.Region = self.view.sel()[0]
        content: str = self.view.substr(region)

        self._prepare_and_run_gemini_thread(content)


class EditGeminiCommand(GeminiBaseAiCommand):
    """
    Provides a prompt of text/code to Gemini along with an instruction of how to
    modify the prompt, while trying to keep the functionality the same.
    """
    def get_settings_key(self) -> str:
        return "edits"

    def get_command_label(self) -> str:
        return "edits"

    def get_prompt_data(self, content: str, syntax_name: str, user_input: str = None) -> Dict[str, Any]:
        """
        Constructs the data payload for the Gemini API edit request.
        """
        settingse: Dict[str, Any] = get_setting(self.view, self.get_settings_key())

        # The preText for the prompt is constructed here for the AI model's input
        preText_for_prompt: str = "{} Code:\n\n```{}\n{}\n```\n\nInstruction:\n\n{}".format(syntax_name, syntax_name.lower(), content, user_input)

        return {
            "model": settingse.get("edit_model", "gemini-2.5-flash"), # Note: 'edit_model' for edits
            "contents": [
                {
                    "role": "user",
                    "parts": [{"text": "You are a helpful {} coding assistant. The user is a programmer so you don’t need to over explain. Respond with markdown.\n{}".format(syntax_name, preText_for_prompt)}]
                }
            ],
            "generationConfig": {
                "temperature": settingse.get("temperature", 0),
                "top_p": settingse.get("top_p", 1),
            }
        }

    def on_api_success(self, thread: 'AsyncGemini'):
        """
        Opens a new tab with the edited content.
        """
        logger.debug("Running command for `edits` with content: {}".format(thread.result))
        # Ensure UI updates are done on the main thread
        sublime.set_timeout(
            lambda: self.view.run_command(
                "open_new_tab_with_content",
                {"instruction": thread.preText, "text": thread.result},
            ),
            100
        )
        sublime.status_message("Gemini AI edit opened in new tab.")

    def run(self, edit: sublime.Edit):
        # Get the active window
        window: Union[sublime.Window, None] = self.view.window()

        # If there is no active window, we cannot proceed
        if not window:
            return

        # Show the input panel
        _ = window.show_input_panel(
            caption="Enter your prompt:",
            initial_text="",
            on_done=self.on_input_done,
            on_change=None,
            on_cancel=self.on_input_cancel
        )

    def on_input_done(self, user_input: str):
        """
        Callback function executed when the user presses Enter in the input panel.
        Initiates the Gemini edit request.
        """
        # Ensure we have a view
        view: sublime.View = self.view
        if not view:
            return

        try:
            self.check_setup()
        except ValueError:
            return

        # Determine if we should use the whole file as context
        # based on whether there is an active selection.
        # If no selection, use the whole file.
        use_whole_file: bool = len(self.view.sel()) == 0 or self.view.sel()[0].empty()

        region: sublime.Region = self.view.sel()[0] if self.view.sel() else sublime.Region(0,0) # Default to empty region if no selection
        content: str = self.view.substr(region)
        if use_whole_file:
            content = whole_file_as_context(self.view)

        # Call the base method to prepare and run the thread
        self._prepare_and_run_gemini_thread(content, user_input)

    def on_input_cancel(self):
        """
        Callback function executed if the input panel is canceled.
        """
        sublime.status_message("Input canceled.")


class ReplaceTextCommand(sublime_plugin.TextCommand):
    """
    Simple command for inserting text into a view at a specified region.
    This command must be run on the main thread.
    """
    def run(self, edit: sublime.Edit, region, text: str):
        # Cast the input region list (e.g., [begin, end]) to a sublime.Region object
        sublime_region: sublime.Region = sublime.Region(*region)
        self.view.replace(edit, sublime_region, text)


class OpenNewTabWithContentCommand(sublime_plugin.TextCommand):
    """
    A Sublime Text plugin command that opens a new empty tab
    and inserts content into it. This command must be run on the main thread.
    """
    def run(self, edit: sublime.Edit, instruction: str, text: str):
        window = self.view.window()
        if not window:
            raise ValueError("No window found for creating the new tab.")

        new_view = window.new_file(sublime.FORCE_GROUP)

        new_view.set_name("Gemini Results")

        # Set syntax highlighting for better readability, e.g., Markdown
        new_view.assign_syntax("Packages/Markdown/Markdown.sublime-syntax")

        # We need to run the insert command on the new_view.
        # The arguments are 'characters' (the text to insert) and 'point' (where to insert, 0 for the beginning).
        new_view.run_command("insert", {"characters": "### User:\n\n{}\n\n---\n\n".format(instruction), "point": 0})
        sublime.set_timeout(
            lambda: new_view.run_command("insert", {"characters": "### Results:\n\n{}".format(text), "point": len(instruction) + 4}),
            100
        )
        sublime.set_timeout(
            lambda: new_view.run_command("move_to", {"to": "bof"}),
            200
        )
        sublime.set_timeout(
            lambda: new_view.run_command("reindent", {"single_line": False}),
            300
        )

        window.focus_view(new_view)
