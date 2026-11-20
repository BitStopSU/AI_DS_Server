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