"""Standalone Discord bot for tribunal management commands."""
from __future__ import annotations

import os
from pathlib import Path

import aiohttp
import discord
from discord.ext import commands, tasks

import config
import database
from tribunal_features import register_tribunal_commands

TOKEN = os.getenv("BOT_TOKEN")


class TribunalBot(commands.Bot):
    def __init__(self):
        intents = discord.Intents.none()
        intents.guilds = True
        super().__init__(command_prefix="!", intents=intents)

    async def setup_hook(self):
        await self.tree.sync()
        heartbeat.start()


bot = TribunalBot()


@tasks.loop(seconds=60)
async def heartbeat():
    try:
        async with aiohttp.ClientSession() as session:
            await session.post(
                "http://127.0.0.1:4477/api/heartbeat",
                json={"bot_id": "tribunal"},
                timeout=4,
            )
    except Exception:
        pass


@heartbeat.before_loop
async def before_heartbeat():
    await bot.wait_until_ready()


def has_owner(member):
    return any(role.id == config.ROLE_OWNER for role in member.roles)


def can_staff(member, command):
    if has_owner(member) or config.role_can_use_command(member, command):
        return True
    return any(role.id in (config.ROLE_STAFF, config.ROLE_SUPPORT, config.ROLE_MODERATOR) for role in member.roles)


register_tribunal_commands(bot, database, can_staff, has_owner)


@bot.event
async def on_ready():
    print(f"Tribunal bot connected: {bot.user}")


if __name__ == "__main__":
    database.init_db()
    if not TOKEN:
        raise RuntimeError("TRIBUNAL_BOT_TOKEN is not configured in the dashboard")
    bot.run(TOKEN)
