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

const client = new Client({ intents: [GatewayIntentBits.Guilds, GatewayIntentBits.GuildMessages, GatewayIntentBits.MessageContent] });
const getGuild = () => client.guilds.cache.get(CONFIG.GUILD_ID);

client.once(Events.ClientReady, async (c) => {
  console.log("✅ Бот:", c.user.tag); 
  await loadModules();
  
  // Настройки по умолчанию (создаются, если их нет в базе)
  const defaults = { 
    request_channel_id: "1572665127528960142", 
    log_channel_id: "1572665336938102894", 
    allowed_role_id: "1572638729879945216",
    default_provider: "openai" 
  };
  
  for (const [k, v] of Object.entries(defaults)) { 
    if (v && !getSetting(k)) setSetting(k, v); 
  }
  
  // Автозапуск ботов, у которых стоит галочка
  await autoStartAll(); 
  
  // Запуск слежки за зависшими ботами
  startWatchdog((msg) => {
    const ch = getGuild()?.channels.cache.get(getSetting("log_channel_id"));
    if (ch) ch.send(msg).catch(()=>{});
  });
  
  // Запуск веб-панели
  await startWebServer(client, getGuild);
});

client.on(Events.MessageCreate, async (message) => {
  if (message.author.bot) return;
  for (const m of getAllModules()) { 
    if (!m.enabled) continue; 
    const mod = getModule(m.id); 
    if (mod?.onMessage) await mod.onMessage(message, { client }); 
  }
});

client.login(CONFIG.DISCORD_TOKEN);