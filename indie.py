import discord
from discord.ext import commands
from dotenv import load_dotenv
import os

# Load token
load_dotenv()
TOKEN = os.getenv("DISCORD_BOT_TOKEN")

# Intents
intents = discord.Intents.default()
intents.members = True
intents.message_content = True

bot = commands.Bot(command_prefix=["in.", "!"], intents=intents)


# Allow only admins to use these commands
def is_admin():
    async def predicate(ctx):
        return ctx.author.guild_permissions.administrator
    return commands.check(predicate)


@bot.event
async def on_ready():
    print(f"Admin bot online as {bot.user}")


# ----------------------------
# ROLE MANAGEMENT
# ----------------------------

@bot.command()
@is_admin()
async def role(ctx, action, *, name=None):
    """
    Usage:
    !role create CyberSec
    !role delete CyberSec
    """
    guild = ctx.guild

    if action.lower() == "create":
        role = await guild.create_role(name=name)
        await ctx.send(f"Created role **{role.name}**.")

    elif action.lower() == "delete":
        role = discord.utils.get(guild.roles, name=name)
        if role:
            await role.delete()
            await ctx.send(f"Deleted role **{name}**.")
        else:
            await ctx.send("Role not found.")

    else:
        await ctx.send("Actions: create/delete")


@bot.command()
@is_admin()
async def giverole(ctx, member: discord.Member, *, role_name):
    """
    Usage:
    !giverole @user CyberSec
    """
    role = discord.utils.get(ctx.guild.roles, name=role_name)
    if role is None:
        await ctx.send("Role not found.")
        return

    await member.add_roles(role)
    await ctx.send(f"Added **{role_name}** to {member.display_name}.")


@bot.command()
@is_admin()
async def removerole(ctx, member: discord.Member, *, role_name):
    """
    Usage:
    !removerole @user CyberSec
    """
    role = discord.utils.get(ctx.guild.roles, name=role_name)
    if role is None:
        await ctx.send("Role not found.")
        return

    await member.remove_roles(role)
    await ctx.send(f"Removed **{role_name}** from {member.display_name}.")


# ----------------------------
# CHANNEL MANAGEMENT
# ----------------------------

@bot.command()
@is_admin()
async def channel(ctx, action, *, name=None):
    """
    Usage:
    !channel create tools
    !channel delete logs
    """

    guild = ctx.guild

    if action.lower() == "create":
        channel = await guild.create_text_channel(name)
        await ctx.send(f"Created channel **#{name}**.")

    elif action.lower() == "delete":
        channel = discord.utils.get(guild.channels, name=name)
        if channel:
            await channel.delete()
            await ctx.send(f"Deleted channel **#{name}**.")
        else:
            await ctx.send("Channel not found.")

    else:
        await ctx.send("Actions: create/delete")


# ----------------------------
# LOCK / UNLOCK CHANNEL
# ----------------------------

@bot.command()
@is_admin()
async def lock(ctx, channel: discord.TextChannel = None):
    """
    Usage:
    !lock #general
    """
    channel = channel or ctx.channel
    await channel.set_permissions(ctx.guild.default_role, send_messages=False)
    await ctx.send(f"Locked **#{channel.name}**.")


@bot.command()
@is_admin()
async def unlock(ctx, channel: discord.TextChannel = None):
    """
    Usage:
    !unlock #general
    """
    channel = channel or ctx.channel
    await channel.set_permissions(ctx.guild.default_role, send_messages=True)
    await ctx.send(f"Unlocked **#{channel.name}**.")


# ----------------------------
# MODERATION COMMANDS
# ----------------------------

@bot.command()
@is_admin()
async def kick(ctx, member: discord.Member, *, reason="No reason"):
    await member.kick(reason=reason)
    await ctx.send(f"Kicked {member.display_name}.")


@bot.command()
@is_admin()
async def ban(ctx, member: discord.Member, *, reason="No reason"):
    await member.ban(reason=reason)
    await ctx.send(f"Banned {member.display_name}.")


