export async function chat({ model, system, messages, tools, temperature, apiKey: url }) {
  const res = await fetch(`${url}/api/chat`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      model,
      messages: [{ role: "system", content: system }, ...messages],
      tools, stream: false, options: { temperature },
    }),
  });
  const data = await res.json();
  const m = data.message;
  if (!m.tool_calls?.length) return { content: m.content, toolCall: null };
  const t = m.tool_calls[0];
  return { content: null, toolCall: {
    name: t.function.name,
    arguments: typeof t.function.arguments === "string" ? JSON.parse(t.function.arguments) : t.function.arguments,
  } };
}