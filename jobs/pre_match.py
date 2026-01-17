import os
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import requests

from gemini_client import GeminiClient, GroundingError, MODEL_ID
from supabase_client import SupabaseClient

UTC = timezone.utc


def _iso_z(dt: datetime) -> str:
    """RFC3339 with Z (no microseconds) for PostgREST filters."""
    dt = dt.astimezone(UTC).replace(microsecond=0)
    return dt.isoformat().replace("+00:00", "Z")


def parse_prob(value):
    """
    Accepts:
    - "55%" -> 0.55
    - "0.55" -> 0.55
    - 55 -> 0.55
    - 0.55 -> 0.55
    Clamps to [0, 1].
    """
    if value is None:
        return 0.0

    if isinstance(value, str):
        v = value.strip()
        if v.endswith("%"):
            v = v[:-1].strip()
            x = float(v) / 100.0
        else:
            x = float(v)
            if x > 1.0:
                x = x / 100.0
    else:
        x = float(value)
        if x > 1.0:
            x = x / 100.0

    if x < 0.0:
        return 0.0
    if x > 1.0:
        return 1.0
    return x


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


def _parse_kickoff_any(match: dict) -> datetime:
    kickoff_raw = match.get("kickoff_utc") or match.get("kickoff_israel")
    if not kickoff_raw:
        raise ValueError("missing kickoff_utc/kickoff_israel")
    # handle Z
    return datetime.fromisoformat(str(kickoff_raw).replace("Z", "+00:00")).astimezone(UTC)


def main():
    tz = ZoneInfo(os.getenv("APP_TZ", "Asia/Jerusalem"))

    # Window tuning (defaults widened so you don't miss matches between runs)
    start_min = int(os.getenv("PREMATCH_START_MIN", "45"))   # minutes from now
    end_min = int(os.getenv("PREMATCH_END_MIN", "120"))      # minutes from now
    max_per_run = int(os.getenv("PREMATCH_MAX_PER_RUN", "5"))

    gemini = GeminiClient(os.environ["GEMINI_API_KEY"])
    supabase = SupabaseClient()

    run_id = supabase.log_run("pre_match")
    status = "ok"
    failure_notes = []

    try:
        now = datetime.now(UTC)

        start = now + timedelta(minutes=start_min)
        end = now + timedelta(minutes=end_min)

        params = {
            "and": f"(kickoff_utc.gte.{_iso_z(start)},kickoff_utc.lte.{_iso_z(end)})",
            "status": "eq.scheduled",
            "order": "kickoff_utc.asc",
            "limit": str(max_per_run),
        }

        matches = supabase.fetch_matches(params)
        if not matches:
            # Not an error; just no games in the window.
            supabase.finish_run(run_id, "ok", f"no_matches_in_window:{start_min}-{end_min}min")
            return

        for match in matches:
            try:
                # Skip if prediction already exists for this match
                existing = supabase.fetch_predictions(match["id"])
                if existing:
                    continue

                kickoff_dt_utc = _parse_kickoff_any(match)
                kickoff_israel = kickoff_dt_utc.astimezone(tz)

                match_ctx = {
                    "league": match["league"],
                    "home_team": match["home_team"],
                    "away_team": match["away_team"],
                    "date_israel": kickoff_israel.strftime("%d/%m/%Y"),
                    "time_israel": kickoff_israel.strftime("%H:%M"),
                    "venue": match.get("venue"),
                }

                payload, duration_ms = gemini.generate_pre_match_prediction(match_ctx)

                mp = payload.get("match_prediction") or {}
                probs = (mp.get("win_probability") or {})

                pred_row = {
                    "match_id": match["id"],
                    "duration_ms": int(duration_ms) if duration_ms is not None else None,
                    "model_name": MODEL_ID,
                    "predicted_winner": mp.get("estimated_winner"),
                    "prob_home": parse_prob(probs.get("home")),
                    "prob_draw": parse_prob(probs.get("draw")),
                    "prob_away": parse_prob(probs.get("away")),
                    "recommended_focus": mp.get("recommended_bet_focus"),
                    "json_payload": payload,
                    "sources": payload.get("sources"),
                    "data_cutoff_time": datetime.now(UTC).replace(microsecond=0).isoformat(),
                    "prompt_version": "v1",
                }

                supabase.insert_prediction(pred_row)

                baseline = compute_baseline(match)
                baseline["match_id"] = match["id"]
                supabase.upsert_baseline(baseline)

            except (GroundingError, requests.RequestException, ValueError, KeyError, TypeError) as exc:
                failure_notes.append(
                    f"משחק {match.get('home_team','?')} - {match.get('away_team','?')}: שגיאה ({exc})"
                )
                status = "partial_fail"
                continue

    except Exception as exc:  # noqa: BLE001
        status = "error"
        failure_notes.append(f"שגיאת מערכת: {exc}")

    finally:
        notes_text = "; ".join(failure_notes) if failure_notes else None
        supabase.finish_run(run_id, status, notes_text)


if __name__ == "__main__":
    main()
