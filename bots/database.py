import sqlite3

DB_PATH = "shared_bot_data.db"

def init_db():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS staff_profiles (
        user_id INTEGER PRIMARY KEY, guild_id INTEGER, role_type TEXT, 
        warns INTEGER DEFAULT 0, mutes INTEGER DEFAULT 0, kicks INTEGER DEFAULT 0, 
        bans INTEGER DEFAULT 0, verifications INTEGER DEFAULT 0, reputation INTEGER DEFAULT 0)''')
    c.execute('''CREATE TABLE IF NOT EXISTS punishments (
        id INTEGER PRIMARY KEY AUTOINCREMENT, guild_id INTEGER, user_id INTEGER, 
        moderator_id INTEGER, type TEXT, reason TEXT, active INTEGER DEFAULT 1, 
        timestamp DATETIME DEFAULT CURRENT_TIMESTAMP)''')
    c.execute('''CREATE TABLE IF NOT EXISTS mod_voice_time (
        user_id INTEGER, guild_id INTEGER, seconds INTEGER DEFAULT 0, 
        PRIMARY KEY (user_id, guild_id))''')
    c.execute('''CREATE TABLE IF NOT EXISTS support_voice_time (
        user_id INTEGER, guild_id INTEGER, seconds INTEGER DEFAULT 0,
        PRIMARY KEY (user_id, guild_id))''')
    c.execute('''CREATE TABLE IF NOT EXISTS recruitment_positions (
        role_id TEXT PRIMARY KEY, name TEXT NOT NULL, description TEXT DEFAULT '',
        active INTEGER DEFAULT 1, sort_order INTEGER DEFAULT 0)''')
    c.execute('''CREATE TABLE IF NOT EXISTS recruitment_applications (
        id INTEGER PRIMARY KEY AUTOINCREMENT, guild_id INTEGER, applicant_id INTEGER,
        position_role_id TEXT, position_name TEXT, answers TEXT DEFAULT '{}',
        status TEXT DEFAULT 'pending',
        created_at DATETIME DEFAULT CURRENT_TIMESTAMP)''')
    conn.commit()
    conn.close()

def get_db():
    conn = sqlite3.connect(DB_PATH, timeout=15)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA busy_timeout = 15000")
    return conn