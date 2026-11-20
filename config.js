import "dotenv/config";

export const CONFIG = {
  DISCORD_TOKEN: process.env.DISCORD_TOKEN,
  GUILD_ID: process.env.GUILD_ID,
  PORT: parseInt(process.env.PORT || "4477", 10),
  DEFAULT_PROVIDER: process.env.DEFAULT_PROVIDER || "openai",
  KEYS: { 
    openai: process.env.OPENAI_API_KEY 
  },
  MODELS: { 
    openai: process.env.OPENAI_MODEL || "gpt-4o-mini" 
  },
};