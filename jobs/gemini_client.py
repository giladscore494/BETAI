import json
import re
import time
from typing import Any, Callable, Dict, List, Optional, Tuple

import requests

MODEL_ID = "gemini-3-flash-preview"
GEMINI_URL = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
GROUNDING_RETRY_NOTE = "\n\nחובה לבצע חיפוש עם google_search ולהחזיר JSON בלבד עם מקורות (URLs) אמיתיים."
JSON_FIX_NOTE = "\n\nתקן והחזר JSON תקני בעברית בלבד וללא טקסט נוסף."

# Prompt templates (Hebrew)
PRE_MATCH_SYSTEM = (
    "חובה לבצע חיפוש אינטרנטי (google_search) לכל טענה. אל תמציא נתונים. "
    "הפלט חייב להיות JSON תקין בלבד בעברית. אם שדה לא מאומת ברשת, כתוב \"לא ידוע\" והסבר אי ודאות בשדה notes."
)

PRE_MATCH_USER = """
משימה: הפק תחזית משחק אחת בלבד בפורמט JSON קשיח ובעברית, עם חיפוש אינטרנטי חובה לכל פרמטר.
נתוני משחק ידועים:
- ליגה: {league}
- בית: {home_team}
- חוץ: {away_team}
- תאריך ושעה בישראל: {date_israel} {time_israel}
- איצטדיון (אם ידוע): {venue_or_unknown}

חובה:
1) לבצע חיפוש אינטרנטי ולאמת:
   - עמדות בטבלה ונקודות לשתי הקבוצות
   - כושר אחרון (לפחות 5 משחקים אחרונים) בשפה תמציתית
   - חיסורים (פציעות/השעיות/נבחרות) + סיבת חיסרון לכל שחקן
   - הרכב משוער לשתי הקבוצות (אם זמין ממקורות אמינים)
   - Head-to-head: משחק אחרון ומגמות רלוונטיות
2) אסור לנחש. אם אין מידע מאומת, כתוב "לא ידוע" וציין אי-ודאות ב-notes.
3) הפלט חייב להיות JSON בלבד (ללא טקסט נוסף).
4) לצרף מקורות אינטרנט (URLs אמיתיים) תחת "sources" בתוך אותו JSON, לכל מקטע לפחות.

החזר את ה-JSON EXACT במבנה הבא (מפתחות זהים):
{
  "match_details": {
    "fixture": "בית vs חוץ",
    "date": "DD/MM/YYYY",
    "time_israel": "HH:MM",
    "venue": "…",
    "league_position": {
      "home": "…",
      "away": "…"
    }
  },
  "team_news": {
    "home": {
      "status": "Home Team",
      "current_form": "…",
      "missing_players": ["שם (סיבה)", "..."],
      "predicted_lineup": ["GK: ...", "DEF: ...", "MID: ...", "ATT: ..."],
      "notes": "…"
    },
    "away": {
      "status": "Away Team",
      "current_form": "…",
      "missing_players": ["..."],
      "predicted_lineup": ["..."],
      "notes": "…"
    }
  },
  "head_to_head_trends": {
    "last_meeting": "…",
    "trend": "…",
    "away_dominance": "…"
  },
  "match_prediction": {
    "estimated_winner": "HOME/DRAW/AWAY",
    "win_probability": {
      "home": "…%",
      "draw": "…%",
      "away": "…%"
    },
    "reasoning": "…",
    "recommended_bet_focus": "…"
  },
  "sources": {
    "match_details": ["<url1>", "<url2>"],
    "team_news_home": ["<url…>"],
    "team_news_away": ["<url…>"],
    "head_to_head": ["<url…>"],
    "prediction_context": ["<url…>"]
  }
}
"""

POST_MATCH_SYSTEM = (
    "חובה לבצע חיפוש אינטרנטי (google_search) כדי לאמת תוצאת משחק. הפלט חייב להיות JSON תקין בלבד בעברית. "
    "לעולם אל תמציא שערים. אם המשחק נדחה/בוטל, ציין ב-notes ושים שערים כ-null."
)

