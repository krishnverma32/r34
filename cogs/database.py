import discord
from discord.ext import commands, tasks
import logging
import asyncio
from database import Database
from verificationg import Verification

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('bot.log'),
        logging.StreamHandler()
    ]
)

logger = logging.getLogger(__name__)

class VerificationBot(commands.Bot):
    """Enhanced Discord bot with comprehensive verification system"""

    def __init__(self):
        intents = discord.Intents.default()
        intents.message_content = True
        intents.members = True
        intents.guilds = True
        intents.reactions = True

        super().__init__(
            command_prefix='!',
            intents=intents,
            help_command=None,
            case_insensitive=True
        )

        # Initialize database
        self.db = Database("verification_bot.db")

        # Add maintenance tasks
        self.cleanup_task.start()
        self.stats_task.start()

    async def setup_hook(self):
        """Called when the bot is starting up"""
        try:
            # Load verification cog
            await self.add_cog(VerificationCog(self))
            logger.info("Verification cog loaded successfully")

            # Sync slash commands if needed
            # await self.tree.sync()

        except Exception as e:
            logger.error(f"Error in setup_hook: {e}")

    async def on_ready(self):
        """Called when bot is ready"""
        logger.info(f'{self.user} has connected to Discord!')
        logger.info(f'Bot is in {len(self.guilds)} guilds')

        # Update bot status
        activity = discord.Activity(
            type=discord.ActivityType.watching,
            name="for !verify commands"
        )
        await self.change_presence(activity=activity)

        # Log database stats
        stats = self.db.get_database_stats()
        logger.info(f"Database stats: {stats}")

    async def on_guild_join(self, guild):
        """Called when bot joins a new guild"""
        logger.info(f"Joined guild: {guild.name} (ID: {guild.id})")

        # Initialize server settings
        self.db.update_server_settings(
            guild_id=guild.id,
            guild_name=guild.name,
            auto_role_enabled=True
        )

        # Log audit action
        self.db.log_audit_action(
            user_id=None,
            admin_id=None,
            guild_id=guild.id,
            action_type="BOT_JOINED_GUILD",
            details=f"Bot joined guild: {guild.name}"
        )

    async def on_guild_remove(self, guild):
        """Called when bot leaves a guild"""
        logger.info(f"Left guild: {guild.name} (ID: {guild.id})")

        # Log audit action
        self.db.log_audit_action(
            user_id=None,
            admin_id=None,
            guild_id=guild.id,
            action_type="BOT_LEFT_GUILD",
            details=f"Bot left guild: {guild.name}"
        )

    async def on_member_join(self, member):
        """Called when a member joins a guild"""
        if member.bot:
            return

        # Update user profile
        self.db.update_user_profile(
            user_id=member.id,
            username=str(member),
            discriminator=member.discriminator,
            avatar_hash=member.avatar.key if member.avatar else None,
            account_created=member.created_at.isoformat(),
            total_servers=len([g for g in self.guilds if g.get_member(member.id)])
        )

        # Check if user is already verified
        if self.db.is_user_verified(member.id):
            # Auto-assign verification role if configured
            settings = self.db.get_server_settings(member.guild.id)
            if settings.get('auto_role_enabled') and settings.get('verification_role_id'):
                role = member.guild.get_role(settings['verification_role_id'])
                if role:
                    try:
                        await member.add_roles(role, reason="Auto-role for verified user")
                        logger.info(f"Auto-assigned verification role to {member}")
                    except discord.Forbidden:
                        logger.warning(f"Cannot assign auto-role in {member.guild.name}")

    async def on_command_error(self, ctx, error):
        """Global error handler"""
        if isinstance(error, commands.CommandOnCooldown):
            embed = discord.Embed(
                title="⏱️ Cooldown Active",
                description=f"Please wait {error.retry_after:.1f} seconds before using this command again.",
                color=discord.Color.orange()
            )
            await ctx.send(embed=embed, delete_after=10)

        elif isinstance(error, commands.MissingPermissions):
            embed = discord.Embed(
                title="🚫 Missing Permissions",
                description="You don't have the required permissions to use this command.",
                color=discord.Color.red()
            )
            await ctx.send(embed=embed, delete_after=15)

        elif isinstance(error, commands.UserInputError):
            embed = discord.Embed(
                title="❓ Invalid Usage",
                description=f"Invalid command usage. Use `!help {ctx.command}` for more information.",
                color=discord.Color.orange()
            )
            await ctx.send(embed=embed, delete_after=15)

        else:
            logger.error(f"Unhandled command error: {error}", exc_info=True)

            # Log to database
            self.db.log_audit_action(
                user_id=ctx.author.id if ctx.author else None,
                admin_id=None,
                guild_id=ctx.guild.id if ctx.guild else None,
                action_type="COMMAND_ERROR",
                details=f"Error in command {ctx.command}: {str(error)}",
                success=False
            )

    @tasks.loop(minutes=30)
    async def cleanup_task(self):
        """Periodic cleanup tasks"""
        try:
            # Clean up expired tokens
            self.db.cleanup_expired_tokens()

            # Reset old rate limits
            cutoff_time = datetime.utcnow() - timedelta(hours=24)
            with self.db.get_connection() as conn:
                conn.execute("""
                    UPDATE rate_limits 
                    SET attempts_count = 0, cooldown_until = NULL 
                    WHERE last_attempt < ?
                """, (cutoff_time.isoformat(),))
                conn.commit()

            logger.debug("Cleanup task completed")

        except Exception as e:
            logger.error(f"Error in cleanup task: {e}")

    @cleanup_task.before_loop
    async def before_cleanup_task(self):
        """Wait until bot is ready before starting cleanup task"""
        await self.wait_until_ready()

    @tasks.loop(hours=6)
    async def stats_task(self):
        """Periodic statistics logging"""
        try:
            stats = self.db.get_verification_stats()
            db_stats = self.db.get_database_stats()

            logger.info(f"Verification stats: {stats}")
            logger.info(f"Database stats: {db_stats}")

            # Create automatic backup if database is large
            if db_stats.get('database_size_mb', 0) > 10:  # Backup if > 10MB
                backup_path = self.db.backup_database()
                if backup_path:
                    logger.info(f"Automatic backup created: {backup_path}")

        except Exception as e:
            logger.error(f"Error in stats task: {e}")

    @stats_task.before_loop
    async def before_stats_task(self):
        """Wait until bot is ready before starting stats task"""
        await self.wait_until_ready()

    async def close(self):
        """Clean shutdown"""
        logger.info("Bot shutting down...")

        # Cancel tasks
        self.cleanup_task.cancel()
        self.stats_task.cancel()

        # Close database
        self.db.close()

        # Close bot
        await super().close()

