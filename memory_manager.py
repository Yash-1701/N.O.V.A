import sqlite3
from datetime import datetime

DB_NAME = "nova_memory.db"

def init_db():
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS memories (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp TEXT,
            fact TEXT
        )
    ''')
    conn.commit()
    conn.close()

def save_fact(fact):
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    cursor.execute("INSERT INTO memories (timestamp, fact) VALUES (?, ?)", (timestamp, fact))
    conn.commit()
    conn.close()

def get_recent_memories(limit=5):
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute("SELECT fact FROM memories ORDER BY id DESC LIMIT ?", (limit,))
    rows = cursor.fetchall()
    conn.close()
    return " | ".join([row[0] for row in rows])

init_db()