import { askLLM } from "./llm.js";
import { TOOLS } from "./tools.js";
import { executeAction } from "./execute.js";
import { validateAction } from "./validate.js";

export async function webAiAsk({ prompt, guild }) {
  try {
    const reply = await askLLM({ prompt, tools: TOOLS });
    if (!reply.toolCall) return { type: "text", content: reply.content };

    const { name, arguments: args } = reply.toolCall;
    const v = validateAction(name, args, guild);
    if (!v.ok) return { type: "error", content: v.reason };

    return { type: "action", action: name, args };
  } catch (error) {
    // Возвращаем ошибку на сайт
    return { type: "error", content: error.message };
  }
}

export async function webAiConfirm({ action, args, guild }) {
  try {
    return await executeAction(action, args, guild);
  } catch (error) {
    return { ok: false, summary: error.message };
  }
}