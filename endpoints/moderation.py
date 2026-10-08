import hmac
import json
from typing import Mapping

from dify_plugin import Endpoint
from werkzeug import Request, Response
from werkzeug.exceptions import BadRequest, UnsupportedMediaType


class ModerationEndpoint(Endpoint):
    @staticmethod
    def _response(payload: dict, status: int = 200) -> Response:
        return Response(json.dumps(payload, ensure_ascii=False), status=status,
                        content_type="application/json")

    def _invoke(self, r: Request, values: Mapping, settings: Mapping) -> Response:
        # Authenticate before parsing untrusted request content.
        expected_key = settings.get("api_key")
        if not isinstance(expected_key, str) or not expected_key.strip():
            return self._response({"error": "API key is not configured"}, 500)
        auth_header = r.headers.get("Authorization", "")
        scheme, _, api_key = auth_header.partition(" ")
        if scheme.lower() != "bearer" or not api_key.strip():
            return self._response({"error": "Missing or invalid Authorization header"}, 401)
        if not hmac.compare_digest(api_key.strip().encode(), expected_key.encode()):
            return self._response({"error": "Invalid API key"}, 403)

        try:
            body = r.get_json()
        except (BadRequest, UnsupportedMediaType):
            return self._response({"error": "Request body must be a valid JSON object"}, 400)
        if not isinstance(body, dict):
            return self._response({"error": "Request body must be a JSON object"}, 400)
        point = body.get("point")
        if point == "ping":
            return self._response({"result": "pong"})
        if point not in ("app.moderation.input", "app.moderation.output"):
            return self._response({"error": "Unsupported moderation point"}, 400)
        params = body.get("params", {})
        if not isinstance(params, dict):
            return self._response({"error": "params must be a JSON object"}, 400)

        keywords_text = settings.get("keywords", "")
        separator = settings.get("separator", " ")
        if not isinstance(separator, str) or not separator:
            return self._response({"error": "Separator must be a non-empty string"}, 500)
        if not isinstance(keywords_text, str):
            return self._response({"error": "Keywords must be a string"}, 500)
        keywords = list(dict.fromkeys(kw.strip() for kw in keywords_text.split(separator) if kw.strip()))
        if not keywords:
            return self._response({"error": "At least one keyword must be configured"}, 500)

        stage = "input" if point == "app.moderation.input" else "output"
        strategy = settings.get(f"{stage}_strategy", "direct_output")
        if strategy not in ("direct_output", "overridden"):
            return self._response({"error": f"Invalid {stage} strategy"}, 500)
        preset = settings.get(f"{stage}_preset_response")
        if preset is None:
            preset = "The content contains illegal content"
        if not isinstance(preset, str):
            return self._response({"error": "Preset response must be a string"}, 500)

        if stage == "input":
            inputs = params.get("inputs", {})
            query = params.get("query", "")
            if not isinstance(inputs, dict) or not isinstance(query, str):
                return self._response({"error": "inputs must be an object and query must be a string"}, 400)
            # Preserve numbers, booleans, and file objects. Only top-level
            # textual input fields are eligible for keyword review.
            flagged = any(isinstance(v, str) and self._is_flagged(v, keywords) for v in inputs.values())
            flagged = flagged or self._is_flagged(query, keywords)
            overridden = {
                "inputs": {k: self._mask_words(v, keywords) if isinstance(v, str) else v
                           for k, v in inputs.items()},
                "query": self._mask_words(query, keywords),
            } if flagged and strategy == "overridden" else {}
        else:
            text = params.get("text", "")
            if not isinstance(text, str):
                return self._response({"error": "text must be a string"}, 400)
            flagged = self._is_flagged(text, keywords)
            overridden = {"text": self._mask_words(text, keywords)} if flagged and strategy == "overridden" else {}

        if not flagged:
            return self._response({"flagged": False, "action": "direct_output"})
        result = {"flagged": True, "action": strategy}
        result.update({"preset_response": preset} if strategy == "direct_output" else overridden)
        return self._response(result)

    @staticmethod
    def _is_flagged(text: str, keywords: list[str]) -> bool:
        return any(keyword in text for keyword in keywords)

    @staticmethod
    def _mask_words(text: str, keywords: list[str]) -> str:
        # Find spans on the original text, including overlapping occurrences.
        # Sequential replacement can expose suffixes or re-mask "***".
        spans = []
        for keyword in keywords:
            if not keyword:
                continue
            start = text.find(keyword)
            while start != -1:
                spans.append((start, start + len(keyword)))
                start = text.find(keyword, start + 1)
        merged = []
        for start, end in sorted(spans):
            if merged and start < merged[-1][1]:
                merged[-1] = (merged[-1][0], max(merged[-1][1], end))
            else:
                merged.append((start, end))
        parts = []
        cursor = 0
        for start, end in merged:
            parts.extend((text[cursor:start], "***"))
            cursor = end
        parts.append(text[cursor:])
        return "".join(parts)
