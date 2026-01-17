import os
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import requests

from gemini_client import GeminiClient, GroundingError, MODEL_ID
from supabase_client import SupabaseClient


def parse_prob(value):
    if isinstance(value, str) and value.endswith("%"):
        value = value.replace("%", "")
    return float(value) / 100.0


def compute_baseline(match):
    # Simple baseline: home advantage + placeholder league position effect if available
    home_rank = match.get("home_rank") or 10
    away_rank = match.get("away_rank") or 10
    total = home_rank + away_rank
    home_strength = (away_rank / total) + 0.1
    away_strength = (home_rank / total)
    draw = 0.2
    norm = home_strength + away_strength + draw
    return {
        "method": "simple_table_home_adv",
        "prob_home": round(home_strength / norm, 3),
        "prob_draw": round(draw / norm, 3),
        "prob_away": round(away_strength / norm, 3),
    }


def main():
    tz = ZoneInfo(os.getenv("APP_TZ", "Asia/Jerusalem"))
    gemini = GeminiClient(os.environ["GEMINI_API_KEY"])
    supabase = SupabaseClient()
    run_id = supabase.log_run("pre_match")
    processed = 0
    status = "ok"
    failure_notes = []
    error_msg = None
    try:
        now = datetime.now(timezone.utc)
        start = now + timedelta(minutes=50)
        end = now + timedelta(minutes=70)
        params = {
            "and": f"(kickoff_utc.gte.{start.isoformat()},kickoff_utc.lte.{end.isoformat()})",
            "status": "eq.scheduled",
        }
        matches = supabase.fetch_matches(params)
        for match in matches:
            try:
                existing = supabase.fetch_predictions(match["id"])
                if existing:
                    continue
                kickoff_raw = match.get("kickoff_utc") or match.get("kickoff_israel")
                kickoff_dt = datetime.fromisoformat(kickoff_raw.replace("Z", "+00:00"))
                kickoff_israel = kickoff_dt.astimezone(tz)
                match_ctx = {
                    "league": match["league"],
                    "home_team": match["home_team"],
                    "away_team": match["away_team"],
                    "date_israel": kickoff_israel.strftime("%d/%m/%Y"),
                    "time_israel": kickoff_israel.strftime("%H:%M"),
                    "venue": match.get("venue"),
                }
                payload, duration_ms = gemini.generate_pre_match_prediction(match_ctx)
                probs = payload["match_prediction"]["win_probability"]
                pred_row = {
                    "match_id": match["id"],
                    "duration_ms": duration_ms,
                    "model_name": MODEL_ID,
                    "predicted_winner": payload["match_prediction"]["estimated_winner"],
                    "prob_home": parse_prob(probs["home"]),
                    "prob_draw": parse_prob(probs["draw"]),
                    "prob_away": parse_prob(probs["away"]),
                    "recommended_focus": payload["match_prediction"]["recommended_bet_focus"],
                    "json_payload": payload,
                    "sources": payload.get("sources"),
                    "data_cutoff_time": datetime.now(timezone.utc).isoformat(),
                    "prompt_version": "v1",
                }
                supabase.insert_prediction(pred_row)
                baseline = compute_baseline(match)
                baseline["match_id"] = match["id"]
                supabase.upsert_baseline(baseline)
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
