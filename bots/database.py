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
    conn.commit()
    conn.close()

def get_db():
    return sqlite3.connect(DB_PATH)