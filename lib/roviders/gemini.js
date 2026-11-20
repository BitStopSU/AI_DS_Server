import { GoogleGenerativeAI } from "@google/generative-ai";

export async function chat({ model, system, messages, tools, temperature, apiKey }) {
  const genAI = new GoogleGenerativeAI(apiKey);
  const m = genAI.getGenerativeModel({
    model, systemInstruction: system,
    tools: [{ functionDeclarations: tools.map(t => ({
      name: t.function.name,
      description: t.function.description,
      parameters: stripTypes(t.function.parameters),
    })) }],
    generationConfig: { temperature },
  });
  const chat = m.startChat({
    history: messages.slice(0, -1).map(x => ({
      role: x.role === "assistant" ? "model" : "user",
      parts: [{ text: x.content }],
    })),
  });
  const res = await chat.sendMessage(messages[messages.length - 1].content);
  const call = res.response.functionCalls()?.[0];
  if (!call) return { content: res.response.text(), toolCall: null };
  return { content: null, toolCall: { name: call.name, arguments: call.args } };
}

function stripTypes(schema) {
  if (!schema || typeof schema !== "object") return schema;
  const out = { ...schema };
  if (out.type) out.type = out.type.toUpperCase();
  if (out.properties) {
    out.properties = Object.fromEntries(
      Object.entries(out.properties).map(([k, v]) => [k, stripTypes(v)])
    );
  }
  return out;
}