import discord
from discord import app_commands
from discord.ext import commands, tasks
import database
from config import *
import os
import aiohttp
import sqlite3
import json

database.init_db()

TOKEN = os.environ.get("BOT_TOKEN")
if not TOKEN:
    raise RuntimeError("BOT_TOKEN не задан! Запустите через панель.")

class Bot(commands.Bot):
    def __init__(self):
        intents = discord.Intents.none()
        intents.guilds = True
        super().__init__(command_prefix="!", intents=intents)
    async def setup_hook(self):
        await self.tree.sync()
        track_support_voice_time.start()
        send_heartbeat.start()
        bot.add_view(RecruitmentView(recruitment_positions()))

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

def recruitment_db_path():
    return os.path.join(os.getcwd(), "data.db")

def recruitment_positions():
    db_path = recruitment_db_path()
    if not os.path.exists(db_path):
        return []
    conn = sqlite3.connect(db_path)
    try:
        conn.execute("SELECT 1 FROM recruitment_positions LIMIT 1")
        rows = conn.execute(
            "SELECT role_id, name, description FROM recruitment_positions "
            "WHERE active=1 ORDER BY sort_order, name"
        ).fetchall()
        return [{"role_id": row[0], "name": row[1], "description": row[2]} for row in rows]
    except sqlite3.Error:
        return []
    finally:
        conn.close()

def recruitment_setting(key):
    db_path = recruitment_db_path()
    if not os.path.exists(db_path):
        return ""
    conn = sqlite3.connect(db_path)
    try:
        row = conn.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
        return row[0] if row else ""
    except sqlite3.Error:
        return ""
    finally:
        conn.close()

class RecruitmentPositionSelect(discord.ui.Select):
    def __init__(self, positions):
        options = [
            discord.SelectOption(
                label=position["name"][:100],
                value=position["role_id"],
                description=(position["description"] or "Открытое направление")[:100],
            )
            for position in positions[:25]
        ]
        super().__init__(
            placeholder="Выберите направление набора",
            min_values=1,
            max_values=1,
            options=options or [discord.SelectOption(label="Нет открытых направлений", value="none")],
            custom_id="recruitment_position_select",
        )
        self.positions = {position["role_id"]: position for position in positions}

    async def callback(self, interaction):
        if self.values[0] == "none":
            await interaction.response.send_message("Открытых направлений пока нет.", ephemeral=True)
            return
        self.view.selected_position = self.positions[self.values[0]]
        await interaction.response.defer_update()

class RecruitmentModal(discord.ui.Modal, title="Заявка на персонал"):
    age = discord.ui.TextInput(label="Возраст", required=True, max_length=3)
    experience = discord.ui.TextInput(label="Опыт и компетенции", required=True, style=discord.TextStyle.paragraph, max_length=1000)
    activity = discord.ui.TextInput(label="Устройства и активность", required=True, style=discord.TextStyle.paragraph, max_length=500)
    schedule = discord.ui.TextInput(label="Сколько часов в день готовы уделить?", required=True, max_length=100)
    about = discord.ui.TextInput(label="Расскажите о себе", required=True, style=discord.TextStyle.paragraph, max_length=1000)

    def __init__(self, position):
        super().__init__()
        self.position = position
        self.title = f"Заявка: {position['name']}"

    async def on_submit(self, interaction):
        answers = {
            "Возраст": str(self.age),
            "Опыт и компетенции": str(self.experience),
            "Устройства и активность": str(self.activity),
            "Готовое время": str(self.schedule),
            "О себе": str(self.about),
        }
        db_path = recruitment_db_path()
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        cursor.execute(
            "INSERT INTO recruitment_applications "
            "(guild_id, applicant_id, position_role_id, position_name, answers, status) "
            "VALUES (?, ?, ?, ?, ?, 'pending')",
            (
                interaction.guild_id,
                interaction.user.id,
                self.position["role_id"],
                self.position["name"],
                json.dumps(answers, ensure_ascii=False),
            ),
        )
        application_id = cursor.lastrowid
        conn.commit()
        conn.close()

        review_setting = "recruitment_review_moderator_channel_id" if str(self.position["role_id"]) == str(ROLE_MODERATOR) else "recruitment_review_support_channel_id"
        review_channel_id = recruitment_setting(review_setting)
        if not review_channel_id:
            review_channel_id = recruitment_setting("recruitment_review_channel_id")
        review_channel = interaction.guild.get_channel(int(review_channel_id)) if review_channel_id else None
        if review_channel:
            embed = discord.Embed(
                title=f"Новая заявка: {self.position['name']}",
                color=discord.Color.blurple(),
            )
            embed.set_author(name=str(interaction.user), icon_url=interaction.user.display_avatar.url)
            embed.add_field(name="Участник", value=f"{interaction.user.mention} ({interaction.user.id})", inline=False)
            for question, answer in answers.items():
                embed.add_field(name=question, value=answer, inline=False)
            embed.set_footer(text=f"Заявка #{application_id}")
            await review_channel.send(embed=embed)

        await interaction.response.send_message(
            f"✅ Заявка на направление **{self.position['name']}** отправлена.",
            ephemeral=True,
        )

