import discord
from discord import app_commands
from discord.ext import commands, tasks
import database
from config import *
import os
import aiohttp

TOKEN = os.environ.get("BOT_TOKEN")
if not TOKEN:
    raise RuntimeError("BOT_TOKEN не задан! Запустите через панель.")

class Bot(commands.Bot):
    def __init__(self):
        super().__init__(command_prefix="!", intents=discord.Intents.all())
    async def setup_hook(self):
        await self.tree.sync()
        send_heartbeat.start()

bot = Bot()

@tasks.loop(seconds=60)
async def send_heartbeat():
    try:
        async with aiohttp.ClientSession() as session:
            await session.post("http://localhost:4477/api/heartbeat", json={"bot_id": "support"})
    except Exception:
        pass

@send_heartbeat.before_loop
async def before_heartbeat(): await bot.wait_until_ready()

def has_support(member): return any(r.id == ROLE_SUPPORT for r in member.roles)
def allowed_channel(interaction): return interaction.channel_id in CHANNELS_ALLOWED

@bot.tree.command(name="verf", description="Верифицировать пользователя")
@app_commands.describe(member="Кого верифицируем", gender="Пол")
@app_commands.choices(gender=[app_commands.Choice(name="Мальчик", value="boy"), app_commands.Choice(name="Девочка", value="girl")])
async def verf(interaction: discord.Interaction, member: discord.Member, gender: app_commands.Choice[str]):
    if not has_support(interaction.user): return await interaction.response.send_message("❌ Нет прав.", ephemeral=True)
    if not allowed_channel(interaction): return await interaction.response.send_message("❌ Канал недоступен.", ephemeral=True)
    if member.bot: return await interaction.response.send_message("❌ Нельзя верифицировать бота.", ephemeral=True)

    role_id = ROLE_GIRL if gender.value == "girl" else ROLE_BOY
    role = interaction.guild.get_role(role_id)
    
    try:
        unv = interaction.guild.get_role(ROLE_UNVERIFY)
        if unv and unv in member.roles: await member.remove_roles(unv)
        await member.add_roles(role)
    except discord.Forbidden: return await interaction.response.send_message("❌ Нет прав у бота.", ephemeral=True)

    conn = database.get_db(); c = conn.cursor()
    c.execute("INSERT OR IGNORE INTO staff_profiles (user_id, guild_id, role_type) VALUES (?,?, 'support')", (interaction.user.id, interaction.guild_id))
    c.execute("UPDATE staff_profiles SET verifications = verifications + 1 WHERE user_id=?", (interaction.user.id,))
    conn.commit(); conn.close()

    await interaction.response.send_message(f"✅ {member.mention} верифицирован.", ephemeral=True)

bot.run(TOKEN)