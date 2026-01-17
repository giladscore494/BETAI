# BETAI – מעקב תחזיות כדורגל אוטומטי

מערכת אוטומטית שמסנכרנת משחקים בחמש הליגות הבכירות, מפיקה תחזיות עם חיפוש רשת (Gemini), מאמתת תוצאות, שומרת הכל ב-Supabase ומציגה ממשק אינטרנטי בעברית.

## הגדרה מהירה
1. **Supabase**
   - צור פרויקט חדש.
   - הרץ את `db/schema.sql` בקונסולת ה-SQL.
2. **סודות GitHub Actions**
   - שמור ב-Environment בשם **BETAI** כדי שזמינים לריצות: `GEMINI_API_KEY`, `SUPABASE_URL`, `SUPABASE_SERVICE_ROLE`, אופציונלי `APP_TZ`.
   - (לאתר) `SUPABASE_ANON_KEY` לקריאה בלבד.
3. **הפעלת אוטומציה**
   - ודא ש-GitHub Actions פעיל.
   - קבצי cron קיימים: `weekly_sync.yml`, `pre_match.yml`, `post_match.yml`.
   - ניתן להפעיל ידנית עם workflow_dispatch מתוך לשונית Actions (בחר את ה-workflow ולחץ Run workflow).
4. **אתר**
   - ערוך את `web/index.html` והחלף את `<SUPABASE_URL>` ו-`<SUPABASE_ANON_KEY>` בערכים שלך.
   - פרוס כ-Static Site (GitHub Pages או Supabase Storage).

## קבצי הריצה
- `jobs/weekly_sync.py` – מביא משחקים לשבוע הקרוב ומבצע upsert ל-`matches`.
- `jobs/pre_match.py` – כל 10 דק׳, מאתר חלון T-50 עד T-70 ומפיק תחזית אחת עם Gemini (עברית, חיפוש חובה).
- `jobs/post_match.py` – כל 15 דק׳, מאמת תוצאות T+120, מחשב correct ומעדכן `results`.
- `jobs/gemini_client.py` – מעטפת Gemini עם חיפוש חובה, JSON קשיח, ולידציה/ריטריי.
- `jobs/metrics.py` – חישוב דיוק שבועי ו-Brier (אופציונלי להרצה ידנית).

## הרצה מקומית
```bash
pip install requests
export GEMINI_API_KEY=...
export SUPABASE_URL=...
export SUPABASE_SERVICE_ROLE=...
# אופציונלי: export APP_TZ="Asia/Jerusalem"
python jobs/weekly_sync.py
python jobs/pre_match.py
python jobs/post_match.py
```

## הגדרת משתני Supabase ל-UI
לפני טעינת `web/index.html` בדפדפן, הזריקו:
```html
<script>
  window.SUPABASE_URL = "https://your-project.supabase.co";
  window.SUPABASE_ANON_KEY = "public-anon-key";
</script>
```

## הערות אבטחה וקרקוע
- מפתח השירות של Supabase (SERVICE ROLE) משמש רק בסקריפטים/CI, לא בדפדפן.
- אתר ה-UI משתמש במפתח `SUPABASE_ANON_KEY` לקריאה בלבד.
- לוגי הריצה מציגים רק בוליאני האם סודות הוגדרו. מקורות/grounding נאכפים אוטומטית; לבדיקה ניתן לעיין ב-runs.notes או בלוגים ולוודא שאין הודעות חסר קרקוע.

## בדיקות
אין סט בדיקות מובנה במאגר. הרצה ידנית של הסקריפטים היא הדרך המהירה לאימות.
