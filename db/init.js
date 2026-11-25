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
    { id: "economy", name: "Экономика", script_path: "economy_bot.py" },
    { id: "creative", name: "Креатив", script_path: "creative_bot.py" },
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
  db.prepare("UPDATE bots SET auto_start = 0 WHERE id IN ('economy', 'creative')").run();

  const seedCategories = [
    { id: "owner", name: "Владельцы", sort_order: 0 },
    { id: "staff", name: "Персонал", sort_order: 1 },
    { id: "support", name: "Саппорт", sort_order: 2 },
    { id: "moderator", name: "Модерация", sort_order: 3 },
  ];
  const insertCategory = db.prepare(`
    INSERT INTO role_categories (id, name, sort_order)
    VALUES (?, ?, ?)
    ON CONFLICT(id) DO UPDATE SET name = excluded.name, sort_order = excluded.sort_order
  `);
  for (const category of seedCategories) {
    insertCategory.run(category.id, category.name, category.sort_order);
  }

  const seedAssignments = [
    ["1572638729879945216", "owner"],
    ["1572636864962240701", "staff"],
    ["1572636865448775816", "support"],
    ["1572636865448775818", "moderator"],
  ];
  const insertAssignment = db.prepare(`
    INSERT OR IGNORE INTO role_assignments (role_id, category_id)
    VALUES (?, ?)
  `);
  for (const assignment of seedAssignments) insertAssignment.run(...assignment);

  const seedPermissions = [
    ["1572638729879945216", "verf"],
    ["1572638729879945216", "achen"],
    ["1572638729879945216", "clear"],
    ["1572636865448775816", "verf"],
    ["1572636865448775818", "achen"],
    ["1572636865448775818", "clear"],
    ["1572636864962240701", "staf_profile"],
    ["1572636864962240701", "staf_stats"],
    ["1572636864962240701", "top_veref"],
    ["1572636864962240701", "top_verf"],
    ["1572636864962240701", "stafftable"],
  ];
  const insertPermission = db.prepare(`
    INSERT OR IGNORE INTO role_command_permissions (role_id, command)
    VALUES (?, ?)
  `);
  for (const permission of seedPermissions) insertPermission.run(...permission);

  const categoryPermissions = [
    ["owner", "verf"], ["owner", "achen"], ["owner", "clear"],
    ["owner", "staf_profile"], ["owner", "staf_stats"], ["owner", "top_veref"],
    ["owner", "stafftable"], ["owner", "recruit_post"],
    ["staff", "staf_profile"], ["staff", "staf_stats"], ["staff", "top_veref"], ["staff", "stafftable"], ["staff", "recruit_post"],
    ["support", "verf"],
    ["moderator", "achen"], ["moderator", "clear"],
  ];
  const insertCategoryPermission = db.prepare(`
    INSERT OR IGNORE INTO role_category_permissions (category_id, command)
    VALUES (?, ?)
  `);
  for (const permission of categoryPermissions) insertCategoryPermission.run(...permission);

  const seedPositions = [
    ["1572636865448775816", "Support", "Помощь участникам и верификация"],
    ["1572636865448775818", "Moderator", "Модерация сервера и голосовых каналов"],
  ];
  const insertPosition = db.prepare(`
    INSERT OR IGNORE INTO recruitment_positions (role_id, name, description, active, sort_order)
    VALUES (?, ?, ?, 1, ?)
  `);
  seedPositions.forEach((position, index) => insertPosition.run(position[0], position[1], position[2], index));

  const recruitSettings = [
    ["recruitment_channel_id", "1572636867046670487"],
    ["recruitment_review_support_channel_id", "1572636866681901071"],
    ["recruitment_review_moderator_channel_id", "1572636866681901069"],
    ["recruitment_banner_url", ""],
  ];
  const insertSetting = db.prepare(`
    INSERT INTO settings (key, value)
    VALUES (?, ?)
    ON CONFLICT(key) DO NOTHING
  `);
  recruitSettings.forEach(setting => insertSetting.run(setting[0], setting[1]));

  return db;
}