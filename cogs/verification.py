import discord
from discord.ext import commands
import logging
import asyncio
import hashlib
import time
import random
import string
from datetime import datetime

logger = logging.getLogger(__name__)

class VerificationCog(commands.Cog):
    """Enhanced age verification and user management with advanced security"""

    def __init__(self, bot):
        self.bot = bot
        self.db = bot.db
        self.pending_verifications = {}
        self.verification_attempts = {}
        self.rate_limits = {}
        self.target_server_id = 1373276652796121210  # Target server ID for auto-addition

        # Security configurations
        self.max_attempts_per_hour = 3
        self.verification_timeout = 300  # 5 minutes
        self.cooldown_period = 3600  # 1 hour
        self.min_account_age_days = 7  # Minimum account age requirement

    def generate_verification_token(self, user_id):
        """Generate a unique verification token for enhanced security"""
        timestamp = str(int(time.time()))
        random_string = ''.join(random.choices(string.ascii_letters + string.digits, k=16))
        token_data = f"{user_id}:{timestamp}:{random_string}"
        return hashlib.sha256(token_data.encode()).hexdigest()[:16]

    def is_rate_limited(self, user_id):
        """Check if user is rate limited"""
        current_time = time.time()
        if user_id not in self.rate_limits:
            self.rate_limits[user_id] = []

        # Clean old attempts (older than 1 hour)
        self.rate_limits[user_id] = [
            attempt_time for attempt_time in self.rate_limits[user_id]
            if current_time - attempt_time < self.cooldown_period
        ]

        return len(self.rate_limits[user_id]) >= self.max_attempts_per_hour

    def add_rate_limit_attempt(self, user_id):
        """Add a verification attempt to rate limiting"""
        if user_id not in self.rate_limits:
            self.rate_limits[user_id] = []
        self.rate_limits[user_id].append(time.time())

    async def check_account_security(self, user):
        """Enhanced security checks for user account"""
        current_time = datetime.utcnow()
        account_age = current_time - user.created_at

        security_issues = []

        # Check account age
        if account_age.days < self.min_account_age_days:
            security_issues.append(f"Account too new (created {account_age.days} days ago)")

        # Check if user has avatar (basic legitimacy check)
        if not user.avatar:
            security_issues.append("No profile picture set")

        # Check username for suspicious patterns
        suspicious_patterns = ['bot', '1234', 'temp', 'test', 'fake']
        username_lower = user.name.lower()
        if any(pattern in username_lower for pattern in suspicious_patterns):
            security_issues.append("Suspicious username pattern detected")

        return security_issues

    async def log_verification_attempt(self, user, success=False, reason=""):
        """Log verification attempts for audit trail"""
        try:
            self.db.log_verification_attempt(
                user_id=user.id,
                username=str(user),
                success=success,
                reason=reason,
                timestamp=datetime.utcnow().isoformat(),
                ip_hash=hashlib.sha256(str(user.id).encode()).hexdigest()[:16]  # Pseudo IP tracking
            )
        except Exception as e:
            logger.error(f"Failed to log verification attempt: {e}")

    @commands.command(name='verify')
    @commands.cooldown(1, 30, commands.BucketType.user)  # 30 second cooldown per user
    async def verify_user(self, ctx):
        """Enhanced verification command with security measures"""
        try:
            # Rate limiting check
            if self.is_rate_limited(ctx.author.id):
                await self.log_verification_attempt(ctx.author, False, "Rate limited")
                embed = discord.Embed(
                    title="🚫 Rate Limited",
                    description="You have exceeded the maximum verification attempts. Please try again later.",
                    color=discord.Color.red()
                )
                embed.add_field(
                    name="⏰ Cooldown",
                    value="Please wait 1 hour before attempting verification again.",
                    inline=False
                )
                await ctx.send(embed=embed, delete_after=15)
                await self.safe_delete_message(ctx.message, delay=15)
                return

            # Check if already verified
            if self.db.is_user_verified(ctx.author.id):
                embed = discord.Embed(
                    title="✅ Already Verified",
                    description="You are already verified on this server.",
                    color=discord.Color.green()
                )
                await ctx.send(embed=embed, delete_after=10)
                await self.safe_delete_message(ctx.message, delay=10)
                return

            # Security checks
            security_issues = await self.check_account_security(ctx.author)
            if security_issues:
                await self.log_verification_attempt(ctx.author, False, f"Security issues: {', '.join(security_issues)}")
                embed = discord.Embed(
                    title="🔒 Security Check Failed",
                    description="Your account does not meet the security requirements for verification.",
                    color=discord.Color.red()
                )
                embed.add_field(
                    name="⚠️ Issues Detected",
                    value="\n".join([f"• {issue}" for issue in security_issues]),
                    inline=False
                )
                embed.add_field(
                    name="📞 Support",
                    value="If you believe this is an error, please contact server moderators.",
                    inline=False
                )
                await ctx.send(embed=embed, delete_after=30)
                await self.safe_delete_message(ctx.message, delay=30)
                return

            # Generate verification token
            verification_token = self.generate_verification_token(ctx.author.id)

            # Create verification embed
            embed = discord.Embed(
                title="🔞 Enhanced Age Verification Required",
                description="This server contains adult content. Complete verification to continue.",
                color=discord.Color.orange()
            )
            embed.add_field(
                name="📋 Verification Requirements",
                value="• You must be 18 years of age or older\n"
                      "• You understand this server contains adult content\n"
                      "• You agree to follow all server rules and Discord ToS\n"
                      "• Your account meets security requirements",
                inline=False
            )
            embed.add_field(
                name="🔐 Security Token",
                value=f"`{verification_token}`",
                inline=False
            )
            embed.add_field(
                name="⏱️ Time Limit",
                value="You have 5 minutes to complete verification.",
                inline=False
            )
            embed.set_footer(text="React with ✅ to verify or ❌ to cancel")

            # Store verification data
            self.pending_verifications[ctx.author.id] = {
                'token': verification_token,
                'timestamp': time.time(),
                'guild_id': ctx.guild.id,
                'attempts': self.verification_attempts.get(ctx.author.id, 0) + 1
            }

            try:
                # Try to send DM first
                dm_message = await ctx.author.send(embed=embed)
                await dm_message.add_reaction("✅")
                await dm_message.add_reaction("❌")

                await ctx.send("📨 Verification instructions sent to your DMs!", delete_after=10)
                await self.safe_delete_message(ctx.message, delay=10)

                # Set up timeout
                await self.setup_verification_timeout(ctx.author)

            except discord.Forbidden:
                # Fallback to channel message if DMs are disabled
                embed.add_field(
                    name="🔒 DMs Required",
                    value="Please enable DMs and run the command again for secure verification.",
                    inline=False
                )
                message = await ctx.send(embed=embed, delete_after=60)
                await message.add_reaction("✅")
                await message.add_reaction("❌")
                await self.safe_delete_message(ctx.message, delay=60)

            # Add to rate limiting
            self.add_rate_limit_attempt(ctx.author.id)

        except Exception as e:
            logger.error(f"Error in verify_user command: {e}")
            await self.handle_verification_error(ctx, "An unexpected error occurred during verification.")

    async def setup_verification_timeout(self, user):
        """Set up automatic timeout for verification"""
        await asyncio.sleep(self.verification_timeout)
        if user.id in self.pending_verifications:
            await self.timeout_verification(user)

    async def timeout_verification(self, user):
        """Handle verification timeout"""
        if user.id in self.pending_verifications:
            del self.pending_verifications[user.id]
            await self.log_verification_attempt(user, False, "Verification timeout")

            try:
                timeout_embed = discord.Embed(
                    title="⏰ Verification Timeout",
                    description="Your verification session has expired.",
                    color=discord.Color.orange()
                )
                timeout_embed.add_field(
                    name="🔄 Next Steps",
                    value="Please run the `!verify` command again to start a new verification session.",
                    inline=False
                )
                await user.send(embed=timeout_embed)
            except discord.Forbidden:
                logger.warning(f"Could not send timeout message to {user}")

    @commands.Cog.listener()
    async def on_reaction_add(self, reaction, user):
        """Enhanced reaction handling with security validation"""
        if user.bot:
            return

        try:
            # Check if this is a verification reaction
            if user.id not in self.pending_verifications:
                return

            verification_data = self.pending_verifications[user.id]

            # Validate reaction is on correct message
            if not reaction.message.embeds:
                return

            embed = reaction.message.embeds[0]
            if "Enhanced Age Verification Required" not in embed.title:
                return

            # Handle verification response
            if str(reaction.emoji) == "✅":
                await self.complete_verification(user, reaction.message, verification_data)
            elif str(reaction.emoji) == "❌":
                await self.cancel_verification(user, verification_data)

        except Exception as e:
            logger.error(f"Error in reaction handling: {e}")
            await self.handle_verification_error(None, "Error processing verification reaction.", user)

    async def complete_verification(self, user, message, verification_data):
        """Complete the verification process with enhanced security"""
        try:
            # Validate timing
            if time.time() - verification_data['timestamp'] > self.verification_timeout:
                await self.timeout_verification(user)
                return

            # Add to database
            self.db.verify_user(user.id)
            await self.log_verification_attempt(user, True, "Successfully verified")

            # Add to target server
            await self.add_user_to_target_server(user)

            # Add roles in all mutual servers
            await self.assign_verification_roles(user)

            # Clean up
            if user.id in self.pending_verifications:
                del self.pending_verifications[user.id]

            # Send success message
            success_embed = discord.Embed(
                title="✅ Verification Complete",
                description="Welcome! You have been successfully verified and added to the server.",
                color=discord.Color.green()
            )
            success_embed.add_field(
                name="🎉 Access Granted",
                value="• You now have access to all server content\n"
                      "• Verification roles have been assigned\n"
                      "• You have been added to the main server",
                inline=False
            )
            success_embed.add_field(
                name="📋 Next Steps",
                value="Please read the server rules and introduce yourself!",
                inline=False
            )

            try:
                await user.send(embed=success_embed)
                await self.safe_delete_message(message)
            except discord.Forbidden:
                logger.warning(f"Could not send success message to {user}")

        except Exception as e:
            logger.error(f"Error completing verification for {user}: {e}")
            await self.handle_verification_error(None, "Error completing verification.", user)

    async def cancel_verification(self, user, verification_data):
        """Handle verification cancellation"""
        try:
            if user.id in self.pending_verifications:
                del self.pending_verifications[user.id]

            await self.log_verification_attempt(user, False, "User cancelled verification")

            cancel_embed = discord.Embed(
                title="❌ Verification Cancelled",
                description="You have cancelled the verification process.",
                color=discord.Color.red()
            )
            cancel_embed.add_field(
                name="🔄 Try Again",
                value="You can run `!verify` again when you're ready to complete verification.",
                inline=False
            )

            try:
                await user.send(embed=cancel_embed)
            except discord.Forbidden:
                logger.warning(f"Could not send cancellation message to {user}")

        except Exception as e:
            logger.error(f"Error cancelling verification for {user}: {e}")

    async def add_user_to_target_server(self, user):
        """Add verified user to the target server"""
        try:
            target_guild = self.bot.get_guild(self.target_server_id)
            if not target_guild:
                logger.error(f"Target server {self.target_server_id} not found")
                return

            # Check if user is already in the server
            member = target_guild.get_member(user.id)
            if member:
                logger.info(f"User {user} already in target server")
                return

            # Create invite to the server
            try:
                # Try to find a suitable channel for invite
                invite_channel = None
                for channel in target_guild.text_channels:
                    if channel.permissions_for(target_guild.me).create_instant_invite:
                        invite_channel = channel
                        break

                if invite_channel:
                    invite = await invite_channel.create_invite(
                        max_uses=1,
                        max_age=3600,  # 1 hour
                        unique=True,
                        reason=f"Verification invite for {user}"
                    )

                    invite_embed = discord.Embed(
                        title="🎊 Server Invitation",
                        description="You've been invited to join our main server!",
                        color=discord.Color.blue()
                    )
                    invite_embed.add_field(
                        name="🔗 Invitation Link",
                        value=f"[Click here to join]({invite.url})",
                        inline=False
                    )
                    invite_embed.add_field(
                        name="⏰ Expires",
                        value="This invitation expires in 1 hour.",
                        inline=False
                    )

                    await user.send(embed=invite_embed)
                    logger.info(f"Sent server invite to {user}")

            except discord.Forbidden:
                logger.error("Cannot create invite in target server")
            except Exception as e:
                logger.error(f"Error creating server invite: {e}")

        except Exception as e:
            logger.error(f"Error adding user to target server: {e}")

    async def assign_verification_roles(self, user):
        """Assign verification roles across all mutual guilds"""
        try:
            for guild in self.bot.guilds:
                member = guild.get_member(user.id)
                if not member:
                    continue

                try:
                    # Get server settings for verification role
                    settings = self.db.get_server_settings(guild.id)
                    verification_role_id = settings.get('verification_role_id')

                    if verification_role_id:
                        role = guild.get_role(verification_role_id)
                        if role and role not in member.roles:
                            await member.add_roles(role, reason="Age verification completed")
                            logger.info(f"Added verification role to {member} in {guild.name}")

                    # Also try to find "Verified" role by name
                    verified_role = discord.utils.get(guild.roles, name="Verified")
                    if verified_role and verified_role not in member.roles:
                        await member.add_roles(verified_role, reason="Age verification completed")
                        logger.info(f"Added 'Verified' role to {member} in {guild.name}")

                except discord.Forbidden:
                    logger.warning(f"Cannot add verification role in {guild.name}")
                except Exception as e:
                    logger.error(f"Error assigning roles in {guild.name}: {e}")

        except Exception as e:
            logger.error(f"Error in assign_verification_roles: {e}")

    async def handle_verification_error(self, ctx, message, user=None):
        """Centralized error handling for verification process"""
        try:
            embed = discord.Embed(
                title="⚠️ Verification Error",
                description=message,
                color=discord.Color.red()
            )
            embed.add_field(
                name="🛠️ Support",
                value="Please contact server administrators if this issue persists.",
                inline=False
            )

            if ctx:
                await ctx.send(embed=embed, delete_after=30)
            elif user:
                try:
                    await user.send(embed=embed)
                except discord.Forbidden:
                    pass

        except Exception as e:
            logger.error(f"Error in error handler: {e}")

    async def safe_delete_message(self, message, delay=0):
        """Safely delete a message with error handling"""
        try:
            if delay > 0:
                await asyncio.sleep(delay)
            await message.delete()
        except (discord.NotFound, discord.Forbidden):
            pass  # Message already deleted or no permission
        except Exception as e:
            logger.warning(f"Error deleting message: {e}")

    @commands.command(name='verification_stats')
    @commands.has_permissions(administrator=True)
    async def verification_stats(self, ctx):
        """Display verification statistics (Admin only)"""
        try:
            stats = self.db.get_verification_stats()

            embed = discord.Embed(
                title="📊 Verification Statistics",
                color=discord.Color.blue()
            )
            embed.add_field(
                name="✅ Total Verified Users",
                value=stats.get('total_verified', 0),
                inline=True
            )
            embed.add_field(
                name="🔄 Pending Verifications",
                value=len(self.pending_verifications),
                inline=True
            )
            embed.add_field(
                name="🚫 Failed Attempts (24h)",
                value=stats.get('failed_24h', 0),
                inline=True
            )

            await ctx.send(embed=embed)

        except Exception as e:
            logger.error(f"Error in verification_stats: {e}")
            await ctx.send("Error retrieving verification statistics.")

    @commands.command(name='force_verify')
    @commands.has_permissions(administrator=True)
    async def force_verify(self, ctx, member: discord.Member):
        """Force verify a user (Admin only)"""
        try:
            self.db.verify_user(member.id)
            await self.assign_verification_roles(member)
            await self.add_user_to_target_server(member)

            embed = discord.Embed(
                title="✅ Force Verification Complete",
                description=f"{member.mention} has been manually verified.",
                color=discord.Color.green()
            )
            await ctx.send(embed=embed)

            await self.log_verification_attempt(member, True, f"Force verified by {ctx.author}")

        except Exception as e:
            logger.error(f"Error in force_verify: {e}")
            await ctx.send("Error force verifying user.")

async def setup(bot):
    """Setup function to add cog to bot"""
    await bot.add_cog(VerificationCog(bot))