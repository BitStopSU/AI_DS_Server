import { ChannelType } from "discord.js";
export async function executeAction(name, args, guild) {
  if (name === "create_channel") { 
    const ch = await guild.channels.create({ name: args.name, type: args.type === "voice" ? ChannelType.GuildVoice : ChannelType.GuildText }); 
    return { ok: true, summary: "Создан <#" + ch.id + ">" }; 
  }
  return { ok: false, summary: "Неизвестно" };
}