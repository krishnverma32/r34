import os
import asyncio
import random
import logging
from typing import Dict, List, Optional, Union
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
import hashlib
import json

import discord
from discord.ext import commands
from discord import app_commands
import praw
import aiohttp
import aioredis
from urllib.parse import quote_plus, urljoin

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class Platform(Enum):
    """Supported gaming platforms"""
    REDDIT = "Reddit"
    ITCH_IO = "Itch.io"
    STEAM = "Steam"
    VNDB = "VNDB"
    NUTAKU = "Nutaku"
    DLSITE = "DLsite"
    F95ZONE = "F95Zone"

@dataclass
class Game:
    """Enhanced game data structure"""
    title: str
    description: str
    url: str
    platform: Platform
    category: Optional[str] = None
    rating: Optional[float] = None
    release_date: Optional[str] = None
    tags: List[str] = field(default_factory=list)
    price: Optional[str] = None
    thumbnail: Optional[str] = None
    developer: Optional[str] = None
    is_adult: bool = True
    last_updated: datetime = field(default_factory=datetime.utcnow)

    def to_dict(self) -> Dict:
        """Convert to dictionary for serialization"""
        return {
            'title': self.title,
            'description': self.description,
            'url': self.url,
            'platform': self.platform.value,
            'category': self.category,
            'rating': self.rating,
            'release_date': self.release_date,
            'tags': self.tags,
            'price': self.price,
            'thumbnail': self.thumbnail,
            'developer': self.developer,
            'is_adult': self.is_adult,
            'last_updated': self.last_updated.isoformat()
        }

    @classmethod
    def from_dict(cls, data: Dict) -> 'Game':
        """Create Game from dictionary"""
        data = data.copy()
        if 'platform' in data:
            data['platform'] = Platform(data['platform'])
        if 'last_updated' in data:
            data['last_updated'] = datetime.fromisoformat(data['last_updated'])
        return cls(**data)

class RateLimiter:
    """Rate limiter for API calls"""
    def __init__(self, calls_per_minute: int = 30):
        self.calls_per_minute = calls_per_minute
        self.calls = []

    async def acquire(self):
        now = datetime.utcnow()
        # Remove calls older than 1 minute
        self.calls = [call_time for call_time in self.calls 
                     if now - call_time < timedelta(minutes=1)]

        if len(self.calls) >= self.calls_per_minute:
            sleep_time = 60 - (now - self.calls[0]).total_seconds()
            if sleep_time > 0:
                await asyncio.sleep(sleep_time)

        self.calls.append(now)

class CacheManager:
    """Advanced caching with Redis support"""
    def __init__(self, redis_url: Optional[str] = None):
        self.redis_url = redis_url
        self.redis = None
        self.local_cache = {}
        self.cache_ttl = 3600  # 1 hour

    async def initialize(self):
        """Initialize Redis connection if available"""
        if self.redis_url:
            try:
                self.redis = await aioredis.from_url(self.redis_url)
                await self.redis.ping()
                logger.info("Redis cache initialized")
            except Exception as e:
                logger.warning(f"Redis unavailable, using local cache: {e}")
                self.redis = None

    async def get(self, key: str) -> Optional[Dict]:
        """Get cached data"""
        try:
            if self.redis:
                data = await self.redis.get(key)
                if data:
                    return json.loads(data)

            # Fallback to local cache
            if key in self.local_cache:
                cached_data, timestamp = self.local_cache[key]
                if datetime.utcnow() - timestamp < timedelta(seconds=self.cache_ttl):
                    return cached_data
                else:
                    del self.local_cache[key]
        except Exception as e:
            logger.error(f"Cache get error: {e}")
        return None

    async def set(self, key: str, value: Dict, ttl: Optional[int] = None):
        """Set cached data"""
        try:
            ttl = ttl or self.cache_ttl
            if self.redis:
                await self.redis.setex(key, ttl, json.dumps(value))

            # Also store in local cache
            self.local_cache[key] = (value, datetime.utcnow())
        except Exception as e:
            logger.error(f"Cache set error: {e}")

    async def close(self):
        """Close cache connections"""
        if self.redis:
            await self.redis.close()