class RecruitmentView(discord.ui.View):
    def __init__(self, positions):
        super().__init__(timeout=None)
        self.selected_position = positions[0] if positions else None
        if positions:
            self.add_item(RecruitmentPositionSelect(positions))

        apply_button = discord.ui.Button(
            label="Подать заявку",
            style=discord.ButtonStyle.primary,
            custom_id="recruitment_apply",
            disabled=not positions,
        )
        apply_button.callback = self.apply
        self.add_item(apply_button)

    async def apply(self, interaction):
        if not self.selected_position:
            await interaction.response.send_message("Сначала выберите направление.", ephemeral=True)
            return
        await interaction.response.send_modal(RecruitmentModal(self.selected_position))

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

def staff_branch(role):
    name = role.name.lower()
    if role.id == ROLE_OWNER:
        return "Стафф Админ"
    if role.id == ROLE_STAFF:
        return "Общий стаф"
    if role.id == ROLE_SUPPORT:
        return "Support"
    if role.id == ROLE_MODERATOR:
        return "Moderator"
    if any(word in name for word in ("administrator", "администратор", "админ", "owner", "владел", "developer", "разработ")):
        return "Стафф Админ"
    if any(word in name for word in ("moderator", "модератор", "куратор", "curator")):
        return "Moderator"
    if any(word in name for word in ("support", "саппорт", "security")):
        return "Support"
    if any(word in name for word in ("control", "контрол")):
        return "Control"
    if any(word in name for word in ("staff", "персонал", "стaf")):
        return "Общий стаф"
    return None

@bot.tree.command(name="stafftable", description="Показать структуру персонала по веткам")
async def stafftable(interaction: discord.Interaction):
    if not can_staff(interaction.user, "stafftable"):
        return await interaction.response.send_message("❌ Нет прав.", ephemeral=True)

    branch_order = ("Стафф Админ", "Moderator", "Support", "Общий стаф", "Control")
    branches = {name: {} for name in branch_order}

    for member in interaction.guild.members:
        if member.bot:
            continue
        assigned_roles = [
            role for role in member.roles
            if not role.is_default() and staff_branch(role)
        ]
        if not assigned_roles:
            continue
        highest_role = max(assigned_roles, key=lambda role: role.position)
        branch = staff_branch(highest_role)
        if not branch:
            continue
        branches[branch].setdefault(highest_role.name, []).append(member)

    lines = [f"Состав персонала • все ветки", f"Участников: {sum(sum(len(items) for items in roles.values()) for roles in branches.values())}"]
    for branch in branch_order:
        role_groups = branches[branch]
        if not role_groups:
            continue
        lines.append("")
        lines.append(f"{branch} • {sum(len(items) for items in role_groups.values())}")
        def role_position(item):
            matched = next((role for role in interaction.guild.roles if role.name == item[0]), None)
            return matched.position if matched else -1

        ordered_groups = sorted(role_groups.items(), key=role_position, reverse=True)
        for role_name, members in ordered_groups:
            lines.append(f"├─ {role_name}")
            sorted_members = sorted(members, key=lambda member: member.display_name.lower())
            for index, member in enumerate(sorted_members):
                prefix = "└─" if index == len(sorted_members) - 1 else "├─"
                lines.append(f"│  {prefix} {member.mention}")

    embed = discord.Embed(title="Состав персонала • все ветки", description="\n".join(lines)[:4096], color=discord.Color.blurple())
    await interaction.response.send_message(embed=embed, ephemeral=True)

@bot.tree.command(name="recruit_post", description="Опубликовать набор персонала")
async def recruit_post(interaction: discord.Interaction):
    if not can_staff(interaction.user, "recruit_post"):
        return await interaction.response.send_message("❌ Нет прав.", ephemeral=True)

    positions = recruitment_positions()
    if not positions:
        return await interaction.response.send_message("Сначала добавьте направления набора в панель.", ephemeral=True)

    target_channel = interaction.channel
    configured_channel_id = recruitment_setting("recruitment_channel_id")
    if configured_channel_id:
        configured_channel = interaction.guild.get_channel(int(configured_channel_id))
        if configured_channel:
            target_channel = configured_channel

    embed = discord.Embed(
        title="Набор в персонал",
        description="Выберите направление в списке ниже и заполните анкету.",
        color=discord.Color.from_rgb(88, 101, 242),
    )
    embed.add_field(
        name="Открытые направления",
        value="\n".join(f"• {position['name']} — {position['description']}".strip() for position in positions),
        inline=False,
    )
    embed.set_footer(text="Заявки рассматриваются администрацией сервера")
    await target_channel.send(embed=embed, view=RecruitmentView(positions))
    await interaction.response.send_message(f"Карточка набора опубликована в {target_channel.mention}.", ephemeral=True)

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