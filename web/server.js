import express from "express"; 
import { CONFIG } from "../config.js";
import path from "node:path";
import fs from "node:fs";
import { fileURLToPath } from "node:url";
import multer from "multer";
import { getAllModules, setEnabled } from "../core/module-manager.js";
import { getDb } from "../db/init.js";
import * as processManager from "../core/process-manager.js";
import { encrypt } from "../core/crypto.js";
import * as webAi from "../lib/web-ai-chat.js";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const BOTS_DIR = path.join(process.cwd(), "bots");
if (!fs.existsSync(BOTS_DIR)) fs.mkdirSync(BOTS_DIR, { recursive: true });

// Настройка сохранения загруженных файлов
const storage = multer.diskStorage({
  destination: (req, file, cb) => cb(null, BOTS_DIR),
  filename: (req, file, cb) => cb(null, file.originalname)
});
const upload = multer({ storage });

export async function startWebServer(client, getGuild) {
  const app = express(); 
  app.use(express.json());
  app.use(express.static(path.join(__dirname, "../public")));

  app.get("/", (req, res) => res.sendFile(path.join(__dirname, "../public/preview.html")));

  // МОДУЛИ
  app.get("/api/modules", (req, res) => res.json(getAllModules()));
  app.post("/api/modules/:id", (req, res) => { setEnabled(req.params.id, !!req.body.enabled); res.json({ ok: true }); });

  // НАСТРОЙКИ
  app.get("/api/settings", (req, res) => {
    const rows = getDb().prepare("SELECT key, value FROM settings").all();
    res.json(Object.fromEntries(rows.map(r => [r.key, r.value])));
  });
  app.post("/api/settings", (req, res) => {
    const stmt = getDb().prepare("INSERT INTO settings (key, value, updated_at) VALUES (?, ?, datetime('now')) ON CONFLICT(key) DO UPDATE SET value = excluded.value");
    for (const [k, v] of Object.entries(req.body)) stmt.run(k, String(v));
    res.json({ ok: true });
  });

  // Роли и привязка команд
  app.get("/api/role-manager", (req, res) => {
    const guild = getGuild();
    const roles = guild
      ? [...guild.roles.cache.values()]
          .filter(role => role.id !== guild.id)
          .sort((a, b) => b.position - a.position)
          .map(role => ({ id: role.id, name: role.name, color: role.hexColor, position: role.position }))
      : [];
    const db = getDb();
    res.json({
      roles,
      categories: db.prepare("SELECT id, name, sort_order FROM role_categories ORDER BY sort_order, name").all(),
      assignments: db.prepare("SELECT role_id, category_id FROM role_assignments").all(),
      permissions: db.prepare("SELECT role_id, command FROM role_command_permissions").all(),
    });
  });

  app.post("/api/role-manager", (req, res) => {
    try {
      const db = getDb();
      const categories = Array.isArray(req.body.categories) ? req.body.categories : [];
      const assignments = Array.isArray(req.body.assignments) ? req.body.assignments : [];
      const permissions = Array.isArray(req.body.permissions) ? req.body.permissions : [];

      const transaction = db.transaction(() => {
        db.prepare("DELETE FROM role_assignments").run();
        db.prepare("DELETE FROM role_command_permissions").run();

        const upsertCategory = db.prepare(`
          INSERT INTO role_categories (id, name, sort_order)
          VALUES (?, ?, ?)
          ON CONFLICT(id) DO UPDATE SET name = excluded.name, sort_order = excluded.sort_order
        `);
        categories.forEach((category, index) => {
          const id = String(category.id || "").trim();
          const name = String(category.name || "").trim();
          if (id && name) upsertCategory.run(id, name, Number.isFinite(category.sort_order) ? category.sort_order : index);
        });
        const keptCategoryIds = categories.map(category => String(category.id || "").trim()).filter(Boolean);
        const existingCategories = db.prepare("SELECT id FROM role_categories").all();
        const deleteCategory = db.prepare("DELETE FROM role_categories WHERE id = ?");
        existingCategories.forEach(category => {
          if (!keptCategoryIds.includes(category.id)) deleteCategory.run(category.id);
        });

        const insertAssignment = db.prepare(`
          INSERT OR REPLACE INTO role_assignments (role_id, category_id, updated_at)
          VALUES (?, ?, datetime('now'))
        `);
        assignments.forEach(item => {
          if (item.role_id && item.category_id) insertAssignment.run(String(item.role_id), String(item.category_id));
        });

        const insertPermission = db.prepare(`
          INSERT OR IGNORE INTO role_command_permissions (role_id, command)
          VALUES (?, ?)
        `);
        permissions.forEach(item => {
          if (item.role_id && item.command) insertPermission.run(String(item.role_id), String(item.command));
        });
      });
      transaction();
      res.json({ ok: true });
    } catch (error) {
      res.status(400).json({ error: error.message });
    }
  });

  // ЛОГИ
  app.get("/api/logs/:botId", (req, res) => {
    const logPath = path.join(process.cwd(), "logs", `${req.params.botId}.log`);
    res.json({ content: fs.existsSync(logPath) ? fs.readFileSync(logPath, "utf-8").split("\n").slice(-50).join("\n") : "Логов нет..." });
  });

  // HEARTBEAT
  app.post("/api/heartbeat", (req, res) => {
    const { bot_id } = req.body;
    if (bot_id) getDb().prepare("UPDATE bots SET last_heartbeat = datetime('now') WHERE id = ?").run(bot_id);
    res.json({ ok: true });
  });

  // БОТЫ
  app.get("/api/bots", (req, res) => res.json(getDb().prepare(
    "SELECT id, name, script_path, status, pid, auto_start, last_error, token_encrypted IS NOT NULL AS has_token FROM bots"
  ).all()));
  
  // Загрузка файла и добавление бота
  app.post("/api/bots/upload", upload.single("script"), (req, res) => {
    try {
      const { id, name, token, auto_start } = req.body;
      const existing = getDb().prepare("SELECT * FROM bots WHERE id = ?").get(id);
      const script_path = req.file ? req.file.filename : existing?.script_path;
      
      if (!id || !name || !script_path) return res.status(400).json({ error: "Заполните все поля и прикрепите файл" });

      const token_encrypted = token ? encrypt(token) : existing?.token_encrypted;
      getDb().prepare(`
        INSERT INTO bots (id, name, script_path, token_encrypted, auto_start)
        VALUES (?, ?, ?, ?, ?)
        ON CONFLICT(id) DO UPDATE SET
          name = excluded.name,
          script_path = excluded.script_path,
          token_encrypted = excluded.token_encrypted,
          auto_start = excluded.auto_start
      `).run(id, name, script_path, token_encrypted, auto_start === 'true' ? 1 : 0);
      
      res.json({ ok: true });
    } catch (e) { res.status(500).json({ error: e.message }); }
  });

  app.post("/api/bots/:id/start", async (req, res) => { try { res.json(await processManager.startBot(req.params.id)); } catch (e) { res.status(500).json({ error: e.message }); } });
  app.post("/api/bots/:id/stop", async (req, res) => res.json(await processManager.stopBot(req.params.id)));
  app.post("/api/bots/:id/restart", async (req, res) => res.json(await processManager.restartBot(req.params.id)));

  // AI-ЧАТ
  app.post("/api/ai/ask", async (req, res) => {
    const guild = getGuild();
    if (!guild) return res.status(400).json({ error: "Гильдия не найдена" });
    try { res.json(await webAi.webAiAsk({ prompt: req.body.prompt, guild })); } catch (e) { res.status(500).json({ error: e.message }); }
  });
  app.post("/api/ai/confirm", async (req, res) => {
    const guild = getGuild();
    try { res.json(await webAi.webAiConfirm({ action: req.body.action, args: req.body.args, guild })); } catch (e) { res.status(500).json({ error: e.message }); }
  });

  app.listen(CONFIG.PORT, () => console.log("🌐 Панель: http://localhost:" + CONFIG.PORT));
}