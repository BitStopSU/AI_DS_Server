CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT NOT NULL, updated_at TEXT NOT NULL DEFAULT (datetime('now')));
CREATE TABLE IF NOT EXISTS modules (id TEXT PRIMARY KEY, enabled INTEGER NOT NULL DEFAULT 0, updated_at TEXT NOT NULL DEFAULT (datetime('now')));
CREATE TABLE IF NOT EXISTS bots (id TEXT PRIMARY KEY, name TEXT NOT NULL, script_path TEXT NOT NULL, token_encrypted TEXT, status TEXT NOT NULL DEFAULT 'stopped', pid INTEGER, auto_start INTEGER DEFAULT 0, restart_limit INTEGER DEFAULT 3, last_heartbeat TEXT, last_error TEXT, created_at TEXT DEFAULT (datetime('now')));
CREATE TABLE IF NOT EXISTS backup_log (id INTEGER PRIMARY KEY AUTOINCREMENT, created_at TEXT NOT NULL DEFAULT (datetime('now')), location TEXT NOT NULL, path TEXT NOT NULL, size_bytes INTEGER, status TEXT NOT NULL DEFAULT 'ok', error TEXT);
CREATE TABLE IF NOT EXISTS role_permissions (role_id TEXT PRIMARY KEY, can_manage_bots TEXT DEFAULT '[]', can_restart INTEGER DEFAULT 0, can_rollback INTEGER DEFAULT 0, updated_at TEXT DEFAULT (datetime('now')));
CREATE TABLE IF NOT EXISTS role_categories (id TEXT PRIMARY KEY, name TEXT NOT NULL, sort_order INTEGER NOT NULL DEFAULT 0);
CREATE TABLE IF NOT EXISTS role_assignments (role_id TEXT PRIMARY KEY, category_id TEXT NOT NULL, updated_at TEXT NOT NULL DEFAULT (datetime('now')));
CREATE TABLE IF NOT EXISTS role_command_permissions (role_id TEXT NOT NULL, command TEXT NOT NULL, PRIMARY KEY (role_id, command));
CREATE TABLE IF NOT EXISTS role_category_permissions (category_id TEXT NOT NULL, command TEXT NOT NULL, PRIMARY KEY (category_id, command));
CREATE TABLE IF NOT EXISTS recruitment_positions (
  role_id TEXT PRIMARY KEY,
  name TEXT NOT NULL,
  description TEXT NOT NULL DEFAULT '',
  active INTEGER NOT NULL DEFAULT 1,
  sort_order INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS recruitment_applications (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  guild_id TEXT NOT NULL,
  applicant_id TEXT NOT NULL,
  position_role_id TEXT NOT NULL,
  position_name TEXT NOT NULL,
  answers TEXT NOT NULL DEFAULT '{}',
  status TEXT NOT NULL DEFAULT 'pending',
  created_at TEXT NOT NULL DEFAULT (datetime('now'))
);