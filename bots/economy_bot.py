"""Standalone Discord economy bot for Chiil coin."""
from __future__ import annotations

import aiohttp
import io
import os
import sqlite3
import time
from pathlib import Path

import discord
from discord import app_commands
from discord.ext import commands, tasks
from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parent.parent
DB_PATH = ROOT / "shared_bot_data.db"
TOKEN = os.getenv("BOT_TOKEN")
CURRENCY = "Chiil coin"
DAILY_AMOUNT = 100
DAILY_COOLDOWN = 24 * 60 * 60
PROFILE_BACKGROUND = ROOT / "public" / "profile-background.png"

def connect() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH, timeout=15)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA busy_timeout = 15000")
    return conn


def init_db() -> None:
    with connect() as db:
        db.execute("""
            CREATE TABLE IF NOT EXISTS economy_accounts (
                guild_id TEXT NOT NULL,
                user_id TEXT NOT NULL,
                balance INTEGER NOT NULL DEFAULT 0 CHECK(balance >= 0),
                earned INTEGER NOT NULL DEFAULT 0 CHECK(earned >= 0),
                spent INTEGER NOT NULL DEFAULT 0 CHECK(spent >= 0),
                daily_at INTEGER NOT NULL DEFAULT 0,
                created_at INTEGER NOT NULL DEFAULT (unixepoch()),
                PRIMARY KEY (guild_id, user_id)
            )
        """)
        db.execute("""
            CREATE TABLE IF NOT EXISTS economy_shop_roles (
                guild_id TEXT NOT NULL,
                role_id TEXT NOT NULL,
                price INTEGER NOT NULL CHECK(price > 0),
                PRIMARY KEY (guild_id, role_id)
            )
        """)
        db.execute("""
            CREATE TABLE IF NOT EXISTS economy_transactions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                guild_id TEXT NOT NULL,
                sender_id TEXT,
                receiver_id TEXT NOT NULL,
                amount INTEGER NOT NULL CHECK(amount > 0),
                kind TEXT NOT NULL,
                created_at INTEGER NOT NULL DEFAULT (unixepoch())
            )
        """)
        db.execute("CREATE INDEX IF NOT EXISTS idx_economy_top ON economy_accounts(guild_id, balance DESC)")


def ensure_account(db: sqlite3.Connection, guild_id: int, user_id: int) -> sqlite3.Row:
    db.execute(
        "INSERT OR IGNORE INTO economy_accounts (guild_id, user_id) VALUES (?, ?)",
        (str(guild_id), str(user_id)),
    )
    return db.execute(
        "SELECT * FROM economy_accounts WHERE guild_id = ? AND user_id = ?",
        (str(guild_id), str(user_id)),
    ).fetchone()


class EconomyBot(commands.Bot):
    def __init__(self) -> None:
        intents = discord.Intents.none()
        intents.guilds = True
        # Slash-command interactions provide resolved members; no privileged member intent needed.
        super().__init__(command_prefix="!", intents=intents)

    async def setup_hook(self) -> None:
        await self.tree.sync()
        heartbeat.start()


bot = EconomyBot()


@tasks.loop(seconds=60)
async def heartbeat() -> None:
    try:
        async with aiohttp.ClientSession() as session:
            await session.post("http://127.0.0.1:4477/api/heartbeat", json={"bot_id": "economy"}, timeout=4)
    except Exception:
        pass


@heartbeat.before_loop
async def before_heartbeat() -> None:
    await bot.wait_until_ready()


@bot.tree.command(name="balance", description="Проверить баланс Chiil coin")
@app_commands.guild_only()
@app_commands.describe(member="Участник, чей баланс посмотреть")
async def balance(interaction: discord.Interaction, member: discord.Member | None = None) -> None:
    target = member or interaction.user
    with connect() as db:
        account = ensure_account(db, interaction.guild_id, target.id)
    await interaction.response.send_message(
        f"**{target.display_name}**: **{account['balance']:,} {CURRENCY}**".replace(",", " "),
        ephemeral=target.id == interaction.user.id,
    )


