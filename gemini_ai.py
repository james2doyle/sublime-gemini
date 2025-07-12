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
    return sublime.load_settings(SETTINGS_FILE)


def view_settings(view: sublime.View) -> Dict[str, Any]:
    # Returns a dictionary representation of the GeminiAI settings specific to the view
    return view.settings().get("GeminiAI", {})


def get_setting(view: sublime.View, key: str, default: Any = None) -> Any:
    try:
        # We attempt to get the setting from the view-specific settings first
        view_specific_setting: Union[Any, None] = view_settings(view).get(key)
        if view_specific_setting is not None:
            return view_specific_setting
        return plugin_settings().get(key, default)
    except KeyError:
        return plugin_settings().get(key, default)


def whole_file_as_context(view: sublime.View) -> str:
    file_size: int = view.size()
    full_region: sublime.Region = sublime.Region(0, file_size)

    return view.substr(full_region)


class GeminiCommand(sublime_plugin.TextCommand):
    def check_setup(self):
        """
        Perform a few checks to make sure gemini can run
        """
        key: Union[str, None] = get_setting(self.view, "api_token")

        if key is None:
            msg: str = "Please put an 'api_token' in the GeminiAI package settings"
            sublime.status_message(msg)
            raise ValueError(msg)

        no_empty_selection: bool = get_setting(self.view, "no_empty_selection", True)

        # Ensure a selection exists before accessing it
        if not self.view.sel():
            if no_empty_selection:
                msg = "Please highlight a section of code."
                sublime.status_message(msg)
                raise ValueError(msg)
            # If no_empty_selection is False and there is no selection,
            # we can use an empty region or handle based on context.
            # Assuming the rest of the code expects `self.view.sel()[0]` to exist if no_empty_selection is False.

        region: sublime.Region = self.view.sel()[0]
        if region.empty() and no_empty_selection:
            msg = "Please highlight a section of code."
            sublime.status_message(msg)
            raise ValueError(msg)

    def handle_thread(self, thread: 'AsyncGemini', label: str, seconds: int = 0):
        """
        Recursive method for checking in on the AsyncGemini API fetcher
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

        # If we finished with no result, something is wrong
        if not thread.result:
            logger.debug("Thread for %s is done", thread.endpoint)
            sublime.status_message("Something is wrong with Gemini - aborting")
            return

        if label == "completions":
            self.view.run_command(
                "replace_text",
                {"region": [thread.region.begin(), thread.region.end()], "text": thread.preText + thread.result},
            )

        if label == "edits":
            self.view.run_command(
                "open_new_tab_with_content",
                {"text": thread.result},
            )


class CompletionGeminiCommand(GeminiCommand):
    """
    Give a prompt of text/code for GPT3 to complete
    """

    def run(self, edit: sublime.Edit):
        # Check config and prompt
        self.check_setup()

        no_empty_selection: bool = get_setting(self.view, "no_empty_selection", True)

        # Check if there are selections and if no_empty_selection is enabled
        if len(self.view.sel()) == 0 and no_empty_selection:
            msg: str = "Please highlight only 1 chunk of code."
            sublime.status_message(msg)
            raise ValueError(msg)

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
    Give a prompt of text/code to GPT3 along with an instruction of how to
    modify the prompt, while trying to keep the functionality the same
    (.e.g.: "Translate this code to Javascript" or "Reduce runtime complexity")
    """

    def run(self, edit: sublime.Edit):
        # Get the active window
        window: Union[sublime.Window, None] = self.view.window()

        # If there is no active window, we cannot proceed
        if not window:
            return

        # Show the input panel
        # The return value of show_input_panel is the InputPanel instance,
        # but we don't need to store it here.
        _ = window.show_input_panel(
            caption="Enter your prompt:",
            initial_text="",
            on_done=self.on_input_done,
            on_change=None,
            on_cancel=self.on_input_cancel
        )

    def on_input_done(self, user_input: str):
        """
        Callback function executed when the user presses Enter.
        """
        # Ensure we have a view and an edit object to modify the buffer
        view: sublime.View = self.view
        if not view:
            return

        # Check config and prompt
        self.check_setup()

        # Determine if we should use the whole file as context
        # based on whether there is an active selection.
        use_whole_file: bool = len(self.view.sel()) == 0

        # Gather data needed for gemini, prep thread to run async
        region: sublime.Region = self.view.sel()[0]
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

        thread: AsyncGemini = AsyncGemini(self.view, region, "completions", data, "")

        # Perform the async fetching and editing
        thread.start()
        self.handle_thread(thread, "edits")

    def on_input_cancel(self):
        """
        Callback function executed if the input is canceled.
        """
        sublime.status_message("Input canceled.")


