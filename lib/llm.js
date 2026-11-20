import OpenAI from "openai";
import Anthropic from "@anthropic-ai/sdk";
import { GoogleGenerativeAI } from "@google/generative-ai";
import { getSetting } from "../core/settings.js";

const SYSTEM_PROMPT = "Ты AI-ассистент Discord. Вызывай функции.";

export async function askLLM({ prompt, history = [], tools }) {
  const provider = getSetting("default_provider", "openai");
  const messages = [...history, { role: "user", content: prompt }];

  // 1. OPENAI и DEEPSEEK
  if (provider === "openai" || provider === "deepseek") {
    const apiKey = getSetting(`${provider}_key`, "");
    if (!apiKey) throw new Error(`Ключ для ${provider} не задан в настройках!`);
    
    const client = new OpenAI({ 
      apiKey: apiKey,
      baseURL: provider === "deepseek" ? "https://api.deepseek.com/v1" : undefined
    });
    
    const res = await client.chat.completions.create({
      model: provider === "openai" ? "gpt-4o-mini" : "deepseek-chat",
      messages: [{ role: "system", content: SYSTEM_PROMPT }, ...messages],
      tools, tool_choice: "auto", temperature: 0.2
    });
    
    const m = res.choices[0].message;
    if (!m.tool_calls?.length) return { content: m.content, toolCall: null };
    const t = m.tool_calls[0];
    return { content: null, toolCall: { name: t.function.name, arguments: JSON.parse(t.function.arguments || "{}") } };
  }

  // 2. ANTHROPIC (CLAUDE)
  if (provider === "anthropic") {
    const apiKey = getSetting("anthropic_key", "");
    if (!apiKey) throw new Error("Ключ Anthropic не задан!");
    
    const client = new Anthropic({ apiKey });
    const res = await client.messages.create({
      model: "claude-3-5-sonnet-20241022",
      system: SYSTEM_PROMPT,
      messages: messages,
      tools: tools.map(t => ({ name: t.function.name, description: t.function.description, input_schema: t.function.parameters })),
      max_tokens: 1024, temperature: 0.2
    });

    const toolBlock = res.content.find(b => b.type === "tool_use");
    if (!toolBlock) {
      const text = res.content.filter(b => b.type === "text").map(b => b.text).join("\n");
      return { content: text || null, toolCall: null };
    }
    return { content: null, toolCall: { name: toolBlock.name, arguments: toolBlock.input } };
  }

  // 3. GOOGLE GEMINI
  if (provider === "gemini") {
    const apiKey = getSetting("gemini_key", "");
    if (!apiKey) throw new Error("Ключ Gemini не задан!");
    
    const genAI = new GoogleGenerativeAI(apiKey);
    const model = genAI.getGenerativeModel({
      model: "gemini-1.5-flash",
      systemInstruction: SYSTEM_PROMPT,
      tools: [{ functionDeclarations: tools.map(t => ({
        name: t.function.name,
        description: t.function.description,
        parameters: stripTypes(t.function.parameters)
      })) }]
    });

    const chat = model.startChat({
      history: history.map(x => ({ role: x.role === "assistant" ? "model" : "user", parts: [{ text: x.content }] }))
    });
    
    const res = await chat.sendMessage(prompt);
    const call = res.response.functionCalls()?.[0];
    if (!call) return { content: res.response.text(), toolCall: null };
    return { content: null, toolCall: { name: call.name, arguments: call.args } };
  }

  throw new Error(`Провайдер ${provider} не поддерживается.`);
}

// Вспомогательная функция для Gemini (она не любит нижний регистр в типах)
function stripTypes(schema) {
  if (!schema || typeof schema !== "object") return schema;
  const out = { ...schema };
  if (out.type) out.type = out.type.toUpperCase();
  if (out.properties) {
    out.properties = Object.fromEntries(Object.entries(out.properties).map(([k, v]) => [k, stripTypes(v)]));
  }
  return out;
}