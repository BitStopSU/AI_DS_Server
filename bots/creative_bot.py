"""Standalone Discord bot for creative staff and event tracking."""
from __future__ import annotations

import os
import sqlite3
import time
from pathlib import Path

import aiohttp
import discord
from discord import app_commands
from discord.ext import commands, tasks

ROOT = Path(__file__).resolve().parent.parent
DB_PATH = ROOT / "shared_bot_data.db"
TOKEN = os.getenv("BOT_TOKEN")


def connect():
    db = sqlite3.connect(DB_PATH, timeout=15)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA busy_timeout=15000")
    return db


def init_db():
    with connect() as db:
        db.executescript("""
            CREATE TABLE IF NOT EXISTS creative_members (
                guild_id TEXT NOT NULL, user_id TEXT NOT NULL, active INTEGER NOT NULL DEFAULT 1,
                created_at INTEGER NOT NULL, PRIMARY KEY(guild_id,user_id));
            CREATE TABLE IF NOT EXISTS creative_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT, guild_id TEXT NOT NULL,
                owner_id TEXT NOT NULL, title TEXT NOT NULL, details TEXT NOT NULL DEFAULT '',
                status TEXT NOT NULL DEFAULT 'open', created_at INTEGER NOT NULL,
                transferred_from TEXT);
            CREATE TABLE IF NOT EXISTS creative_actions (
                id INTEGER PRIMARY KEY AUTOINCREMENT, guild_id TEXT NOT NULL,
                creative_id TEXT NOT NULL, actor_id TEXT NOT NULL, action TEXT NOT NULL,
                details TEXT NOT NULL DEFAULT '', created_at INTEGER NOT NULL);
        """)


class CreativeBot(commands.Bot):
    def __init__(self):
        intents = discord.Intents.none()
        intents.guilds = True
        super().__init__(command_prefix="!", intents=intents)

    async def setup_hook(self):
        await self.tree.sync()
        heartbeat.start()


bot = CreativeBot()
creative = app_commands.Group(name="creative", description="Управление креативами и событиями")
bot.tree.add_command(creative)


@tasks.loop(seconds=60)
async def heartbeat():
    try:
        async with aiohttp.ClientSession() as session:
            await session.post("http://127.0.0.1:4477/api/heartbeat", json={"bot_id": "creative"}, timeout=4)
    except Exception:
        pass


@heartbeat.before_loop
async def before_heartbeat():
    await bot.wait_until_ready()


def is_admin(interaction: discord.Interaction) -> bool:
    return interaction.user.guild_permissions.manage_guild or interaction.user.guild_permissions.administrator


def is_creative(guild_id: int, user_id: int) -> bool:
    with connect() as db:
        row = db.execute("SELECT active FROM creative_members WHERE guild_id=? AND user_id=?", (str(guild_id), str(user_id))).fetchone()
    return bool(row and row["active"])


@bot.tree.command(name="afisha", description="Опубликовать анонс мероприятия")
@app_commands.guild_only()
@app_commands.describe(title="Название", when="Дата или время", details="Описание мероприятия")
async def afisha(interaction: discord.Interaction, title: app_commands.Range[str, 1, 180], when: app_commands.Range[str, 1, 100], details: app_commands.Range[str, 1, 1500]):
    if not is_admin(interaction) and not is_creative(interaction.guild_id, interaction.user.id):
        return await interaction.response.send_message("Команда доступна только креативам и администраторам.", ephemeral=True)
    embed = discord.Embed(title=title, description=details, color=discord.Color.blurple())
    embed.add_field(name="Когда", value=when)
    embed.set_footer(text=f"Анонс от {interaction.user.display_name}")
    await interaction.response.send_message(embed=embed)
    with connect() as db:
        db.execute("INSERT INTO creative_actions(guild_id,creative_id,actor_id,action,details,created_at) VALUES(?,?,?,?,?,?)", (str(interaction.guild_id),str(interaction.user.id),str(interaction.user.id),"afisha",title,int(time.time())))


@creative.command(name="action", description="Добавить или убрать креатива")
@app_commands.describe(member="Пользователь", action="add или remove")
async def creative_action(interaction: discord.Interaction, member: discord.Member, action: str):
    if not is_admin(interaction):
        return await interaction.response.send_message("Нужны права администратора сервера.", ephemeral=True)
    action = action.lower()
    if action not in {"add", "remove"}:
        return await interaction.response.send_message("Укажите действие add или remove.", ephemeral=True)
    active = int(action == "add")
    with connect() as db:
        db.execute("INSERT INTO creative_members(guild_id,user_id,active,created_at) VALUES(?,?,?,?) ON CONFLICT(guild_id,user_id) DO UPDATE SET active=excluded.active", (str(interaction.guild_id),str(member.id),active,int(time.time())))
        db.execute("INSERT INTO creative_actions(guild_id,creative_id,actor_id,action,details,created_at) VALUES(?,?,?,?,?,?)", (str(interaction.guild_id),str(member.id),str(interaction.user.id),action,"",int(time.time())))
    await interaction.response.send_message(f"{member.mention}: статус креатива обновлён.", ephemeral=True)


