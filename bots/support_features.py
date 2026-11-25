"""Additional support-team slash commands and persistent records."""
from __future__ import annotations

import sqlite3
import time
from pathlib import Path

import discord
from discord import app_commands


def register_support_commands(bot, database, config, can_staff, has_support, has_owner):
    def connect():
        return database.get_db()

    with connect() as db:
        db.executescript("""
            CREATE TABLE IF NOT EXISTS support_feature_warnings (
                id INTEGER PRIMARY KEY AUTOINCREMENT, guild_id TEXT NOT NULL,
                staff_id TEXT NOT NULL, actor_id TEXT NOT NULL, reason TEXT NOT NULL,
                created_at INTEGER NOT NULL);
            CREATE TABLE IF NOT EXISTS support_feature_twinks (
                guild_id TEXT NOT NULL, user_id TEXT NOT NULL, twink_id TEXT NOT NULL,
                note TEXT NOT NULL DEFAULT '', added_by TEXT NOT NULL, created_at INTEGER NOT NULL,
                PRIMARY KEY (guild_id, user_id, twink_id));
            CREATE TABLE IF NOT EXISTS support_feature_vacations (
                id INTEGER PRIMARY KEY AUTOINCREMENT, guild_id TEXT NOT NULL,
                user_id TEXT NOT NULL, starts_at TEXT NOT NULL, ends_at TEXT NOT NULL,
                reason TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'pending', created_at INTEGER NOT NULL);
            CREATE TABLE IF NOT EXISTS support_feature_mistakes (
                id INTEGER PRIMARY KEY AUTOINCREMENT, guild_id TEXT NOT NULL,
                staff_id TEXT NOT NULL, reporter_id TEXT NOT NULL, details TEXT NOT NULL,
                created_at INTEGER NOT NULL);
            CREATE TABLE IF NOT EXISTS support_feature_profiles (
                guild_id TEXT NOT NULL, user_id TEXT NOT NULL, telegram TEXT NOT NULL DEFAULT '',
                pkm_link TEXT NOT NULL DEFAULT '', pkm_count INTEGER NOT NULL DEFAULT 0,
                PRIMARY KEY (guild_id, user_id));
            CREATE TABLE IF NOT EXISTS support_feature_quests (
                id INTEGER PRIMARY KEY AUTOINCREMENT, guild_id TEXT NOT NULL,
                title TEXT NOT NULL, details TEXT NOT NULL DEFAULT '', active INTEGER NOT NULL DEFAULT 1);
            CREATE TABLE IF NOT EXISTS vacancy_blacklist (
                guild_id TEXT NOT NULL, user_id TEXT NOT NULL, reason TEXT NOT NULL,
                actor_id TEXT NOT NULL, created_at INTEGER NOT NULL, PRIMARY KEY(guild_id,user_id));
            CREATE TABLE IF NOT EXISTS vacancy_schedule (
                guild_id TEXT PRIMARY KEY, schedule TEXT NOT NULL, updated_by TEXT NOT NULL,
                updated_at INTEGER NOT NULL);
        """)

    def allowed(interaction, command):
        return can_staff(interaction.user, command) or has_owner(interaction.user)

    async def deny(interaction):
        await interaction.response.send_message("Нет прав для этой команды.", ephemeral=True)

    @bot.tree.command(name="swarn", description="Выдать предупреждение саппорту")
    @app_commands.guild_only()
    async def swarn(interaction: discord.Interaction, member: discord.Member, reason: app_commands.Range[str, 3, 500]):
        if not allowed(interaction, "swarn"):
            return await deny(interaction)
        with connect() as db:
            db.execute("INSERT INTO support_feature_warnings (guild_id, staff_id, actor_id, reason, created_at) VALUES (?, ?, ?, ?, ?)", (str(interaction.guild_id), str(member.id), str(interaction.user.id), reason, int(time.time())))
        await interaction.response.send_message(f"Предупреждение саппорту {member.mention} записано.", ephemeral=True)

    @bot.tree.command(name="teststats", description="Подробная статистика саппорта за неделю")
    @app_commands.guild_only()
    async def teststats(interaction: discord.Interaction, member: discord.Member | None = None):
        target = member or interaction.user
        if not allowed(interaction, "teststats") and target.id != interaction.user.id:
            return await deny(interaction)
        since = int(time.time()) - 7 * 86400
        with connect() as db:
            logs = db.execute("SELECT action, COUNT(*) AS n FROM support_log WHERE guild_id=? AND staff_id=? AND created_at>=? GROUP BY action", (interaction.guild_id, target.id, since)).fetchall()
            warnings = db.execute("SELECT COUNT(*) FROM support_feature_warnings WHERE guild_id=? AND staff_id=? AND created_at>=?", (str(interaction.guild_id), str(target.id), since)).fetchone()[0]
        summary = ", ".join(f"{row['action']}: {row['n']}" for row in logs) or "нет действий"
        await interaction.response.send_message(f"**Статистика {target.display_name} за 7 дней**\n{summary}\nПредупреждения: {warnings}", ephemeral=True)

    @bot.tree.command(name="addtwink", description="Добавить твинка участнику")
    @app_commands.guild_only()
    async def addtwink(interaction: discord.Interaction, member: discord.Member, account: str, note: str = ""):
        if not allowed(interaction, "addtwink"):
            return await deny(interaction)
        with connect() as db:
            db.execute("INSERT OR REPLACE INTO support_feature_twinks (guild_id,user_id,twink_id,note,added_by,created_at) VALUES (?,?,?,?,?,?)", (str(interaction.guild_id), str(member.id), account[:100], note[:300], str(interaction.user.id), int(time.time())))
        await interaction.response.send_message(f"Аккаунт `{discord.utils.escape_markdown(account[:100])}` записан для {member.mention}.", ephemeral=True)

    @bot.tree.command(name="twinks", description="Список твинков участника")
    @app_commands.guild_only()
    async def twinks(interaction: discord.Interaction, member: discord.Member | None = None):
        target = member or interaction.user
        if target.id != interaction.user.id and not allowed(interaction, "twinks"):
            return await deny(interaction)
        with connect() as db:
            rows = db.execute("SELECT twink_id,note FROM support_feature_twinks WHERE guild_id=? AND user_id=? ORDER BY created_at DESC LIMIT 20", (str(interaction.guild_id), str(target.id))).fetchall()
        text = "\n".join(f"• `{discord.utils.escape_markdown(row['twink_id'])}` — {discord.utils.escape_markdown(row['note']) or 'без заметки'}" for row in rows) or "Список пуст."
        await interaction.response.send_message(f"**Твинки {target.display_name}**\n{text}", ephemeral=True)

    @bot.tree.command(name="vacation", description="Подать заявку на отпуск")
    @app_commands.guild_only()
    async def vacation(interaction: discord.Interaction, starts: str, ends: str, reason: app_commands.Range[str, 3, 300]):
        if not has_support(interaction.user) and not has_owner(interaction.user):
            return await deny(interaction)
        with connect() as db:
            db.execute("INSERT INTO support_feature_vacations (guild_id,user_id,starts_at,ends_at,reason,created_at) VALUES (?,?,?,?,?,?)", (str(interaction.guild_id), str(interaction.user.id), starts[:40], ends[:40], reason, int(time.time())))
        await interaction.response.send_message("Заявка на отпуск сохранена. Даты укажите в формате ГГГГ-ММ-ДД.", ephemeral=True)

    @bot.tree.command(name="vacations", description="Посмотреть заявки на отпуск")
    @app_commands.guild_only()
    async def vacations(interaction: discord.Interaction):
        if not allowed(interaction, "vacations"):
            return await deny(interaction)
        with connect() as db:
            rows = db.execute("SELECT id,user_id,starts_at,ends_at,reason,status FROM support_feature_vacations WHERE guild_id=? ORDER BY id DESC LIMIT 15", (str(interaction.guild_id),)).fetchall()
        if not rows:
            return await interaction.response.send_message("Заявок на отпуск пока нет.", ephemeral=True)
        lines = [f"#{r['id']} <@{r['user_id']}> · {r['starts_at']} — {r['ends_at']} · {r['status']} · {discord.utils.escape_markdown(r['reason'])}" for r in rows]
        await interaction.response.send_message("\n".join(lines), ephemeral=True)

    async def top_support(interaction: discord.Interaction):
        if not allowed(interaction, "alltop"):
            return await deny(interaction)
        with connect() as db:
            rows = db.execute("SELECT staff_id,COUNT(*) AS n FROM support_log WHERE guild_id=? AND action='verify' GROUP BY staff_id ORDER BY n DESC LIMIT 10", (interaction.guild_id,)).fetchall()
        lines = [f"{i}. <@{r['staff_id']}> — {r['n']}" for i, r in enumerate(rows, 1)]
        await interaction.response.send_message("**Топ саппортов по верификациям**\n" + ("\n".join(lines) or "Пока нет данных."))

    @bot.tree.command(name="alltop", description="Топ саппортов за всё время")
    @app_commands.guild_only()
    async def alltop(interaction: discord.Interaction):
        await top_support(interaction)

    @bot.tree.command(name="gtop", description="Топ саппортов за всё время")
    @app_commands.guild_only()
    async def gtop(interaction: discord.Interaction):
        await top_support(interaction)

    @bot.tree.command(name="smistakeadd", description="Записать ошибку саппорта")
    @app_commands.guild_only()
    async def smistakeadd(interaction: discord.Interaction, member: discord.Member, details: app_commands.Range[str, 3, 800]):
        if not allowed(interaction, "smistakeadd"):
            return await deny(interaction)
        with connect() as db:
            db.execute("INSERT INTO support_feature_mistakes (guild_id,staff_id,reporter_id,details,created_at) VALUES (?,?,?,?,?)", (str(interaction.guild_id), str(member.id), str(interaction.user.id), details, int(time.time())))
        await interaction.response.send_message(f"Запись об ошибке {member.mention} добавлена.", ephemeral=True)

    @bot.tree.command(name="smistakes", description="Ошибки саппортов")
    @app_commands.guild_only()
    async def smistakes(interaction: discord.Interaction, member: discord.Member | None = None):
        if not allowed(interaction, "smistakes"):
            return await deny(interaction)
        with connect() as db:
            if member:
                rows = db.execute("SELECT id,staff_id,details,created_at FROM support_feature_mistakes WHERE guild_id=? AND staff_id=? ORDER BY id DESC LIMIT 15", (str(interaction.guild_id), str(member.id))).fetchall()
            else:
                rows = db.execute("SELECT id,staff_id,details,created_at FROM support_feature_mistakes WHERE guild_id=? ORDER BY id DESC LIMIT 15", (str(interaction.guild_id),)).fetchall()
        lines = [f"#{r['id']} <@{r['staff_id']}> · <t:{r['created_at']}:R> · {discord.utils.escape_markdown(r['details'])}" for r in rows]
        await interaction.response.send_message("\n".join(lines) or "Ошибок не записано.", ephemeral=True)

    @bot.tree.command(name="sadd", description="Выдать роль саппорта")
    @app_commands.guild_only()
    async def sadd(interaction: discord.Interaction, member: discord.Member):
        if not allowed(interaction, "sadd"):
            return await deny(interaction)
        role = interaction.guild.get_role(config.ROLE_SUPPORT)
        if not role or role >= interaction.guild.me.top_role:
            return await interaction.response.send_message("Роль саппорта не найдена или выше роли бота.", ephemeral=True)
        try:
            await member.add_roles(role, reason=f"Support role added by {interaction.user}")
        except discord.Forbidden:
            return await interaction.response.send_message("У бота нет права выдавать эту роль.", ephemeral=True)
        await interaction.response.send_message(f"Роль саппорта выдана {member.mention}.", ephemeral=True)

    @bot.tree.command(name="slist", description="Список саппортов")
    @app_commands.guild_only()
    async def slist(interaction: discord.Interaction):
        if not allowed(interaction, "slist"):
            return await deny(interaction)
        role = interaction.guild.get_role(config.ROLE_SUPPORT)
        members = [m.mention for m in role.members if not m.bot] if role else []
        text = "\n".join(members[:40]) or "Саппорты не найдены в кеше; проверьте роли сервера."
        await interaction.response.send_message(f"**Саппорты**\n{text}", ephemeral=True)

    @bot.tree.command(name="sprofile", description="Профиль саппорта")
    @app_commands.guild_only()
    async def sprofile(interaction: discord.Interaction, member: discord.Member | None = None):
        target = member or interaction.user
        if target.id != interaction.user.id and not allowed(interaction, "sprofile"):
            return await deny(interaction)
        with connect() as db:
            logs = db.execute("SELECT action,COUNT(*) AS n FROM support_log WHERE guild_id=? AND staff_id=? GROUP BY action", (interaction.guild_id,target.id)).fetchall()
            notes = db.execute("SELECT COUNT(*) FROM support_feature_mistakes WHERE guild_id=? AND staff_id=?", (str(interaction.guild_id),str(target.id))).fetchone()[0]
        summary = "\n".join(f"{r['action']}: {r['n']}" for r in logs) or "Действий пока нет."
        embed = discord.Embed(title=f"Профиль саппорта · {target.display_name}", color=discord.Color.blurple(), description=summary)
        embed.add_field(name="Ошибки", value=str(notes))
        embed.set_thumbnail(url=target.display_avatar.url)
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @bot.tree.command(name="spkmadd", description="Добавить очки ПKМ саппорту")
    @app_commands.guild_only()
    async def spkmadd(interaction: discord.Interaction, member: discord.Member, amount: app_commands.Range[int, 1, 10000]):
        if not allowed(interaction, "spkmadd"):
            return await deny(interaction)
        with connect() as db:
            db.execute("INSERT OR IGNORE INTO support_feature_profiles (guild_id,user_id) VALUES (?,?)", (str(interaction.guild_id),str(member.id)))
            db.execute("UPDATE support_feature_profiles SET pkm_count=pkm_count+? WHERE guild_id=? AND user_id=?", (amount,str(interaction.guild_id),str(member.id)))
        await interaction.response.send_message(f"Добавлено {amount} очков ПKМ для {member.mention}.", ephemeral=True)

    @bot.tree.command(name="spkmlink", description="Сохранить ссылку ПKМ саппорта")
    @app_commands.guild_only()
    async def spkmlink(interaction: discord.Interaction, link: app_commands.Range[str, 8, 300]):
        if not has_support(interaction.user) and not has_owner(interaction.user):
            return await deny(interaction)
        if not link.startswith(("https://", "http://")):
            return await interaction.response.send_message("Ссылка должна начинаться с http:// или https://.", ephemeral=True)
        with connect() as db:
            db.execute("INSERT OR IGNORE INTO support_feature_profiles (guild_id,user_id) VALUES (?,?)", (str(interaction.guild_id),str(interaction.user.id)))
            db.execute("UPDATE support_feature_profiles SET pkm_link=? WHERE guild_id=? AND user_id=?", (link,str(interaction.guild_id),str(interaction.user.id)))
        await interaction.response.send_message("Ссылка ПKМ сохранена.", ephemeral=True)

    @bot.tree.command(name="spkmrem", description="Снять очки ПKМ саппорту")
    @app_commands.guild_only()
    async def spkmrem(interaction: discord.Interaction, member: discord.Member, amount: app_commands.Range[int, 1, 10000]):
        if not allowed(interaction, "spkmrem"):
            return await deny(interaction)
        with connect() as db:
            db.execute("UPDATE support_feature_profiles SET pkm_count=MAX(0,pkm_count-?) WHERE guild_id=? AND user_id=?", (amount,str(interaction.guild_id),str(member.id)))
        await interaction.response.send_message(f"Обновлены очки ПKМ для {member.mention}.", ephemeral=True)

    async def pkm_stats(interaction: discord.Interaction, member: discord.Member | None):
        target = member or interaction.user
        if target.id != interaction.user.id and not allowed(interaction, "pkmstats"):
            return await deny(interaction)
        with connect() as db:
            row = db.execute("SELECT pkm_count,pkm_link FROM support_feature_profiles WHERE guild_id=? AND user_id=?", (str(interaction.guild_id),str(target.id))).fetchone()
        await interaction.response.send_message(f"**ПKМ · {target.display_name}**\nОчки: {row['pkm_count'] if row else 0}\nСсылка: {row['pkm_link'] if row and row['pkm_link'] else 'не задана'}", ephemeral=True)

    @bot.tree.command(name="pkmstats", description="Статистика ПKМ саппорта")
    @app_commands.guild_only()
    async def pkmstats(interaction: discord.Interaction, member: discord.Member | None = None):
        await pkm_stats(interaction, member)

    @bot.tree.command(name="ptstats", description="Статистика по праймтаймам саппорта")
    @app_commands.guild_only()
    async def ptstats(interaction: discord.Interaction, member: discord.Member | None = None):
        await pkm_stats(interaction, member)

    @bot.tree.command(name="slinktg", description="Указать Telegram саппорта")
    @app_commands.guild_only()
    async def slinktg(interaction: discord.Interaction, link: app_commands.Range[str, 3, 100]):
        if not has_support(interaction.user) and not has_owner(interaction.user):
            return await deny(interaction)
        if not link.startswith("https://t.me/"):
            return await interaction.response.send_message("Укажите ссылку вида https://t.me/username.", ephemeral=True)
        with connect() as db:
            db.execute("INSERT OR IGNORE INTO support_feature_profiles (guild_id,user_id) VALUES (?,?)", (str(interaction.guild_id),str(interaction.user.id)))
            db.execute("UPDATE support_feature_profiles SET telegram=? WHERE guild_id=? AND user_id=?", (link,str(interaction.guild_id),str(interaction.user.id)))
        await interaction.response.send_message("Telegram-ссылка сохранена.", ephemeral=True)

    @bot.tree.command(name="slink", description="Найти ссылку на замену саппорта")
    @app_commands.guild_only()
    async def slink(interaction: discord.Interaction):
        await interaction.response.send_message("Для поиска замены попросите администратора добавить доступных сотрудников через /slist.", ephemeral=True)

    @bot.tree.command(name="spcheck", description="Проверить профиль саппорта")
    @app_commands.guild_only()
    async def spcheck(interaction: discord.Interaction, member: discord.Member):
        if not allowed(interaction, "spcheck"):
            return await deny(interaction)
        is_support = any(r.id == config.ROLE_SUPPORT for r in member.roles)
        await interaction.response.send_message(f"{member.mention}: {'роль саппорта есть' if is_support else 'роли саппорта нет'}.", ephemeral=True)

    @bot.tree.command(name="sedprofile", description="Изменить профиль саппорта")
    @app_commands.guild_only()
    async def sedprofile(interaction: discord.Interaction, member: discord.Member, telegram: str = "", pkm_link: str = ""):
        if not allowed(interaction, "sedprofile"):
            return await deny(interaction)
        if telegram and not telegram.startswith("https://t.me/"):
            return await interaction.response.send_message("Telegram-ссылка должна начинаться с https://t.me/.", ephemeral=True)
        if pkm_link and not pkm_link.startswith(("https://", "http://")):
            return await interaction.response.send_message("Ссылка ПKМ должна быть http:// или https://.", ephemeral=True)
        with connect() as db:
            db.execute("INSERT OR IGNORE INTO support_feature_profiles (guild_id,user_id) VALUES (?,?)", (str(interaction.guild_id),str(member.id)))
            db.execute("UPDATE support_feature_profiles SET telegram=CASE WHEN ?='' THEN telegram ELSE ? END, pkm_link=CASE WHEN ?='' THEN pkm_link ELSE ? END WHERE guild_id=? AND user_id=?", (telegram,telegram,pkm_link,pkm_link,str(interaction.guild_id),str(member.id)))
        await interaction.response.send_message(f"Профиль {member.mention} обновлён.", ephemeral=True)

    @bot.tree.command(name="smpanel", description="Сводка панели саппорта")
    @app_commands.guild_only()
    async def smpanel(interaction: discord.Interaction):
        if not allowed(interaction, "smpanel"):
            return await deny(interaction)
        with connect() as db:
            counts = {
                "vacations": db.execute("SELECT COUNT(*) FROM support_feature_vacations WHERE guild_id=? AND status='pending'", (str(interaction.guild_id),)).fetchone()[0],
                "mistakes": db.execute("SELECT COUNT(*) FROM support_feature_mistakes WHERE guild_id=?", (str(interaction.guild_id),)).fetchone()[0],
                "warnings": db.execute("SELECT COUNT(*) FROM support_feature_warnings WHERE guild_id=?", (str(interaction.guild_id),)).fetchone()[0],
            }
        await interaction.response.send_message(f"Заявок на отпуск: {counts['vacations']} · ошибок: {counts['mistakes']} · предупреждений: {counts['warnings']}", ephemeral=True)

    @bot.tree.command(name="squest", description="Активные квесты саппортов")
    @app_commands.guild_only()
    async def squest(interaction: discord.Interaction):
        with connect() as db:
            rows = db.execute("SELECT title,details FROM support_feature_quests WHERE guild_id=? AND active=1 ORDER BY id DESC LIMIT 20", (str(interaction.guild_id),)).fetchall()
        text = "\n".join(f"• **{discord.utils.escape_markdown(r['title'])}** — {discord.utils.escape_markdown(r['details']) or 'без описания'}" for r in rows) or "Активных квестов пока нет."
        await interaction.response.send_message(text, ephemeral=True)

    @bot.tree.command(name="nedo", description="Выдать роль недопуска участнику")
    @app_commands.guild_only()
    async def nedo(interaction: discord.Interaction, member: discord.Member, reason: str = "Не указана"):
        if not allowed(interaction, "nedo"):
            return await deny(interaction)
        role = interaction.guild.get_role(config.ROLE_UNVERIFY)
        if not role or role >= interaction.guild.me.top_role:
            return await interaction.response.send_message("Роль недопуска не найдена или выше роли бота.", ephemeral=True)
        try:
            await member.add_roles(role, reason=reason[:400])
        except discord.Forbidden:
            return await interaction.response.send_message("У бота нет права выдать роль.", ephemeral=True)
        await interaction.response.send_message(f"Роль недопуска выдана {member.mention}.", ephemeral=True)

    @bot.tree.command(name="unnedo", description="Снять роль недопуска")
    @app_commands.guild_only()
    async def unnedo(interaction: discord.Interaction, member: discord.Member):
        if not allowed(interaction, "unnedo"):
            return await deny(interaction)
        role = interaction.guild.get_role(config.ROLE_UNVERIFY)
        if not role or role not in member.roles:
            return await interaction.response.send_message("У участника нет роли недопуска.", ephemeral=True)
        try:
            await member.remove_roles(role, reason=f"Недопуск снят {interaction.user}")
        except discord.Forbidden:
            return await interaction.response.send_message("У бота нет права снять роль.", ephemeral=True)
        await interaction.response.send_message(f"Роль недопуска снята с {member.mention}.", ephemeral=True)

    @bot.tree.command(name="uwu", description="Информация о верификации участника")
    @app_commands.guild_only()
    async def uwu(interaction: discord.Interaction, member: discord.Member):
        role_ids = {r.id for r in member.roles}
        verified = bool(role_ids.intersection({config.ROLE_BOY, config.ROLE_GIRL}))
        unverified = config.ROLE_UNVERIFY in role_ids
        text = "верифицирован" if verified else ("не верифицирован" if unverified else "статус не задан")
        await interaction.response.send_message(f"{member.mention}: {text}.", ephemeral=True)

    @bot.tree.command(name="cornsgive", description="Выдать бонус Chiil coin для ивента")
    @app_commands.guild_only()
    async def cornsgive(interaction: discord.Interaction, member: discord.Member, amount: app_commands.Range[int, 1, 100000]):
        if not allowed(interaction, "cornsgive"):
            return await deny(interaction)
        with connect() as db:
            db.execute("INSERT OR IGNORE INTO economy_accounts (guild_id,user_id) VALUES (?,?)", (str(interaction.guild_id),str(member.id)))
            db.execute("UPDATE economy_accounts SET balance=balance+?,earned=earned+? WHERE guild_id=? AND user_id=?", (amount,amount,str(interaction.guild_id),str(member.id)))
            db.execute("INSERT INTO economy_transactions (guild_id,receiver_id,amount,kind) VALUES (?,?,?,'support_event')", (str(interaction.guild_id),str(member.id),amount))
        await interaction.response.send_message(f"Выдано {amount} Chiil coin пользователю {member.mention}.", ephemeral=True)

    @bot.tree.command(name="vacancy-blacklist", description="Добавить или убрать участника из чёрного списка набора")
    @app_commands.guild_only()
    async def vacancy_blacklist(interaction: discord.Interaction, member: discord.Member, action: str, reason: str = ""):
        if not allowed(interaction, "vacancy-blacklist"):
            return await deny(interaction)
        if action not in {"add", "remove"}:
            return await interaction.response.send_message("Действие должно быть add или remove.", ephemeral=True)
        with connect() as db:
            if action == "add":
                db.execute("INSERT INTO vacancy_blacklist(guild_id,user_id,reason,actor_id,created_at) VALUES(?,?,?,?,?) ON CONFLICT(guild_id,user_id) DO UPDATE SET reason=excluded.reason,actor_id=excluded.actor_id,created_at=excluded.created_at", (str(interaction.guild_id),str(member.id),reason[:500],str(interaction.user.id),int(time.time())))
            else:
                db.execute("DELETE FROM vacancy_blacklist WHERE guild_id=? AND user_id=?", (str(interaction.guild_id),str(member.id)))
        await interaction.response.send_message(f"Чёрный список: {member.mention} — {action}.", ephemeral=True)

    @bot.tree.command(name="vacancy-schedule", description="Задать или посмотреть расписание набора")
    @app_commands.guild_only()
    async def vacancy_schedule(interaction: discord.Interaction, schedule: str = ""):
        if schedule:
            if not allowed(interaction, "vacancy-schedule"):
                return await deny(interaction)
            with connect() as db:
                db.execute("INSERT INTO vacancy_schedule(guild_id,schedule,updated_by,updated_at) VALUES(?,?,?,?) ON CONFLICT(guild_id) DO UPDATE SET schedule=excluded.schedule,updated_by=excluded.updated_by,updated_at=excluded.updated_at", (str(interaction.guild_id),schedule[:1500],str(interaction.user.id),int(time.time())))
        with connect() as db:
            row=db.execute("SELECT schedule,updated_by,updated_at FROM vacancy_schedule WHERE guild_id=?", (str(interaction.guild_id),)).fetchone()
        await interaction.response.send_message(f"**Расписание набора**\n{row['schedule'] if row else 'Расписание пока не задано.'}",ephemeral=True)

    @bot.tree.command(name="vacancy-settings", description="Настройки набора персонала")
    @app_commands.guild_only()
    async def vacancy_settings(interaction: discord.Interaction):
        if not allowed(interaction, "vacancy-settings"):
            return await deny(interaction)
        conn=sqlite3.connect(Path(__file__).resolve().parent.parent / "data.db")
        try:
            positions=conn.execute("SELECT name,active FROM recruitment_positions ORDER BY sort_order,name").fetchall()
            settings=conn.execute("SELECT key,value FROM settings WHERE key LIKE 'recruitment_%'").fetchall()
        finally:
            conn.close()
        active=sum(1 for _,enabled in positions if enabled)
        await interaction.response.send_message(f"Открытых направлений: {active}\nКанал публикации: {dict(settings).get('recruitment_channel_id','не задан')}\nURL баннера: {'задан' if dict(settings).get('recruitment_banner_url') else 'используется встроенный'}",ephemeral=True)

    @bot.tree.command(name="vacancy-send", description="Опубликовать набор в текущий канал")
    @app_commands.guild_only()
    async def vacancy_send(interaction: discord.Interaction):
        if not allowed(interaction, "recruit_post"):
            return await deny(interaction)
        conn=sqlite3.connect(Path(__file__).resolve().parent.parent / "data.db")
        try:
            positions=conn.execute("SELECT role_id,name,description FROM recruitment_positions WHERE active=1 ORDER BY sort_order,name LIMIT 25").fetchall()
            banner=conn.execute("SELECT value FROM settings WHERE key='recruitment_banner_url'").fetchone()
        finally:
            conn.close()
        if not positions:
            return await interaction.response.send_message("Открытых вакансий нет.",ephemeral=True)
        lines=[]
        for role_id,name,description in positions:
            role=interaction.guild.get_role(int(role_id))
            mention=role.mention if role else f"**{discord.utils.escape_markdown(name)}**"
            lines.append(f"🟣 {mention} — {discord.utils.escape_markdown(description or 'Открытое направление')}")
        embed=discord.Embed(title="🚀 Набор в команду",description="Выбери направление в меню и отправь заявку.\n\n"+"\n".join(lines),color=discord.Color.from_rgb(124,92,255))
        banner_url=banner[0].strip() if banner and banner[0] else ""
        if banner_url.startswith(("https://","http://")):
            embed.set_image(url=banner_url)
        embed.set_footer(text="Выберите роль в меню ниже · Набор открыт")
        await interaction.channel.send(embed=embed,allowed_mentions=discord.AllowedMentions(roles=False))
        await interaction.response.send_message("Объявление набора отправлено в этот канал.",ephemeral=True)
