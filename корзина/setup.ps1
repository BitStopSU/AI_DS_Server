# setup.ps1
$ErrorActionPreference = "Stop"

function Write-File($path, $content) {
    $dir = Split-Path $path -Parent
    if ($dir -and !(Test-Path $dir)) { New-Item -ItemType Directory -Force -Path $dir | Out-Null }
    [System.IO.File]::WriteAllText((Join-Path $PWD $path), $content, [System.Text.Encoding]::UTF8)
    Write-Host "Создан: $path"
}

Write-File "config.js" @"
import "dotenv/config";
export const CONFIG = {
  DISCORD_TOKEN: process.env.DISCORD_TOKEN,
  DISCORD_CLIENT_ID: process.env.DISCORD_CLIENT_ID,
  DISCORD_CLIENT_SECRET: process.env.DISCORD_CLIENT_SECRET,
  GUILD_ID: process.env.GUILD_ID,
  PORT: parseInt(process.env.PORT || "4477", 10),
  SESSION_SECRET: process.env.DASHBOARD_SESSION_SECRET || "change_me",
  REDIRECT_URI: process.env.DASHBOARD_REDIRECT_URI || "http://localhost:4477/dashboard/callback",
  OWNER_IDS: (process.env.OWNER_IDS || "").split(",").map(s => s.trim()).filter(Boolean),
  ENCRYPTION_KEY: process.env.ENCRYPTION_KEY,
  DEFAULT_PROVIDER: process.env.DEFAULT_PROVIDER || "openai",
  KEYS: { openai: process.env.OPENAI_API_KEY, anthropic: process.env.ANTHROPIC_API_KEY, deepseek: process.env.DEEPSEEK_API_KEY, gemini: process.env.GEMINI_API_KEY, ollama: process.env.OLLAMA_URL },
  MODELS: { openai: process.env.OPENAI_MODEL || "gpt-4o-mini", anthropic: process.env.ANTHROPIC_MODEL || "claude-sonnet-4-5", deepseek: process.env.DEEPSEEK_MODEL || "deepseek-chat", gemini: process.env.GEMINI_MODEL || "gemini-2.0-flash", ollama: process.env.OLLAMA_MODEL || "llama3.2" },
};
"@

Write-File "db\schema.sql" @"
CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT NOT NULL, updated_at TEXT NOT NULL DEFAULT (datetime('now')));
CREATE TABLE IF NOT EXISTS modules (id TEXT PRIMARY KEY, enabled INTEGER NOT NULL DEFAULT 0, updated_at TEXT NOT NULL DEFAULT (datetime('now')));
CREATE TABLE IF NOT EXISTS bots (id TEXT PRIMARY KEY, name TEXT NOT NULL, script_path TEXT NOT NULL, token_encrypted TEXT, status TEXT NOT NULL DEFAULT 'stopped', pid INTEGER, auto_start INTEGER DEFAULT 0, restart_limit INTEGER DEFAULT 3, last_heartbeat TEXT, last_error TEXT, created_at TEXT DEFAULT (datetime('now')));
CREATE TABLE IF NOT EXISTS backup_log (id INTEGER PRIMARY KEY AUTOINCREMENT, created_at TEXT NOT NULL DEFAULT (datetime('now')), location TEXT NOT NULL, path TEXT NOT NULL, size_bytes INTEGER, status TEXT NOT NULL DEFAULT 'ok', error TEXT);
"@

Write-File "db\init.js" @"
import Database from "better-sqlite3";
import fs from "node:fs"; import path from "node:path"; import { fileURLToPath } from "node:url";
const __dirname = path.dirname(fileURLToPath(import.meta.url));
const DB_PATH = path.join(__dirname, "..", "data.db"); const SCHEMA_PATH = path.join(__dirname, "schema.sql");
let db;
export function getDb() { if (db) return db; db = new Database(DB_PATH); db.pragma("journal_mode = WAL"); db.exec(fs.readFileSync(SCHEMA_PATH, "utf-8")); return db; }
"@

Write-File "core\settings.js" @"
import { getDb } from "../db/init.js";
export function getSetting(key, defaultValue = null) { const row = getDb().prepare("SELECT value FROM settings WHERE key = ?").get(key); return row ? row.value : defaultValue; }
export function setSetting(key, value) { getDb().prepare("INSERT INTO settings (key, value, updated_at) VALUES (?, ?, datetime('now')) ON CONFLICT(key) DO UPDATE SET value = excluded.value, updated_at = excluded.updated_at").run(key, String(value)); }
export function getAllSettings() { const rows = getDb().prepare("SELECT key, value FROM settings").all(); return Object.fromEntries(rows.map(r => [r.key, r.value])); }
"@

