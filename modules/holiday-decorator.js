import { getDb } from "../db/init.js";
import { getSetting, setSetting } from "../core/settings.js";

export const HOLIDAY_PRESETS = {
  normal: { name: "Обычный вид", prefix: "", suffix: "", schedule: null },
  newyear: { name: "Новый год", prefix: "❄", suffix: "✦", schedule: [["01-01", "01-14"]] },
  valentines: { name: "День святого Валентина", prefix: "💞", suffix: "♡", schedule: [["02-13", "02-15"]] },
  feb23: { name: "День защитника", prefix: "🎖", suffix: "★", schedule: [["02-22", "02-24"]] },
  march8: { name: "8 Марта", prefix: "🌷", suffix: "✿", schedule: [["03-07", "03-10"]] },
  victory: { name: "День Победы", prefix: "🎗", suffix: "★", schedule: [["05-08", "05-10"]] },
  summer: { name: "Лето", prefix: "☀", suffix: "🌊", schedule: [["06-01", "08-31"]] },
  halloween: { name: "Хэллоуин", prefix: "🎃", suffix: "👻", schedule: [["10-30", "11-02"]] },
};

function currentDateKey(date) {
  const month = String(date.getMonth() + 1).padStart(2, "0");
  const day = String(date.getDate()).padStart(2, "0");
  return `${month}-${day}`;
}

function inRange(key, range) {
  return range[0] <= key && key <= range[1];
}

export function presetForDate(date = new Date()) {
  const key = currentDateKey(date);
  for (const [id, preset] of Object.entries(HOLIDAY_PRESETS)) {
    if (preset.schedule?.some(range => inRange(key, range))) return id;
  }
  return "normal";
}

function cleanName(name) {
  return String(name).replace(/^(❄|💞|🎖|🌷|🎗|☀|🎃)\s*[·•ー-]*\s*/, "").replace(/\s*(✦|♡|★|✿|🌊|👻)\s*$/, "").trim();
}

function decorateName(name, preset) {
  const clean = cleanName(name);
  const prefix = preset.prefix ? `${preset.prefix} · ` : "";
  const suffix = preset.suffix ? ` ${preset.suffix}` : "";
  return `${prefix}${clean}${suffix}`.slice(0, 100);
}

async function writeHolidayLog(guild, text) {
  const channelId = getSetting("log_channel_id", "1572636868321873942");
  const channel = guild.channels.cache.get(channelId);
  if (channel?.isTextBased()) await channel.send(text).catch(() => {});
}

export default {
  id: "holiday-decorator",
  name: "Праздничное оформление",
  description: "Меняет имена каналов в праздничных категориях",
  defaultEnabled: true,

  getPresets() {
    return Object.entries(HOLIDAY_PRESETS).map(([id, preset]) => ({ id, name: preset.name }));
  },

  async apply(guild, presetId = presetForDate()) {
    if (!HOLIDAY_PRESETS[presetId]) return { ok: false, error: "Неизвестный праздник" };

    const snapshotRaw = getSetting("holiday_channel_snapshot", "[]");
    let snapshot;
    try { snapshot = JSON.parse(snapshotRaw); } catch { snapshot = []; }

    if (snapshot.length) await this.restore(guild);

    const categoryIds = [
      "1572636867587874995",
      "1572636867789193326",
    ];
    const db = getDb();
    const saved = [];
    const preset = HOLIDAY_PRESETS[presetId];

    for (const categoryId of categoryIds) {
      const category = guild.channels.cache.get(categoryId);
      if (!category) continue;
      for (const channel of guild.channels.cache.filter(item => item.parentId === categoryId).values()) {
        saved.push({ channel_id: channel.id, original_name: channel.name, category_id: categoryId });
        if (presetId !== "normal") {
          await channel.setName(decorateName(channel.name, preset), `Праздничное оформление: ${preset.name}`).catch(() => {});
        }
      }
    }

    setSetting("holiday_channel_snapshot", JSON.stringify(saved));
    setSetting("holiday_active_preset", presetId);
    await writeHolidayLog(
      guild,
      `🎉 Праздничное оформление: **${preset.name}**. Обработано каналов: ${saved.length}.`,
    );
    db.prepare("INSERT OR REPLACE INTO settings (key, value, updated_at) VALUES ('holiday_category_ids', ?, datetime('now'))")
      .run(JSON.stringify(categoryIds));
    return { ok: true, preset: presetId, changed: saved.length };
  },

  async restore(guild) {
    let snapshot;
    try { snapshot = JSON.parse(getSetting("holiday_channel_snapshot", "[]")); } catch { snapshot = []; }
    for (const item of snapshot) {
      const channel = guild.channels.cache.get(item.channel_id);
      if (channel) await channel.setName(item.original_name, "Возврат обычных названий каналов").catch(() => {});
    }
    setSetting("holiday_channel_snapshot", "[]");
    setSetting("holiday_active_preset", "normal");
    await writeHolidayLog(guild, `🔄 Праздничное оформление отключено. Восстановлено имён каналов: ${snapshot.length}.`);
    return { ok: true, restored: snapshot.length };
  },

  getStatus() {
    return {
      activePreset: getSetting("holiday_active_preset", "normal"),
      categoryIds: [
        "1572636867587874995",
        "1572636867789193326",
      ],
    };
  },

  startScheduler(client) {
    setInterval(async () => {
      const guild = client.guilds.cache.get(process.env.GUILD_ID);
      if (!guild) return;
      const active = getSetting("holiday_active_preset", "normal");
      const expected = presetForDate();
      if (active !== expected) await this.apply(guild, expected);
    }, 60 * 60 * 1000);
  },
};
