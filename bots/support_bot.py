import discord
from discord import app_commands
from discord.ext import commands, tasks
import database
from config import *
import os
import aiohttp

database.init_db()

TOKEN = os.environ.get("BOT_TOKEN")
if not TOKEN:
    raise RuntimeError("BOT_TOKEN не задан! Запустите через панель.")

class Bot(commands.Bot):
    def __init__(self):
        super().__init__(command_prefix="!", intents=discord.Intents.all())
    async def setup_hook(self):
        await self.tree.sync()
        track_support_voice_time.start()
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

def has_support(member):
    return role_can_use_command(member, "verf") or any(r.id in (ROLE_SUPPORT, ROLE_OWNER) for r in member.roles)

def has_staff(member):
    return any(r.id == ROLE_STAFF for r in member.roles)

def allowed_channel(interaction):
    return interaction.channel_id in CHANNELS_ALLOWED or has_support(interaction.user) or has_staff(interaction.user)

def format_duration(seconds):
    seconds = int(seconds or 0)
    hours, remainder = divmod(seconds, 3600)
    minutes, seconds = divmod(remainder, 60)
    return f"{hours}ч {minutes}м"

def can_staff(member, command):
    if role_can_use_command(member, command):
        return True
    return any(role.id in (ROLE_STAFF, ROLE_SUPPORT, ROLE_MODERATOR, ROLE_OWNER) for role in member.roles)

@tasks.loop(minutes=1)
async def track_support_voice_time():
    guild = bot.guilds[0] if bot.guilds else None
    if not guild:
        return
    conn = database.get_db()
    c = conn.cursor()
    for channel in guild.channels:
        if getattr(channel, "category_id", None) != CATEGORY_SUPPORT:
            continue
        if not hasattr(channel, "members"):
            continue
        for member in channel.members:
            if member.bot:
                continue
            if any(role.id == ROLE_SUPPORT for role in member.roles):
                c.execute(
                    "INSERT INTO support_voice_time (user_id, guild_id, seconds) VALUES (?, ?, 60) "
                    "ON CONFLICT(user_id, guild_id) DO UPDATE SET seconds = seconds + 60",
                    (member.id, member.guild.id),
                )
    conn.commit()
    conn.close()

@track_support_voice_time.before_loop
async def before_support_voice():
    await bot.wait_until_ready()

@bot.tree.command(name="staf_profile", description="Профиль сотрудника")
@app_commands.describe(member="Сотрудник")
async def staf_profile(interaction: discord.Interaction, member: discord.Member = None):
    if not can_staff(interaction.user, "staf_profile"):
        return await interaction.response.send_message("❌ Нет прав.", ephemeral=True)

    target = member or interaction.user
    conn = database.get_db()
    c = conn.cursor()
    c.execute(
        "SELECT verifications, warns, mutes, kicks, bans, reputation FROM staff_profiles "
        "WHERE user_id=? AND guild_id=?",
        (target.id, interaction.guild_id),
    )
    profile = c.fetchone()
    c.execute(
        "SELECT seconds FROM support_voice_time WHERE user_id=? AND guild_id=?",
        (target.id, interaction.guild_id),
    )
    support_time = c.fetchone()
    c.execute(
        "SELECT seconds FROM mod_voice_time WHERE user_id=? AND guild_id=?",
        (target.id, interaction.guild_id),
    )
    mod_time = c.fetchone()
    conn.close()

    verifications = profile[0] if profile else 0
    warns = profile[1] if profile else 0
    mutes = profile[2] if profile else 0
    kicks = profile[3] if profile else 0
    bans = profile[4] if profile else 0
    reputation = profile[5] if profile else 0

    embed = discord.Embed(title=f"Профиль сотрудника: {target.display_name}", color=discord.Color.blurple())
    embed.add_field(name="Верификации", value=str(verifications), inline=True)
    embed.add_field(name="Предупреждения", value=str(warns), inline=True)
    embed.add_field(name="Муты", value=str(mutes), inline=True)
    embed.add_field(name="Кики", value=str(kicks), inline=True)
    embed.add_field(name="Баны", value=str(bans), inline=True)
    embed.add_field(name="Репутация", value=str(reputation), inline=True)
    embed.add_field(name="Время саппорта", value=format_duration(support_time[0] if support_time else 0), inline=True)
    embed.add_field(name="Время модератора", value=format_duration(mod_time[0] if mod_time else 0), inline=True)
    await interaction.response.send_message(embed=embed, ephemeral=not can_staff(interaction.user, "staf_profile"))

@bot.tree.command(name="staf_stats", description="Общая статистика персонала")
async def staf_stats(interaction: discord.Interaction):
    if not can_staff(interaction.user, "staf_stats"):
        return await interaction.response.send_message("❌ Нет прав.", ephemeral=True)

    conn = database.get_db()
    c = conn.cursor()
    c.execute(
        "SELECT role_type, COUNT(*), COALESCE(SUM(verifications),0), COALESCE(SUM(warns),0), "
        "COALESCE(SUM(mutes),0), COALESCE(SUM(kicks),0), COALESCE(SUM(bans),0) "
        "FROM staff_profiles WHERE guild_id=? GROUP BY role_type",
        (interaction.guild_id,),
    )
    rows = c.fetchall()
    conn.close()

    embed = discord.Embed(title="Статистика персонала", color=discord.Color.gold())
    if not rows:
        embed.description = "Действий пока нет."
    for role_type, count, verifications, warns, mutes, kicks, bans in rows:
        name = "Саппорт" if role_type == "support" else "Модерация"
        embed.add_field(
            name=name,
            value=f"Сотрудников: {count}\nВерификации: {verifications}\nПредупреждения: {warns}\nМуты: {mutes}\nКики: {kicks}\nБаны: {bans}",
            inline=False,
        )
    await interaction.response.send_message(embed=embed, ephemeral=True)

async def send_verification_top(interaction: discord.Interaction):
    if not can_staff(interaction.user, "top_veref"):
        return await interaction.response.send_message("❌ Нет прав.", ephemeral=True)

    conn = database.get_db()
    c = conn.cursor()
    c.execute(
        "SELECT user_id, verifications FROM staff_profiles "
        "WHERE guild_id=? AND role_type='support' AND verifications > 0 "
        "ORDER BY verifications DESC, user_id ASC LIMIT 10",
        (interaction.guild_id,),
    )
    rows = c.fetchall()
    conn.close()

    embed = discord.Embed(title="Топ саппортов по верификации", color=discord.Color.green())
    if not rows:
        embed.description = "Пока нет верификаций."
    else:
        lines = []
        for index, (user_id, verifications) in enumerate(rows, start=1):
            member = interaction.guild.get_member(user_id)
            name = member.mention if member else f"<@{user_id}>"
            lines.append(f"{index}. {name} — **{verifications}**")
        embed.description = "\n".join(lines)
    await interaction.response.send_message(embed=embed, ephemeral=True)

@bot.tree.command(name="top_veref", description="Топ саппортов по верификации")
async def top_veref(interaction: discord.Interaction):
    await send_verification_top(interaction)

@bot.tree.command(name="top_verf", description="Топ саппортов по верификации")
async def top_verf(interaction: discord.Interaction):
    await send_verification_top(interaction)

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