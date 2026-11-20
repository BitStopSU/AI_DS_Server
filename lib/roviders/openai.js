import OpenAI from "openai";

export async function chat({ model, system, messages, tools, temperature, apiKey }) {
  const client = new OpenAI({ apiKey });
  const res = await client.chat.completions.create({
    model,
    messages: [{ role: "system", content: system }, ...messages],
    tools, tool_choice: "auto", temperature,
  });
  const m = res.choices[0].message;
  if (!m.tool_calls?.length) return { content: m.content, toolCall: null };
  const t = m.tool_calls[0];
  return { content: null, toolCall: { name: t.function.name, arguments: JSON.parse(t.function.arguments || "{}") } };
}