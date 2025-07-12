import http.client
import json
import logging
import threading

from typing import Any, Dict, Union

import sublime
import sublime_plugin

# --- Configuration ---
SETTINGS_FILE = "gemini-ai.sublime-settings"

# Configure logging
# By default, Sublime Text captures logs from the Python logging module.
# You can set the logging level as needed.
logging.basicConfig(level=logging.DEBUG)

# Get a logger for your plugin
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

    def handle_thread(self, thread: 'AsyncGemini', label: str, seconds: int = 0):
        """
        Recursively checks the status of the AsyncGemini thread and updates the UI
        or shows feedback. Dispatches UI updates to the main thread.
        """
        max_seconds: int = get_setting(self.view, "max_seconds", 60)

        # If we ran out of time, let user know, stop checking on the thread
        if seconds > max_seconds:
            logger.debug("Thread for %s is maxed out", thread.endpoint)
            msg: str = "Gemini ran out of time! {}s".format(max_seconds)
            sublime.status_message(msg)
            return

        # While the thread is running, show them some feedback,
        # and keep checking on the thread
        if thread.running:
            logger.debug("Thread for %s is running", thread.endpoint)
            msg: str = "Gemini is thinking, one moment... ({}/{}s)".format(seconds, max_seconds)
            sublime.status_message(msg)
            # Wait a second, then check on it again
            sublime.set_timeout(lambda: self.handle_thread(thread, label, seconds + 1), 1000)
            return

        # If the thread finished but encountered an error
        if thread.error:
            logger.error("Thread for %s finished with error: %s", thread.endpoint, thread.error)
            sublime.error_message(f"Gemini AI Error: {thread.error}")
            return

        # If we finished with no result (and no explicit error), something is wrong
        if not thread.result:
            logger.debug("Thread for %s is done, but no result found.", thread.endpoint)
            sublime.status_message("Something is wrong with Gemini - aborting (no result)")
            return

        # If the thread finished successfully and has a result, update the UI
        if label == "completions":
            # Ensure UI updates are done on the main thread
            sublime.set_timeout(
                lambda: self.view.run_command(
                    "replace_text",
                    {"region": [thread.region.begin(), thread.region.end()], "text": thread.preText + thread.result},
                ),
                0
            )
            sublime.status_message("Gemini AI completion inserted.")


        if label == "edits":
            # Ensure UI updates are done on the main thread
            sublime.set_timeout(
                lambda: self.view.run_command(
                    "open_new_tab_with_content",
                    {"text": thread.result},
                ),
                0
            )
            sublime.status_message("Gemini AI edit opened in new tab.")


class CompletionGeminiCommand(GeminiCommand):
    """
    Provides a prompt of text/code for Gemini to complete.
    """
    def run(self, edit: sublime.Edit):
        try:
            # Check config and prompt
            self.check_setup()
        except ValueError as e:
            # check_setup already displays status/error messages
            return

        no_empty_selection: bool = get_setting(self.view, "no_empty_selection", True)

        # Check if there are selections and if no_empty_selection is enabled
        if len(self.view.sel()) == 0 and no_empty_selection:
            msg: str = "Please highlight only 1 chunk of code."
            sublime.status_message(msg)
            return

        # Gather data needed for gemini, prep thread to run async
        region: sublime.Region = self.view.sel()[0]
        settingsc: Dict[str, Any] = get_setting(self.view, "completions")

        data: Dict[str, Any] = {
            "model": settingsc.get("model", "gemini-2.5-flash"),
            "messages": [
                {"role": "system", "content": "You are a helpful coding assistant. Complete code to the best of your ability when given some. Do not wrap the output with backticks"},
                {
                    "role": "user",
                    "content": "Here is some pyton code: {}".format(self.view.substr(region))
                }
            ],
            "max_tokens": settingsc.get("max_tokens", 100),
            "temperature": settingsc.get("temperature", 0),
            "top_p": settingsc.get("top_p", 1),
        }

        hasPreText: bool = settingsc.get("keep_prompt_text", False)
        preText: str = ""
        if hasPreText:
            preText = self.view.substr(region)

        thread: AsyncGemini = AsyncGemini(self.view, region, "completions", data, preText)

        # Perform the async fetching and editing
        thread.start()
        self.handle_thread(thread, "completions")


class EditGeminiCommand(GeminiCommand):
    """
    Provides a prompt of text/code to Gemini along with an instruction of how to
    modify the prompt, while trying to keep the functionality the same.
    """
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
            # Check config and prompt
            self.check_setup()
        except ValueError as e:
            # check_setup already displays status/error messages
            return

        # Determine if we should use the whole file as context
        # based on whether there is an active selection.
        # If no selection, use the whole file.
        use_whole_file: bool = len(self.view.sel()) == 0 or self.view.sel()[0].empty()

        region: sublime.Region = self.view.sel()[0] if self.view.sel() else sublime.Region(0,0) # Default to empty region if no selection
        content: str = self.view.substr(region)
        if use_whole_file:
            content = whole_file_as_context(self.view)

        settingse: Dict[str, Any] = get_setting(self.view, "edits")

        data: Dict[str, Any] = {
            "model": settingse.get("edit_model", "gemini-2.5-flash"),
            "messages": [
                {"role": "system", "content": "You are a helpful coding assistant. Do not wrap any code output with backticks or format it as markdown."},
                {
                    "role": "user",
                    "content": "Code:\n{}\nInstruction:\n{}".format(content, user_input)
                }
            ],
            "temperature": settingse.get("temperature", 0),
            "top_p": settingse.get("top_p", 1),
        }

        # Note: The original code passed "completions" as endpoint for edits.
        # It should likely be "edits" or a different endpoint if the API supports it.
        # Assuming the API endpoint for edits is still under "chat" and uses "completions" internally
        # or that the instruction in the message handles the "edit" functionality.
        # If the Gemini API has a dedicated "edits" endpoint, this might need adjustment.
        thread: AsyncGemini = AsyncGemini(self.view, region, "completions", data, "") # Keeping "completions" as per original logic

        # Perform the async fetching and editing
        thread.start()
        self.handle_thread(thread, "edits")

    def on_input_cancel(self):
        """
        Callback function executed if the input panel is canceled.
        """
        sublime.status_message("Input canceled.")