Write-File "core\crypto.js" @"
import crypto from "node:crypto"; import { CONFIG } from "../config.js";
const ALGO = "aes-256-gcm";
function getKey() { if (!CONFIG.ENCRYPTION_KEY) throw new Error("ENCRYPTION_KEY missing"); return Buffer.from(CONFIG.ENCRYPTION_KEY, "hex"); }
export function encrypt(text) { if (!text) return null; const iv = crypto.randomBytes(12); const cipher = crypto.createCipheriv(ALGO, getKey(), iv); const enc = Buffer.concat([cipher.update(text, "utf8"), cipher.final()]); const tag = cipher.getAuthTag(); return `${iv.toString("hex")}:${tag.toString("hex")}:${enc.toString("hex")}`; }
export function decrypt(payload) { if (!payload) return null; const [ivHex, tagHex, dataHex] = payload.split(":"); const decipher = crypto.createDecipheriv(ALGO, getKey(), Buffer.from(ivHex, "hex")); decipher.setAuthTag(Buffer.from(tagHex, "hex")); return Buffer.concat([decipher.update(Buffer.from(dataHex, "hex")), decipher.final()]).toString("utf8"); }
"@

Write-File "core\module-manager.js" @"
import fs from "node:fs"; import path from "node:path"; import { fileURLToPath, pathToFileURL } from "node:url"; import { getDb } from "../db/init.js";
const __dirname = path.dirname(fileURLToPath(import.meta.url)); const MODULES_DIR = path.join(__dirname, "..", "modules"); const registry = new Map();
export async function loadModules() { if (!fs.existsSync(MODULES_DIR)) return; for (const file of fs.readdirSync(MODULES_DIR).filter(f => f.endsWith(".js"))) { try { const mod = await import(pathToFileURL(path.join(MODULES_DIR, file)).href); const m = mod.default; if (!m?.id) continue; registry.set(m.id, m); const db = getDb(); const exists = db.prepare("SELECT id FROM modules WHERE id = ?").get(m.id); if (!exists) db.prepare("INSERT INTO modules (id, enabled) VALUES (?, ?)").run(m.id, m.defaultEnabled ? 1 : 0); } catch (err) { console.error(err); } } }
export function isEnabled(id) { const row = getDb().prepare("SELECT enabled FROM modules WHERE id = ?").get(id); return !!row?.enabled; }
export function setEnabled(id, enabled) { getDb().prepare("INSERT INTO modules (id, enabled, updated_at) VALUES (?, ?, datetime('now')) ON CONFLICT(id) DO UPDATE SET enabled = excluded.enabled, updated_at = excluded.updated_at").run(id, enabled ? 1 : 0); }
export function getAllModules() { const rows = getDb().prepare("SELECT id, enabled FROM modules").all(); const stateMap = Object.fromEntries(rows.map(r => [r.id, !!r.enabled])); return [...registry.values()].map(m => ({ id: m.id, name: m.name || m.id, description: m.description || "", enabled: stateMap[m.id] ?? !!m.defaultEnabled })); }
export function getModule(id) { return registry.get(id) || null; }
"@

Write-File "lib\providers\index.js" @"
import * as openai from "./openai.js"; import * as anthropic from "./anthropic.js"; import * as deepseek from "./deepseek.js"; import * as gemini from "./gemini.js"; import * as ollama from "./ollama.js"; import { CONFIG } from "../../config.js";
const REGISTRY = { openai, anthropic, deepseek, gemini, ollama };
export function listProviders() { return Object.keys(REGISTRY).filter(k => CONFIG.KEYS[k]); }
export async function chat({ provider, model, system, messages, tools, temperature = 0.2 }) { const p = REGISTRY[provider]; if (!p) throw new Error("Провайдер не найден"); return p.chat({ model: model || CONFIG.MODELS[provider], system, messages, tools, temperature, apiKey: CONFIG.KEYS[provider] }); }
"@

Write-File "lib\providers\openai.js" @"
import OpenAI from "openai";
export async function chat({ model, system, messages, tools, temperature, apiKey }) { const client = new OpenAI({ apiKey }); const res = await client.chat.completions.create({ model, messages: [{ role: "system", content: system }, ...messages], tools, tool_choice: "auto", temperature }); const m = res.choices[0].message; if (!m.tool_calls?.length) return { content: m.content, toolCall: null }; const t = m.tool_calls[0]; return { content: null, toolCall: { name: t.function.name, arguments: JSON.parse(t.function.arguments || "{}") } }; }
"@

# Добавляем заглушки для остальных провайдеров, чтобы не падало
foreach ($p in @("anthropic", "deepseek", "gemini", "ollama")) {
    Write-File "lib\providers\$p.js" "export async function chat() { throw new Error('Провайдер $p пока не настроен'); }"
}

