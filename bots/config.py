# ===== РОЛИ =====
ROLE_STAFF      = 1572636864962240701
ROLE_SUPPORT    = 1572636865448775816
ROLE_MODERATOR  = 1572636865448775818
ROLE_OWNER      = 1572638729879945216
ROLE_UNVERIFY   = 1572636865390051351
ROLE_GIRL       = 1572636865406701689
ROLE_BOY        = 1572636865406701688

# ===== КАНАЛЫ =====
CATEGORY_SUPPORT = 1572636865897435327
CHANNELS_STAFF = [1572636866077925520, 1572636866379784216]
CHANNELS_ALLOWED = [
    1572636866077925520,
    1572636865897435335, 1572636865897435336, 1572636866077925517, 
    1572636866077925518, 1572636866077925519, 1572636866862252119, 1572636866862252121
]
VOICE_MOD_TIME = 1572636867587874995

import os
import sqlite3

def role_ids(member):
    return [str(role.id) for role in member.roles]

def role_can_use_command(member, command):
    if ROLE_OWNER in [role.id for role in member.roles]:
        return True

    db_path = os.path.join(os.getcwd(), "data.db")
    if not os.path.exists(db_path):
        return False

    ids = role_ids(member)
    conn = sqlite3.connect(db_path)
    try:
        placeholders = ",".join("?" for _ in ids)
        if not placeholders:
            return False
        row = conn.execute(
            f"SELECT 1 FROM role_command_permissions WHERE command = ? AND role_id IN ({placeholders}) LIMIT 1",
            [command, *ids],
        ).fetchone()
        return row is not None
    finally:
        conn.close()