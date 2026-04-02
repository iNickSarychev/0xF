import sqlite3
import hashlib
from config import config


class Database:
    def __init__(self, db_path: str = config.DB_PATH):
        self.db_path = db_path
        self._init_db()

    def _init_db(self):
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS sent_news (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    news_hash TEXT UNIQUE NOT NULL,
                    title TEXT NOT NULL,
                    sent_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS subscribers (
                    chat_id INTEGER PRIMARY KEY
                )
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS rejected_vectors (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    text_preview TEXT NOT NULL,
                    vector_json TEXT NOT NULL,
                    rejected_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            conn.commit()

    def is_news_sent(self, title: str, link: str) -> bool:
        """Проверяет, была ли новость уже отправлена по хешу (title+link)."""
        news_hash = self._generate_hash(title, link)
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute("SELECT 1 FROM sent_news WHERE news_hash = ?", (news_hash,))
            return cursor.fetchone() is not None

    def save_news(self, title: str, link: str):
        """Сохраняет новость в базу после отправки."""
        news_hash = self._generate_hash(title, link)
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("INSERT OR IGNORE INTO sent_news (news_hash, title) VALUES (?, ?)", (news_hash, title))
            conn.commit()

    def add_subscriber(self, chat_id: int):
        """Добавляет подписчика."""
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("INSERT OR IGNORE INTO subscribers (chat_id) VALUES (?)", (chat_id,))
            conn.commit()

    def get_subscribers(self) -> list[int]:
        """Возвращает список chat_id всех подписчиков."""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute("SELECT chat_id FROM subscribers")
            return [row[0] for row in cursor.fetchall()]

    def _generate_hash(self, title: str, link: str) -> str:
        return hashlib.md5(f"{title}{link}".encode()).hexdigest()

    def save_rejected_vector(self, text_preview: str, vector: list[float]):
        import json
        vector_json = json.dumps(vector)
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("INSERT INTO rejected_vectors (text_preview, vector_json) VALUES (?, ?)", (text_preview, vector_json))
            conn.commit()

    def get_all_rejected_vectors(self) -> list[tuple[str, list[float]]]:
        import json
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute("SELECT text_preview, vector_json FROM rejected_vectors")
            return [(row[0], json.loads(row[1])) for row in cursor.fetchall()]

db = Database()
