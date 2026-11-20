import { spawn } from "node:child_process";
import fs from "node:fs";
import path from "node:path";
import { getDb } from "../db/init.js";
import { decrypt } from "./crypto.js";
import { CONFIG } from "../config.js";

const processes = new Map();
const LOGS_DIR = path.join(process.cwd(), "logs");
if (!fs.existsSync(LOGS_DIR)) fs.mkdirSync(LOGS_DIR, { recursive: true });

function logStream(botId) {
  return fs.createWriteStream(path.join(LOGS_DIR, `${botId}.log`), { flags: "a" });
}

export async function startBot(botId) {
  const db = getDb();
  const bot = db.prepare("SELECT * FROM bots WHERE id = ?").get(botId);
  if (!bot) throw new Error("Бот не найден");
  if (processes.has(botId)) return { ok: false, reason: "Уже запущен" };

  const token = bot.token_encrypted ? decrypt(bot.token_encrypted) : "";
  const child = spawn("python", [bot.script_path], {
    cwd: process.cwd(),
    env: { ...process.env, BOT_TOKEN: token },
    stdio: ["ignore", "pipe", "pipe"],
  });

  processes.set(botId, { child, pid: child.pid });
  db.prepare(`
    UPDATE bots SET status='running', pid=?, last_error=NULL WHERE id=?
  `).run(child.pid, botId);

  const stream = logStream(botId);
  child.stdout.pipe(stream);
  child.stderr.pipe(stream);
  child.stdout.on("data", d => console.log(`[${botId}] ${d}`.trim()));
  child.stderr.on("data", d => console.error(`[${botId}] ${d}`.trim()));

  child.on("exit", (code) => {
    processes.delete(botId);
    const status = code === 0 ? "stopped" : "crashed";
    db.prepare(`
      UPDATE bots SET status=?, pid=NULL, last_error=? WHERE id=?
    `).run(status, code !== 0 ? `Exit code ${code}` : null, botId);
    console.log(`[${botId}] завершён с кодом ${code}`);
  });

  return { ok: true, pid: child.pid };
}

export async function stopBot(botId) {
  const proc = processes.get(botId);
  if (!proc) return { ok: false, reason: "Не запущен" };
  proc.child.kill("SIGTERM");
  setTimeout(() => {
    if (processes.has(botId)) proc.child.kill("SIGKILL");
  }, 5000);
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
    try {
      await startBot(id);
      console.log(`[process-manager] Автозапуск ${id}`);
    } catch (err) {
      console.error(`[process-manager] Не удалось запустить ${id}:`, err.message);
    }
  }
}

// Watchdog: если heartbeat старше 3 минут — перезапуск
export function startWatchdog(notifyFn) {
  setInterval(async () => {
    const db = getDb();
    const bots = db.prepare("SELECT * FROM bots WHERE status = 'running'").all();
    for (const bot of bots) {
      if (!bot.last_heartbeat) continue;
      const age = (Date.now() - new Date(bot.last_heartbeat + "Z").getTime()) / 1000;
      if (age > 180) {
        console.warn(`[watchdog] ${bot.id}: heartbeat ${age}с, перезапуск`);
        await stopBot(bot.id);
        setTimeout(() => startBot(bot.id), 2000);
        if (notifyFn) notifyFn(`⚠️ ${bot.name}: heartbeat отсутствует ${Math.round(age)}с, перезапущен`);
      }
    }
  }, 30_000);
}