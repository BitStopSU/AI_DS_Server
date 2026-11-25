"""
Модуль саппорта.

Необязательные настройки в config.py (если их нет, функция просто отключена):
    CHANNEL_SUPPORT_LOG = 0            # канал логов (верификации, недельный отчёт)
    CHANNEL_SUPPORT_STAFF = 0          # канал, куда приходят уведомления «участник ждёт саппорта»
    VOICE_SUPPORT_WAIT = 0             # голосовой канал «Ожидание саппорта»
    ROLE_ON_DUTY = 0                   # роль «На смене» (выдаётся командой /duty)
    SUPPORT_NORM_VOICE_HOURS = 0       # норма часов в голосовых за неделю
    SUPPORT_NORM_VERIFICATIONS = 0     # норма верификаций за неделю
"""
import discord
from discord import app_commands
from discord.ext import commands, tasks
from datetime import date, datetime, timedelta
from pathlib import Path
import database
import config as _config
from config import *
import os
import re
import time
import aiohttp
import sqlite3
import json
from support_features import register_support_commands
from tribunal_features import register_tribunal_commands

database.init_db()

TOKEN = os.environ.get("BOT_TOKEN")
if not TOKEN:
    raise RuntimeError("BOT_TOKEN не задан! Запустите через панель.")


def cfg(name, default=0):
    """Необязательная настройка из config.py."""
    return getattr(_config, name, default)


# ---------------------------------------------------------------------- БД
def init_support_tables():
    conn = database.get_db()
    c = conn.cursor()
    c.execute(
        "CREATE TABLE IF NOT EXISTS support_log ("
        "id INTEGER PRIMARY KEY AUTOINCREMENT, guild_id INTEGER, staff_id INTEGER, "
        "action TEXT, target_id INTEGER, extra TEXT, created_at INTEGER)"
    )
    c.execute(
        "CREATE TABLE IF NOT EXISTS member_notes ("
        "id INTEGER PRIMARY KEY AUTOINCREMENT, guild_id INTEGER, user_id INTEGER, "
        "staff_id INTEGER, text TEXT, created_at INTEGER)"
    )
    c.execute(
        "CREATE TABLE IF NOT EXISTS duty_active ("
        "guild_id INTEGER, user_id INTEGER, started_at INTEGER, PRIMARY KEY (guild_id, user_id))"
    )
    c.execute(
        "CREATE TABLE IF NOT EXISTS support_voice_daily ("
        "guild_id INTEGER, user_id INTEGER, day TEXT, seconds INTEGER DEFAULT 0, "
        "PRIMARY KEY (guild_id, user_id, day))"
    )
    conn.commit()
    conn.close()


init_support_tables()


def log_support(guild_id, staff_id, action, target_id=None, extra=None):
    conn = database.get_db()
    c = conn.cursor()
    c.execute(
        "INSERT INTO support_log (guild_id, staff_id, action, target_id, extra, created_at) VALUES (?,?,?,?,?,?)",
        (guild_id, staff_id, action, target_id, extra, int(time.time())),
    )
    conn.commit()
    conn.close()


# --------------------------------------------------------------------- бот
class Bot(commands.Bot):
    def __init__(self):
        intents = discord.Intents.none()
        intents.guilds = True
        intents.voice_states = True
        super().__init__(command_prefix="!", intents=intents)

    async def setup_hook(self):
        await self.tree.sync()
        track_support_voice_time.start()
        send_heartbeat.start()
        weekly_report_task.start()
        self.add_view(RecruitmentView(recruitment_positions()))
        self.add_view(ReviewView())


bot = Bot()


@tasks.loop(seconds=60)
async def send_heartbeat():
    try:
        async with aiohttp.ClientSession() as session:
            await session.post("http://localhost:4477/api/heartbeat", json={"bot_id": "support"})
    except Exception:
        pass


@send_heartbeat.before_loop
async def before_heartbeat():
    await bot.wait_until_ready()


# ------------------------------------------------------------------- права
def has_support(member):
    return role_can_use_command(member, "verf") or any(r.id in (ROLE_SUPPORT, ROLE_OWNER) for r in member.roles)


def has_staff(member):
    return any(r.id == ROLE_STAFF for r in member.roles)


def has_owner(member):
    return any(r.id == ROLE_OWNER for r in member.roles)


def allowed_channel(interaction):
    return interaction.channel_id in CHANNELS_ALLOWED or has_support(interaction.user) or has_staff(interaction.user)


