import Anthropic from "@anthropic-ai/sdk";

export async function chat({ model, system, messages, tools, temperature, apiKey }) {
  const client = new Anthropic({ apiKey });
  const res = await client.messages.create({
    model, system,
    messages: messages.map(m => ({ role: m.role, content: m.content })),
    tools: tools.map(t => ({
      name: t.function.name,
      description: t.function.description,
      input_schema: t.function.parameters,
    })),
    temperature, max_tokens: 1024,
  });
  const toolBlock = res.content.find(b => b.type === "tool_use");
  if (!toolBlock) {
    const text = res.content.filter(b => b.type === "text").map(b => b.text).join("\n");
    return { content: text || null, toolCall: null };
  }
  return { content: null, toolCall: { name: toolBlock.name, arguments: toolBlock.input } };
}