@bot.command()
@is_admin()
async def unban(ctx, *, name_tag):
    """
    Usage:
    !unban Username#1234
    """
    banned = await ctx.guild.bans()
    name, discrim = name_tag.split("#")

    for entry in banned:
        user = entry.user
        if (user.name, user.discriminator) == (name, discrim):
            await ctx.guild.unban(user)
            await ctx.send(f"Unbanned {user}.")
            return

    await ctx.send("User not found in ban list.")

@bot.event
async def on_command_error(ctx, error):
    if isinstance(error, commands.MissingPermissions) or isinstance(error, commands.CheckFailure):
        await ctx.send("Chaleja Bhosdike")
    else:
        await ctx.send(f"Error: {error}")

# ----------------------------------------------------
# RANK SYSTEM (XP + LEVELS + AUTO ROLE ASSIGN)
# ----------------------------------------------------
import aiosqlite
import time
import random

DB_PATH = "ranks.db"
XP_MIN = 5
XP_MAX = 12
XP_COOLDOWN = 60   # seconds per message XP

# ----------------------------------------------------
# NEW XP CURVE (NON-LINEAR / GRADIENT GRIND)
# ----------------------------------------------------

def xp_to_level(xp):
    # Directly match your specified grind curve
    # Feel: Easy early, painful later
    levels = [
        (1, 10),
        (2, 50),
        (5, 290),
        (10, 1090),
        (25, 6490),
        (50, 25490),
        (75, 56990),
        (100, 100990),
    ]

    level = 0
    for lvl, req_xp in levels:
        if xp >= req_xp:
            level = lvl
        else:
            break
    return level


def next_level_xp(level):
    # Returns XP required for next milestone
    levels = {
        0: 10,
        1: 50,
        2: 290,
        5: 1090,
        10: 6490,
        25: 25490,
        50: 56990,
        75: 100990
    }
    return levels.get(level, 100990)


# Funny milestone reactions
MILESTONE_MESSAGES = {
    1:  "Welcome to Level 1 — You typed 'Hi' and got a medal.",
    2:  "Level 2? Okay, you're actually staying here. Respect.",
    5:  "Level 5 unlocked — First week regular. Touch some grass?",
    10: "Level 10 — Certified Regular. Server furniture level achieved.",
    25: "Level 25 — Ah, a dedicated chatter. Family thinks you're missing.",
    50: "Level 50 — You're now part of the Discord elite. No life detected.",
    75: "Level 75 — Veteran. You’ve seen things. Horrible things.",
    100: "Level 100 — Legend. Bro, go outside. It's been years.",
}



# Init DB once at startup
async def init_db():
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""
            CREATE TABLE IF NOT EXISTS xp_users (
                guild_id INTEGER,
                user_id INTEGER,
                xp INTEGER DEFAULT 0,
                PRIMARY KEY (guild_id, user_id)
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS xp_roles (
                guild_id INTEGER,
                level INTEGER,
                role_id INTEGER,
                PRIMARY KEY (guild_id, level)
            )
        """)
        await db.commit()

# run DB init before bot login
import asyncio
asyncio.run(init_db())

_last_xp = {}  # cooldown tracker


# ----------------------------------------------------
# GIVE XP WHEN USER SENDS A NORMAL MESSAGE
# ----------------------------------------------------
@bot.event
async def on_message(msg):
    if msg.author.bot or msg.guild is None:
        return await bot.process_commands(msg)

    # don't give XP for bot commands
    prefixes = ("in.", "!")
    if msg.content.startswith(prefixes):
        return await bot.process_commands(msg)

    now = time.time()
    key = (msg.guild.id, msg.author.id)

    if key in _last_xp and now - _last_xp[key] < XP_COOLDOWN:
        return await bot.process_commands(msg)

    _last_xp[key] = now
    gained = random.randint(XP_MIN, XP_MAX)

    # Add XP
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""
            INSERT INTO xp_users (guild_id, user_id, xp)
            VALUES (?, ?, ?)
            ON CONFLICT(guild_id, user_id) DO UPDATE SET xp = xp + ?
        """, (msg.guild.id, msg.author.id, gained, gained))
        await db.commit()

        # Check level
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            "SELECT xp FROM xp_users WHERE guild_id=? AND user_id=?",
            (msg.guild.id, msg.author.id)
        ) as cur:
            row = await cur.fetchone()
            xp = row[0] if row else 0

    old = xp_to_level(xp - gained)
    new = xp_to_level(xp)

    # Level up event
    if new > old:

        # milestone funny messages
        if new in MILESTONE_MESSAGES:
            await msg.channel.send(
                f"🎉 {msg.author.mention} reached **Level {new}**!\n{MILESTONE_MESSAGES[new]}"
            )
        else:
            await msg.channel.send(
                f"🎉 {msg.author.mention} hit Level {new}!"
            )

        await apply_level_role(msg.guild, msg.author, new)

    await bot.process_commands(msg)