POST_MATCH_USER = """
משימה: אימות תוצאת משחק בפורמט JSON קשיח ובעברית, עם חיפוש אינטרנטי חובה.
נתוני משחק:
- ליגה: {league}
- בית: {home_team}
- חוץ: {away_team}
- תאריך ושעה בישראל: {date_israel} {time_israel}

תחזית שנשמרה לפני המשחק:
- predicted_winner: {predicted_winner}  (HOME/DRAW/AWAY)

חובה:
1) לבצע חיפוש אינטרנטי ולאמת תוצאה סופית (שערים).
2) לקבוע winner_result (HOME/DRAW/AWAY) לפי התוצאה.
3) לחשב is_correct ביחס ל-predicted_winner.
4) הפלט חייב להיות JSON בלבד, ולכלול sources (URLs אמיתיים).

החזר JSON במבנה הבא:
{
  "match_details": {
    "fixture": "…",
    "date": "DD/MM/YYYY",
    "time_israel": "HH:MM",
    "venue": "…"
  },
  "final_score": {
    "home_goals": 0,
    "away_goals": 0
  },
  "winner_result": "HOME/DRAW/AWAY",
  "comparison": {
    "predicted_winner": "HOME/DRAW/AWAY",
    "is_correct": true
  },
  "notes": "…",
  "sources": {
    "result_verification": ["<url1>", "<url2>"]
  }
}
"""


class GroundingError(Exception):
    """Raised when grounding evidence is missing after retries."""


