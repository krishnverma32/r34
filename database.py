
import sqlite3
import logging
from datetime import datetime

logger = logging.getLogger(__name__)

class Database:
    def __init__(self, db_path="bot_data.db"):
        self.db_path = db_path
        self.init_database()
    
    def init_database(self):
        """Initialize the database with required tables"""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            
            # Create verified_users table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS verified_users (
                    user_id INTEGER PRIMARY KEY,
                    verified_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    verification_method TEXT DEFAULT 'reaction'
                )
            """)
            
            # Create server_settings table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS server_settings (
                    guild_id INTEGER PRIMARY KEY,
                    verification_role_id INTEGER,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            
            conn.commit()
            logger.info("Database initialized successfully")
    
    def is_user_verified(self, user_id):
        """Check if a user is verified"""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT 1 FROM verified_users WHERE user_id = ?", (user_id,))
            return cursor.fetchone() is not None
    
    def add_verified_user(self, user_id, method="reaction"):
        """Add a verified user to the database"""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute(
                "INSERT OR REPLACE INTO verified_users (user_id, verification_method) VALUES (?, ?)",
                (user_id, method)
            )
            conn.commit()
            logger.info(f"Added verified user: {user_id}")
    
    def get_server_settings(self, guild_id):
        """Get server settings for a guild"""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT verification_role_id FROM server_settings WHERE guild_id = ?", (guild_id,))
            result = cursor.fetchone()
            if result:
                return {"verification_role_id": result[0]}
            return {}
    
    def set_verification_role(self, guild_id, role_id):
        """Set the verification role for a guild"""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute(
                "INSERT OR REPLACE INTO server_settings (guild_id, verification_role_id) VALUES (?, ?)",
                (guild_id, role_id)
            )
            conn.commit()
            logger.info(f"Set verification role {role_id} for guild {guild_id}")
