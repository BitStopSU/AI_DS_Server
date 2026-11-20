import { askLLM } from "../lib/llm.js"; import { TOOLS } from "../lib/tools.js"; import { validateAction } from "../lib/validate.js"; import { executeAction } from "../lib/execute.js"; import { getSetting } from "../core/settings.js";
export default {
  id: "discord-ai-chat", name: "AI-чат в Discord", defaultEnabled: true,
  async onMessage(message) {
    if (message.author.bot) return; 
    if (message.channelId !== getSetting("request_channel_id")) return;
    
    const reply = await askLLM({ prompt: message.content, tools: TOOLS });
    if (!reply.toolCall) { if (reply.content) await message.reply(reply.content); return; }
    
    const { name, arguments: args } = reply.toolCall; 
    const v = validateAction(name, args, message.guild);
    if (!v.ok) return message.reply(v.reason);
    
    const result = await executeAction(name, args, message.guild); 
    await message.reply(result.summary);
  }
};