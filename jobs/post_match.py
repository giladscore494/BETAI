import os
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import requests

from gemini_client import GeminiClient, GroundingError
from supabase_client import SupabaseClient


def decide_winner(home_goals, away_goals):
    if home_goals is None or away_goals is None:
        return "DRAW"
    if home_goals > away_goals:
        return "HOME"
    if away_goals > home_goals:
        return "AWAY"
    return "DRAW"


def main():
    tz = ZoneInfo(os.getenv("APP_TZ", "Asia/Jerusalem"))
    gemini = GeminiClient(os.environ["GEMINI_API_KEY"])
    supabase = SupabaseClient()
    run_id = supabase.log_run("post_match")
    processed = 0
    status = "ok"
    failure_notes = []
    error_msg = None
    try:
        now = datetime.now(timezone.utc)
        cutoff = now - timedelta(minutes=120)
        params = {
            "and": f"(kickoff_utc.lte.{cutoff.isoformat()})",
        }
        matches = supabase.fetch_matches(params)
        for match in matches:
            try:
                existing = supabase._rest("results", params={"match_id": f"eq.{match['id']}"}, method="get") or []
                if existing:
                    continue
                preds = supabase.fetch_predictions(match["id"])
                predicted_winner = preds[0]["predicted_winner"] if preds else "DRAW"
                kickoff_raw = match.get("kickoff_utc") or match.get("kickoff_israel")
                kickoff_dt = datetime.fromisoformat(kickoff_raw.replace("Z", "+00:00"))
                kickoff_israel = kickoff_dt.astimezone(tz)
                match_ctx = {
                    "league": match["league"],
                    "home_team": match["home_team"],
                    "away_team": match["away_team"],
                    "date_israel": kickoff_israel.strftime("%d/%m/%Y"),
                    "time_israel": kickoff_israel.strftime("%H:%M"),
                }
                payload, duration_ms = gemini.verify_match_result(match_ctx, predicted_winner)
                final_score = payload.get("final_score", {})
                home_goals = final_score.get("home_goals")
                away_goals = final_score.get("away_goals")
                result_text = decide_winner(home_goals, away_goals)
                is_correct = result_text == predicted_winner
                result_row = {
                    "match_id": match["id"],
                    "verified_at": datetime.now(timezone.utc).isoformat(),
                    "duration_ms": duration_ms,
                    "final_home_goals": home_goals,
                    "final_away_goals": away_goals,
                    "result_text": result_text,
                    "correct": is_correct,
                    "json_payload": payload,
                    "sources": payload.get("sources"),
                    "data_cutoff_time": datetime.now(timezone.utc).isoformat(),
                }
                supabase.insert_result(result_row)
                supabase.update_match_status(match["id"], "finished")
                processed += 1
            except (GroundingError, requests.RequestException, ValueError) as exc:
                failure_notes.append(f"משחק {match.get('home_team')} - {match.get('away_team')}: {exc}")
                status = "partial_fail"
                continue
    except Exception as exc:  # noqa: BLE001
        status = "error"
        error_msg = str(exc)
    finally:
        notes_text = "; ".join(failure_notes) if failure_notes else None
        supabase.finish_run(run_id, status, processed, error=error_msg, notes=notes_text)


if __name__ == "__main__":
    main()