def can_staff(member, command):
    if role_can_use_command(member, command):
        return True
    return any(role.id in (ROLE_STAFF, ROLE_SUPPORT, ROLE_MODERATOR, ROLE_OWNER) for role in member.roles)


def can_review(member):
    if role_can_use_command(member, "recruit_review"):
        return True
    return any(role.id in (ROLE_OWNER, ROLE_STAFF) for role in member.roles)


register_support_commands(bot, database, _config, can_staff, has_support, has_owner)
register_tribunal_commands(bot, database, can_staff, has_owner)


# --------------------------------------------------------------- утилиты
def format_duration(seconds):
    seconds = int(seconds or 0)
    hours, remainder = divmod(seconds, 3600)
    minutes, seconds = divmod(remainder, 60)
    return f"{hours}ч {minutes}м"


async def try_dm(user, text):
    try:
        await user.send(text)
        return True
    except (discord.Forbidden, discord.HTTPException):
        return False


async def send_log(guild, embed):
    channel_id = cfg("CHANNEL_SUPPORT_LOG")
    channel = guild.get_channel(channel_id) if channel_id else None
    if channel:
        try:
            await channel.send(embed=embed)
        except discord.HTTPException:
            pass


# ------------------------------------------------------------------ набор
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
                value=str(position["role_id"]),
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
        self.positions = {str(position["role_id"]): position for position in positions}

    async def callback(self, interaction):
        if self.values[0] == "none":
            await interaction.response.send_message("Открытых направлений пока нет.", ephemeral=True)
            return
        position = self.positions.get(self.values[0])
        if position is None:
            await interaction.response.send_message("Это направление больше недоступно.", ephemeral=True)
            return
        # выбор хранится отдельно для каждого участника
        self.view.selected[interaction.user.id] = position
        await interaction.response.defer()


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
        age_text = str(self.age).strip()
        if not age_text.isdigit() or not 13 <= int(age_text) <= 99:
            return await interaction.response.send_message("❌ Укажите возраст числом (13–99).", ephemeral=True)

        answers = {
            "Возраст": age_text,
            "Опыт и компетенции": str(self.experience),
            "Устройства и активность": str(self.activity),
            "Готовое время": str(self.schedule),
            "О себе": str(self.about),
        }
        db_path = recruitment_db_path()
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        cursor.execute(
            "SELECT 1 FROM recruitment_applications WHERE guild_id=? AND applicant_id=? AND status='pending' LIMIT 1",
            (interaction.guild_id, interaction.user.id),
        )
        if cursor.fetchone():
            conn.close()
            return await interaction.response.send_message(
                "ℹ️ У вас уже есть заявка на рассмотрении. Дождитесь решения.", ephemeral=True
            )
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
            await review_channel.send(embed=embed, view=ReviewView())

        await interaction.response.send_message(
            f"✅ Заявка на направление **{self.position['name']}** отправлена.",
            ephemeral=True,
        )


class RecruitmentView(discord.ui.View):
    def __init__(self, positions):
        super().__init__(timeout=None)
        self.positions = positions
        self.selected = {}  # user_id -> направление
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
        position = self.selected.get(interaction.user.id)
        if position is None and len(self.positions) == 1:
            position = self.positions[0]
        if position is None:
            await interaction.response.send_message("Сначала выберите направление в списке.", ephemeral=True)
            return
        await interaction.response.send_modal(RecruitmentModal(position))


# --- рассмотрение заявок (кнопки «Принять» / «Отклонить») ---
def application_id_from_message(message):
    if not message.embeds:
        return None
    footer = message.embeds[0].footer
    if not footer or not footer.text:
        return None
    match = re.search(r"#(\d+)", footer.text)
    return int(match.group(1)) if match else None


