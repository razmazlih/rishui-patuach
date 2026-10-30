# חוזה מקורות ומיפויים
המימוש הנוכחי כולל adapters הצהרתיים לשישה סוגים: vehicles, specs, ownership, mileage, statuses, recalls. אין עדיין adapter שאומת מול מאגר אמיתי. הכותרות נבדקות בדיוק ובסדר המוצהר; שם קובץ אינו קובע קטגוריה.

לכל mapping: id קבוע למקור, kind מרשימה סגורה, version, verified, synthetic, encoding, encoding_verified, delimiter, fields, keys, coverage. fields ממפה כותרת מקור אל target, type (text/integer/date/month), required, normalize (plate בלבד) ו־precision. keys הם מזהי רשומות **בתוך המקור** בלבד. מיפוי לא מוכר/לא מאומת או כותרות שונות נעצר.

coverage מכיל description, as_of, date_precision, scope ו־stale_after_days. covered=false מציין חוסר כיסוי. as_of הוא מועד הנתונים במקור, לא יום היבוא. תאריך חודש נשאר YYYY-MM; source_files.received_at הוא מועד קליטת הקובץ, ו־sources.updated_at מועד פרסום הגרסה במערכת. official_url נשאר null עד אימות המקור הרשמי.

מפרט: spec_key הוא JSON array קומפקטי של manufacturer_code,model_code,variant_code,year. היבואן מאמת את ההתאמה לרכיבים ואת הייחודיות, גם מול מקורות פעילים. vehicles קושר מפתח זה בלבד, בלי ניחוש לפי שם דגם. התאמה עמומה אינה מוצגת כמפרט מאומת.

ריקולים: verified_plate_link נדרש; ניתן לסמנו רק לאחר אימות שמשמעות המזהה אכן מספר הרישוי. אין קישור דרך _id של קובץ אחר. required_sources מגדיר תלויות; מקור חובה חסר מונע פרסום. max_unmatched_rate הוא סף איכות מפורש (ברירת מחדל 0); התאמות נמדדות ב־SQL מול גרסאות פעילות, לא set בזיכרון.

inspect הוא sampled בלבד, דוגם עד שלוש רשומות לצורך רוחב מבני ואינו מדפיס תוכן שורות. בחירת קידוד מפורשת אינה פוטרת מאימות טקסט. יבוא סורק את כל הקובץ ב־parser ומחזיק לכל היותר 1000 רשומות באצווה ושדה עד 1MiB; חריגה נעצרת, אינה נחתכת בשקט.

דוח יבוא: records_read, records_parsed_valid, records_staged, records_accepted, records_rejected, records_published, missing_values, decode_errors, structure_errors, full_duplicates, key_conflicts, matching, scan_complete, record_count_reliable. complete מציין סריקה ובדיקות שהושלמו; failed עם scan_complete=false אינו ספירה מלאה. matching not_run אומר שלא הופעל מבחן התאמה לאותו סוג, לא שהתאמה הצליחה. פסילות וריצות נשמרות במסד; דוחות מפורטים ב־DATA_DIR/reports.

ריצה חוזרת זהה מחזירה unchanged ואינה מזיזה אוטומטית גרסה פעילה אחרת; לשחזור השתמשו ב־rollback. אין מחיקה אוטומטית של גרסאות. יש לתכנן מדיניות שימור לאחר מדידת נפח אמיתי. נעילה חלה על כל היבואנים המחוברים לאותו מסד. הפרסום אטומי למקור אחד; החלפת כמה מקורות אינה עסקה משותפת.
