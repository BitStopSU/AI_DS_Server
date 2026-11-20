import fs from "node:fs";
import path from "node:path";

const LOGS_DIR = path.join(process.cwd(), "logs");
if (!fs.existsSync(LOGS_DIR)) fs.mkdirSync(LOGS_DIR, { recursive: true });

export default {
  id: "logging",
  name: "Логи",
  description: "Аудит действий в канал",
  defaultEnabled: true,

  readLog(botId, lines = 200) {
    const file = path.join(LOGS_DIR, `${botId}.log`);
    if (!fs.existsSync(file)) return "";
    const content = fs.readFileSync(file, "utf-8").split("\n").filter(Boolean);
    return content.slice(-lines).join("\n");
  },

  listLogs() {
    if (!fs.existsSync(LOGS_DIR)) return [];
    return fs.readdirSync(LOGS_DIR).filter(f => f.endsWith(".log"));
  },
};