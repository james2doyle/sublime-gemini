import sublime
import sublime_plugin

import json
import http.client
import threading

from typing import Dict, Any

# --- Configuration ---
SETTINGS_FILE = "gemini-ai.sublime-settings"


# --- Helper Functions ---
# ... (plugin_settings, view_settings, get_setting, run_linter, parse_flags - keep as before) ...
# ... (parse_linter_output - keep version that optionally captures end_line/col) ...
def plugin_settings():
    return sublime.load_settings(SETTINGS_FILE)


def view_settings(view: sublime.View) -> Any:
    return view.settings().get("GeminiAI", {})


def get_setting(view: sublime.View, key: str, default: Any = None) -> Any:
    try:
        return view_settings(view)[key] or default
    except KeyError:
        return plugin_settings().get(key, default)

def whole_file_as_context(view: sublime.View) -> str:
    # 2. Get the size of the entire buffer (the file content)
    file_size = view.size()

    full_region = sublime.Region(0, file_size)

    return view.substr(full_region)


class GeminiCommand(sublime_plugin.TextCommand):
    def check_setup(self):
        """
        Perform a few checks to make sure gemini can run
        """
        key = get_setting(self.view, "api_token")

        if key is None:
            msg = "Please put an 'api_token' in the GeminiAI package settings"
            sublime.status_message(msg)
            raise ValueError(msg)

        no_empty_selection: bool = get_setting(self.view, "no_empty_selection", True)

        region = self.view.sel()[0]
        if region.empty() and no_empty_selection:
            msg = "Please highlight a section of code."
            sublime.status_message(msg)
            raise ValueError(msg)

    def handle_thread(self, thread, label: str, seconds: int = 0):
        """
        Recursive method for checking in on the AsyncGemini API fetcher
        """
        max_seconds = get_setting(self.view, "max_seconds", 60)

        # If we ran out of time, let user know, stop checking on the thread
        if seconds > max_seconds:
            msg = "Gemini ran out of time! {}s".format(max_seconds)
            sublime.status_message(msg)
            return

        # While the thread is running, show them some feedback,
        # and keep checking on the thread
        if thread.running:
            msg = "Gemini is thinking, one moment... ({}/{}s)".format(seconds, max_seconds)
            sublime.status_message(msg)
            # Wait a second, then check on it again
            sublime.set_timeout(lambda: self.handle_thread(thread, label, seconds + 1), 1000)
            return

        # If we finished with no result, something is wrong
        if not thread.result:
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

    def run(self, edit):
        # Check config and prompt
        self.check_setup()

        no_empty_selection: bool = get_setting(self.view, "no_empty_selection", True)

        if len(self.view.sel()) == 0 and no_empty_selection:
            msg = "Please highlight only 1 chunk of code."
            sublime.status_message(msg)
            raise ValueError(msg)

        # Gather data needed for gemini, prep thread to run async
        region = self.view.sel()[0]
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
        if hasPreText:
            preText = self.view.substr(region)
        else:
            preText = ""

        thread = AsyncGemini(self.view, region, "completions", data, preText)

        # Perform the async fetching and editing
        thread.start()
        self.handle_thread(thread, "completions")


class EditGeminiCommand(GeminiCommand):
    """
    Give a prompt of text/code to GPT3 along with an instruction of how to
    modify the prompt, while trying to keep the functionality the same
    (.e.g.: "Translate this code to Javascript" or "Reduce runtime complexity")
    """

    def run(self, edit):
        # Get the active window
        window = self.view.window()

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
        Callback function executed when the user presses Enter.
        """
        # Ensure we have a view and an edit object to modify the buffer
        view = self.view
        if not view:
            return

        # Insert the user input at the current cursor position(s)
        # We need to run this insertion within an edit object
        # In a TextCommand's run method, the edit argument is provided automatically.
        # However, since this is a callback function (on_input_done), we must use
        # view.run_command() to perform the edit action.

        # Note: When using an input panel, the code execution continues immediately
        # after show_input_panel() is called. The on_done callback is executed
        # asynchronously when the user provides input.

        # We use a separate command or direct view modification if appropriate.
        # For simplicity in a TextCommand, we can define the action in a helper method
        # and then call it using run_command or rely on the fact that on_done is
        # called within a context where modifications can be made safely, typically
        # using the TextCommand's view.

        # Check config and prompt
        self.check_setup()

        use_whole_file = len(self.view.sel()) == 0

        # Gather data needed for gemini, prep thread to run async
        region = self.view.sel()[0]
        content = self.view.substr(region)
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

        thread = AsyncGemini(self.view, region, "completions", data, "")

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

    running = False
    result = None

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
        self.view = view
        self.region = region
        self.endpoint = endpoint
        self.data = data
        self.preText = preText

    def run(self):
        self.running = True
        self.result = self.get_gemini_response()
        self.running = False

    def get_gemini_response(self) -> str:
        """
        Pass the given data to Open AI's gemini (davinci)
        model, returning the response
        """

        token: str = get_setting(self.view, "api_token", None)
        hostname: str = get_setting(self.view, "hostname", "generativelanguage.googleapis.com")

        conn = http.client.HTTPSConnection(hostname)
        headers = {"Authorization": "Bearer " + token, "Content-Type": "application/json"}
        data = json.dumps(self.data)

        conn.request("POST", "/v1beta/openai/chat/{}".format(self.endpoint), data, headers)
        response = conn.getresponse()

        response_dict: Dict[str, Any] = json.loads(response.read().decode())

        if response_dict.get("error", None):
            raise ValueError(response_dict["error"])
        else:
            choice = response_dict.get("choices", [{}])[0]
            ai_text = choice["message"]["content"]
            useage = response_dict["usage"]["total_tokens"]
            sublime.status_message("Gemini tokens used: " + str(useage))

            return ai_text


class ReplaceTextCommand(sublime_plugin.TextCommand):
    """
    Simple command for inserting text
    https://forum.sublimetext.com/t/solved-st3-edit-object-outside-run-method-has-return-how-to/19011/7
    """
    def run(self, edit, region, text: str):
        region = sublime.Region(*region)
        self.view.replace(edit, region, text)


class OpenNewTabWithContentCommand(sublime_plugin.WindowCommand):
    """
    A Sublime Text plugin command that opens a new empty tab
    and inserts content into it.
    """
    def run(self, text: str):
        new_view = self.window.new_file()
        new_view.set_name("Gemini Results")
        new_view.assign_syntax('source:text.html.markdown')
        new_view.run_command("insert", {"characters": text})