@creative.command(name="manage", description="Создать событие креатива")
@app_commands.describe(title="Название события", details="Описание")
async def creative_manage(interaction: discord.Interaction, title: app_commands.Range[str,1,180], details: app_commands.Range[str,1,1000]):
    if not is_admin(interaction) and not is_creative(interaction.guild_id, interaction.user.id):
        return await interaction.response.send_message("Команда доступна только креативам и администраторам.", ephemeral=True)
    with connect() as db:
        cur=db.execute("INSERT INTO creative_events(guild_id,owner_id,title,details,created_at) VALUES(?,?,?,?,?)", (str(interaction.guild_id),str(interaction.user.id),title,details,int(time.time())))
        event_id=cur.lastrowid
        db.execute("INSERT INTO creative_actions(guild_id,creative_id,actor_id,action,details,created_at) VALUES(?,?,?,?,?,?)", (str(interaction.guild_id),str(interaction.user.id),str(interaction.user.id),"create_event",str(event_id),int(time.time())))
    await interaction.response.send_message(f"Событие **#{event_id} {discord.utils.escape_markdown(title)}** создано.", ephemeral=True)


@creative.command(name="profile", description="Профиль креатива")
@app_commands.describe(member="Участник")
async def creative_profile(interaction: discord.Interaction, member: discord.Member | None = None):
    target=member or interaction.user
    with connect() as db:
        row=db.execute("SELECT COUNT(*) AS total FROM creative_events WHERE guild_id=? AND owner_id=?", (str(interaction.guild_id),str(target.id))).fetchone()
        actions=db.execute("SELECT COUNT(*) FROM creative_actions WHERE guild_id=? AND creative_id=?", (str(interaction.guild_id),str(target.id))).fetchone()[0]
        events=db.execute("SELECT id,title,status FROM creative_events WHERE guild_id=? AND owner_id=? ORDER BY id DESC LIMIT 5", (str(interaction.guild_id),str(target.id))).fetchall()
    embed=discord.Embed(title=f"Профиль креатива · {target.display_name}",color=discord.Color.blurple())
    embed.set_thumbnail(url=target.display_avatar.url)
    embed.add_field(name="Событий создано",value=str(row['total']))
    embed.add_field(name="Действий",value=str(actions))
    embed.add_field(name="Последние события",value="\n".join(f"#{e['id']} {discord.utils.escape_markdown(e['title'])} · {e['status']}" for e in events) or "Пока нет")
    await interaction.response.send_message(embed=embed,ephemeral=True)


@creative.command(name="stats", description="Статистика событий креативов")
async def creative_stats(interaction: discord.Interaction):
    with connect() as db:
        events=db.execute("SELECT owner_id,COUNT(*) AS n FROM creative_events WHERE guild_id=? GROUP BY owner_id ORDER BY n DESC LIMIT 10",(str(interaction.guild_id),)).fetchall()
        total=db.execute("SELECT COUNT(*) FROM creative_events WHERE guild_id=?",(str(interaction.guild_id),)).fetchone()[0]
        open_count=db.execute("SELECT COUNT(*) FROM creative_events WHERE guild_id=? AND status='open'",(str(interaction.guild_id),)).fetchone()[0]
    lines=[f"<@{r['owner_id']}> — {r['n']}" for r in events]
    await interaction.response.send_message(f"**События:** {total} всего, {open_count} открыто.\n"+("\n".join(lines) or "Данных пока нет."),ephemeral=True)


@creative.command(name="transfer", description="Передать событие другому креативу")
@app_commands.describe(event_id="Номер события", member="Новый владелец")
async def creative_transfer(interaction: discord.Interaction,event_id: int,member: discord.Member):
    with connect() as db:
        db.execute("BEGIN IMMEDIATE")
        event=db.execute("SELECT owner_id,title FROM creative_events WHERE guild_id=? AND id=? AND status='open'",(str(interaction.guild_id),event_id)).fetchone()
        if not event:
            db.rollback()
            return await interaction.response.send_message("Открытое событие не найдено.",ephemeral=True)
        if str(event['owner_id'])!=str(interaction.user.id) and not is_admin(interaction):
            db.rollback()
            return await interaction.response.send_message("Передать событие может его владелец или администратор.",ephemeral=True)
        if not is_admin(interaction) and not is_creative(interaction.guild_id,member.id):
            db.rollback()
            return await interaction.response.send_message("Новый владелец не состоит в креативе.",ephemeral=True)
        db.execute("UPDATE creative_events SET owner_id=?,transferred_from=? WHERE guild_id=? AND id=?",(str(member.id),event['owner_id'],str(interaction.guild_id),event_id))
        db.execute("INSERT INTO creative_actions(guild_id,creative_id,actor_id,action,details,created_at) VALUES(?,?,?,?,?,?)",(str(interaction.guild_id),str(member.id),str(interaction.user.id),"transfer",str(event_id),int(time.time())))
    await interaction.response.send_message(f"Событие **{discord.utils.escape_markdown(event['title'])}** передано {member.mention}.",ephemeral=True)


@bot.event
async def on_ready():
    print(f"Creative bot connected: {bot.user}")


if __name__ == "__main__":
    if not TOKEN:
        raise RuntimeError("CREATIVE_BOT_TOKEN is not configured in the dashboard")
    init_db()
    bot.run(TOKEN)
