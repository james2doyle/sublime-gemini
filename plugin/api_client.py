import http.client
import json
import logging
import threading
from typing import Any, Dict, List, Union

import sublime

# Import get_setting from the new settings module
from .settings import get_setting

logger = logging.getLogger("GeminiAIPlugin")


class AsyncGemini(threading.Thread):
    """
    A simple async thread class for accessing the Gemini API and waiting for a response.
    """

    def __init__(self, view: sublime.View, region: sublime.Region, data: Dict[str, Any], instruction: str):
        """
        Initializes the AsyncGemini thread.

        Args:
            view: The Sublime Text view associated with the command.
            region: The sublime.Region object representing the highlighted text.
            data: The payload data for the API request.
            instruction: Original prompt text
        """
        super().__init__()
        self.view: sublime.View = view
        self.region: sublime.Region = region
        self.data: Dict[str, Any] = data
        self.instruction: str = instruction
        self.running: bool = False
        self.result: Union[str, None] = None
        self.error: Union[str, None] = None

    def run(self) -> None:
        """
        Overrides the threading.Thread run method.
        Performs the API call and handles potential errors.
        """
        self.running = True
        self.result = None
        self.error = None
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
        model_name: str = self.data.get("model", "gemini-2.5-flash")
        api_path: str = "/v1beta/models/{}:generateContent".format(model_name)

        if token is None:
            raise ValueError("API token is missing.")

        conn: http.client.HTTPSConnection = http.client.HTTPSConnection(hostname)
        headers: Dict[str, str] = {"Content-Type": "application/json"}

        payload_for_body = self.data.copy()
        if "model" in payload_for_body:
            del payload_for_body["model"]

        data_payload: str = json.dumps(payload_for_body)
        logger.debug("API request data: {}".format(data_payload))

        full_path = "{}?key={}".format(api_path, token)
        logger.debug("API request path: {}".format(full_path))

        conn.request("POST", full_path, data_payload, headers)
        response: http.client.HTTPResponse = conn.getresponse()
        response_body: str = response.read().decode("utf-8")
        response_dict: Dict[str, Any] = json.loads(response_body)
        logger.debug("API response data: {}".format(response_dict))

        if response_dict.get("error", None):
            error_details = response_dict["error"].get("message", "Unknown API error")
            raise ValueError("API Error: {}".format(error_details))
        else:
            prompt_feedback = response_dict.get("promptFeedback", {})
            safety_ratings = prompt_feedback.get("safetyRatings", [])
            for rating in safety_ratings:
                if rating.get("blocked"):
                    raise ValueError(
                        "Prompt blocked by safety filters: {}".format(rating.get("reason", "Unknown reason"))
                    )

            candidates: List[Dict[str, Any]] = response_dict.get("candidates", [])
            if not candidates:
                raise ValueError(
                    "Gemini did not return any candidates. The model might have generated no response or encountered an internal issue."
                )

            first_candidate: Dict[str, Any] = candidates[0]
            finish_reason = first_candidate.get("finishReason", None)

            if finish_reason:
                if finish_reason == "STOP":
                    pass
                elif finish_reason == "MAX_TOKENS":
                    usage_metadata = response_dict.get("usageMetadata", {})
                    total_token_count = usage_metadata.get("totalTokenCount", 0)
                    raise ValueError(
                        "Gemini finished early due to max tokens limit. Used {} tokens. Try increasing 'max_tokens' in settings.".format(
                            total_token_count
                        )
                    )
                elif finish_reason == "SAFETY":
                    raise ValueError("Gemini response blocked by safety filters.")
                elif finish_reason == "RECITATION":
                    raise ValueError("Gemini response blocked due to recitation policy.")
                else:
                    raise ValueError("Gemini finished early with reason: {}".format(finish_reason))

            content_parts: List[Dict[str, Any]] = first_candidate.get("content", {}).get("parts", [])

            if not content_parts:
                raise ValueError("No text content parts found in AI response.")

            ai_text: str = content_parts[0].get("text", "")

            if not ai_text:
                raise ValueError("No text content found in AI response part.")

            return ai_text
