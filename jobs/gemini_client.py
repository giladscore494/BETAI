import json
import time
from typing import Any, Dict, Optional, Tuple

import requests


GEMINI_URL = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"

# Prompt templates (Hebrew)
PRE_MATCH_SYSTEM = (
    "You must browse the web for every claim. You must not invent any data. "
    "Output MUST be valid JSON only in Hebrew. If a field cannot be verified, set it to \"לא ידוע\" "
    "and add a short Hebrew note in the relevant \"notes\" field explaining uncertainty."
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
4) לצרף מקורות אינטרנט (URLs) תחת "sources" בתוך אותו JSON, לכל מקטע לפחות.

החזר את ה-JSON EXACT במבנה הבא (מפתחות זהים):
{{
  "match_details": {{
    "fixture": "בית vs חוץ",
    "date": "DD/MM/YYYY",
    "time_israel": "HH:MM",
    "venue": "…",
    "league_position": {{
      "home": "…",
      "away": "…"
    }}
  }},
  "team_news": {{
    "home": {{
      "status": "Home Team",
      "current_form": "…",
      "missing_players": ["שם (סיבה)", "..."],
      "predicted_lineup": ["GK: ...", "DEF: ...", "MID: ...", "ATT: ..."],
      "notes": "…"
    }},
    "away": {{
      "status": "Away Team",
      "current_form": "…",
      "missing_players": ["..."],
      "predicted_lineup": ["..."],
      "notes": "…"
    }}
  }},
  "head_to_head_trends": {{
    "last_meeting": "…",
    "trend": "…",
    "away_dominance": "…"
  }},
  "match_prediction": {{
    "estimated_winner": "HOME/DRAW/AWAY",
    "win_probability": {{
      "home": "…%",
      "draw": "…%",
      "away": "…%"
    }},
    "reasoning": "…",
    "recommended_bet_focus": "…"
  }},
  "sources": {{
    "match_details": ["<url1>", "<url2>"],
    "team_news_home": ["<url…>"],
    "team_news_away": ["<url…>"],
    "head_to_head": ["<url…>"],
    "prediction_context": ["<url…>"]
  }}
}}
"""

POST_MATCH_SYSTEM = (
    "You must browse the web to verify the final score. Output MUST be valid JSON only in Hebrew. "
    "Never invent scores. If match was postponed/abandoned, indicate in notes and set goals to null."
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
4) הפלט חייב להיות JSON בלבד, ולכלול sources (URLs).

החזר JSON במבנה הבא:
{{
  "match_details": {{
    "fixture": "…",
    "date": "DD/MM/YYYY",
    "time_israel": "HH:MM",
    "venue": "…"
  }},
  "final_score": {{
    "home_goals": 0,
    "away_goals": 0
  }},
  "winner_result": "HOME/DRAW/AWAY",
  "comparison": {{
    "predicted_winner": "HOME/DRAW/AWAY",
    "is_correct": true
  }},
  "notes": "…",
  "sources": {{
    "result_verification": ["<url1>", "<url2>"]
  }}
}}
"""


class GeminiClient:
    """Wrapper around Gemini HTTP API with strict JSON validation and retries."""

    def __init__(self, api_key: str, model: str = "gemini-1.5-flash-latest"):
        self.api_key = api_key
        self.model = model

    def _call_api(self, system_instruction: str, user_prompt: str) -> str:
        url = GEMINI_URL.format(model=self.model)
        headers = {"Content-Type": "application/json"}
        params = {"key": self.api_key}
        payload = {
            "system_instruction": {"parts": [{"text": system_instruction}]},
            "contents": [{"role": "user", "parts": [{"text": user_prompt}]}],
            "generationConfig": {"response_mime_type": "application/json"},
            "tools": [{"google_search": {}}],
        }
        start = time.time()
        resp = requests.post(url, params=params, headers=headers, json=payload, timeout=90)
        duration_ms = int((time.time() - start) * 1000)
        resp.raise_for_status()
        data = resp.json()
        text = (
            data.get("candidates", [{}])[0]
            .get("content", {})
            .get("parts", [{}])[0]
            .get("text", "")
        )
        if not text:
            raise ValueError("Gemini response missing text")
        return text, duration_ms

    @staticmethod
    def _parse_json(text: str) -> Dict[str, Any]:
        return json.loads(text)

    def _retry_parse(
        self, system_prompt: str, user_prompt: str, max_attempts: int = 3
    ) -> Tuple[Optional[Dict[str, Any]], int]:
        last_error = None
        total_duration = 0
        for attempt in range(max_attempts):
            text, duration_ms = self._call_api(system_prompt, user_prompt)
            total_duration += duration_ms
            try:
                parsed = self._parse_json(text)
                return parsed, total_duration
            except (json.JSONDecodeError, ValueError) as exc:
                last_error = exc
                user_prompt = user_prompt + "\n\nתקן את הפורמט ל-JSON תקני בלבד."
        raise ValueError(f"Failed to parse JSON after retries: {last_error}")

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
        payload, duration_ms = self._retry_parse(PRE_MATCH_SYSTEM, user_prompt)
        self._validate_prediction(payload)
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
        payload, duration_ms = self._retry_parse(POST_MATCH_SYSTEM, user_prompt)
        self._validate_result(payload)
        return payload, duration_ms
