import os
from datetime import datetime, timedelta, timezone

from supabase_client import SupabaseClient


def compute_brier(prob_home, prob_draw, prob_away, outcome):
    actual = {"HOME": 0, "DRAW": 0, "AWAY": 0}
    actual[outcome] = 1
    return (
        (prob_home - actual["HOME"]) ** 2
        + (prob_draw - actual["DRAW"]) ** 2
        + (prob_away - actual["AWAY"]) ** 2
    )


def main():
    os.environ["TZ"] = "UTC"
    supabase = SupabaseClient()
    end = datetime.now(timezone.utc)
    start = end - timedelta(days=7)
    results = supabase.fetch_results({"and": f"(verified_at.gte.{start.isoformat()})"})
    total = len(results)
    if total == 0:
        print("No results to summarize")
        return
    correct = 0
    brier_sum = 0.0
    for res in results:
        preds = supabase.fetch_predictions(res["match_id"])
        if preds:
            pred = preds[0]
            brier_sum += compute_brier(pred["prob_home"], pred["prob_draw"], pred["prob_away"], res["result_text"])
            if res["result_text"] == pred["predicted_winner"]:
                correct += 1
    accuracy = correct / total if total else 0
    brier = brier_sum / total if total else 0
    print(
        f"סטטיסטיקה שבועית: משחקים={total}, דיוק={accuracy:.2%}, Brier={brier:.3f}"
    )


if __name__ == "__main__":
    main()