class GameSearchAPI:
    """Base class for game search APIs"""
    def __init__(self, api_key: Optional[str] = None, rate_limiter: Optional[RateLimiter] = None):
        self.api_key = api_key
        self.rate_limiter = rate_limiter or RateLimiter()
        self.session: Optional[aiohttp.ClientSession] = None

    async def get_session(self) -> aiohttp.ClientSession:
        """Get or create aiohttp session"""
        if not self.session or self.session.closed:
            timeout = aiohttp.ClientTimeout(total=30)
            connector = aiohttp.TCPConnector(limit=100, limit_per_host=30)
            self.session = aiohttp.ClientSession(
                timeout=timeout,
                connector=connector,
                headers={'User-Agent': 'NSFWGameBot/2.0'}
            )
        return self.session

    async def close(self):
        """Close session"""
        if self.session and not self.session.closed:
            await self.session.close()

    async def search(self, query: str, limit: int = 10) -> List[Game]:
        """Override in subclasses"""
        raise NotImplementedError

class RedditAPI(GameSearchAPI):
    """Enhanced Reddit API integration"""
    def __init__(self, client_id: str, client_secret: str, user_agent: str):
        super().__init__(rate_limiter=RateLimiter(calls_per_minute=60))
        self.reddit = praw.Reddit(
            client_id=client_id,
            client_secret=client_secret,
            user_agent=user_agent,
            check_for_async=False
        )

    async def search(self, query: str, limit: int = 10) -> List[Game]:
        """Search Reddit for NSFW games"""
        games = []
        try:
            await self.rate_limiter.acquire()

            subreddits = ['NSFWgaming', 'lewdgames', 'AdultGamers', 'eroge']

            for subreddit_name in subreddits:
                try:
                    subreddit = self.reddit.subreddit(subreddit_name)
                    for submission in subreddit.search(query, limit=max(1, limit // len(subreddits))):
                        if not submission.over_18:
                            continue

                        game = Game(
                            title=submission.title[:100],
                            description=self._clean_description(submission.selftext),
                            url=submission.url,
                            platform=Platform.REDDIT,
                            rating=submission.score / 100.0 if submission.score > 0 else None,
                            tags=[flair.display_text for flair in getattr(submission, 'link_flair_richtext', [])],
                            last_updated=datetime.fromtimestamp(submission.created_utc)
                        )
                        games.append(game)

                        if len(games) >= limit:
                            break
                except Exception as e:
                    logger.error(f"Error searching subreddit {subreddit_name}: {e}")
                    continue

        except Exception as e:
            logger.error(f"Reddit API error: {e}")

        return games[:limit]

    def _clean_description(self, text: str) -> str:
        """Clean and truncate description"""
        if not text:
            return "No description available"
        # Remove markdown and limit length
        cleaned = text.replace('**', '').replace('*', '').replace('\n\n', '\n')
        return cleaned[:300] + '...' if len(cleaned) > 300 else cleaned

class ItchIOAPI(GameSearchAPI):
    """Enhanced Itch.io API integration"""
    def __init__(self, api_key: Optional[str] = None):
        super().__init__(api_key, RateLimiter(calls_per_minute=120))
        self.base_url = "https://itch.io/api/1/"

    async def search(self, query: str, limit: int = 10) -> List[Game]:
        """Search Itch.io for games"""
        games = []
        try:
            await self.rate_limiter.acquire()
            session = await self.get_session()

            # Use both search and browse endpoints
            endpoints = [
                f"search/games?q={quote_plus(query)}&nsfw=true",
                f"games?nsfw=true&tag={quote_plus(query)}"
            ]

            for endpoint in endpoints:
                try:
                    url = urljoin(self.base_url, endpoint)
                    if self.api_key:
                        url += f"&api_key={self.api_key}"

                    async with session.get(url) as response:
                        if response.status == 200:
                            data = await response.json()
                            for game_data in data.get('games', [])[:limit]:
                                game = Game(
                                    title=game_data.get('title', 'Unknown'),
                                    description=game_data.get('short_text', 'No description'),
                                    url=game_data.get('url', ''),
                                    platform=Platform.ITCH_IO,
                                    category=game_data.get('classification', ''),
                                    rating=game_data.get('rating', 0) / 5.0 if game_data.get('rating') else None,
                                    price=game_data.get('price', 'Free'),
                                    thumbnail=game_data.get('cover_url'),
                                    developer=game_data.get('user', {}).get('display_name'),
                                    tags=game_data.get('tags', [])
                                )
                                games.append(game)

                except Exception as e:
                    logger.error(f"Error with Itch.io endpoint {endpoint}: {e}")
                    continue

        except Exception as e:
            logger.error(f"Itch.io API error: {e}")

        return games[:limit]

class VNDBAPI(GameSearchAPI):
    """VNDB API integration"""
    def __init__(self):
        super().__init__(rate_limiter=RateLimiter(calls_per_minute=100))
        self.base_url = "https://api.vndb.org/kana/"

    async def search(self, query: str, limit: int = 10) -> List[Game]:
        """Search VNDB for visual novels"""
        games = []
        try:
            await self.rate_limiter.acquire()
            session = await self.get_session()

            search_data = {
                "filters": ["search", "=", query],
                "fields": "title,description,image.url,length,rating,released,tags.name,developers.name",
                "results": limit
            }

            async with session.post(
                f"{self.base_url}vn",
                json=search_data,
                headers={"Content-Type": "application/json"}
            ) as response:
                if response.status == 200:
                    data = await response.json()
                    for vn in data.get('results', []):
                        game = Game(
                            title=vn.get('title', 'Unknown VN'),
                            description=vn.get('description', 'No description')[:300],
                            url=f"https://vndb.org/v{vn.get('id')}",
                            platform=Platform.VNDB,
                            category="Visual Novel",
                            rating=vn.get('rating', 0) / 10.0 if vn.get('rating') else None,
                            release_date=vn.get('released'),
                            thumbnail=vn.get('image', {}).get('url'),
                            developer=', '.join([dev.get('name', '') for dev in vn.get('developers', [])]),
                            tags=[tag.get('name', '') for tag in vn.get('tags', [])]
                        )
                        games.append(game)

        except Exception as e:
            logger.error(f"VNDB API error: {e}")

        return games

class NSFWGameCog(commands.Cog):
    """Enhanced NSFW Game Cog with robust error handling and caching"""

    def __init__(self, bot):
        self.bot = bot
        self.cache = CacheManager(os.getenv("REDIS_URL"))

        # Initialize APIs
        self.apis = {}
        self._init_apis()

        # Game categories with weighted selection
        self.categories = {
            "Visual Novel": 3,
            "RPG": 2,
            "Adventure": 2,
            "Dating Sim": 3,
            "Puzzle": 1,
            "Shooter": 1,
            "Fantasy": 2,
            "Romance": 3,
            "Simulation": 2
        }

        # Statistics tracking
        self.stats = {
            'searches': 0,
            'games_found': 0,
            'cache_hits': 0,
            'api_errors': 0
        }

    def _init_apis(self):
        """Initialize all API clients"""
        try:
            # Reddit API
            if all(os.getenv(key) for key in ["REDDIT_CLIENT_ID", "REDDIT_SECRET"]):
                self.apis[Platform.REDDIT] = RedditAPI(
                    client_id=os.getenv("REDDIT_CLIENT_ID"),
                    client_secret=os.getenv("REDDIT_SECRET"),
                    user_agent=os.getenv("USER_AGENT", "NSFWGameBot/2.0")
                )
                logger.info("Reddit API initialized")

            # Itch.io API
            self.apis[Platform.ITCH_IO] = ItchIOAPI(os.getenv("ITCH_API"))
            logger.info("Itch.io API initialized")

            # VNDB API
            self.apis[Platform.VNDB] = VNDBAPI()
            logger.info("VNDB API initialized")

        except Exception as e:
            logger.error(f"API initialization error: {e}")

    async def cog_load(self):
        """Initialize cog resources"""
        await self.cache.initialize()
        logger.info("NSFWGameCog loaded successfully")

    async def cog_unload(self):
        """Cleanup resources"""
        await self.cache.close()
        for api in self.apis.values():
            await api.close()
        logger.info("NSFWGameCog unloaded")

    def _create_cache_key(self, query: str, search_type: str) -> str:
        """Create cache key for queries"""
        return f"nsfwgame:{search_type}:{hashlib.md5(query.encode()).hexdigest()}"

    async def _search_with_fallback(self, query: str, limit: int = 10) -> List[Game]:
        """Search with API fallback and error handling"""
        cache_key = self._create_cache_key(query, "search")

        # Check cache first
        cached_results = await self.cache.get(cache_key)
        if cached_results:
            self.stats['cache_hits'] += 1
            return [Game.from_dict(game_data) for game_data in cached_results]

        all_games = []
        errors = []

        # Try all available APIs
        for platform, api in self.apis.items():
            try:
                games = await api.search(query, max(1, limit // len(self.apis)))
                all_games.extend(games)
                logger.debug(f"{platform.value} returned {len(games)} games")
            except Exception as e:
                error_msg = f"{platform.value} API error: {str(e)}"
                errors.append(error_msg)
                logger.error(error_msg)
                self.stats['api_errors'] += 1

        # Sort by rating and relevance
        all_games.sort(key=lambda g: (
            g.rating or 0,
            len([tag for tag in g.tags if query.lower() in tag.lower()]),
            query.lower() in g.title.lower()
        ), reverse=True)

        result_games = all_games[:limit]

        # Cache results
        if result_games:
            await self.cache.set(
                cache_key, 
                [game.to_dict() for game in result_games],
                ttl=1800  # 30 minutes
            )

        self.stats['searches'] += 1
        self.stats['games_found'] += len(result_games)

        return result_games

    def _create_game_embed(self, game: Game, title_prefix: str = "") -> discord.Embed:
        """Create enhanced embed for a game"""
        embed = discord.Embed(
            title=f"{title_prefix}{game.title}",
            description=game.description[:2048],  # Discord limit
            color=self._get_platform_color(game.platform),
            url=game.url
        )

        embed.add_field(name="🎮 Platform", value=game.platform.value, inline=True)

        if game.category:
            embed.add_field(name="📂 Category", value=game.category, inline=True)

        if game.rating:
            stars = "⭐" * min(5, int(game.rating * 5))
            embed.add_field(name="⭐ Rating", value=f"{stars} ({game.rating:.1f})", inline=True)

        if game.developer:
            embed.add_field(name="👥 Developer", value=game.developer, inline=True)

        if game.price:
            embed.add_field(name="💰 Price", value=game.price, inline=True)

        if game.release_date:
            embed.add_field(name="📅 Released", value=game.release_date, inline=True)

        if game.tags:
            tags_str = ", ".join(game.tags[:5])  # Limit to 5 tags
            if len(game.tags) > 5:
                tags_str += f" (+{len(game.tags) - 5} more)"
            embed.add_field(name="🏷️ Tags", value=tags_str, inline=False)

        if game.thumbnail:
            embed.set_thumbnail(url=game.thumbnail)

        embed.set_footer(text=f"🔞 Adult Content • Last updated: {game.last_updated.strftime('%Y-%m-%d')}")

        return embed

    def _get_platform_color(self, platform: Platform) -> discord.Color:
        """Get color based on platform"""
        color_map = {
            Platform.REDDIT: discord.Color.orange(),
            Platform.ITCH_IO: discord.Color.from_rgb(250, 92, 92),
            Platform.STEAM: discord.Color.from_rgb(23, 26, 33),
            Platform.VNDB: discord.Color.purple(),
            Platform.NUTAKU: discord.Color.gold(),
            Platform.DLSITE: discord.Color.blue()
        }
        return color_map.get(platform, discord.Color.red())

    async def _get_weighted_random_category(self) -> str:
        """Get weighted random category"""
        categories = list(self.categories.keys())
        weights = list(self.categories.values())
        return random.choices(categories, weights=weights)[0]

    # ============= COMMANDS =============

    @commands.command(name="gamehelp")
    async def gamehelp(self, ctx):
        """Enhanced help command"""
        embed = discord.Embed(
            title="🎮 NSFW Game Bot - Help",
            description="Advanced NSFW game discovery bot with multiple platform support",
            color=discord.Color.blurple()
        )

        embed.add_field(
            name="🎲 Random Game",
            value="`n!nsfwgame [category]` - Get a random NSFW game, optionally from a specific category",
            inline=False
        )

        embed.add_field(
            name="🔍 Search Games",
            value="`n!nsfwlist <query>` - Search games across all platforms",
            inline=False
        )

        embed.add_field(
            name="📂 Categories",
            value="`n!categories` - Show available game categories",
            inline=False
        )

        embed.add_field(
            name="📊 Statistics",
            value="`n!gamestats` - Show bot usage statistics",
            inline=False
        )

        embed.add_field(
            name="🎮 Supported Platforms",
            value="Reddit, Itch.io, VNDB, Steam, Nutaku, DLsite",
            inline=False
        )

        embed.set_footer(text="🔞 All content is adult-oriented • Use responsibly")

        await ctx.send(embed=embed)

    # ============= SLASH COMMANDS =============

    @app_commands.command(name="gamehelp", description="Show comprehensive help for NSFW game commands")
    async def gamehelp_slash(self, interaction: discord.Interaction):
        """Enhanced help command with slash command support"""
        embed = discord.Embed(
            title="🎮 NSFW Game Bot - Help",
            description="Advanced NSFW game discovery bot with multiple platform support",
            color=discord.Color.blurple()
        )

        embed.add_field(
            name="🎲 Random Game",
            value="</nsfwgame:0> - Get a random NSFW game with optional category filter",
            inline=False
        )

        embed.add_field(
            name="🔍 Search Games",
            value="</nsfwlist:0> - Search games across all platforms",
            inline=False
        )

        embed.add_field(
            name="🎯 Advanced Search",
            value="</gamesearch:0> - Advanced search with filters (platform, rating, etc.)",
            inline=False
        )

        embed.add_field(
            name="📂 Categories",
            value="</categories:0> - Show available game categories",
            inline=False
        )

        embed.add_field(
            name="📊 Statistics",
            value="</gamestats:0> - Show bot usage statistics",
            inline=False
        )

        embed.add_field(
            name="⚙️ Preferences",
            value="</gameprefs:0> - Set your game preferences",
            inline=False
        )

        embed.add_field(
            name="🎮 Supported Platforms",
            value="Reddit, Itch.io, VNDB, Steam, Nutaku, DLsite",
            inline=False
        )

        embed.set_footer(text="🔞 All content is adult-oriented • Use responsibly")
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="nsfwgame", description="Get a random NSFW game")
    @app_commands.describe(
        category="Game category (optional - leave blank for random)",
        platform="Specific platform to search (optional)"
    )
    async def nsfwgame_slash(
        self, 
        interaction: discord.Interaction, 
        category: str = None,
        platform: str = None
    ):
        """Get random NSFW game with enhanced options"""
        await interaction.response.defer(thinking=True)

        try:
            if not category:
                category = await self._get_weighted_random_category()

            # Filter by platform if specified
            if platform and platform.upper() in [p.name for p in Platform]:
                target_platform = Platform[platform.upper()]
                if target_platform in self.apis:
                    games = await self.apis[target_platform].search(category, limit=20)
                else:
                    await interaction.followup.send(f"❌ Platform '{platform}' is not available.")
                    return
            else:
                games = await self._search_with_fallback(category, limit=20)

            if not games:
                embed = discord.Embed(
                    title="❌ No Games Found",
                    description=f"No games found for category '{category}'. Try a different category!",
                    color=discord.Color.red()
                )
                await interaction.followup.send(embed=embed)
                return

            game = random.choice(games)
            embed = self._create_game_embed(game, "🎲 Random Game: ")
            await interaction.followup.send(embed=embed)

        except Exception as e:
            logger.error(f"Error in nsfwgame slash command: {e}")
            await interaction.followup.send("❌ An error occurred while fetching the game. Please try again.")

    @app_commands.command(name="nsfwlist", description="Search NSFW games across platforms")
    @app_commands.describe(
        query="Search term for games",
        limit="Number of results to show (1-20)"
    )
    async def nsfwlist_slash(
        self, 
        interaction: discord.Interaction, 
        query: str, 
        limit: int = 5
    ):
        """Enhanced search with result limit control"""
        if len(query) < 2:
            await interaction.response.send_message("❌ Search query must be at least 2 characters long.", ephemeral=True)
            return

        if not 1 <= limit <= 20:
            await interaction.response.send_message("❌ Limit must be between 1 and 20.", ephemeral=True)
            return

        await interaction.response.defer(thinking=True)

        try:
            games = await self._search_with_fallback(query, limit=limit)

            if not games:
                embed = discord.Embed(
                    title="❌ No Results Found",
                    description=f"No games found for '{query}'. Try different keywords!",
                    color=discord.Color.red()
                )
                await interaction.followup.send(embed=embed)
                return

            embed = discord.Embed(
                title=f"🔍 Search Results for '{query}'",
                description=f"Found {len(games)} games across multiple platforms",
                color=discord.Color.purple()
            )

            for i, game in enumerate(games, 1):
                rating_text = f" ⭐{game.rating:.1f}" if game.rating else ""
                price_text = f" • {game.price}" if game.price and game.price != "Free" else ""

                embed.add_field(
                    name=f"{i}. {game.title}{rating_text}",
                    value=f"[🔗 Play]({game.url}) • {game.platform.value}{price_text}\n{game.description[:100]}{'...' if len(game.description) > 100 else ''}",
                    inline=False
                )

            await interaction.followup.send(embed=embed)

        except Exception as e:
            logger.error(f"Error in nsfwlist slash command: {e}")
            await interaction.followup.send("❌ An error occurred while searching. Please try again.")

    @app_commands.command(name="gamesearch", description="Advanced game search with filters")
    @app_commands.describe(
        query="Search term",
        platform="Platform to search on",
        min_rating="Minimum rating (0.0-5.0)",
        category="Game category",
        sort_by="Sort results by"
    )
    async def gamesearch_slash(
        self,
        interaction: discord.Interaction,
        query: str,
        platform: str = None,
        min_rating: float = 0.0,
        category: str = None,
        sort_by: str = "relevance"
    ):
        """Advanced search with comprehensive filters"""
        await interaction.response.defer(thinking=True)

        try:
            # Validate inputs
            if len(query) < 2:
                await interaction.followup.send("❌ Search query must be at least 2 characters long.")
                return

            if not 0.0 <= min_rating <= 5.0:
                await interaction.followup.send("❌ Rating must be between 0.0 and 5.0.")
                return

            # Perform search
            search_term = f"{query} {category}" if category else query

            if platform and platform.upper() in [p.name for p in Platform]:
                target_platform = Platform[platform.upper()]
                if target_platform in self.apis:
                    games = await self.apis[target_platform].search(search_term, limit=20)
                else:
                    await interaction.followup.send(f"❌ Platform '{platform}' is not available.")
                    return
            else:
                games = await self._search_with_fallback(search_term, limit=20)

            # Apply filters
            filtered_games = []
            for game in games:
                if game.rating is not None and game.rating < min_rating:
                    continue
                if category and category.lower() not in (game.category or "").lower():
                    continue
                filtered_games.append(game)

            # Sort results
            if sort_by == "rating":
                filtered_games.sort(key=lambda g: g.rating or 0, reverse=True)
            elif sort_by == "date":
                filtered_games.sort(key=lambda g: g.last_updated, reverse=True)
            # Default is relevance (already sorted by search)

            if not filtered_games:
                embed = discord.Embed(
                    title="❌ No Results Found",
                    description="No games match your search criteria. Try adjusting your filters.",
                    color=discord.Color.red()
                )
                await interaction.followup.send(embed=embed)
                return

            embed = discord.Embed(
                title=f"🎯 Advanced Search: '{query}'",
                description=f"Found {len(filtered_games)} games matching your criteria",
                color=discord.Color.gold()
            )

            # Show filters applied
            filters = []
            if platform: filters.append(f"Platform: {platform}")
            if min_rating > 0: filters.append(f"Min Rating: {min_rating}")
            if category: filters.append(f"Category: {category}")
            if sort_by != "relevance": filters.append(f"Sort: {sort_by}")

            if filters:
                embed.add_field(name="🔧 Filters Applied", value=" • ".join(filters), inline=False)

            for i, game in enumerate(filtered_games[:5], 1):
                rating_text = f" ⭐{game.rating:.1f}" if game.rating else ""
                price_text = f" • {game.price}" if game.price and game.price != "Free" else ""

                embed.add_field(
                    name=f"{i}. {game.title}{rating_text}",
                    value=f"[🔗 Play]({game.url}) • {game.platform.value}{price_text}\n{game.description[:100]}{'...' if len(game.description) > 100 else ''}",
                    inline=False
                )

            if len(filtered_games) > 5:
                embed.set_footer(text=f"Showing top 5 of {len(filtered_games)} results")

            await interaction.followup.send(embed=embed)

        except Exception as e:
            logger.error(f"Error in gamesearch slash command: {e}")
            await interaction.followup.send("❌ An error occurred during advanced search.")

    @app_commands.command(name="categories", description="Show NSFW game categories")
    async def categories_slash(self, interaction: discord.Interaction):
        """Show categories with enhanced formatting"""
        embed = discord.Embed(
            title="📂 Game Categories",
            description="Available categories (🔥 = more popular)",
            color=discord.Color.blue()
        )

        sorted_categories = sorted(self.categories.items(), key=lambda x: x[1], reverse=True)

        category_text = ""
        for category, weight in sorted_categories:
            popularity = "🔥" * min(3, weight)
            category_text += f"{popularity} `{category}`\n"

        embed.add_field(name="Categories", value=category_text, inline=False)
        embed.add_field(
            name="💡 Usage Tips",
            value="• Use categories with `/nsfwgame`\n• Mix categories in `/gamesearch`\n• Popular categories have better results",
            inline=False
        )

        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="gamestats", description="Show bot usage statistics")
    async def gamestats_slash(self, interaction: discord.Interaction):
        """Enhanced statistics with more details"""
        embed = discord.Embed(
            title="📊 Bot Statistics",
            color=discord.Color.green()
        )

        embed.add_field(name="🔍 Total Searches", value=f"{self.stats['searches']:,}", inline=True)
        embed.add_field(name="🎮 Games Found", value=f"{self.stats['games_found']:,}", inline=True)
        embed.add_field(name="⚡ Cache Hits", value=f"{self.stats['cache_hits']:,}", inline=True)
        embed.add_field(name="❌ API Errors", value=f"{self.stats['api_errors']:,}", inline=True)

        success_rate = ((self.stats['searches'] - self.stats['api_errors']) / max(1, self.stats['searches']) * 100)
        embed.add_field(name="🎯 Success Rate", value=f"{success_rate:.1f}%", inline=True)
        embed.add_field(name="🌐 Active APIs", value=len(self.apis), inline=True)

        # Additional stats
        avg_games_per_search = self.stats['games_found'] / max(1, self.stats['searches'])
        embed.add_field(name="📈 Avg Games/Search", value=f"{avg_games_per_search:.1f}", inline=True)

        cache_hit_rate = (self.stats['cache_hits'] / max(1, self.stats['searches']) * 100)
        embed.add_field(name="💾 Cache Hit Rate", value=f"{cache_hit_rate:.1f}%", inline=True)

        # Platform status
        platform_status = "\n".join([f"✅ {platform.value}" for platform in self.apis.keys()])
        embed.add_field(name="🔌 Platform Status", value=platform_status, inline=False)

        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="gameprefs", description="Set your game preferences")
    @app_commands.describe(
        favorite_category="Your favorite game category",
        preferred_platform="Your preferred platform",
        min_rating="Minimum rating for recommendations"
    )
    async def gameprefs_slash(
        self,
        interaction: discord.Interaction,
        favorite_category: str = None,
        preferred_platform: str = None,
        min_rating: float = 0.0
    ):
        """User preferences system (uses in-memory storage)"""
        user_id = str(interaction.user.id)

        if not hasattr(self, 'user_prefs'):
            self.user_prefs = {}

        if not any([favorite_category, preferred_platform, min_rating > 0]):
            # Show current preferences
            prefs = self.user_prefs.get(user_id, {})
            if not prefs:
                await interaction.response.send_message("❌ You haven't set any preferences yet. Use the command options to set them!")
                return

            embed = discord.Embed(
                title="⚙️ Your Game Preferences",
                color=discord.Color.blue()
            )

            if 'favorite_category' in prefs:
                embed.add_field(name="📂 Favorite Category", value=prefs['favorite_category'], inline=True)
            if 'preferred_platform' in prefs:
                embed.add_field(name="🎮 Preferred Platform", value=prefs['preferred_platform'], inline=True)
            if 'min_rating' in prefs:
                embed.add_field(name="⭐ Min Rating", value=f"{prefs['min_rating']:.1f}", inline=True)

            embed.set_footer(text="These preferences will be used for personalized recommendations")
            await interaction.response.send_message(embed=embed)
            return

        # Set preferences
        if user_id not in self.user_prefs:
            self.user_prefs[user_id] = {}

        changes = []
        if favorite_category:
            self.user_prefs[user_id]['favorite_category'] = favorite_category
            changes.append(f"Favorite category: {favorite_category}")

        if preferred_platform:
            self.user_prefs[user_id]['preferred_platform'] = preferred_platform
            changes.append(f"Preferred platform: {preferred_platform}")

        if min_rating > 0:
            self.user_prefs[user_id]['min_rating'] = min_rating
            changes.append(f"Minimum rating: {min_rating}")

        embed = discord.Embed(
            title="✅ Preferences Updated",
            description="Your preferences have been saved:\n• " + "\n• ".join(changes),
            color=discord.Color.green()
        )

        await interaction.response.send_message(embed=embed, ephemeral=True)

    # ============= AUTOCOMPLETE =============

    @nsfwgame_slash.autocomplete('category')
    @gamesearch_slash.autocomplete('category')
    async def category_autocomplete(self, interaction: discord.Interaction, current: str) -> List[app_commands.Choice[str]]:
        """Autocomplete for game categories"""
        categories = list(self.categories.keys())
        return [
            app_commands.Choice(name=category, value=category)
            for category in categories
            if current.lower() in category.lower()
        ][:25]

    @nsfwgame_slash.autocomplete('platform')
    @gamesearch_slash.autocomplete('platform')
    @gameprefs_slash.autocomplete('preferred_platform')
    async def platform_autocomplete(self, interaction: discord.Interaction, current: str) -> List[app_commands.Choice[str]]:
        """Autocomplete for platforms"""
        platforms = [platform.value for platform in Platform if platform in self.apis]
        return [
            app_commands.Choice(name=platform, value=platform)
            for platform in platforms
            if current.lower() in platform.lower()
        ][:25]

    @gamesearch_slash.autocomplete('sort_by')
    async def sort_autocomplete(self, interaction: discord.Interaction, current: str) -> List[app_commands.Choice[str]]:
        """Autocomplete for sort options"""
        sort_options = ["relevance", "rating", "date"]
        return [
            app_commands.Choice(name=option.title(), value=option)
            for option in sort_options
            if current.lower() in option.lower()
        ]

    @gameprefs_slash.autocomplete('favorite_category')
    async def prefs_category_autocomplete(self, interaction: discord.Interaction, current: str) -> List[app_commands.Choice[str]]:
        """Autocomplete for preference categories"""
        return await self.category_autocomplete(interaction, current)

    # ============= PREFIX COMMANDS (for backward compatibility) =============

    @commands.command(name="nsfwgame")
    async def nsfwgame(self, ctx, *, category: str = None):
        """Get random NSFW game (prefix version)"""
        # Create a mock interaction for code reuse
        class MockInteraction:
            def __init__(self, ctx):
                self.user = ctx.author
                self.response = MockResponse(ctx)
                self.followup = MockFollowup(ctx)

        class MockResponse:
            def __init__(self, ctx):
                self.ctx = ctx
                self._deferred = False

            async def defer(self, thinking=False):
                self._deferred = True
                if hasattr(self.ctx, 'typing'):
                    return self.ctx.typing()

            async def send_message(self, *args, **kwargs):
                return await self.ctx.send(*args, **kwargs)

        class MockFollowup:
            def __init__(self, ctx):
                self.ctx = ctx

            async def send(self, *args, **kwargs):
                return await self.ctx.send(*args, **kwargs)

        mock_interaction = MockInteraction(ctx)
        await self.nsfwgame_slash(mock_interaction, category)

    @commands.command(name="nsfwlist")
    async def nsfwlist(self, ctx, *, query: str):
        """Search NSFW games (prefix version)"""
        class MockInteraction:
            def __init__(self, ctx):
                self.user = ctx.author
                self.response = MockResponse(ctx)
                self.followup = MockFollowup(ctx)

        class MockResponse:
            def __init__(self, ctx):
                self.ctx = ctx

            async def defer(self, thinking=False):
                if hasattr(self.ctx, 'typing'):
                    return self.ctx.typing()

            async def send_message(self, *args, **kwargs):
                return await self.ctx.send(*args, **kwargs)

        class MockFollowup:
            def __init__(self, ctx):
                self.ctx = ctx

            async def send(self, *args, **kwargs):
                return await self.ctx.send(*args, **kwargs)

        mock_interaction = MockInteraction(ctx)
        await self.nsfwlist_slash(mock_interaction, query)

    @commands.command(name="categories")
    async def categories_cmd(self, ctx):
        """Show categories (prefix version)"""
        class MockInteraction:
            def __init__(self, ctx):
                self.response = MockResponse(ctx)

        class MockResponse:
            def __init__(self, ctx):
                self.ctx = ctx

            async def send_message(self, *args, **kwargs):
                return await self.ctx.send(*args, **kwargs)

        mock_interaction = MockInteraction(ctx)
        await self.categories_slash(mock_interaction)

    @commands.command(name="gamestats")
    async def gamestats(self, ctx):
        """Show stats (prefix version)"""
        class MockInteraction:
            def __init__(self, ctx):
                self.response = MockResponse(ctx)

        class MockResponse:
            def __init__(self, ctx):
                self.ctx = ctx

            async def send_message(self, *args, **kwargs):
                return await self.ctx.send(*args, **kwargs)

        mock_interaction = MockInteraction(ctx)
        await self.gamestats_slash(mock_interaction)

async def setup(bot):
    """Setup function for the cog"""
    await bot.add_cog(NSFWGameCog(bot))
