import discord
from discord import app_commands
from discord.ext import commands, tasks
from datetime import timedelta
import database
from config import *
import os
import aiohttp
import asyncio

database.init_db()

# Читаем токен, который передает панель
TOKEN = os.environ.get("BOT_TOKEN")
if not TOKEN:
    raise RuntimeError("BOT_TOKEN не задан! Запустите через панель.")

class Bot(commands.Bot):
    def __init__(self):
        super().__init__(command_prefix="!", intents=discord.Intents.all())
    async def setup_hook(self):
        await self.tree.sync()
        track_voice_time.start()
        send_heartbeat.start()

bot = Bot()

@tasks.loop(seconds=60)
async def send_heartbeat():
    try:
        async with aiohttp.ClientSession() as session:
            await session.post("http://localhost:4477/api/heartbeat", json={"bot_id": "mod"})
    except Exception:
        pass

@send_heartbeat.before_loop
async def before_heartbeat():
    await bot.wait_until_ready()

def has_mod(member): return any(r.id == ROLE_MODERATOR for r in member.roles)
def allowed_channel(interaction): return interaction.channel_id in CHANNELS_ALLOWED

def log_to_db(guild_id, user_id, mod_id, ptype, reason):
    conn = database.get_db(); c = conn.cursor()
    c.execute("INSERT INTO punishments (guild_id,user_id,moderator_id,type,reason) VALUES (?,?,?,?,?)", (guild_id, user_id, mod_id, ptype, reason))
    field = {"warn":"warns","mute":"mutes","kick":"kicks","ban":"bans"}[ptype]
    c.execute("INSERT OR IGNORE INTO staff_profiles (user_id, guild_id, role_type) VALUES (?,?, 'moderator')", (mod_id, guild_id))
    c.execute(f"UPDATE staff_profiles SET {field} = {field} + 1 WHERE user_id=?", (mod_id,))
    conn.commit(); conn.close()

@tasks.loop(minutes=1)
async def track_voice_time():
    channel = bot.get_channel(VOICE_MOD_TIME)
    if not channel: return
    conn = database.get_db(); c = conn.cursor()
    for member in channel.members:
        if member.bot: continue
        if any(r.id == ROLE_MODERATOR for r in member.roles):
            c.execute("INSERT INTO mod_voice_time (user_id, guild_id, seconds) VALUES (?, ?, 60) ON CONFLICT(user_id, guild_id) DO UPDATE SET seconds = seconds + 60", (member.id, member.guild.id))
    conn.commit(); conn.close()

@track_voice_time.before_loop
async def before_voice(): await bot.wait_until_ready()

@bot.tree.command(name="achen", description="Модерация участника")
@app_commands.describe(member="Нарушитель", action="warn/mute/kick/ban", reason="Причина", duration="Минуты (для mute)")
@app_commands.choices(action=[app_commands.Choice(name="warn", value="warn"), app_commands.Choice(name="mute", value="mute"), app_commands.Choice(name="kick", value="kick"), app_commands.Choice(name="ban", value="ban")])
async def achen(interaction: discord.Interaction, member: discord.Member, action: app_commands.Choice[str], reason: str = "Не указана", duration: int = 10):
    if not has_mod(interaction.user): return await interaction.response.send_message("❌ Нет прав.", ephemeral=True)
    if not allowed_channel(interaction): return await interaction.response.send_message("❌ Канал недоступен.", ephemeral=True)
    if member.top_role >= interaction.user.top_role and interaction.user.id != interaction.guild.owner_id: return await interaction.response.send_message("❌ Иерархия ролей.", ephemeral=True)
    
    act = action.value
    try:
        if act == "warn": await member.send(f"⚠️ Предупреждение на {interaction.guild.name}\nПричина: {reason}")
        elif act == "mute": await member.timeout(timedelta(minutes=duration), reason=reason)
        elif act == "kick": await member.kick(reason=reason)
        elif act == "ban": await member.ban(reason=reason)
    except discord.Forbidden: return await interaction.response.send_message("❌ Нет прав у бота.", ephemeral=True)
    
    log_to_db(interaction.guild_id, member.id, interaction.user.id, act, reason)
    await interaction.response.send_message(f"✅ `{act}` применён к {member.mention}", ephemeral=True)

@bot.tree.command(name="clear", description="Очистить сообщения")
async def clear(interaction: discord.Interaction, amount: int):
    if not has_mod(interaction.user): return await interaction.response.send_message("❌ Нет прав.", ephemeral=True)
    if not allowed_channel(interaction): return await interaction.response.send_message("❌ Канал недоступен.", ephemeral=True)
    amount = max(1, min(amount, 100))
    await interaction.channel.purge(limit=amount)
    await interaction.response.send_message(f"🧹 Удалено {amount} сообщений.", ephemeral=True)

bot.run(TOKEN)