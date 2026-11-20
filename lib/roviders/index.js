import * as openai from "./openai.js";
import * as anthropic from "./anthropic.js";
import * as deepseek from "./deepseek.js";
import * as gemini from "./gemini.js";
import * as ollama from "./ollama.js";
import { CONFIG } from "../../config.js";

const REGISTRY = { openai, anthropic, deepseek, gemini, ollama };

export function listProviders() {
  return Object.keys(REGISTRY).filter(k => CONFIG.KEYS[k]);
}

export async function chat({ provider, model, system, messages, tools, temperature = 0.2 }) {
  const p = REGISTRY[provider];
  if (!p) throw new Error(`Провайдер ${provider} не найден`);
  return p.chat({
    model: model || CONFIG.MODELS[provider],
    system, messages, tools, temperature,
    apiKey: CONFIG.KEYS[provider],
  });
}