async def finish_review(interaction, message, status, reason=None):
    if not can_review(interaction.user):
        return await interaction.response.send_message("❌ Нет прав рассматривать заявки.", ephemeral=True)

    app_id = application_id_from_message(message)
    if app_id is None:
        return await interaction.response.send_message("❌ Не удалось определить номер заявки.", ephemeral=True)

    conn = sqlite3.connect(recruitment_db_path())
    row = conn.execute(
        "SELECT applicant_id, position_name, status FROM recruitment_applications WHERE rowid=?", (app_id,)
    ).fetchone()
    if not row:
        conn.close()
        return await interaction.response.send_message("❌ Заявка не найдена в базе.", ephemeral=True)
    applicant_id, position_name, current_status = row
    if current_status != "pending":
        conn.close()
        return await interaction.response.send_message("ℹ️ Эта заявка уже рассмотрена.", ephemeral=True)
    conn.execute("UPDATE recruitment_applications SET status=? WHERE rowid=?", (status, app_id))
    conn.commit()
    conn.close()

    await interaction.response.defer(ephemeral=True)

    accepted = status == "accepted"
    embed = discord.Embed.from_dict(message.embeds[0].to_dict())
    embed.color = discord.Color.green() if accepted else discord.Color.red()
    value = f"{'✅ Принята' if accepted else '❌ Отклонена'} — {interaction.user.mention}"
    if reason:
        value += f"\nПричина: {reason}"
    embed.add_field(name="Решение", value=value[:1024], inline=False)
    await message.edit(embed=embed, view=None)

    user = interaction.guild.get_member(applicant_id)
    if user is None:
        try:
            user = await bot.fetch_user(applicant_id)
        except discord.HTTPException:
            user = None
    if accepted:
        text = f"✅ Ваша заявка на направление «{position_name}» на сервере {interaction.guild.name} принята. С вами свяжутся."
    else:
        text = f"❌ Ваша заявка на направление «{position_name}» на сервере {interaction.guild.name} отклонена."
        if reason:
            text += f"\nПричина: {reason}"
    dm_ok = await try_dm(user, text) if user else False

    answer = f"Заявка #{app_id}: {'принята' if accepted else 'отклонена'}."
    if not dm_ok:
        answer += " ЛС заявителя закрыты, уведомление не доставлено."
    await interaction.followup.send(answer, ephemeral=True)


class DeclineModal(discord.ui.Modal, title="Отклонить заявку"):
    reason = discord.ui.TextInput(label="Причина (необязательно)", required=False, style=discord.TextStyle.paragraph, max_length=500)

    def __init__(self, message):
        super().__init__()
        self.message = message

    async def on_submit(self, interaction):
        await finish_review(interaction, self.message, "declined", str(self.reason).strip() or None)


