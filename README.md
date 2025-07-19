Sublime Gemini
=================

> This project is inspired by [necarlson97/codex-ai-sublime](https://github.com/necarlson97/codex-ai-sublime) but refactored with the help of Gemini

Sublime Gemini is a powerful Sublime Text plugin that integrates Google's Gemini AI directly into your editor, enhancing your coding workflow with intelligent assistance. From generating code snippets to refactoring and answering programming questions, Sublime Gemini brings the power of AI to your fingertips.

### Features

**Intelligent Code Completion**: Get context-aware suggestions for your code.
**Code Generation**: Generate functions, classes, or entire code blocks based on your natural language prompts.
**Code Refactoring**: Ask Gemini to refactor selected code for improved readability, performance, or adherence to best practices.
**Contextual Q&A**: Ask questions about your code, programming concepts, or general knowledge, and get instant answers within Sublime Text.
**Error Explanation & Debugging Help**: Understand and resolve errors faster with AI-driven explanations and suggestions.

### Commands

#### `completion_gemini`

Write an incomplete part of text and have Gemini try and complete it. Useful for completing functions or code. Requires some code to be selected.

#### `instruct_gemini`

Select some code and then provide an additional prompt for it. Useful for asking questions about code or wanting to ask for a rewrite of the selected code. If no code is selected, the entire file content is sent.

### Installation

#### Via Package Control (Recommended)

1. Open Sublime Text.
1. Go to Tools > Command Palette... (or press Ctrl+Shift+P / Cmd+Shift+P).
1. Type Package Control: Install Package and press Enter.
1. Search for Sublime Gemini and press Enter to install.

#### Manual Installation

1. Navigate to your Sublime Text Packages directory. You can find this by going to Preferences > Browse Packages... in Sublime Text.
1. Run `git clone https://github.com/james2doyle/sublime-gemini GeminiAI` in that folder

### Configuration

Before using Sublime Gemini, you need to configure your Google Gemini API key.
Obtain your API key from the Google AI Studio.

In Sublime Text, go to Preferences > Package Settings > Sublime Gemini > Settings.

Add your API key to the `sublime_gemini.sublime-settings` file:

```json
{
    "api_token": "YOUR_API_KEY_HERE"
}
```

Important: Replace `"YOUR_API_KEY_HERE"` with your actual Gemini API key.

#### Project Configuration

You can also configure the `api_token` on the project level.

In your `sublime-project` file:

```json
{
    // ... folders array with paths, etc.
    "settings": {
        "GeminiAI": {
            "api_token": "YOUR_API_KEY_HERE"
        }
        // ... the rest of your settings
    }
}
```

The settings code will check your local `sublime-project` first and then the global User `sublime_gemini.sublime-settings` file.

### Usage

Sublime Gemini provides several commands accessible via the Command Palette or custom key bindings.

#### Command Palette

1. Open Tools > Command Palette... (Ctrl+Shift+P / Cmd+Shift+P).
1. Type Gemini to see available commands:
  - Gemini: Complete Code: Generates the rest of the code that has been selected.
  - Gemini: Instruct Code: Add an additional prompt to the selected code.

#### Key Bindings

You can set up custom key bindings for frequently used commands. Go to Preferences > Key Bindings and add entries like this:

```json
[
    { "keys": ["ctrl+alt+g", "ctrl+alt+c"], "command": "completion_gemini" },
    { "keys": ["ctrl+alt+g", "ctrl+alt+g"], "command": "instruct_gemini" }
]
```

### Development

#### Project Structure

- `gemini_ai.py`: Main plugin entry point and core logic.
- `plugin/api_client.py`: Handles communication with the Google Gemini API.
- `plugin/commands.py`: Defines the Sublime Text commands for AI interactions.
- `plugin/listeners.py`: Contains event listeners for various Sublime Text events (e.g., selection changes).
- `plugin/settings.py`: Manages plugin settings and API key storage.
- `pyproject.toml`: Project configuration for dependency management and build tools.