class AsyncGemini(threading.Thread):
    """
    A simple async thread class for accessing the Gemini API and waiting for a response.
    """

    def __init__(self, view: sublime.View, region: sublime.Region, endpoint: str, data: Dict[str, Any], preText: str):
        """
        Initializes the AsyncGemini thread.

        Args:
            view: The Sublime Text view associated with the command.
            region: The sublime.Region object representing the highlighted text.
            endpoint: The API endpoint to hit (e.g., "completions").
            data: The payload data for the API request.
            preText: Text to prepend to the result (e.g., original prompt text).
        """
        super().__init__()
        self.view: sublime.View = view
        self.region: sublime.Region = region
        self.endpoint: str = endpoint
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
            logger.error("Error in AsyncGemini thread: %s", self.error)
        finally:
            self.running = False

    def get_gemini_response(self) -> str:
        """
        Passes the given data to Gemini API, returning the response.
        Raises ValueError if API token is missing or if the API returns an error.
        """
        token: Union[str, None] = get_setting(self.view, "api_token", None)
        hostname: str = get_setting(self.view, "hostname", "generativelanguage.googleapis.com")

        # Ensure token is not None before proceeding
        if token is None:
            raise ValueError("API token is missing.")

        # Using http.client for HTTPS connection
        conn: http.client.HTTPSConnection = http.client.HTTPSConnection(hostname)
        headers: Dict[str, str] = {
            "Authorization": "Bearer " + token,
            "Content-Type": "application/json"
        }

        # Prepare the data payload as a JSON string
        data_payload: str = json.dumps(self.data)
        logger.debug("API request data: %s", data_payload)

        # The endpoint path for Gemini API is typically /v1beta/models/{model_id}:generateContent
        # The original code uses /v1beta/openai/chat/{self.endpoint} which might be an older
        # or specific proxy setup. Assuming the current setup expects this path.
        # If you are directly calling Google's Gemini API, the path should be:
        # "/v1beta/models/{model_name}:generateContent?key={API_KEY}"
        # Given the `hostname` is `generativelanguage.googleapis.com` and `Authorization: Bearer {token}`
        # it suggests a direct Google API call. The `self.endpoint` being "completions"
        # implies a custom mapping. I will keep the original path structure but note this.

        # Original: conn.request("POST", "/v1beta/openai/chat/{}".format(self.endpoint), data_payload, headers)
        # More standard Gemini API path:
        # model_name = self.data.get("model", "gemini-2.5-flash")
        # conn.request("POST", f"/v1beta/models/{model_name}:generateContent", data_payload, headers)
        # However, the current setup uses Authorization: Bearer, which is common for OAuth.
        # If `api_token` is truly a bearer token for a custom proxy or an OAuth token,
        # the original path might be correct for that specific setup.
        # I will stick to the original path for now to minimize breaking changes.
        conn.request("POST", "/v1beta/openai/chat/{}".format(self.endpoint), data_payload, headers)

        response: http.client.HTTPResponse = conn.getresponse()

        # Decode the response and load the JSON
        response_body: str = response.read().decode('utf-8')
        response_dict: Dict[str, Any] = json.loads(response_body)
        logger.debug("API response data: %s", response_dict)

        if response_dict.get("error", None):
            # If the API returns an error, raise it
            error_details = response_dict["error"].get("message", "Unknown API error")
            raise ValueError(f"API Error: {error_details}")
        else:
            # Type hinting the retrieved choice and usage data
            # Assuming the response structure for choices is consistent with OpenAI-like models
            # For direct Gemini API, the structure is usually `candidates[0].content.parts[0].text`
            # The current structure `choices[0].message.content` suggests an OpenAI compatibility layer.
            choices: list[Dict[str, Any]] = response_dict.get("choices", [])
            if not choices:
                raise ValueError("No choices found in API response.")

            choice: Dict[str, Any] = choices[0]
            message: Dict[str, Any] = choice.get("message", {})
            ai_text: str = message.get("content", "")

            if not ai_text:
                raise ValueError("No content found in AI response message.")

            # Accessing usage information
            usage_info: Dict[str, int] = response_dict.get("usage", {})
            total_tokens: int = usage_info.get("total_tokens", 0)

            sublime.status_message("Gemini tokens used: " + str(total_tokens))

            return ai_text


class ReplaceTextCommand(sublime_plugin.TextCommand):
    """
    Simple command for inserting text into a view at a specified region.
    This command must be run on the main thread.
    """
    def run(self, edit: sublime.Edit, region, text: str):
        # Cast the input region list (e.g., [begin, end]) to a sublime.Region object
        sublime_region: sublime.Region = sublime.Region(*region)
        self.view.replace(edit, sublime_region, text)


class OpenNewTabWithContentCommand(sublime_plugin.WindowCommand):
    """
    A Sublime Text plugin command that opens a new empty tab
    and inserts content into it. This command must be run on the main thread.
    """
    def run(self, text: str):
        new_view: sublime.View = self.window.new_file()
        new_view.set_name("Gemini Results")
        # Set syntax highlighting for better readability, e.g., Markdown
        new_view.assign_syntax('source:text.html.markdown')
        new_view.run_command("insert", {"characters": text})
