"""Tribunal schedule, quests and shop commands for the support bot."""
from __future__ import annotations

import sqlite3
import time

import discord
from discord import app_commands


def register_tribunal_commands(bot, database, can_staff, has_owner):
    def connect():
        return database.get_db()

    with connect() as db:
        db.executescript("""
            CREATE TABLE IF NOT EXISTS tribunal_members (
                guild_id TEXT NOT NULL, user_id TEXT NOT NULL, joined_at INTEGER NOT NULL,
                profile TEXT NOT NULL DEFAULT '', status TEXT NOT NULL DEFAULT 'active',
                PRIMARY KEY (guild_id,user_id));
            CREATE TABLE IF NOT EXISTS tribunal_schedule (
                id INTEGER PRIMARY KEY AUTOINCREMENT, guild_id TEXT NOT NULL,
                user_id TEXT NOT NULL, schedule TEXT NOT NULL, updated_by TEXT NOT NULL,
                updated_at INTEGER NOT NULL);
            CREATE TABLE IF NOT EXISTS tribunal_quests (
                id INTEGER PRIMARY KEY AUTOINCREMENT, guild_id TEXT NOT NULL,
                title TEXT NOT NULL, description TEXT NOT NULL DEFAULT '', active INTEGER NOT NULL DEFAULT 1);
            CREATE TABLE IF NOT EXISTS tribunal_shop (
                id INTEGER PRIMARY KEY AUTOINCREMENT, guild_id TEXT NOT NULL,
                name TEXT NOT NULL, description TEXT NOT NULL DEFAULT '', price INTEGER NOT NULL CHECK(price >= 0), active INTEGER NOT NULL DEFAULT 1);
            CREATE TABLE IF NOT EXISTS tribunal_warnings (
                id INTEGER PRIMARY KEY AUTOINCREMENT, guild_id TEXT NOT NULL,
                user_id TEXT NOT NULL, actor_id TEXT NOT NULL, reason TEXT NOT NULL, created_at INTEGER NOT NULL);
        """)

    def permitted(interaction, command):
        return has_owner(interaction.user) or can_staff(interaction.user, command)

    async def deny(interaction):
        await interaction.response.send_message("Нет прав для этой команды.", ephemeral=True)

    @bot.tree.command(name="tadd", description="Добавить участника в трибунал")
    @app_commands.guild_only()
    async def tadd(interaction: discord.Interaction, member: discord.Member):
        if not permitted(interaction, "tadd"):
            return await deny(interaction)
        with connect() as db:
            db.execute("INSERT OR IGNORE INTO tribunal_members(guild_id,user_id,joined_at) VALUES(?,?,?)", (str(interaction.guild_id),str(member.id),int(time.time())))
        await interaction.response.send_message(f"{member.mention} добавлен в список трибунала.", ephemeral=True)

    @bot.tree.command(name="trem", description="Убрать участника из трибунала")
    @app_commands.guild_only()
    async def trem(interaction: discord.Interaction, member: discord.Member):
        if not permitted(interaction, "trem"):
            return await deny(interaction)
        with connect() as db:
            db.execute("DELETE FROM tribunal_members WHERE guild_id=? AND user_id=?", (str(interaction.guild_id),str(member.id)))
        await interaction.response.send_message(f"{member.mention} удалён из списка трибунала.", ephemeral=True)

    @bot.tree.command(name="tedit", description="Изменить расписание трибунала")
    @app_commands.guild_only()
    async def tedit(interaction: discord.Interaction, member: discord.Member, schedule: app_commands.Range[str,1,300]):
        if not permitted(interaction, "tedit"):
            return await deny(interaction)
        with connect() as db:
            db.execute("INSERT INTO tribunal_schedule(guild_id,user_id,schedule,updated_by,updated_at) VALUES(?,?,?,?,?)", (str(interaction.guild_id),str(member.id),schedule,str(interaction.user.id),int(time.time())))
            db.execute("INSERT OR IGNORE INTO tribunal_members(guild_id,user_id,joined_at) VALUES(?,?,?)", (str(interaction.guild_id),str(member.id),int(time.time())))
        await interaction.response.send_message(f"Расписание {member.mention} обновлено.", ephemeral=True)

    @bot.tree.command(name="tlist", description="Показать список трибунала")
    @app_commands.guild_only()
    async def tlist(interaction: discord.Interaction):
        with connect() as db:
            rows=db.execute("SELECT user_id,status FROM tribunal_members WHERE guild_id=? ORDER BY joined_at",(str(interaction.guild_id),)).fetchall()
        await interaction.response.send_message("\n".join(f"<@{r['user_id']}> · {r['status']}" for r in rows) or "Список трибунала пуст.",ephemeral=True)

    @bot.tree.command(name="tprofedit", description="Изменить профиль трибунала")
    @app_commands.guild_only()
    async def tprofedit(interaction: discord.Interaction, member: discord.Member, profile: app_commands.Range[str,1,800]):
        if not permitted(interaction,"tprofedit"):
            return await deny(interaction)
        with connect() as db:
            db.execute("INSERT INTO tribunal_members(guild_id,user_id,joined_at,profile) VALUES(?,?,?,?) ON CONFLICT(guild_id,user_id) DO UPDATE SET profile=excluded.profile",(str(interaction.guild_id),str(member.id),int(time.time()),profile))
        await interaction.response.send_message(f"Профиль {member.mention} обновлён.",ephemeral=True)

    @bot.tree.command(name="tprofile", description="Профиль участника трибунала")
    @app_commands.guild_only()
    async def tprofile(interaction: discord.Interaction, member: discord.Member):
        with connect() as db:
            row=db.execute("SELECT profile,status,joined_at FROM tribunal_members WHERE guild_id=? AND user_id=?",(str(interaction.guild_id),str(member.id))).fetchone()
            schedule=db.execute("SELECT schedule FROM tribunal_schedule WHERE guild_id=? AND user_id=? ORDER BY id DESC LIMIT 1",(str(interaction.guild_id),str(member.id))).fetchone()
            warnings=db.execute("SELECT COUNT(*) FROM tribunal_warnings WHERE guild_id=? AND user_id=?",(str(interaction.guild_id),str(member.id))).fetchone()[0]
        if not row:
            return await interaction.response.send_message("Профиль не найден.",ephemeral=True)
        embed=discord.Embed(title=f"Трибунал · {member.display_name}",description=row['profile'] or "Профиль не заполнен.",color=discord.Color.blurple())
        embed.add_field(name="Статус",value=row['status'])
        embed.add_field(name="Расписание",value=schedule['schedule'] if schedule else "Не задано")
        embed.add_field(name="Предупреждения",value=str(warnings))
        embed.set_thumbnail(url=member.display_avatar.url)
        await interaction.response.send_message(embed=embed,ephemeral=True)

    @bot.tree.command(name="tquestadd", description="Добавить квест трибунала")
    @app_commands.guild_only()
    async def tquestadd(interaction: discord.Interaction, title: app_commands.Range[str,1,100], description: str = ""):
        if not permitted(interaction,"tquestadd"):
            return await deny(interaction)
        with connect() as db:
            db.execute("INSERT INTO tribunal_quests(guild_id,title,description) VALUES(?,?,?)",(str(interaction.guild_id),title,description[:500]))
        await interaction.response.send_message("Квест добавлен.",ephemeral=True)

    @bot.tree.command(name="tquest", description="Показать квесты трибунала")
    @app_commands.guild_only()
    async def tquest(interaction: discord.Interaction):
        with connect() as db:
            rows=db.execute("SELECT id,title,description FROM tribunal_quests WHERE guild_id=? AND active=1 ORDER BY id DESC LIMIT 20",(str(interaction.guild_id),)).fetchall()
        await interaction.response.send_message("\n".join(f"#{r['id']} **{discord.utils.escape_markdown(r['title'])}** — {discord.utils.escape_markdown(r['description']) or 'без описания'}" for r in rows) or "Активных квестов нет.",ephemeral=True)

    @bot.tree.command(name="tquestmanage", description="Включить или закрыть квест")
    @app_commands.guild_only()
    async def tquestmanage(interaction: discord.Interaction, quest_id: int, active: bool):
        if not permitted(interaction,"tquestmanage"):
            return await deny(interaction)
        with connect() as db:
            cur=db.execute("UPDATE tribunal_quests SET active=? WHERE guild_id=? AND id=?",(int(active),str(interaction.guild_id),quest_id))
        await interaction.response.send_message("Квест обновлён." if cur.rowcount else "Квест не найден.",ephemeral=True)

    @bot.tree.command(name="tshopadd", description="Добавить предмет в магазин трибунала")
    @app_commands.guild_only()
    async def tshopadd(interaction: discord.Interaction, name: app_commands.Range[str,1,100], price: app_commands.Range[int,0,100000000], description: str = ""):
        if not permitted(interaction,"tshopadd"):
            return await deny(interaction)
        with connect() as db:
            db.execute("INSERT INTO tribunal_shop(guild_id,name,description,price) VALUES(?,?,?,?)",(str(interaction.guild_id),name,description[:500],price))
        await interaction.response.send_message("Предмет добавлен в магазин.",ephemeral=True)

    @bot.tree.command(name="tshop", description="Магазин трибунала")
    @app_commands.guild_only()
    async def tshop(interaction: discord.Interaction):
        with connect() as db:
            rows=db.execute("SELECT id,name,description,price FROM tribunal_shop WHERE guild_id=? AND active=1 ORDER BY price",(str(interaction.guild_id),)).fetchall()
        await interaction.response.send_message("\n".join(f"#{r['id']} **{discord.utils.escape_markdown(r['name'])}** · {r['price']} · {discord.utils.escape_markdown(r['description'])}" for r in rows) or "Магазин пуст.",ephemeral=True)

    @bot.tree.command(name="tshopmanage", description="Управление магазином трибунала")
    @app_commands.guild_only()
    async def tshopmanage(interaction: discord.Interaction, item_id: int, active: bool):
        if not permitted(interaction,"tshopmanage"):
            return await deny(interaction)
        with connect() as db:
            cur=db.execute("UPDATE tribunal_shop SET active=? WHERE guild_id=? AND id=?",(int(active),str(interaction.guild_id),item_id))
        await interaction.response.send_message("Предмет обновлён." if cur.rowcount else "Предмет не найден.",ephemeral=True)

    @bot.tree.command(name="tstatus", description="Просмотр и управление статусом трибунала")
    @app_commands.guild_only()
    async def tstatus(interaction: discord.Interaction, member: discord.Member, status: str = "active"):
        if not permitted(interaction,"tstatus"):
            return await deny(interaction)
        if status not in {"active","paused","removed"}:
            return await interaction.response.send_message("Статус: active, paused или removed.",ephemeral=True)
        with connect() as db:
            db.execute("INSERT INTO tribunal_members(guild_id,user_id,joined_at,status) VALUES(?,?,?,?) ON CONFLICT(guild_id,user_id) DO UPDATE SET status=excluded.status",(str(interaction.guild_id),str(member.id),int(time.time()),status))
        await interaction.response.send_message(f"Статус {member.mention}: {status}.",ephemeral=True)

    @bot.tree.command(name="ttribuna", description="Открыть или закрыть трибун")
    @app_commands.guild_only()
    async def ttribuna(interaction: discord.Interaction, action: str, member: discord.Member):
        if not permitted(interaction,"ttribuna"):
            return await deny(interaction)
        if action not in {"open","close"}:
            return await interaction.response.send_message("Действие: open или close.",ephemeral=True)
        status="active" if action=="open" else "paused"
        with connect() as db:
            db.execute("INSERT INTO tribunal_members(guild_id,user_id,joined_at,status) VALUES(?,?,?,?) ON CONFLICT(guild_id,user_id) DO UPDATE SET status=excluded.status",(str(interaction.guild_id),str(member.id),int(time.time()),status))
        await interaction.response.send_message(f"Трибун {member.mention}: {status}.",ephemeral=True)

    @bot.tree.command(name="ttribunes", description="Расписание трибун на месяц")
    @app_commands.guild_only()
    async def ttribunes(interaction: discord.Interaction):
        with connect() as db:
            rows=db.execute("SELECT s.user_id,s.schedule FROM tribunal_schedule s JOIN (SELECT user_id,MAX(id) id FROM tribunal_schedule WHERE guild_id=? GROUP BY user_id) latest ON latest.id=s.id WHERE s.guild_id=? ORDER BY s.schedule",(str(interaction.guild_id),str(interaction.guild_id))).fetchall()
        await interaction.response.send_message("\n".join(f"<@{r['user_id']}> — {discord.utils.escape_markdown(r['schedule'])}" for r in rows) or "Расписание пока пусто.",ephemeral=True)

    @bot.tree.command(name="twarn", description="Выдать предупреждение участнику трибунала")
    @app_commands.guild_only()
    async def twarn(interaction: discord.Interaction, member: discord.Member, reason: app_commands.Range[str,3,500]):
        if not permitted(interaction,"twarn"):
            return await deny(interaction)
        with connect() as db:
            db.execute("INSERT INTO tribunal_warnings(guild_id,user_id,actor_id,reason,created_at) VALUES(?,?,?,?,?)",(str(interaction.guild_id),str(member.id),str(interaction.user.id),reason,int(time.time())))
            count=db.execute("SELECT COUNT(*) FROM tribunal_warnings WHERE guild_id=? AND user_id=?",(str(interaction.guild_id),str(member.id))).fetchone()[0]
        await interaction.response.send_message(f"Предупреждение {member.mention} записано. Всего: {count}.",ephemeral=True)
