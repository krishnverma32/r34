# 📁 main.py
import discord
import logging
import os
import time
import asyncio
from discord.ext import commands
from dotenv import load_dotenv
from database import Database

# --- Load .env ---
load_dotenv()

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# === Load token from environment ===
TOKEN = os.getenv("DISCORD_TOKEN")
if not TOKEN:
    logging.critical("DISCORD_TOKEN not found in environment variables!")
    exit(1)

# === Intents & Prefix ===
PREFIX = commands.when_mentioned_or("n ", "n!", "natsu", " N")
intents = discord.Intents.default()
intents.message_content = True
intents.guilds = True
intents.members = True

# === Bot class ===
class Bot(commands.Bot):
    def __init__(self):
        super().__init__(
            command_prefix=PREFIX,
            intents=intents,
            help_command=None
        )
        self.start_time = time.time()
        self.processing_commands = set()
        self.db = Database()

    async def setup_hook(self):
        """Called when the bot is starting up"""
        logging.info("Setting up bot extensions...")

        if not os.path.exists("cogs"):
            os.makedirs("cogs")
            logging.warning("Created missing cogs directory")

        loaded_cogs = []
        for filename in os.listdir("cogs"):
            if filename.endswith(".py") and not filename.startswith("__"):
                try:
                    await self.load_extension(f"cogs.{filename[:-3]}")
                    loaded_cogs.append(filename[:-3])
                    logging.info(f"✅ Loaded extension: {filename}")
                except Exception as e:
                    logging.error(f"❌ Failed to load {filename}: {e}")

        logging.info(f"Loaded {len(loaded_cogs)} extensions: {', '.join(loaded_cogs)}")

    async def on_ready(self):
        """Called when the bot is ready"""
        logging.info(f"✅ Logged in as {self.user} (ID: {self.user.id})")

        await asyncio.sleep(2)

        # Sync slash commands
        try:
            synced = await self.tree.sync()
            logging.info(f"✅ Synced {len(synced)} slash commands")
            print(f"📋 Synced commands: {[cmd.name for cmd in synced]}")
        except Exception as e:
            logging.error(f"❌ Failed to sync slash commands: {e}")

        await self.change_presence(
            activity=discord.Activity(
                type=discord.ActivityType.watching, 
                name=f"for commands | /help"
            )
        )

        print("🔗 Connected to the following servers:")
        for guild in self.guilds:
            print(f" - {guild.name} (ID: {guild.id}) - {len(guild.members)} members")

    async def process_commands(self, message):
        if message.id in self.processing_commands:
            return
        self.processing_commands.add(message.id)
        try:
            await super().process_commands(message)
        finally:
            self.processing_commands.discard(message.id)

    def uptime(self):
        return int(time.time() - self.start_time)


# === Initialize bot ===
bot = Bot()

# === Commands ===
@bot.command(name="uptime")
async def uptime_command(ctx):
    uptime_seconds = bot.uptime()
    minutes, seconds = divmod(uptime_seconds, 60)
    hours, minutes = divmod(minutes, 60)
    days, hours = divmod(hours, 24)
    uptime_str = f"{days}d {hours}h {minutes}m {seconds}s"
    embed = discord.Embed(
        title="🕒 Bot Uptime",
        description=f"Bot has been online for: **{uptime_str}**",
        color=discord.Color.blue()
    )
    await ctx.send(embed=embed)

@bot.command(name="ping")
async def ping_command(ctx):
    latency = round(bot.latency * 1000)
    await ctx.send(f"🏓 Pong! Latency: {latency}ms")

@bot.command(name="reload")
@commands.is_owner()
async def reload_cogs(ctx, cog_name: str = None):
    if cog_name:
        try:
            await bot.reload_extension(f"cogs.{cog_name}")
            await ctx.send(f"✅ Reloaded {cog_name}")
        except Exception as e:
            await ctx.send(f"❌ Failed to reload {cog_name}: {e}")
    else:
        reloaded = []
        for filename in os.listdir("cogs"):
            if filename.endswith(".py") and not filename.startswith("__"):
                try:
                    await bot.reload_extension(f"cogs.{filename[:-3]}")
                    reloaded.append(filename[:-3])
                except Exception as e:
                    await ctx.send(f"❌ Failed to reload {filename[:-3]}: {e}")
        await ctx.send(f"✅ Reloaded {len(reloaded)} cogs: {', '.join(reloaded)}")

@bot.command(name="sync")
@commands.is_owner()
async def sync_commands(ctx):
    try:
        synced = await bot.tree.sync()
        await ctx.send(f"✅ Synced {len(synced)} slash commands")
    except Exception as e:
        await ctx.send(f"❌ Failed to sync commands: {e}")

# === Error Handlers ===
@bot.event
async def on_command_error(ctx, error):
    if isinstance(error, commands.CommandNotFound):
        return
    elif isinstance(error, commands.NotOwner):
        await ctx.send("❌ This command is owner-only!")
        return

    logging.error(f"Command error in {ctx.command}: {error}", exc_info=True)

    if isinstance(error, commands.MissingRequiredArgument):
        await ctx.send(f"⚠️ Missing required argument: {error.param.name}")
    elif isinstance(error, commands.BadArgument):
        await ctx.send("⚠️ Invalid argument provided")
    elif isinstance(error, commands.MissingPermissions):
        await ctx.send("⚠️ You don't have permission to use this command")
    else:
        await ctx.send("⚠️ Something went wrong with that command")

@bot.tree.error
async def on_app_command_error(interaction: discord.Interaction, error):
    logging.error(f"Slash command error: {error}", exc_info=True)
    try:
        if not interaction.response.is_done():
            await interaction.response.send_message("⚠️ An error occurred with this command", ephemeral=True)
        else:
            await interaction.followup.send("⚠️ An error occurred with this command", ephemeral=True)
    except Exception as e:
        logging.error(f"Error handling slash command error: {e}")

# === Run bot ===
if __name__ == "__main__":
    try:
        logging.info("Starting bot...")
        bot.run(TOKEN)
    except KeyboardInterrupt:
        logging.info("Bot shutdown by keyboard interrupt")
    except Exception as e:
        logging.critical(f"Fatal error: {e}", exc_info=True)
