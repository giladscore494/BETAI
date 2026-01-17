import os
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import requests

from gemini_client import GeminiClient, GroundingError
from supabase_client import SupabaseClient

LEAGUES = {
    "EPL": "Premier League",
    "LaLiga": "La Liga",
    "SerieA": "Serie A",
    "Bundesliga": "Bundesliga",
    "Ligue1": "Ligue 1",
}

TZ_NAME = os.getenv("APP_TZ", "Asia/Jerusalem")
TZ = ZoneInfo(TZ_NAME)


FIXTURE_PROMPT = """
השב במבנה JSON של מערך משחקים לשבעת הימים הקרובים בליגה {league_name}.
כל אובייקט במערך חייב להכיל:
{{
  "league": "{league_code}",
  "home_team": "...",
  "away_team": "...",
  "venue": "...",
  "kickoff_utc": "YYYY-MM-DDTHH:MM:SSZ",
  "source_urls": ["<url1>", "<url2>"]
}}
הקפד לבצע חיפוש אינטרנטי ולתת זמני התחלה מדויקים ב-UTC. החזר JSON בלבד ללא טקסט נוסף.
"""


def parse_kickoff(ts: str) -> datetime:
    if ts.endswith("Z"):
        ts = ts.replace("Z", "+00:00")
    return datetime.fromisoformat(ts).astimezone(timezone.utc)


def convert_to_israel(dt: datetime) -> datetime:
    return dt.astimezone(TZ)


def build_match_row(raw):
    kickoff = parse_kickoff(raw["kickoff_utc"])
    israel = convert_to_israel(kickoff)
    return {
        "league": raw["league"],
        "home_team": raw["home_team"],
        "away_team": raw["away_team"],
        "venue": raw.get("venue"),
        "kickoff_utc": kickoff.isoformat(),
        "kickoff_israel": israel.isoformat(),
        "fixture_source": "gemini_web",
        "fixture_source_url": (raw.get("source_urls") or [None])[0],
        "status": "scheduled",
        "_kickoff_dt": kickoff,
    }


def main():
    gemini_key = os.environ["GEMINI_API_KEY"]
    gemini = GeminiClient(gemini_key)
    supabase = SupabaseClient()
    run_id = supabase.log_run("weekly_sync")
    processed = 0
    status = "ok"
    failure_notes = []
    duration_notes = []
    error_msg = None
    try:
        all_matches = []
        for code, name in LEAGUES.items():
            try:
                fixtures, duration_ms = gemini.fetch_fixtures(code, name)
                duration_notes.append(f"{code}:{duration_ms}ms")
            except (GroundingError, requests.RequestException, ValueError) as exc:
                failure_notes.append(f"ליגה {code}: {exc}")
                status = "partial_fail"
                continue
            for fx in fixtures:
                try:
                    match_row = build_match_row(fx)
                except (KeyError, TypeError, ValueError) as exc:
                    failure_notes.append(f"שגיאת המרה במשחק {fx.get('home_team','?')}-{fx.get('away_team','?')}: {exc}")
                    status = "partial_fail"
                    continue
                window_end = datetime.now(timezone.utc) + timedelta(days=7)
                if match_row["_kickoff_dt"] > window_end:
                    continue
                match_row.pop("_kickoff_dt", None)
                all_matches.append(match_row)
        if all_matches:
            supabase.upsert_matches(all_matches)
            processed = len(all_matches)
    except Exception as exc:  # noqa: BLE001
        status = "error"
        error_msg = str(exc)
    finally:
        all_notes = failure_notes + duration_notes
        notes_text = "; ".join(all_notes) if all_notes else None
        supabase.finish_run(run_id, status, processed, error=error_msg, notes=notes_text)


if __name__ == "__main__":
    main()