class GeminiClient:
    """Wrapper around Gemini HTTP API with strict JSON validation and retries."""

    def __init__(self, api_key: str, model: str = MODEL_ID):
        self.api_key = api_key
        # Ignore caller-provided model to hard-enforce required id
        self.model = MODEL_ID

    @staticmethod
    def _extract_json_text(text: str) -> str:
        cleaned = text.strip()
        cleaned = re.sub(r"^```(?:json)?", "", cleaned, flags=re.IGNORECASE).strip()
        cleaned = re.sub(r"```$", "", cleaned).strip()
        start_positions = [pos for pos in (cleaned.find("{"), cleaned.find("[")) if pos != -1]
        if start_positions:
            cleaned = cleaned[min(start_positions) :]
        end = max(cleaned.rfind("}"), cleaned.rfind("]"))
        if end != -1:
            cleaned = cleaned[: end + 1]
        return cleaned

    @staticmethod
    def _is_valid_url(url: Any) -> bool:
        return isinstance(url, str) and url.startswith("http") and "<" not in url and " " not in url

    @staticmethod
    def _has_grounding(metadata: Dict[str, Any]) -> bool:
        if not metadata or not isinstance(metadata, dict):
            return False
        queries = metadata.get("webSearchQueries") or []
        chunks = metadata.get("groundingChunks") or []
        chunk_has_uri = any(
            isinstance(chunk, dict)
            and (
                chunk.get("web", {}).get("uri")
                or chunk.get("uri")
                or (chunk.get("groundingChunk") or {}).get("web", {}).get("uri")
            )
            for chunk in chunks
        )
        return bool(queries) or chunk_has_uri

    @staticmethod
    def _ensure_sources(
        sources: Dict[str, Any], required_keys: List[str], min_counts: Optional[Dict[str, int]] = None
    ) -> None:
        if not isinstance(sources, dict):
            raise ValueError("sources must be a dict with URLs")
        min_counts = min_counts or {}
        for key in required_keys:
            urls = sources.get(key) or []
            valid_urls = [url for url in urls if GeminiClient._is_valid_url(url)]
            if len(valid_urls) < min_counts.get(key, 1):
                raise ValueError(f"Missing valid URLs in sources.{key}")

    @staticmethod
    def _parse_json(text: str) -> Dict[str, Any]:
        cleaned = GeminiClient._extract_json_text(text)
        return json.loads(cleaned)

    def _call_api(self, system_instruction: str, user_prompt: str) -> Tuple[str, Dict[str, Any], int]:
        url = GEMINI_URL.format(model=self.model)
        headers = {"Content-Type": "application/json"}
        params = {"key": self.api_key}
        payload = {
            "systemInstruction": {"parts": [{"text": system_instruction}]},
            "contents": [{"role": "user", "parts": [{"text": user_prompt}]}],
            "generationConfig": {"responseMimeType": "application/json"},
            "tools": [{"google_search": {}}],
        }
        start = time.time()
        resp = requests.post(url, params=params, headers=headers, json=payload, timeout=90)
        duration_ms = int((time.time() - start) * 1000)
        resp.raise_for_status()
        data = resp.json()
        candidate = (data.get("candidates") or [{}])[0]
        text = (candidate.get("content") or {}).get("parts", [{}])[0].get("text", "")
        metadata = candidate.get("groundingMetadata") or {}
        if not text:
            raise ValueError("Gemini response missing text")
        return text, metadata, duration_ms

    def _retry_parse(
        self,
        system_prompt: str,
        user_prompt: str,
        validator: Optional[Callable[[Dict[str, Any]], None]] = None,
        max_attempts: int = 3,
    ) -> Tuple[Dict[str, Any], int]:
        last_error: Optional[Exception] = None
        total_duration = 0
        prompt_base = user_prompt
        for attempt in range(max_attempts):
            prompt = prompt_base + (GROUNDING_RETRY_NOTE if attempt > 0 else "")
            text, metadata, duration_ms = self._call_api(system_prompt, prompt)
            total_duration += duration_ms
            try:
                parsed = self._parse_json(text)
            except (json.JSONDecodeError, ValueError) as exc:
                last_error = exc
                prompt_base = user_prompt + JSON_FIX_NOTE
                continue
            if validator:
                try:
                    validator(parsed)
                except (ValueError, KeyError, TypeError) as exc:
                    last_error = exc
                    prompt_base = user_prompt + JSON_FIX_NOTE
                    continue
            if not self._has_grounding(metadata):
                last_error = GroundingError("grounding metadata missing or empty")
                prompt_base = user_prompt + GROUNDING_RETRY_NOTE
                continue
            return parsed, total_duration
        raise last_error or GroundingError("Grounding missing after retries")

    @staticmethod
    def _validate_prediction(payload: Dict[str, Any]) -> None:
        required = [
            "match_details",
            "team_news",
            "head_to_head_trends",
            "match_prediction",
            "sources",
        ]
        for key in required:
            if key not in payload:
                raise ValueError(f"Missing key {key}")
        probs = payload["match_prediction"]["win_probability"]
        numbers = []
        for k in ("home", "draw", "away"):
            val = probs.get(k)
            if isinstance(val, str) and val.endswith("%"):
                val = val.replace("%", "")
            numbers.append(float(val))
        total = sum(numbers)
        if not 98 <= total <= 102:
            raise ValueError("Probabilities must sum to ~100")
        sources = payload.get("sources") or {}
        GeminiClient._ensure_sources(
            sources,
            ["match_details", "team_news_home", "team_news_away", "head_to_head", "prediction_context"],
        )

    @staticmethod
    def _validate_result(payload: Dict[str, Any]) -> None:
        required = [
            "match_details",
            "final_score",
            "winner_result",
            "comparison",
            "sources",
        ]
        for key in required:
            if key not in payload:
                raise ValueError(f"Missing key {key}")
        sources = payload.get("sources") or {}
        GeminiClient._ensure_sources(sources, ["result_verification"], {"result_verification": 2})

    @staticmethod
    def _validate_fixtures(payload: Any) -> None:
        if not isinstance(payload, list):
            raise ValueError("Fixture response must be list")
        for item in payload:
            if not isinstance(item, dict):
                raise ValueError("Fixture entries must be objects")
            for key in ("league", "home_team", "away_team", "kickoff_utc", "source_urls"):
                if key not in item:
                    raise ValueError(f"Missing {key} in fixture row")
            GeminiClient._ensure_sources({"source_urls": item.get("source_urls")}, ["source_urls"])

    def generate_pre_match_prediction(
        self, match: Dict[str, Any]
    ) -> Tuple[Dict[str, Any], int]:
        user_prompt = PRE_MATCH_USER.format(
            league=match["league"],
            home_team=match["home_team"],
            away_team=match["away_team"],
            date_israel=match["date_israel"],
            time_israel=match["time_israel"],
            venue_or_unknown=match.get("venue") or "לא ידוע",
        )
        payload, duration_ms = self._retry_parse(PRE_MATCH_SYSTEM, user_prompt, self._validate_prediction)
        return payload, duration_ms

    def verify_match_result(
        self, match: Dict[str, Any], predicted_winner: str
    ) -> Tuple[Dict[str, Any], int]:
        user_prompt = POST_MATCH_USER.format(
            league=match["league"],
            home_team=match["home_team"],
            away_team=match["away_team"],
            date_israel=match["date_israel"],
            time_israel=match["time_israel"],
            predicted_winner=predicted_winner,
        )
        payload, duration_ms = self._retry_parse(POST_MATCH_SYSTEM, user_prompt, self._validate_result)
        return payload, duration_ms

    def fetch_fixtures(self, league_code: str, league_name: str) -> Tuple[List[Dict[str, Any]], int]:
        system_prompt = "בצע חיפוש אינטרנטי והחזר JSON של משחקי שבוע הקרוב בלבד. השתמש בכלי google_search."
        user_prompt = (
            "השב במבנה JSON של מערך משחקים לשבעת הימים הקרובים בליגה {league_name}. "
            "כל אובייקט במערך חייב להכיל: "
            '{{"league":"{league_code}","home_team":"...","away_team":"...","venue":"...",'
            '"kickoff_utc":"YYYY-MM-DDTHH:MM:SSZ","source_urls":["<url1>","<url2>"]}} '
            "החזר JSON בלבד בעברית ללא טקסט נוסף."
        ).format(league_name=league_name, league_code=league_code)
        payload, duration_ms = self._retry_parse(system_prompt, user_prompt, self._validate_fixtures)
        return payload, duration_ms
