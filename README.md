# Sublime Gemini AI Plugin

> This project is inspired by [necarlson97/codex-ai-sublime](https://github.com/necarlson97/codex-ai-sublime) but refactored with the help of Gemini

A Sublime Text 3/4 plugin that integrates Google's Gemini AI for intelligent code completion and editing directly within your editor. Leverage Gemini's capabilities to generate code, refactor, or get suggestions based on your current file or selection.

## Features

- **Code Completion:** Get AI-generated code completions based on your highlighted selection.
- **Code Editing/Refactoring:** Provide instructions to Gemini to modify selected code or even the entire file, with results presented in a new, clean tab for easy comparison.
- **Asynchronous Operations:** All AI API calls are performed in a separate thread, ensuring Sublime Text's UI remains responsive.
- **Configurable Settings:** Customize API keys, models, temperature, max tokens, and other parameters via `gemini-ai.sublime-settings`.
- **Context-Aware Prompts:** Automatically includes the current file's syntax name in prompts for better AI responses.
- **User Feedback:** Provides status messages and error alerts for a smooth user experience.

## Installation

1. **Manual Installation:**

- Navigate to your Sublime Text `Packages` directory. You can find this by going to `Preferences > Browse Packages...` in Sublime Text.
- Create a new folder named `GeminiAI` inside the `Packages` directory.
- Save the provided Python code (e.g., `gemini_ai.py`) into this new `GeminiAI` folder.

2. **Create Settings File:**

- Inside the `GeminiAI` folder, create a new file named `gemini-ai.sublime-settings`.
- Refer to the [Configuration](#configuration) section below for the content of this file.

## Configuration

The plugin's settings are managed via `gemini-ai.sublime-settings`. You can access this file by going to `Preferences > Package Settings > Gemini AI > Settings`.

**Example `gemini-ai.sublime-settings`:**

```json
{
    "api_token": "YOUR_GEMINI_API_TOKEN_HERE",
    "hostname": "generativelanguage.googleapis.com",
    "max_seconds": 10,
    "no_empty_selection": true,
    "completions": {
        "model": "gemini-2.5-flash",
        "temperature": 0.0,
        "top_p": 1,
        "max_tokens": 100,
        "keep_prompt_text": true
    },
    "edits": {
        "model": "gemini-2.5-flash",
        "temperature": 0.4,
        "top_p": 1
    }
}
```

**Important:** Replace `"YOUR_GEMINI_API_TOKEN_HERE"` with your actual Gemini API key. You can obtain a key from [Google AI Studio](https://aistudio.google.com/app/apikey) or through Google Cloud.

## Usage

All commands are accessible via the Sublime Text Command Palette (`Ctrl+Shift+P` or `Cmd+Shift+P`).

### 1. Gemini: Complete Code

This command provides code completions based on your current selection.

**How to use:**

1. Select the code you want Gemini to complete or continue.
1. Open the Command Palette (`Ctrl+Shift+P` / `Cmd+Shift+P`).
1. Type `Gemini: Complete Code` and press Enter.

**Result:** The AI's generated completion will be inserted directly at the location of your selection.

### 2. Gemini: Edit Code

This command allows you to provide an instruction to Gemini to modify a section of code or the entire file.

**How to use:**

1. **(Optional) Select code:** Highlight the specific code you want Gemini to edit. If no code is selected, the entire file content will be sent as context.
1. Open the Command Palette (`Ctrl+Shift+P` / `Cmd+Shift+P`).
1. Type `Gemini: Edit Code` and press Enter.
1. An input panel will appear at the bottom of the window. Enter your instruction (e.g., "Refactor this function to be more concise", "Add error handling", "Translate this to Python 3").
1. Press Enter.

**Result:** A new tab named "Gemini Results" will open, containing your original instruction and Gemini's modified code, formatted in Markdown for readability.

## Troubleshooting

- **"Please put an 'api_token' in the GeminiAI package settings"**: Ensure you have configured your `gemini-ai.sublime-settings` file with a valid `api_token`.
- **"Please highlight a section of code."**: For commands that require a selection (or if `no_empty_selection` is `true`), make sure you have text highlighted.
- **"Gemini ran out of time!"**: The AI response took longer than the `max_seconds` configured. You can increase `max_seconds` in your settings, or try a simpler prompt.
- **"Gemini AI Error: [Error Message]"**: An error occurred during the API call. Check the Sublime Text console (`View > Show Console`) for more detailed error messages. Common causes include:
- Invalid API token.
- Network issues.
- API rate limits.
- Incorrect `hostname` or API endpoint path (though the default should work for standard Gemini API access).
- **No response / Unexpected output**:
- Check your `temperature` and `top_p` settings. Higher values can lead to more creative but sometimes less predictable results.
- Review the Sublime Text console (`View > Show Console`) for `DEBUG` logs from the plugin, which can provide insights into the API request and response.
- Ensure your prompt is clear and specific.

## Contributing

Feel free to open issues or submit pull requests if you have suggestions, bug fixes, or new features to add.

## License

This project is licensed under the MIT License.