Write-File "lib\tools.js" @"
export const TOOLS = [
  { type: "function", function: { name: "create_channel", description: "Создать канал", parameters: { type: "object", properties: { name: { type: "string" }, type: { type: "string", enum: ["text", "voice"] } }, required: ["name", "type"] } } },
];
export const DANGEROUS = new Set();
"@

Write-File "lib\validate.js" @"
export function validateAction(name, args, guild) {
  if (name === "create_channel" && (!args.name || args.name.length < 2)) return { ok: false, reason: "Имя 2-100" };
  return { ok: true };
}
"@

Write-File "lib\execute.js" @"
import { ChannelType } from "discord.js";
export async function executeAction(name, args, guild) {
  if (name === "create_channel") { const ch = await guild.channels.create({ name: args.name, type: args.type === "voice" ? ChannelType.GuildVoice : ChannelType.GuildText }); return { ok: true, summary: "Создан <#" + ch.id + ">" }; }
  return { ok: false, summary: "Неизвестно" };
}
"@

Write-File "lib\logger.js" @"
export async function logAction(guild, executor, actionName, args, result) { console.log("Action:", actionName, result); }
"@

Write-File "lib\llm.js" @"
import { chat } from "./providers/index.js"; import { getSetting } from "../core/settings.js";
const SYSTEM_PROMPT = "Ты AI-ассистент Discord. Вызывай функции.";
export async function askLLM({ prompt, history = [], provider, model, tools }) { const p = provider || getSetting("default_provider", "openai"); return chat({ provider: p, model, system: SYSTEM_PROMPT, messages: [...history, { role: "user", content: prompt }], tools }); }
"@

Write-File "modules\discord-ai-chat.js" @"
import { askLLM } from "../lib/llm.js"; import { TOOLS } from "../lib/tools.js"; import { validateAction } from "../lib/validate.js"; import { executeAction } from "../lib/execute.js"; import { getSetting } from "../core/settings.js";
export default {
  id: "discord-ai-chat", name: "AI-чат в Discord", defaultEnabled: false,
  async onMessage(message) {
    if (message.author.bot) return; if (message.channelId !== getSetting("request_channel_id")) return;
    const reply = await askLLM({ prompt: message.content, tools: TOOLS });
    if (!reply.toolCall) { if (reply.content) await message.reply(reply.content); return; }
    const { name, arguments: args } = reply.toolCall; const v = validateAction(name, args, message.guild);
    if (!v.ok) return message.reply(v.reason);
    const result = await executeAction(name, args, message.guild); await message.reply(result.summary);
  }
};
"@

Write-File "web\server.js" @"
import express from "express"; import { CONFIG } from "../config.js";
export async function startWebServer(client, getGuild) {
  const app = express(); app.use(express.json());
  app.get("/api/status", (req, res) => res.json({ ok: true, bot: client.user.tag }));
  app.listen(CONFIG.PORT, () => console.log("🌐 Панель: http://localhost:" + CONFIG.PORT));
}
"@

Write-File "core\process-manager.js" @"
export async function autoStartAll() { console.log("Auto-start bots..."); }
export function startWatchdog(fn) { console.log("Watchdog started"); }
"@

Write-File "index.js" @"
import { Client, GatewayIntentBits, Events } from "discord.js"; import { CONFIG } from "./config.js"; import { loadModules, getAllModules, getModule } from "./core/module-manager.js"; import { setSetting, getSetting } from "./core/settings.js"; import { startWebServer } from "./web/server.js"; import { autoStartAll, startWatchdog } from "./core/process-manager.js";
const client = new Client({ intents: [GatewayIntentBits.Guilds, GatewayIntentBits.GuildMessages, GatewayIntentBits.MessageContent] });
function getGuild() { return client.guilds.cache.get(CONFIG.GUILD_ID); }
client.once(Events.ClientReady, async (c) => {
  console.log("✅ Бот:", c.user.tag); await loadModules();
  const defaults = { request_channel_id: "1572665127528960142", log_channel_id: "1572665336938102894", allowed_role_id: "1572638729879945216", default_provider: CONFIG.DEFAULT_PROVIDER };
  for (const [k, v] of Object.entries(defaults)) { if (v && !getSetting(k)) setSetting(k, v); }
  await autoStartAll(); startWatchdog(() => {});
  await startWebServer(client, getGuild);
});
client.on(Events.MessageCreate, async (message) => {
  if (message.author.bot) return;
  for (const m of getAllModules()) { if (!m.enabled) continue; const mod = getModule(m.id); if (mod?.onMessage) await mod.onMessage(message, { client }); }
});
client.login(CONFIG.DISCORD_TOKEN);
"@

Write-Host "✅ Все файлы успешно созданы!"
Write-Host "Теперь запусти: npm start"