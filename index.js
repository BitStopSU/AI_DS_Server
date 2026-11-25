import { Client, GatewayIntentBits, Events } from "discord.js"; 
import { CONFIG } from "./config.js"; 
import { loadModules, getAllModules, getModule } from "./core/module-manager.js"; 
import { setSetting, getSetting } from "./core/settings.js"; 
import { startWebServer } from "./web/server.js"; 
import { autoStartAll, startWatchdog } from "./core/process-manager.js";
import fs from "node:fs"; 

// Создаем папку logs, если ее нет
if (!fs.existsSync('logs')) fs.mkdirSync('logs');
const logStream = fs.createWriteStream('logs/ai.log', { flags: 'a' });

// Перехватываем console.log, чтобы писать одновременно в консоль и в файл
const originalLog = console.log;
console.log = function(...args) {
  originalLog.apply(console, args);
  logStream.write(`[${new Date().toLocaleTimeString()}] ${args.join(' ')}\n`);
};

const UNVERIFY_ROLE_ID = "1572636865390051351";

const client = new Client({
  intents: [
    GatewayIntentBits.Guilds,
    GatewayIntentBits.GuildMembers,
    GatewayIntentBits.GuildMessages,
    GatewayIntentBits.MessageContent,
  ],
});
const getGuild = () => client.guilds.cache.get(CONFIG.GUILD_ID);

// Keep the local dashboard available even when Discord login is unavailable.
await startWebServer(client, getGuild);

client.on(Events.GuildMemberAdd, async (member) => {
  if (member.user.bot) return;
  const role = member.guild.roles.cache.get(UNVERIFY_ROLE_ID);
  if (!role) {
    console.error(`Роль unverify ${UNVERIFY_ROLE_ID} не найдена`);
    return;
  }
  try {
    await member.roles.add(role, "Автоматическая выдача unverify до прохождения верификации");
  } catch (error) {
    console.error(`Не удалось выдать unverify участнику ${member.id}:`, error.message);
  }
});

client.once(Events.ClientReady, async (c) => {
  console.log("✅ Бот:", c.user.tag); 
  await loadModules();
  for (const moduleInfo of getAllModules()) {
    if (!moduleInfo.enabled) continue;
    const mod = getModule(moduleInfo.id);
    if (mod?.startScheduler) mod.startScheduler(c);
  }
  
  // Настройки по умолчанию (создаются, если их нет в базе)
  const defaults = { 
    request_channel_id: "1572665127528960142", 
    log_channel_id: "1572636868321873942", 
    allowed_role_id: "1572638729879945216",
    default_provider: "openai" 
  };
  
  for (const [k, v] of Object.entries(defaults)) { 
    if (v && !getSetting(k)) setSetting(k, v); 
  }
  if (getSetting("log_channel_id") === "1572665336938102894") {
    setSetting("log_channel_id", "1572636868321873942");
  }
  
  // Автозапуск ботов, у которых стоит галочка
  await autoStartAll(); 
  
  // Запуск слежки за зависшими ботами
  startWatchdog((msg) => {
    const ch = getGuild()?.channels.cache.get(getSetting("log_channel_id"));
    if (ch?.isTextBased?.() && typeof ch.send === "function") {
      ch.send(msg).catch((error) => console.error("Watchdog notification failed:", error.message));
    }
  });
});

client.on(Events.MessageCreate, async (message) => {
  if (message.author.bot) return;
  for (const m of getAllModules()) { 
    if (!m.enabled) continue; 
    const mod = getModule(m.id); 
    if (mod?.onMessage) await mod.onMessage(message, { client }); 
  }
});

if (!CONFIG.DISCORD_TOKEN) {
  console.error("❌ DISCORD_TOKEN не задан в файле .env");
} else {
  client.login(CONFIG.DISCORD_TOKEN).catch((err) => {
    console.error("❌ Не удалось войти в Discord:", err.message);
    console.error("Проверьте DISCORD_TOKEN в .env или создайте новый токен бота в Discord Developer Portal.");
  });
}