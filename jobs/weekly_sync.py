import os
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import requests

from gemini_client import GeminiClient
from supabase_client import SupabaseClient

LEAGUES = {
    "EPL": "Premier League",
    "LaLiga": "La Liga",
    "SerieA": "Serie A",
    "Bundesliga": "Bundesliga",
    "Ligue1": "Ligue 1",
}


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
    return dt.astimezone(ZoneInfo("Asia/Jerusalem"))


def fetch_fixtures(client: GeminiClient, league_code: str, league_name: str):
    payload, _ = client._retry_parse(
        "בצע חיפוש אינטרנטי והחזר JSON של משחקי שבוע הקרוב בלבד.",
        FIXTURE_PROMPT.format(league_name=league_name, league_code=league_code),
    )
    if not isinstance(payload, list):
        raise ValueError("Fixture response must be list")
    return payload


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
    try:
        all_matches = []
        for code, name in LEAGUES.items():
            fixtures = fetch_fixtures(gemini, code, name)
            for fx in fixtures:
                match_row = build_match_row(fx)
                window_end = datetime.now(timezone.utc) + timedelta(days=7)
                if match_row["_kickoff_dt"] > window_end:
                    continue
                match_row.pop("_kickoff_dt", None)
                all_matches.append(match_row)
        if all_matches:
            supabase.upsert_matches(all_matches)
            processed = len(all_matches)
        supabase.finish_run(run_id, "ok", processed)
    except (requests.RequestException, ValueError) as exc:
        supabase.finish_run(run_id, "error", processed, error=str(exc))
        raise


if __name__ == "__main__":
    main()