class AsyncGemini(threading.Thread):
    """
    A simple async thread class for accessing the
    OpenAI Gemini API, and waiting for a response
    """

    # Class attributes for thread state and result
    running: bool = False
    result: Union[str, None] = None

    def __init__(self, view: sublime.View, region: sublime.Region, endpoint: str, data: Dict[str, Any], preText: str):
        """
        key - the open-ai given API key for this specific user
        prompt - the string of code/text to be operated on by GPT3
        region - the sublime-text hilighted region we are looking at,
            and will be dropping the result into
        instruction - for the edit endpoint, an instruction is needed, e.g.:
            "translate this code to javascript". If just generating code,
            leave as None
        """
        super().__init__()
        self.view: sublime.View = view
        self.region: sublime.Region = region
        self.endpoint: str = endpoint
        self.data: Dict[str, Any] = data
        self.preText: str = preText

    def run(self):
        # Override of the threading.Thread run method
        self.running = True
        self.result = self.get_gemini_response()
        self.running = False

    def get_gemini_response(self) -> str:
        """
        Pass the given data to Open AI's gemini (davinci)
        model, returning the response
        """

        token: Union[str, None] = get_setting(self.view, "api_token", None)
        hostname: str = get_setting(self.view, "hostname", "generativelanguage.googleapis.com")

        # Ensure token is not None before proceeding
        if token is None:
            raise ValueError("API token is missing.")

        conn: http.client.HTTPSConnection = http.client.HTTPSConnection(hostname)
        headers: Dict[str, str] = {"Authorization": "Bearer " + token, "Content-Type": "application/json"}
        # Data is already dumped to JSON string in the `run` method when passed to conn.request.
        # However, `json.dumps(self.data)` converts the Python dict to a JSON string bytes.
        data: str = json.dumps(self.data)
        logger.debug("API request data: %s", data)

        conn.request("POST", "/v1beta/openai/chat/{}".format(self.endpoint), data, headers)
        response: http.client.HTTPResponse = conn.getresponse()

        # Decode the response and load the JSON
        response_dict: Dict[str, Any] = json.loads(response.read().decode())
        logger.debug("API response data: %s", response_dict)

        if response_dict.get("error", None):
            raise ValueError(response_dict["error"])
        else:
            # Type hinting the retrieved choice and usage data
            choices: list[Dict[str, Any]] = response_dict.get("choices", [{}])
            choice: Dict[str, Any] = choices[0]

            # Accessing content from the message dictionary within the choice
            ai_text: str = choice["message"]["content"]

            # Accessing usage information
            usage_info: Dict[str, int] = response_dict["usage"]
            useage: int = usage_info["total_tokens"]

            sublime.status_message("Gemini tokens used: " + str(useage))

            return ai_text


class ReplaceTextCommand(sublime_plugin.TextCommand):
    """
    Simple command for inserting text
    https://forum.sublimetext.com/t/solved-st3-edit-object-outside-run-method-has-return-how-to/19011/7
    """
    def run(self, edit: sublime.Edit, region, text: str):
        # Cast the input region list to a sublime.Region object
        sublime_region: sublime.Region = sublime.Region(*region)
        self.view.replace(edit, sublime_region, text)


class OpenNewTabWithContentCommand(sublime_plugin.WindowCommand):
    """
    A Sublime Text plugin command that opens a new empty tab
    and inserts content into it.
    """
    def run(self, text: str):
        new_view: sublime.View = self.window.new_file()
        new_view.set_name("Gemini Results")
        new_view.assign_syntax('source:text.html.markdown')
        new_view.run_command("insert", {"characters": text})