class ReviewView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="Принять", style=discord.ButtonStyle.success, custom_id="recruit_accept")
    async def accept(self, interaction: discord.Interaction, button: discord.ui.Button):
        await finish_review(interaction, interaction.message, "accepted")

    @discord.ui.button(label="Отклонить", style=discord.ButtonStyle.danger, custom_id="recruit_decline")
    async def decline(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not can_review(interaction.user):
            return await interaction.response.send_message("❌ Нет прав рассматривать заявки.", ephemeral=True)
        await interaction.response.send_modal(DeclineModal(interaction.message))


# -------------------------------------------- ожидание саппорта в голосовом
wait_cooldown = {}


class WaitView(discord.ui.View):
    def __init__(self, user_id):
        super().__init__(timeout=1800)
        self.user_id = user_id
        self.taken = False

    @discord.ui.button(label="Взять", style=discord.ButtonStyle.success, emoji="🎧")
    async def take(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not has_support(interaction.user):
            return await interaction.response.send_message("❌ Нет прав.", ephemeral=True)
        if self.taken:
            return await interaction.response.send_message("ℹ️ Участника уже взял другой саппорт.", ephemeral=True)

        wait_id = cfg("VOICE_SUPPORT_WAIT")
        member = interaction.guild.get_member(self.user_id)
        if not member or not member.voice or not member.voice.channel or member.voice.channel.id != wait_id:
            button.disabled = True
            return await interaction.response.edit_message(content="Участник уже вышел из ожидания.", view=self)

        voice = interaction.user.voice
        if not voice or not voice.channel:
            return await interaction.response.send_message(
                "ℹ️ Зайдите в голосовой канал и нажмите «Взять» ещё раз.", ephemeral=True
            )

        self.taken = True
        try:
            await member.move_to(voice.channel, reason=f"Взял саппорт {interaction.user}")
        except discord.Forbidden:
            self.taken = False
            return await interaction.response.send_message("❌ У бота нет права перемещать участников.", ephemeral=True)
        except discord.HTTPException:
            self.taken = False
            return await interaction.response.send_message("❌ Не удалось переместить участника.", ephemeral=True)

        log_support(interaction.guild_id, interaction.user.id, "take", member.id)
        button.disabled = True
        embed = interaction.message.embeds[0]
        embed.color = discord.Color.green()
        embed.description = f"{member.mention} — взял {interaction.user.mention}"
        await interaction.response.edit_message(content=None, embed=embed, view=self)


@bot.event
async def on_voice_state_update(member, before, after):
    wait_id = cfg("VOICE_SUPPORT_WAIT")
    if not wait_id or member.bot:
        return
    if not after.channel or after.channel.id != wait_id:
        return
    if before.channel and before.channel.id == wait_id:
        return
    if has_support(member) or has_staff(member):
        return

    now = time.time()
    if now - wait_cooldown.get(member.id, 0) < 60:
        return
    wait_cooldown[member.id] = now

    channel_id = cfg("CHANNEL_SUPPORT_STAFF") or cfg("CHANNEL_SUPPORT_LOG")
    channel = member.guild.get_channel(channel_id) if channel_id else None
    if not channel:
        return

    embed = discord.Embed(
        title="🎧 Участник ждёт саппорта",
        description=f"{member.mention} зашёл в {after.channel.mention}",
        color=discord.Color.orange(),
    )
    try:
        await channel.send(
            content=f"<@&{ROLE_SUPPORT}>",
            embed=embed,
            view=WaitView(member.id),
            allowed_mentions=discord.AllowedMentions(roles=True),
        )
    except discord.HTTPException:
        pass


# ------------------------------------------------------ голосовое время
@tasks.loop(minutes=1)
async def track_support_voice_time():
    today = date.today().isoformat()
    conn = database.get_db()
    c = conn.cursor()
    for guild in bot.guilds:
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
                    c.execute(
                        "INSERT INTO support_voice_daily (guild_id, user_id, day, seconds) VALUES (?, ?, ?, 60) "
                        "ON CONFLICT(guild_id, user_id, day) DO UPDATE SET seconds = seconds + 60",
                        (member.guild.id, member.id, today),
                    )
    conn.commit()
    conn.close()


@track_support_voice_time.before_loop
async def before_support_voice():
    await bot.wait_until_ready()


# --------------------------------------------------- недельная статистика
def week_stats(guild_id, user_id):
    since = int(time.time()) - 7 * 86400
    day_from = (date.today() - timedelta(days=6)).isoformat()
    conn = database.get_db()
    c = conn.cursor()

    def count(action):
        c.execute(
            "SELECT COUNT(*) FROM support_log WHERE guild_id=? AND staff_id=? AND action=? AND created_at>=?",
            (guild_id, user_id, action, since),
        )
        return c.fetchone()[0]

    stats = {"verify": count("verify"), "unverify": count("unverify"), "take": count("take")}
    c.execute(
        "SELECT COALESCE(SUM(CAST(extra AS INTEGER)),0) FROM support_log "
        "WHERE guild_id=? AND staff_id=? AND action='duty' AND created_at>=?",
        (guild_id, user_id, since),
    )
    stats["duty"] = c.fetchone()[0]
    c.execute(
        "SELECT COALESCE(SUM(seconds),0) FROM support_voice_daily WHERE guild_id=? AND user_id=? AND day>=?",
        (guild_id, user_id, day_from),
    )
    stats["voice"] = c.fetchone()[0]
    conn.close()
    return stats


def norm_status(stats):
    """None — нормы не заданы, True/False — выполнена или нет."""
    voice_norm = cfg("SUPPORT_NORM_VOICE_HOURS", 0)
    verif_norm = cfg("SUPPORT_NORM_VERIFICATIONS", 0)
    if not voice_norm and not verif_norm:
        return None
    if voice_norm and stats["voice"] < voice_norm * 3600:
        return False
    if verif_norm and stats["verify"] < verif_norm:
        return False
    return True


def build_week_report(guild):
    role = guild.get_role(ROLE_SUPPORT)
    members = [m for m in role.members if not m.bot] if role else []
    rows = [(m, week_stats(guild.id, m.id)) for m in members]
    rows.sort(key=lambda r: (r[1]["verify"], r[1]["voice"]), reverse=True)

    lines = []
    for m, s in rows:
        mark = norm_status(s)
        prefix = "" if mark is None else ("✅ " if mark else "❌ ")
        lines.append(
            f"{prefix}{m.mention} — верификаций: {s['verify']}, из ожидания: {s['take']}, "
            f"голос: {format_duration(s['voice'])}, смена: {format_duration(s['duty'])}"
        )
    description = "\n".join(lines) or "Участников с ролью саппорта не найдено."
    if len(description) > 4000:
        description = description[:3990] + "\n…"
    embed = discord.Embed(title="Недельный отчёт саппорта", description=description, color=discord.Color.gold())
    embed.set_footer(text="За последние 7 дней")
    return embed


@tasks.loop(hours=1)
async def weekly_report_task():
    now = datetime.now()
    if now.weekday() != 0 or now.hour < 10:
        return
    channel_id = cfg("CHANNEL_SUPPORT_LOG")
    if not channel_id:
        return
    iso = now.isocalendar()
    week_key = f"{iso[0]}-W{iso[1]:02d}"

    for guild in bot.guilds:
        channel = guild.get_channel(channel_id)
        if not channel:
            continue
        conn = database.get_db()
        c = conn.cursor()
        c.execute(
            "SELECT 1 FROM support_log WHERE guild_id=? AND action='weekly_report' AND extra=?",
            (guild.id, week_key),
        )
        already = c.fetchone()
        conn.close()
        if already:
            continue
        try:
            await channel.send(embed=build_week_report(guild))
        except discord.HTTPException:
            continue
        log_support(guild.id, bot.user.id, "weekly_report", None, week_key)


@weekly_report_task.before_loop
async def before_weekly_report():
    await bot.wait_until_ready()


@bot.tree.command(name="myweek", description="Моя неделя в саппорте")
@app_commands.guild_only()
@app_commands.describe(member="Сотрудник (по умолчанию вы)")
async def myweek(interaction: discord.Interaction, member: discord.Member = None):
    if not can_staff(interaction.user, "myweek"):
        return await interaction.response.send_message("❌ Нет прав.", ephemeral=True)
    target = member or interaction.user
    s = week_stats(interaction.guild_id, target.id)
    mark = norm_status(s)

    embed = discord.Embed(title=f"Неделя: {target.display_name}", color=discord.Color.blurple())
    embed.add_field(name="Верификации", value=str(s["verify"]), inline=True)
    embed.add_field(name="Снято верификаций", value=str(s["unverify"]), inline=True)
    embed.add_field(name="Взято из ожидания", value=str(s["take"]), inline=True)
    embed.add_field(name="Голосовые", value=format_duration(s["voice"]), inline=True)
    embed.add_field(name="На смене", value=format_duration(s["duty"]), inline=True)
    if mark is not None:
        embed.add_field(name="Норма", value="✅ выполнена" if mark else "❌ не выполнена", inline=True)
    embed.set_footer(text="За последние 7 дней")
    await interaction.response.send_message(embed=embed, ephemeral=True)


@bot.tree.command(name="weekreport", description="Недельный отчёт по всем саппортам")
@app_commands.guild_only()
async def weekreport(interaction: discord.Interaction):
    if not can_staff(interaction.user, "weekreport"):
        return await interaction.response.send_message("❌ Нет прав.", ephemeral=True)
    await interaction.response.send_message(embed=build_week_report(interaction.guild), ephemeral=True)


# --------------------------------------------------------------- смены
@bot.tree.command(name="duty", description="Начать или закончить смену")
@app_commands.guild_only()
async def duty(interaction: discord.Interaction):
    if not has_support(interaction.user):
        return await interaction.response.send_message("❌ Нет прав.", ephemeral=True)

    guild = interaction.guild
    role_id = cfg("ROLE_ON_DUTY")
    role = guild.get_role(role_id) if role_id else None

    conn = database.get_db()
    c = conn.cursor()
    c.execute("SELECT started_at FROM duty_active WHERE guild_id=? AND user_id=?", (guild.id, interaction.user.id))
    row = c.fetchone()
    if row:
        seconds = max(0, int(time.time()) - int(row[0]))
        c.execute("DELETE FROM duty_active WHERE guild_id=? AND user_id=?", (guild.id, interaction.user.id))
        conn.commit()
        conn.close()
        log_support(guild.id, interaction.user.id, "duty", None, str(seconds))
        text = f"🔴 Смена окончена. Длительность: {format_duration(seconds)}."
        if role and role in interaction.user.roles:
            try:
                await interaction.user.remove_roles(role, reason="Конец смены")
            except discord.HTTPException:
                text += "\n(Не удалось снять роль «На смене».)"
    else:
        c.execute(
            "INSERT OR REPLACE INTO duty_active (guild_id, user_id, started_at) VALUES (?,?,?)",
            (guild.id, interaction.user.id, int(time.time())),
        )
        conn.commit()
        conn.close()
        text = "🟢 Смена начата."
        if role:
            try:
                await interaction.user.add_roles(role, reason="Начало смены")
            except discord.HTTPException:
                text += "\n(Не удалось выдать роль «На смене».)"
    await interaction.response.send_message(text, ephemeral=True)


@bot.tree.command(name="onduty", description="Кто сейчас на смене")
@app_commands.guild_only()
async def onduty(interaction: discord.Interaction):
    if not can_staff(interaction.user, "onduty"):
        return await interaction.response.send_message("❌ Нет прав.", ephemeral=True)
    conn = database.get_db()
    c = conn.cursor()
    c.execute(
        "SELECT user_id, started_at FROM duty_active WHERE guild_id=? ORDER BY started_at",
        (interaction.guild_id,),
    )
    rows = c.fetchall()
    conn.close()
    if not rows:
        return await interaction.response.send_message("Сейчас на смене никого нет.", ephemeral=True)
    lines = [f"<@{user_id}> — с <t:{int(started)}:R>" for user_id, started in rows]
    await interaction.response.send_message("🟢 На смене:\n" + "\n".join(lines), ephemeral=True)


# ----------------------------------------------------- заметки и история
@bot.tree.command(name="note", description="Добавить внутреннюю заметку об участнике")
@app_commands.guild_only()
@app_commands.describe(member="Участник", text="Текст заметки")
async def note(interaction: discord.Interaction, member: discord.Member, text: app_commands.Range[str, 1, 500]):
    if not can_staff(interaction.user, "note"):
        return await interaction.response.send_message("❌ Нет прав.", ephemeral=True)
    conn = database.get_db()
    c = conn.cursor()
    c.execute(
        "INSERT INTO member_notes (guild_id, user_id, staff_id, text, created_at) VALUES (?,?,?,?,?)",
        (interaction.guild_id, member.id, interaction.user.id, text, int(time.time())),
    )
    note_id = c.lastrowid
    conn.commit()
    conn.close()
    await interaction.response.send_message(f"📝 Заметка #{note_id} о {member.mention} сохранена.", ephemeral=True)


@bot.tree.command(name="delnote", description="Удалить заметку по номеру")
@app_commands.guild_only()
@app_commands.describe(note_id="Номер заметки из /history")
async def delnote(interaction: discord.Interaction, note_id: int):
    if not can_staff(interaction.user, "delnote"):
        return await interaction.response.send_message("❌ Нет прав.", ephemeral=True)
    conn = database.get_db()
    c = conn.cursor()
    c.execute("SELECT staff_id FROM member_notes WHERE id=? AND guild_id=?", (note_id, interaction.guild_id))
    row = c.fetchone()
    if not row:
        conn.close()
        return await interaction.response.send_message("❌ Заметка не найдена.", ephemeral=True)
    if row[0] != interaction.user.id and not has_owner(interaction.user):
        conn.close()
        return await interaction.response.send_message("❌ Удалить чужую заметку может только владелец.", ephemeral=True)
    c.execute("DELETE FROM member_notes WHERE id=?", (note_id,))
    conn.commit()
    conn.close()
    await interaction.response.send_message(f"🗑️ Заметка #{note_id} удалена.", ephemeral=True)


def short(text, limit=150):
    text = (text or "—").replace("\n", " ")
    return text if len(text) <= limit else text[: limit - 1] + "…"


@bot.tree.command(name="history", description="История участника: наказания, заметки, верификации")
@app_commands.guild_only()
@app_commands.describe(member="Участник")
async def history(interaction: discord.Interaction, member: discord.Member):
    if not can_staff(interaction.user, "history"):
        return await interaction.response.send_message("❌ Нет прав.", ephemeral=True)

    gid = interaction.guild_id
    conn = database.get_db()
    c = conn.cursor()
    c.execute("SELECT type, COUNT(*) FROM punishments WHERE guild_id=? AND user_id=? GROUP BY type", (gid, member.id))
    counts = dict(c.fetchall())
    c.execute(
        "SELECT rowid, type, moderator_id, reason FROM punishments "
        "WHERE guild_id=? AND user_id=? ORDER BY rowid DESC LIMIT 5",
        (gid, member.id),
    )
    punishments = c.fetchall()
    c.execute(
        "SELECT id, staff_id, text, created_at FROM member_notes "
        "WHERE guild_id=? AND user_id=? ORDER BY id DESC LIMIT 5",
        (gid, member.id),
    )
    notes = c.fetchall()
    c.execute(
        "SELECT action, staff_id, created_at FROM support_log "
        "WHERE guild_id=? AND target_id=? AND action IN ('verify','unverify') ORDER BY id DESC LIMIT 3",
        (gid, member.id),
    )
    verifs = c.fetchall()
    conn.close()

    embed = discord.Embed(title=f"История: {member.display_name}", color=discord.Color.blurple())
    embed.set_thumbnail(url=member.display_avatar.url)
    embed.add_field(
        name="Наказания (всего)",
        value=f"Варны: {counts.get('warn', 0)} • Муты: {counts.get('mute', 0)} • "
              f"Кики: {counts.get('kick', 0)} • Баны: {counts.get('ban', 0)}",
        inline=False,
    )
    if punishments:
        value = "\n".join(f"`#{pid}` {ptype} — <@{mod}>: {short(reason)}" for pid, ptype, mod, reason in punishments)
        embed.add_field(name="Последние наказания", value=value[:1024], inline=False)
    if notes:
        value = "\n".join(f"`#{nid}` <@{staff}> (<t:{ts}:d>): {short(text)}" for nid, staff, text, ts in notes)
        embed.add_field(name="Заметки", value=value[:1024], inline=False)
    if verifs:
        value = "\n".join(
            f"{'✅ верифицирован' if action == 'verify' else '↩️ верификация снята'} — <@{staff}> (<t:{ts}:d>)"
            for action, staff, ts in verifs
        )
        embed.add_field(name="Верификация", value=value[:1024], inline=False)
    if not (punishments or notes or verifs):
        embed.description = "Записей об участнике нет."
    await interaction.response.send_message(embed=embed, ephemeral=True)


# ----------------------------------------------------------- профили
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
    c.execute(
        "SELECT COUNT(*) FROM support_log WHERE guild_id=? AND staff_id=? AND action='take'",
        (interaction.guild_id, target.id),
    )
    takes = c.fetchone()[0]
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
    embed.add_field(name="Взято из ожидания", value=str(takes), inline=True)
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

    role_lines = []
    for position in positions:
        role = interaction.guild.get_role(int(position["role_id"]))
        role_label = role.mention if role else f"**{discord.utils.escape_markdown(position['name'])}**"
        description = discord.utils.escape_markdown(position["description"] or "Открыто направление")
        role_lines.append(f"🟣 {role_label} — {description}")

    description = (
        "## ✨ Открыт набор в команду сервера\n"
        "Хочешь присоединиться к команде? Выбери направление в меню и отправь заявку.\n\n"
        + "\n".join(role_lines)
        + "\n\n*Заявки рассматривает администрация сервера.*"
    )
    embed = discord.Embed(
        title="🚀 Набор в команду",
        description=description[:4000],
        color=discord.Color.from_rgb(124, 92, 255),
    )
    banner_url = recruitment_setting("recruitment_banner_url").strip()
    if banner_url.startswith(("https://", "http://")):
        embed.set_image(url=banner_url)
    else:
        embed.set_image(url="attachment://recruitment-banner.png")
    embed.set_footer(text="Выберите роль в меню ниже · Набор открыт")
    if banner_url.startswith(("https://", "http://")):
        await target_channel.send(embed=embed, view=RecruitmentView(positions), allowed_mentions=discord.AllowedMentions(roles=False))
    else:
        banner_path = Path(__file__).resolve().parent.parent / "public" / "recruitment-banner.png"
        await target_channel.send(embed=embed, view=RecruitmentView(positions), file=discord.File(banner_path, filename="recruitment-banner.png"), allowed_mentions=discord.AllowedMentions(roles=False))
    await interaction.response.send_message(f"Карточка набора опубликована в {target_channel.mention}.", ephemeral=True)


# ------------------------------------------------------ верификация
@bot.tree.command(name="verf", description="Верифицировать пользователя")
@app_commands.guild_only()
@app_commands.describe(member="Кого верифицируем", gender="Пол")
@app_commands.choices(gender=[app_commands.Choice(name="Мальчик", value="boy"), app_commands.Choice(name="Девочка", value="girl")])
async def verf(interaction: discord.Interaction, member: discord.Member, gender: app_commands.Choice[str]):
    if not has_support(interaction.user):
        return await interaction.response.send_message("❌ Нет прав.", ephemeral=True)
    if not allowed_channel(interaction):
        return await interaction.response.send_message("❌ Канал недоступен.", ephemeral=True)
    if member.bot:
        return await interaction.response.send_message("❌ Нельзя верифицировать бота.", ephemeral=True)

    guild = interaction.guild
    if any(r.id in (ROLE_BOY, ROLE_GIRL) for r in member.roles):
        return await interaction.response.send_message("ℹ️ Участник уже верифицирован.", ephemeral=True)

    role = guild.get_role(ROLE_GIRL if gender.value == "girl" else ROLE_BOY)
    if role is None:
        return await interaction.response.send_message(
            "❌ Роль не найдена на сервере. Проверьте ROLE_BOY и ROLE_GIRL в config.", ephemeral=True
        )
    if role >= guild.me.top_role:
        return await interaction.response.send_message("❌ Роль бота ниже выдаваемой роли.", ephemeral=True)

    try:
        await member.add_roles(role, reason=f"Верификация: {interaction.user}")
        unv = guild.get_role(ROLE_UNVERIFY)
        if unv and unv in member.roles:
            await member.remove_roles(unv, reason=f"Верификация: {interaction.user}")
    except discord.Forbidden:
        return await interaction.response.send_message("❌ Нет прав у бота.", ephemeral=True)

    conn = database.get_db()
    c = conn.cursor()
    c.execute(
        "INSERT OR IGNORE INTO staff_profiles (user_id, guild_id, role_type) VALUES (?,?, 'support')",
        (interaction.user.id, interaction.guild_id),
    )
    c.execute(
        "UPDATE staff_profiles SET verifications = verifications + 1 WHERE user_id=? AND guild_id=?",
        (interaction.user.id, interaction.guild_id),
    )
    conn.commit()
    conn.close()
    log_support(interaction.guild_id, interaction.user.id, "verify", member.id, gender.value)

    embed = discord.Embed(title="✅ Верификация", color=discord.Color.green())
    embed.add_field(name="Участник", value=f"{member.mention} ({member.id})", inline=True)
    embed.add_field(name="Саппорт", value=interaction.user.mention, inline=True)
    embed.add_field(name="Пол", value="Девочка" if gender.value == "girl" else "Мальчик", inline=True)
    await send_log(guild, embed)

    await interaction.response.send_message(f"✅ {member.mention} верифицирован.", ephemeral=True)


@bot.tree.command(name="unverify", description="Снять верификацию (вернуть роль unverify)")
@app_commands.guild_only()
@app_commands.describe(member="Участник", reason="Причина")
async def unverify(interaction: discord.Interaction, member: discord.Member, reason: str = "Не указана"):
    if not has_support(interaction.user):
        return await interaction.response.send_message("❌ Нет прав.", ephemeral=True)
    if not allowed_channel(interaction):
        return await interaction.response.send_message("❌ Канал недоступен.", ephemeral=True)
    if member.bot:
        return await interaction.response.send_message("❌ Нельзя применить к боту.", ephemeral=True)

    guild = interaction.guild
    if member.top_role >= interaction.user.top_role and interaction.user.id != guild.owner_id:
        return await interaction.response.send_message("❌ Иерархия ролей.", ephemeral=True)

    to_remove = [r for r in member.roles if r.id in (ROLE_BOY, ROLE_GIRL)]
    if not to_remove:
        return await interaction.response.send_message("ℹ️ У участника нет роли верификации.", ephemeral=True)
    if any(r >= guild.me.top_role for r in to_remove):
        return await interaction.response.send_message("❌ Роль бота ниже снимаемой роли.", ephemeral=True)

    try:
        await member.remove_roles(*to_remove, reason=f"Снятие верификации: {interaction.user} — {reason}")
        unv = guild.get_role(ROLE_UNVERIFY)
        if unv and unv not in member.roles:
            await member.add_roles(unv, reason=f"Снятие верификации: {interaction.user}")
    except discord.Forbidden:
        return await interaction.response.send_message("❌ Нет прав у бота.", ephemeral=True)

    log_support(interaction.guild_id, interaction.user.id, "unverify", member.id, reason)

    embed = discord.Embed(title="↩️ Верификация снята", color=discord.Color.orange())
    embed.add_field(name="Участник", value=f"{member.mention} ({member.id})", inline=True)
    embed.add_field(name="Саппорт", value=interaction.user.mention, inline=True)
    embed.add_field(name="Причина", value=reason[:1024], inline=False)
    await send_log(guild, embed)

    await interaction.response.send_message(f"↩️ Верификация снята с {member.mention}.", ephemeral=True)


try:
    bot.run(TOKEN)
except discord.PrivilegedIntentsRequired:
    print(
        "ERROR: Server Members Intent is disabled. Open Discord Developer Portal -> your application -> "
        "Bot -> Privileged Gateway Intents, enable SERVER MEMBERS INTENT, then restart this bot."
    )
    raise SystemExit(1)
