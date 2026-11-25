import { spawn } from "node:child_process";
import fs from "node:fs";
import path from "node:path";
import { getDb } from "../db/init.js";
import { decrypt } from "./crypto.js";

const processes = new Map();
const LOGS_DIR = path.join(process.cwd(), "logs");
if (!fs.existsSync(LOGS_DIR)) fs.mkdirSync(LOGS_DIR, { recursive: true });

export async function startBot(botId) {
  const db = getDb();
  const bot = db.prepare("SELECT * FROM bots WHERE id = ?").get(botId);
  if (!bot) throw new Error("Бот не найден в БД");
  if (processes.has(botId)) return { ok: false, reason: "Уже запущен" };

  const envTokenNames = { support: "SUPPORT_BOT_TOKEN", mod: "MOD_BOT_TOKEN", economy: "ECONOMY_BOT_TOKEN", creative: "CREATIVE_BOT_TOKEN", tribunal: "TRIBUNAL_BOT_TOKEN" };
  const envToken = process.env[envTokenNames[botId]];
  const token = bot.token_encrypted ? decrypt(bot.token_encrypted) : envToken;
  if (!token) {
    db.prepare("UPDATE bots SET status='stopped', pid=NULL, last_error=? WHERE id=?")
      .run("Токен бота не настроен", botId);
    return { ok: false, reason: "Токен бота не настроен" };
  }
  const scriptPath = path.join(process.cwd(), "bots", bot.script_path);
  
  const child = spawn("python", [scriptPath], {
    cwd: process.cwd(),
    env: { ...process.env, BOT_TOKEN: token || "" },
    stdio: ["ignore", "pipe", "pipe"],
  });

  processes.set(botId, { child, pid: child.pid });
  db.prepare("UPDATE bots SET status='running', pid=?, last_heartbeat=NULL, last_error=NULL WHERE id=?").run(child.pid, botId);

  const stream = fs.createWriteStream(path.join(LOGS_DIR, `${botId}.log`), { flags: "a" });
  child.stdout.pipe(stream);
  child.stderr.pipe(stream);

  child.on("error", (err) => {
    processes.delete(botId);
    db.prepare("UPDATE bots SET status='crashed', pid=NULL, last_error=? WHERE id=?")
      .run(err.message, botId);
  });
  
  console.log(`[${botId}] Запущен, PID: ${child.pid}`);

  child.on("exit", (code) => {
    processes.delete(botId);
    const status = code === 0 ? "stopped" : "crashed";
    db.prepare("UPDATE bots SET status=?, pid=NULL, last_error=? WHERE id=?").run(status, code !== 0 ? `Exit code ${code}` : null, botId);
    console.log(`[${botId}] Остановлен (код ${code})`);
  });
  return { ok: true, pid: child.pid };
}

export async function stopBot(botId) {
  const proc = processes.get(botId);
  if (!proc) return { ok: false, reason: "Не запущен" };
  proc.child.kill("SIGTERM");
  return { ok: true };
}

export async function restartBot(botId) {
  await stopBot(botId);
  await new Promise(r => setTimeout(r, 1000));
  return startBot(botId);
}

export function getStatus(botId) {
  return getDb().prepare("SELECT * FROM bots WHERE id = ?").get(botId);
}

export async function autoStartAll() {
  const bots = getDb().prepare("SELECT id FROM bots WHERE auto_start = 1").all();
  for (const { id } of bots) {
    try { await startBot(id); } catch (err) { console.error(`Автозапуск ${id} упал:`, err.message); }
  }
}

// Слежка за heartbeat (если Python-бот будет отправлять его)
export function startWatchdog(notifyFn) {
  setInterval(async () => {
    const db = getDb();
    const bots = db.prepare("SELECT * FROM bots WHERE status = 'running'").all();
    for (const bot of bots) {
      if (!bot.last_heartbeat) continue;
      const age = (Date.now() - new Date(bot.last_heartbeat + "Z").getTime()) / 1000;
      if (age > 180) {
        console.warn(`[watchdog] ${bot.id} завис, перезапуск...`);
        await restartBot(bot.id);
        if (notifyFn) notifyFn(`⚠️ Бот ${bot.name} завис и был перезапущен.`);
      }
    }
  }, 30_000);
  console.log("Watchdog запущен");
}