@bot.tree.command(name="daily", description="Забрать ежедневную награду")
@app_commands.guild_only()
async def daily(interaction: discord.Interaction) -> None:
    now = int(time.time())
    with connect() as db:
        account = ensure_account(db, interaction.guild_id, interaction.user.id)
        next_at = account["daily_at"] + DAILY_COOLDOWN
        if now < next_at:
            remaining = next_at - now
            hours, rem = divmod(remaining, 3600)
            minutes = rem // 60
            return await interaction.response.send_message(
                f"Ежедневная награда будет доступна через {hours} ч. {minutes} мин.", ephemeral=True
            )
        db.execute(
            "UPDATE economy_accounts SET balance = balance + ?, earned = earned + ?, daily_at = ? "
            "WHERE guild_id = ? AND user_id = ?",
            (DAILY_AMOUNT, DAILY_AMOUNT, now, str(interaction.guild_id), str(interaction.user.id)),
        )
        db.execute(
            "INSERT INTO economy_transactions (guild_id, receiver_id, amount, kind) VALUES (?, ?, ?, 'daily')",
            (str(interaction.guild_id), str(interaction.user.id), DAILY_AMOUNT),
        )
    await interaction.response.send_message(f"Получено **{DAILY_AMOUNT} {CURRENCY}**!", ephemeral=True)


@bot.tree.command(name="give", description="Передать Chiil coin участнику")
@app_commands.guild_only()
@app_commands.describe(member="Получатель", amount="Сумма перевода")
async def give(interaction: discord.Interaction, member: discord.Member, amount: app_commands.Range[int, 1, 1_000_000_000]) -> None:
    if member.bot or member.id == interaction.user.id:
        return await interaction.response.send_message("Нельзя переводить себе или ботам.", ephemeral=True)
    guild_id = str(interaction.guild_id)
    sender_id, receiver_id = str(interaction.user.id), str(member.id)
    with connect() as db:
        db.execute("BEGIN IMMEDIATE")
        sender = ensure_account(db, interaction.guild_id, interaction.user.id)
        if sender["balance"] < amount:
            db.rollback()
            return await interaction.response.send_message("Недостаточно средств.", ephemeral=True)
        ensure_account(db, interaction.guild_id, member.id)
        db.execute("UPDATE economy_accounts SET balance = balance - ?, spent = spent + ? WHERE guild_id=? AND user_id=?", (amount, amount, guild_id, sender_id))
        db.execute("UPDATE economy_accounts SET balance = balance + ?, earned = earned + ? WHERE guild_id=? AND user_id=?", (amount, amount, guild_id, receiver_id))
        db.execute("INSERT INTO economy_transactions (guild_id, sender_id, receiver_id, amount, kind) VALUES (?, ?, ?, ?, 'transfer')", (guild_id, sender_id, receiver_id, amount))
    await interaction.response.send_message(f"Переведено **{amount:,} {CURRENCY}** пользователю {member.mention}.".replace(",", " "))


