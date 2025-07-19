import logging
from typing import Any, Callable, Dict, List, Union

import sublime
import sublime_plugin

from .api_client import AsyncGemini

# Import necessary functions and classes from their new locations
from .settings import evaluate_instruction_snippet, get_setting, whole_file_as_context

logger = logging.getLogger("GeminiAIPlugin")
logging.basicConfig(level=logging.DEBUG)


class GeminiCommand(sublime_plugin.TextCommand):
    """
    Base class for Gemini AI commands, providing common setup and thread handling.
    """

    def check_setup(self) -> None:
        """
        Performs checks to ensure Gemini AI can run, such as API key presence
        and selection validity.
        Raises ValueError if setup is incomplete or invalid.
        """
        key: Union[str, None] = get_setting(self.view, "api_token", None)

        if key is None:
            msg: str = "Please put an 'api_token' in the GeminiAI package settings"
            sublime.error_message(msg)
            raise ValueError(msg)

        no_empty_selection: bool = get_setting(self.view, "no_empty_selection", True)

        if not self.view.sel():
            if no_empty_selection:
                msg = "Please highlight a section of code."
                sublime.status_message(msg)
                raise ValueError(msg)

        if self.view.sel() and self.view.sel()[0].empty() and no_empty_selection:
            msg = "Please highlight a section of code."
            sublime.status_message(msg)
            raise ValueError(msg)

    def handle_thread(
        self, thread: "AsyncGemini", label: str, on_success_callback: Callable[["AsyncGemini"], None], seconds: int = 0
    ) -> None:
        """
        Recursively checks the status of the AsyncGemini thread and updates the UI
        or shows feedback. Dispatches UI updates to the main thread.

        Args:
            thread: The AsyncGemini thread instance.
            label: A string label for the command (e.g., "completions", "instruct").
            on_success_callback: A callable function to execute when the thread finishes successfully.
                                 It will receive the thread instance as an argument.
            seconds: Current elapsed time for the timeout.
        """
        max_seconds: int = get_setting(self.view, "max_seconds", 60)

        if seconds > max_seconds:
            logger.debug("Thread for {} is maxed out".format(label))
            msg: str = "Gemini ran out of time! {}s".format(max_seconds)
            sublime.status_message(msg)
            return

        if thread.running:
            logger.debug("Thread for {} is running".format(label))
            msg: str = "Gemini is thinking, one moment... ({}/{}s)".format(seconds, max_seconds)
            sublime.status_message(msg)
            sublime.set_timeout(lambda: self.handle_thread(thread, label, on_success_callback, seconds + 1), 1000)
            return

        if thread.error:
            logger.error("Thread for {} finished with error: {}".format(label, thread.error))
            sublime.error_message("Gemini AI Error: {}".format(thread.error))
            return

        if not thread.result:
            logger.debug("Thread for {} is done, but no result found.".format(label))
            sublime.status_message("Something is wrong with Gemini - aborting (no result)")
            return

        logger.debug("Thread for {} finished successfully. Calling on_success_callback.".format(label))
        sublime.set_timeout(lambda: on_success_callback(thread), 0)


class GeminiBaseAiCommand(GeminiCommand):
    """
    Abstract base class for Gemini AI commands, providing common logic for
    preparing data and handling successful API responses.
    """

    def get_command_info(self) -> str:
        """
        Returns the command name, which is used to retrieve command-specific settings
        and for logging/status messages. Must be implemented by subclasses.
        """
        raise NotImplementedError("Subclasses must implement get_command_info()")

    def get_prompt_data(self, content: str, syntax_name: str, user_input: Union[str, None] = None) -> Dict[str, Any]:
        """
        Constructs the data payload for the Gemini API request.
        Must be implemented by subclasses.

        Args:
            content: The selected text or whole file content.
            syntax_name: The name of the current file's syntax.
            user_input: Optional user input for commands like 'instruct'.
        """
        raise NotImplementedError("Subclasses must implement get_prompt_data()")

    def on_api_success(self, thread: "AsyncGemini") -> None:
        """
        Callback executed when the AsyncGemini thread finishes successfully.
        Contains the logic for handling the API response (e.g., inserting text,
        opening new tab). Must be implemented by subclasses.
        """
        raise NotImplementedError("Subclasses must implement on_api_success()")

    def _prepare_and_run_gemini_thread(self, content: str, user_input: Union[str, None] = None) -> None:
        """
        Internal method to prepare the data, create the thread, and start monitoring it.
        """
        command_name: str = self.get_command_info()
        command_settings: Dict[str, Any] = get_setting(self.view, command_name)

        syntax_path: str = self.view.settings().get("syntax")
        syntax_name: str = syntax_path.split("/").pop().split(".")[0] if syntax_path else "plain text"
        logger.debug("Current syntax name: {}".format(syntax_name))

        data: Dict[str, Any] = self.get_prompt_data(content, syntax_name, user_input)

        instruction: str = ""
        if command_name == "instruct":
            instruction = "{} Code:\n\n```{}\n{}\n```\n\nInstruction:\n\n{}".format(
                syntax_name, syntax_name.lower(), content, user_input
            )

        region: sublime.Region = self.view.sel()[0] if self.view.sel() else sublime.Region(0, 0)

        thread: AsyncGemini = AsyncGemini(self.view, region, data, instruction)
        thread.start()
        self.handle_thread(thread, command_name, self.on_api_success)