# ----------------------------------------------------
# AUTO ROLE APPLY ON LEVEL-UP
# ----------------------------------------------------
async def apply_level_role(guild, member, level):
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT role_id FROM xp_roles WHERE guild_id=? AND level=?", (guild.id, level)) as cur:
            row = await cur.fetchone()

    if not row:
        return

    role = guild.get_role(row[0])
    if role is None:
        return

    try:
        await member.add_roles(role, reason="Level-up role")
    except:
        pass


# ----------------------------------------------------
# RANK COMMANDS
# ----------------------------------------------------
@bot.group(name="rank", invoke_without_command=True)
async def rank(ctx):
    await ctx.send("Rank Commands: stats, leaderboard, setrole, removerole, addxp, reset")


@rank.command()
async def stats(ctx, member: discord.Member = None):
    member = member or ctx.author
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT xp FROM xp_users WHERE guild_id=? AND user_id=?", (ctx.guild.id, member.id)) as cur:
            row = await cur.fetchone()
    xp = row[0] if row else 0
    level = xp_to_level(xp)
    await ctx.send(f"{member.display_name} — XP: `{xp}`, Level: `{level}`")


@rank.command()
async def leaderboard(ctx, limit: int = 10):
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            "SELECT user_id, xp FROM xp_users WHERE guild_id=? ORDER BY xp DESC LIMIT ?",
            (ctx.guild.id, limit),
        ) as cur:
            rows = await cur.fetchall()

    if not rows:
        return await ctx.send("No XP data yet.")

    out = []
    pos = 1
    for uid, xp in rows:
        m = ctx.guild.get_member(uid)
        name = m.display_name if m else f"User {uid}"
        out.append(f"**{pos}. {name}** — XP `{xp}`, Level `{xp_to_level(xp)}`")
        pos += 1

    await ctx.send("\n".join(out))


@rank.command()
@is_admin()
async def setrole(ctx, level: int, role: discord.Role):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""
            INSERT INTO xp_roles (guild_id, level, role_id)
            VALUES (?, ?, ?)
            ON CONFLICT(guild_id, level) DO UPDATE SET role_id=excluded.role_id
        """, (ctx.guild.id, level, role.id))
        await db.commit()
    await ctx.send(f"Level `{level}` now gives role **{role.name}**")


@rank.command()
@is_admin()
async def removerole(ctx, level: int):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("DELETE FROM xp_roles WHERE guild_id=? AND level=?", (ctx.guild.id, level))
        await db.commit()
    await ctx.send(f"Removed level `{level}` role mapping.")


@rank.command()
@is_admin()
async def addxp(ctx, member: discord.Member, amount: int):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""
            INSERT INTO xp_users (guild_id, user_id, xp)
            VALUES (?, ?, ?)
            ON CONFLICT(guild_id, user_id) DO UPDATE SET xp = xp + ?
        """, (ctx.guild.id, member.id, amount, amount))
        await db.commit()
    await ctx.send(f"Added `{amount}` XP to {member.display_name}.")


@rank.command()
@is_admin()
async def reset(ctx, member: discord.Member):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("DELETE FROM xp_users WHERE guild_id=? AND user_id=?", (ctx.guild.id, member.id))
        await db.commit()
    await ctx.send(f"Reset XP for {member.display_name}.")


# ----------------------------
# LIMIT COMMAND USAGE TO ONE CHANNEL
# ----------------------------


bot.run(TOKEN)
