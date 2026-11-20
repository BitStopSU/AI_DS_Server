import { askLLM } from "../lib/llm.js";
import { TOOLS, DANGEROUS } from "../lib/tools.js";
import { validateAction } from "../lib/validate.js";
import { executeAction } from "../lib/execute.js";
import { logAction } from "../lib/logger.js";
import { getDb } from "../db/init.js";

export default {
  id: "web-ai-chat",
  name: "AI-окно на сайте",
  description: "Чат с AI в веб-панели",
  defaultEnabled: true,

  async ask({ prompt, provider, guild }) {
    const reply = await askLLM({ prompt, provider, tools: TOOLS });

    // сохраняем историю
    const db = getDb();
    db.prepare("INSERT INTO chat_history (role, content, provider) VALUES (?, ?, ?)")
      .run("user", prompt, provider || null);

    if (!reply.toolCall) {
      if (reply.content) {
        db.prepare("INSERT INTO chat_history (role, content, provider) VALUES (?, ?, ?)")
          .run("assistant", reply.content, provider || null);
      }
      return { type: "text", content: reply.content };
    }

    const { name, arguments: args } = reply.toolCall;
    const v = validateAction(name, args, guild);
    if (!v.ok) return { type: "error", content: v.reason };

    return {
      type: "action",
      action: name,
      args,
      dangerous: DANGEROUS.has(name),
    };
  },

  async confirm({ action, args, guild, executor }) {
    const result = await executeAction(action, args, guild);
    await logAction(guild, executor, action, args, result);
    const db = getDb();
    db.prepare("INSERT INTO chat_history (role, content, action_name) VALUES (?, ?, ?)")
      .run("assistant", result.summary || "", action);
    return result;
  },

  getHistory(limit = 50) {
    return getDb().prepare("SELECT * FROM chat_history ORDER BY id DESC LIMIT ?").all(limit).reverse();
  },
};