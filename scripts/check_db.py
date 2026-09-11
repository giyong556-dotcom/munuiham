from app import db
with db.db() as conn:
    rows = conn.execute("select id,name,phone,status,is_read from leads").fetchall()
    print("leads", len(rows))
    for r in rows: print(dict(r))
    forms = conn.execute("select id,slug,title from forms").fetchall()
    print("forms", [dict(f) for f in forms])