def load_font(size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    candidates = [
        Path(os.environ.get("WINDIR", "C:/Windows")) / "Fonts" / "arial.ttf",
        Path("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"),
    ]
    for candidate in candidates:
        try:
            return ImageFont.truetype(str(candidate), size)
        except OSError:
            continue
    return ImageFont.load_default()


def render_profile(user: discord.abc.User, account: sqlite3.Row, rank: int) -> io.BytesIO:
    if PROFILE_BACKGROUND.is_file():
        try:
            canvas = Image.open(PROFILE_BACKGROUND).convert("RGB").resize((900, 360))
        except OSError:
            canvas = Image.new("RGB", (900, 360), "#171d29")
    else:
        canvas = Image.new("RGB", (900, 360), "#171d29")
    draw = ImageDraw.Draw(canvas, "RGBA")
    draw.rounded_rectangle((24, 24, 876, 336), radius=28, fill=(20, 27, 39, 225), outline=(100, 120, 155, 150), width=2)
    draw.rounded_rectangle((48, 48, 294, 312), radius=22, fill=(40, 52, 69, 235))
    draw.rounded_rectangle((318, 48, 850, 312), radius=22, fill=(30, 38, 51, 220))
    draw.text((70, 70), user.display_name[:22], font=load_font(32), fill="#f3f5fa")
    draw.text((70, 128), f"{account['balance']:,} {CURRENCY}".replace(",", " "), font=load_font(22), fill="#a9d4ff")
    draw.text((70, 177), f"Рейтинг: #{rank}", font=load_font(18), fill="#d8deea")
    draw.text((350, 82), "Профиль экономики", font=load_font(26), fill="#ffffff")
    draw.text((350, 145), f"Заработано: {account['earned']:,}".replace(",", " "), font=load_font(21), fill="#e8edf5")
    draw.text((350, 195), f"Потрачено: {account['spent']:,}", font=load_font(21), fill="#e8edf5")
    draw.text((350, 245), "Валюта: Chiil coin", font=load_font(19), fill="#a9d4ff")
    output = io.BytesIO()
    canvas.save(output, format="PNG")
    output.seek(0)
    return output


@bot.tree.command(name="profile", description="Показать карточку экономического профиля")
@app_commands.guild_only()
@app_commands.describe(member="Участник")
async def profile(interaction: discord.Interaction, member: discord.Member | None = None) -> None:
    target = member or interaction.user
    with connect() as db:
        account = ensure_account(db, interaction.guild_id, target.id)
        rank_row = db.execute(
            "SELECT COUNT(*) + 1 AS rank FROM economy_accounts WHERE guild_id=? AND balance > ?",
            (str(interaction.guild_id), account["balance"]),
        ).fetchone()
    image = render_profile(target, account, rank_row["rank"])
    try:
        avatar_bytes = await target.display_avatar.replace(size=256, static_format="png").read()
        avatar = Image.open(io.BytesIO(avatar_bytes)).convert("RGBA").resize((132, 132))
        mask = Image.new("L", avatar.size, 0)
        ImageDraw.Draw(mask).ellipse((0, 0, 131, 131), fill=255)
        card = Image.open(image).convert("RGBA")
        card.paste(avatar, (105, 115), mask)
        image = io.BytesIO()
        card.convert("RGB").save(image, format="PNG")
        image.seek(0)
    except (discord.HTTPException, OSError):
        image.seek(0)
    await interaction.response.send_message(file=discord.File(image, filename="chiil-profile.png"))


@bot.tree.command(name="top", description="Рейтинг участников по Chiil coin")
@app_commands.guild_only()
async def top(interaction: discord.Interaction) -> None:
    with connect() as db:
        rows = db.execute(
            "SELECT user_id, balance FROM economy_accounts WHERE guild_id=? ORDER BY balance DESC LIMIT 10",
            (str(interaction.guild_id),),
        ).fetchall()
    if not rows:
        return await interaction.response.send_message("Рейтинг пока пуст.", ephemeral=True)
    lines = [f"**{i}.** <@{row['user_id']}> — {row['balance']:,} {CURRENCY}".replace(",", " ") for i, row in enumerate(rows, 1)]
    await interaction.response.send_message("\n".join(lines))


@bot.tree.command(name="shop", description="Магазин ролей за Chiil coin")
@app_commands.guild_only()
async def shop(interaction: discord.Interaction) -> None:
    with connect() as db:
        rows = db.execute(
            "SELECT role_id, price FROM economy_shop_roles WHERE guild_id=? ORDER BY price, role_id",
            (str(interaction.guild_id),),
        ).fetchall()
    if not rows:
        return await interaction.response.send_message("Магазин пока пуст. Администратор может добавить роли командой /shop-add.", ephemeral=True)
    embed = discord.Embed(title="Магазин ролей", description="Покупка выдаёт роль за Chiil coin.", color=discord.Color.blurple())
    for row in rows[:25]:
        role = interaction.guild.get_role(int(row["role_id"]))
        if role:
            embed.add_field(name=role.name, value=f"{row['price']:,} {CURRENCY} · `/shop-buy role_id:{role.id}`".replace(",", " "), inline=False)
    await interaction.response.send_message(embed=embed, ephemeral=True)


@bot.tree.command(name="shop-add", description="Добавить роль в магазин (администратор)")
@app_commands.guild_only()
@app_commands.default_permissions(administrator=True)
@app_commands.describe(role="Роль для продажи", price="Цена в Chiil coin")
async def shop_add(interaction: discord.Interaction, role: discord.Role, price: app_commands.Range[int, 1, 1_000_000_000]) -> None:
    if role.is_default() or role.managed or role >= interaction.guild.me.top_role:
        return await interaction.response.send_message("Эту роль нельзя продавать: проверьте иерархию ролей бота.", ephemeral=True)
    with connect() as db:
        db.execute(
            "INSERT INTO economy_shop_roles (guild_id, role_id, price) VALUES (?, ?, ?) "
            "ON CONFLICT(guild_id, role_id) DO UPDATE SET price=excluded.price",
            (str(interaction.guild_id), str(role.id), price),
        )
    await interaction.response.send_message(f"Роль {role.mention} добавлена в магазин за {price:,} {CURRENCY}.".replace(",", " "), ephemeral=True)


@bot.tree.command(name="shop-remove", description="Убрать роль из магазина (администратор)")
@app_commands.guild_only()
@app_commands.default_permissions(administrator=True)
@app_commands.describe(role="Роль")
async def shop_remove(interaction: discord.Interaction, role: discord.Role) -> None:
    with connect() as db:
        cursor = db.execute("DELETE FROM economy_shop_roles WHERE guild_id=? AND role_id=?", (str(interaction.guild_id), str(role.id)))
    await interaction.response.send_message("Удалено из магазина." if cursor.rowcount else "Такой роли нет в магазине.", ephemeral=True)


@bot.tree.command(name="shop-buy", description="Купить роль из магазина")
@app_commands.guild_only()
@app_commands.describe(role_id="ID роли из списка /shop")
async def shop_buy(interaction: discord.Interaction, role_id: str) -> None:
    if not role_id.isdigit():
        return await interaction.response.send_message("Укажите числовой ID роли из магазина.", ephemeral=True)
    role = interaction.guild.get_role(int(role_id))
    if not role:
        return await interaction.response.send_message("Роль не найдена на сервере.", ephemeral=True)
    guild_id, user_id = str(interaction.guild_id), str(interaction.user.id)
    with connect() as db:
        db.execute("BEGIN IMMEDIATE")
        row = db.execute("SELECT price FROM economy_shop_roles WHERE guild_id=? AND role_id=?", (guild_id, role_id)).fetchone()
        if not row:
            db.rollback()
            return await interaction.response.send_message("Этой роли нет в магазине.", ephemeral=True)
        account = ensure_account(db, interaction.guild_id, interaction.user.id)
        if account["balance"] < row["price"]:
            db.rollback()
            return await interaction.response.send_message("Недостаточно Chiil coin.", ephemeral=True)
        if role in interaction.user.roles:
            db.rollback()
            return await interaction.response.send_message("У вас уже есть эта роль.", ephemeral=True)
        try:
            await interaction.user.add_roles(role, reason="Покупка за Chiil coin")
        except discord.Forbidden:
            db.rollback()
            return await interaction.response.send_message("У бота нет прав выдать роль. Поднимите его роль выше продаваемой.", ephemeral=True)
        db.execute("UPDATE economy_accounts SET balance=balance-?, spent=spent+? WHERE guild_id=? AND user_id=?", (row["price"], row["price"], guild_id, user_id))
        db.execute("INSERT INTO economy_transactions (guild_id, sender_id, receiver_id, amount, kind) VALUES (?, ?, ?, ?, 'shop')", (guild_id, user_id, user_id, row["price"]))
    await interaction.response.send_message(f"Куплена роль {role.mention} за {row['price']:,} {CURRENCY}.".replace(",", " "), ephemeral=True)


@bot.tree.command(name="transactions", description="Последние операции с Chiil coin")
@app_commands.guild_only()
async def transactions(interaction: discord.Interaction) -> None:
    with connect() as db:
        rows = db.execute(
            "SELECT sender_id, receiver_id, amount, kind, created_at FROM economy_transactions "
            "WHERE guild_id=? AND (sender_id=? OR receiver_id=?) ORDER BY id DESC LIMIT 10",
            (str(interaction.guild_id), str(interaction.user.id), str(interaction.user.id)),
        ).fetchall()
    if not rows:
        return await interaction.response.send_message("Операций пока нет.", ephemeral=True)
    lines = [f"`{row['kind']}` · {row['amount']:,} {CURRENCY} · <t:{row['created_at']}:R>".replace(",", " ") for row in rows]
    await interaction.response.send_message("\n".join(lines), ephemeral=True)


@bot.tree.command(name="economy-add", description="Начислить Chiil coin (администратор)")
@app_commands.guild_only()
@app_commands.default_permissions(administrator=True)
@app_commands.describe(member="Участник", amount="Сумма начисления")
async def economy_add(interaction: discord.Interaction, member: discord.Member, amount: app_commands.Range[int, 1, 1_000_000_000]) -> None:
    with connect() as db:
        ensure_account(db, interaction.guild_id, member.id)
        db.execute("UPDATE economy_accounts SET balance=balance+?, earned=earned+? WHERE guild_id=? AND user_id=?", (amount, amount, str(interaction.guild_id), str(member.id)))
        db.execute("INSERT INTO economy_transactions (guild_id, receiver_id, amount, kind) VALUES (?, ?, ?, 'admin_grant')", (str(interaction.guild_id), str(member.id), amount))
    await interaction.response.send_message(f"Начислено {amount:,} {CURRENCY} пользователю {member.mention}.".replace(",", " "), ephemeral=True)


@bot.event
async def on_ready() -> None:
    print(f"Economy bot connected: {bot.user}")


if __name__ == "__main__":
    if not TOKEN:
        raise RuntimeError("ECONOMY_BOT_TOKEN is not configured in the dashboard")
    init_db()
    bot.run(TOKEN)
