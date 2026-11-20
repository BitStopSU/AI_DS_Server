import fs from "node:fs";
import path from "node:path";
import { getDb } from "../db/init.js";
import { CONFIG } from "../config.js";
import { getSetting } from "../core/settings.js";
import discordBackup from "discord-backup-v2";

const BACKUP_DIR = path.join(process.cwd(), "backups");
if (!fs.existsSync(BACKUP_DIR)) fs.mkdirSync(BACKUP_DIR, { recursive: true });

let backupClient;

async function getClient() {
  if (backupClient) return backupClient;
  backupClient = await discordBackup.createBackupClient({
    storage: "file",
    storagePath: BACKUP_DIR,
  });
  return backupClient;
}

export default {
  id: "backups",
  name: "Бекапы",
  description: "Ежедневно в 03:00 + Яндекс.Диск",
  defaultEnabled: true,

  async create(guild, { upload = false } = {}) {
    const db = getDb();
    try {
      const client = await getClient();
      const data = await client.create(guild, { maxMessagesPerChannel: 0 });
      const filePath = path.join(BACKUP_DIR, `${data.id}.json`);
      const size = fs.existsSync(filePath) ? fs.statSync(filePath).size : null;

      let location = "local";
      if (upload) {
        const token = getSetting("yandex_token");
        if (token) {
          try {
            const { default: YandexDisk } = await import("yandisk");
            const disk = new YandexDisk(token, getSetting("yandex_path", "/DiscordBackups"));
            await disk.uploadFile(`${data.id}.json`, fs.readFileSync(filePath));
            location = "yandex";
          } catch (err) {
            console.error("[backups] Ошибка загрузки на Яндекс.Диск:", err.message);
          }
        }
      }

      db.prepare("INSERT INTO backup_log (location, path, size_bytes, status) VALUES (?, ?, ?, 'ok')")
        .run(location, data.id, size);
      return { ok: true, id: data.id, location, size };
    } catch (err) {
      db.prepare("INSERT INTO backup_log (location, path, status, error) VALUES ('local', '', 'error', ?)")
        .run(err.message);
      return { ok: false, error: err.message };
    }
  },

  startScheduler(client) {
    // проверка раз в минуту, не пора ли делать бекап
    setInterval(async () => {
      const now = new Date();
      if (now.getHours() !== 3 || now.getMinutes() !== 0) return;
      const guild = client.guilds.cache.get(CONFIG.GUILD_ID);
      if (!guild) return;
      console.log("[backups] Ежедневный бекап");
      await this.create(guild, { upload: !!getSetting("yandex_token") });
    }, 60_000);
  },

  getHistory(limit = 30) {
    return getDb().prepare("SELECT * FROM backup_log ORDER BY id DESC LIMIT ?").all(limit);
  },
};