# Admin commands for server management
class AdminCog(commands.Cog):
    """Administrative commands for server management"""

    def __init__(self, bot):
        self.bot = bot
        self.db = bot.db

    @commands.command(name='setup_verification')
    @commands.has_permissions(administrator=True)
    async def setup_verification(self, ctx, role: discord.Role = None):
        """Set up verification for this server"""
        try:
            settings = {
                'guild_name': ctx.guild.name,
                'verification_channel_id': ctx.channel.id
            }

            if role:
                settings['verification_role_id'] = role.id

            self.db.update_server_settings(ctx.guild.id, **settings)

            embed = discord.Embed(
                title="✅ Verification Setup Complete",
                description="Verification system has been configured for this server.",
                color=discord.Color.green()
            )

            if role:
                embed.add_field(
                    name="🎭 Verification Role",
                    value=role.mention,
                    inline=False
                )

            embed.add_field(
                name="📋 Next Steps",
                value="• Users can now use `!verify` to get verified\n"
                      "• Verified users will be automatically added to the target server\n"
                      "• Use `!verification_settings` to customize settings",
                inline=False
            )

            await ctx.send(embed=embed)

        except Exception as e:
            logger.error(f"Error in setup_verification: {e}")
            await ctx.send("❌ Error setting up verification system.")

    @commands.command(name='verification_settings')
    @commands.has_permissions(administrator=True)
    async def verification_settings(self, ctx):
        """View current verification settings"""
        try:
            settings = self.db.get_server_settings(ctx.guild.id)

            embed = discord.Embed(
                title="⚙️ Verification Settings",
                color=discord.Color.blue()
            )

            # Basic settings
            embed.add_field(
                name="🎭 Verification Role",
                value=f"<@&{settings['verification_role_id']}>" if settings.get('verification_role_id') else "Not set",
                inline=True
            )

            embed.add_field(
                name="📺 Verification Channel",
                value=f"<#{settings['verification_channel_id']}>" if settings.get('verification_channel_id') else "Not set",
                inline=True
            )

            embed.add_field(
                name="🔄 Auto Role",
                value="✅ Enabled" if settings.get('auto_role_enabled') else "❌ Disabled",
                inline=True
            )

            # Security settings
            embed.add_field(
                name="📅 Min Account Age",
                value=f"{settings.get('min_account_age_days', 7)} days",
                inline=True
            )

            embed.add_field(
                name="🔢 Max Attempts",
                value=f"{settings.get('max_verification_attempts', 3)} per hour",
                inline=True
            )

            embed.add_field(
                name="⏱️ Timeout",
                value=f"{settings.get('verification_timeout_minutes', 5)} minutes",
                inline=True
            )

            await ctx.send(embed=embed)

        except Exception as e:
            logger.error(f"Error in verification_settings: {e}")
            await ctx.send("❌ Error retrieving verification settings.")

    @commands.command(name='audit_log')
    @commands.has_permissions(administrator=True)
    async def audit_log(self, ctx, limit: int = 10):
        """View recent audit log entries"""
        try:
            if limit > 50:
                limit = 50

            entries = self.db.get_audit_log(limit=limit, guild_id=ctx.guild.id)

            if not entries:
                embed = discord.Embed(
                    title="📋 Audit Log",
                    description="No audit log entries found.",
                    color=discord.Color.blue()
                )
                await ctx.send(embed=embed)
                return

            embed = discord.Embed(
                title="📋 Recent Audit Log",
                color=discord.Color.blue()
            )

            for entry in entries[:10]:  # Show max 10 in embed
                timestamp = datetime.fromisoformat(entry['timestamp'])
                formatted_time = timestamp.strftime("%m/%d %H:%M")

                user_mention = f"<@{entry['user_id']}>" if entry['user_id'] else "System"
                success_icon = "✅" if entry['success'] else "❌"

                embed.add_field(
                    name=f"{success_icon} {entry['action_type']} - {formatted_time}",
                    value=f"User: {user_mention}\nDetails: {entry['action_details'][:100]}{'...' if len(entry['action_details']) > 100 else ''}",
                    inline=False
                )

            if len(entries) > 10:
                embed.set_footer(text=f"Showing 10 of {len(entries)} entries")

            await ctx.send(embed=embed)

        except Exception as e:
            logger.error(f"Error in audit_log: {e}")
            await ctx.send("❌ Error retrieving audit log.")

# Main bot runner
async def main():
    """Main function to run the bot"""
    bot = VerificationBot()

    try:
        # Add admin cog
        await bot.add_cog(AdminCog(bot))

        # Start the bot (replace with your actual token)
        await bot.start('YOUR_BOT_TOKEN_HERE')

    except KeyboardInterrupt:
        logger.info("Bot stopped by user")
    except Exception as e:
        logger.error(f"Bot error: {e}")
    finally:
        await bot.close()

if __name__ == "__main__":
    # Run the bot
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("Bot stopped by user")
    except Exception as e:
        logger.error(f"Fatal error: {e}")