class CompletionGeminiCommand(GeminiBaseAiCommand):
    """
    Provides a prompt of text/code for Gemini to complete.
    """

    def get_command_info(self) -> str:
        return "completions"

    def get_prompt_data(self, content: str, syntax_name: str, user_input: Union[str, None] = None) -> Dict[str, Any]:
        settingsc: Dict[str, Any] = get_setting(self.view, self.get_command_info())
        return {
            "model": settingsc.get("model", "gemini-2.5-flash"),
            "contents": [
                {
                    "role": "user",
                    "parts": [
                        {
                            "text": "You are a helpful {} coding assistant. Complete code to the best of your ability when given some. Do not wrap the output with backticks\n{}".format(
                                syntax_name, content
                            )
                        }
                    ],
                }
            ],
            "generationConfig": {
                "temperature": settingsc.get("temperature", 0),
                "top_p": settingsc.get("top_p", 1),
                "max_output_tokens": settingsc.get("max_tokens", 100),
            },
        }

    def on_api_success(self, thread: "AsyncGemini") -> None:
        logger.debug("Running command for `{}` with content: {}".format(self.get_command_info(), thread.result))
        sublime.set_timeout(
            lambda: self.view.run_command(
                "replace_text",
                {
                    "region": [thread.region.begin(), thread.region.end()],
                    "results": "{}{}".format(thread.instruction, thread.result),
                },
            ),
            0,
        )
        sublime.status_message("Gemini AI completion inserted.")

    def run(self, edit: sublime.Edit):
        try:
            self.check_setup()
        except ValueError:
            return

        no_empty_selection: bool = get_setting(self.view, "no_empty_selection", True)

        if len(self.view.sel()) == 0 and no_empty_selection:
            msg: str = "Please highlight only 1 chunk of code."
            sublime.status_message(msg)
            return

        region: sublime.Region = self.view.sel()[0]
        content: str = self.view.substr(region)

        self._prepare_and_run_gemini_thread(content)


class InstructGeminiCommand(GeminiBaseAiCommand):
    """
    Provides a prompt of text/code to Gemini along with an instruction of how to
    modify the prompt, while trying to keep the functionality the same.
    """

    def get_command_info(self) -> str:
        return "instruct"

    def get_prompt_data(self, content: str, syntax_name: str, user_input: str) -> Dict[str, Any]:
        settingse: Dict[str, Any] = get_setting(self.view, self.get_command_info())

        text_for_prompt = evaluate_instruction_snippet(self.view, user_input, content)

        return {
            "model": settingse.get("model", "gemini-2.5-flash"),
            "contents": [
                {
                    "role": "user",
                    "parts": [{"text": text_for_prompt}],
                }
            ],
            "generationConfig": {
                "temperature": settingse.get("temperature", 0),
                "top_p": settingse.get("top_p", 1),
            },
        }

    def on_api_success(self, thread: "AsyncGemini") -> None:
        logger.debug("Running command for `{}` with content: {}".format(self.get_command_info(), thread.result))
        sublime.set_timeout(
            lambda: self.view.run_command(
                "open_new_tab_with_content",
                {"instruction": thread.instruction, "results": thread.result},
            ),
            100,
        )
        sublime.status_message("Gemini AI instruction opened in new tab.")

    def run(self, edit: sublime.Edit):
        window: Union[sublime.Window, None] = self.view.window()

        if not window:
            return

        _ = window.show_input_panel(
            caption="Enter your instruction:",
            initial_text="",
            on_done=self.on_input_done,
            on_change=None,
            on_cancel=self.on_input_cancel,
        )

    def on_input_done(self, user_input: str) -> None:
        view: sublime.View = self.view
        if not view:
            return

        try:
            self.check_setup()
        except ValueError:
            return

        use_whole_file: bool = len(self.view.sel()) == 0 or self.view.sel()[0].empty()

        region: sublime.Region = self.view.sel()[0] if self.view.sel() else sublime.Region(0, 0)
        content: str = self.view.substr(region)
        if use_whole_file:
            content = whole_file_as_context(self.view)

        self._prepare_and_run_gemini_thread(content, user_input)

    def on_input_cancel(self) -> None:
        sublime.status_message("Input canceled.")


class ReplaceTextCommand(sublime_plugin.TextCommand):
    """
    Simple command for inserting text into a view at a specified region.
    This command must be run on the main thread.
    """

    def run(self, edit: sublime.Edit, region: List[int], results: str) -> None:
        sublime_region: sublime.Region = sublime.Region(*region)
        self.view.replace(edit, sublime_region, results)


class OpenNewTabWithContentCommand(sublime_plugin.TextCommand):
    """
    A Sublime Text plugin command that opens a new empty tab
    and inserts content into it. This command must be run on the main thread.
    """

    def run(self, edit: sublime.Edit, instruction: str, results: str) -> None:
        window: Union[sublime.Window, None] = self.view.window()
        if not window:
            raise ValueError("No window found for creating the new tab.")

        new_view: sublime.View = window.new_file(sublime.FORCE_GROUP)

        new_view.set_scratch(True)
        new_view.set_name("Gemini Results")
        new_view.assign_syntax("Packages/Markdown/Markdown.sublime-syntax")

        output = "### User:\n\n{}\n\n---\n\n### Results:\n\n{}".format(instruction, results)

        sublime.set_timeout(lambda: new_view.run_command("append", {"characters": output}), 0)
        sublime.set_timeout(lambda: new_view.run_command("move_to", {"to": "bof"}), 100)

        window.focus_view(new_view)
