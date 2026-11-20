import Database from "better-sqlite3";
import fs from "node:fs"; import path from "node:path"; import { fileURLToPath } from "node:url";
const __dirname = path.dirname(fileURLToPath(import.meta.url));
const DB_PATH = path.join(__dirname, "..", "data.db"); const SCHEMA_PATH = path.join(__dirname, "schema.sql");
let db;
export function getDb() {
  if (db) return db;
  db = new Database(DB_PATH);
  db.pragma("journal_mode = WAL");
  db.exec(fs.readFileSync(SCHEMA_PATH, "utf-8"));

  const seedBots = [
    { id: "support", name: "Саппорт", script_path: "support_bot.py" },
    { id: "mod", name: "Модератор", script_path: "mod_bot.py" },
  ];

  const insertBot = db.prepare(`
    INSERT INTO bots (id, name, script_path, auto_start)
    VALUES (?, ?, ?, 1)
    ON CONFLICT(id) DO UPDATE SET
      name = excluded.name,
      script_path = excluded.script_path
  `);
  for (const bot of seedBots) {
    insertBot.run(bot.id, bot.name, bot.script_path);
  }

  return db;
}