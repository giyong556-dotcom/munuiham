# -*- coding: utf-8 -*-
import sqlite3
name = "테스트"
c = sqlite3.connect("/workspace/munuiham/data/munuiham.db")
c.execute("UPDATE leads SET name=? WHERE id=1", (name,))
c.commit()
print(c.execute("select id,name,phone from leads").fetchall())
c.close()
