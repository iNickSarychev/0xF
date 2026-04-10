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
            try:
                conn.execute("ALTER TABLE sent_news ADD COLUMN source_url TEXT")
            except sqlite3.OperationalError:
                pass  # Столбец уже существует

            conn.execute("""
                CREATE TABLE IF NOT EXISTS pending_posts (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    text TEXT NOT NULL,
                    image_url TEXT,
                    source_url TEXT,
                    image_query TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS subscribers (
                    chat_id INTEGER PRIMARY KEY
                )
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS sent_vectors (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    text_preview TEXT NOT NULL,
                    vector_json TEXT NOT NULL,
                    sent_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
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
            conn.execute("""
                CREATE TABLE IF NOT EXISTS sources (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    url TEXT UNIQUE NOT NULL
                )
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS settings (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                )
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS scheduled_posts (
                    message_id INTEGER PRIMARY KEY,
                    data_json TEXT NOT NULL,
                    publish_at TIMESTAMP NOT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            conn.commit()

            # Всегда синхронизируем ленты из конфига с БД (новые добавятся, старые проигнорируются)
            for feed in config.RSS_FEEDS:
                conn.execute("INSERT OR IGNORE INTO sources (url) VALUES (?)", (feed,))
            
            # Удаляем 404 адреса, чтобы бот не стучался впустую
            bad_feeds = [
                "https://ai.meta.com/blog/rss/",
                "https://ai.meta.com/blog/feed/",
                "https://www.anthropic.com/feed.xml",
                "https://dev.to/feed/tag/prompt-engineering"
            ]
            for bad_feed in bad_feeds:
                conn.execute("DELETE FROM sources WHERE url = ?", (bad_feed,))
            
            conn.commit()
                
            cursor = conn.execute("SELECT COUNT(*) FROM settings WHERE key='theme'")
            if cursor.fetchone()[0] == 0:
                default_theme = (
                    "1. Прорывные технологии и открытия, которые перевернут мир (футуризм, квантовые вычисления, биохокинг, новая энергия)\n"
                    "2. Будущее человечества и цивилизации: как изменится наша жизнь в ближайшие 5-10 лет\n"
                    "3. Важные релизы новых AI-моделей (скорость, возможности, архитектура)\n"
                    "4. Крупные запуски IT-корпораций и скрытые мотивы рынка\n"
                    "5. Регулирование AI, угрозы безопасности, путь к AGI\n"
                    "6. Прочие важные технологические тренды"
                )
                conn.execute("INSERT INTO settings (key, value) VALUES ('theme', ?)", (default_theme,))
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
            conn.execute("INSERT OR IGNORE INTO sent_news (news_hash, title, source_url) VALUES (?, ?, ?)", (news_hash, title, link))
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

    def save_sent_vector(self, text_preview: str, vector: list[float]):
        import json
        vector_json = json.dumps(vector)
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("INSERT INTO sent_vectors (text_preview, vector_json) VALUES (?, ?)", (text_preview, vector_json))
            # Удаляем старые векторы (старше 7 дней), чтобы база не пухла
            conn.execute("DELETE FROM sent_vectors WHERE sent_at < datetime('now', '-7 days')")
            conn.commit()

    def get_all_sent_vectors(self) -> list[tuple[str, list[float]]]:
        import json
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute("SELECT text_preview, vector_json FROM sent_vectors WHERE sent_at >= datetime('now', '-7 days')")
            return [(row[0], json.loads(row[1])) for row in cursor.fetchall()]

    def add_source(self, url: str) -> bool:
        with sqlite3.connect(self.db_path) as conn:
            try:
                conn.execute("INSERT INTO sources (url) VALUES (?)", (url,))
                conn.commit()
                return True
            except sqlite3.IntegrityError:
                return False

    def remove_source(self, source_id: int) -> bool:
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute("DELETE FROM sources WHERE id = ?", (source_id,))
            conn.commit()
            return cursor.rowcount > 0

    # Группа методов для ожидающих публикации постов (Persistence)
    def add_pending_post(self, text: str, image_url: str = None, source_url: str = None, image_query: str = None) -> int:
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute(
                "INSERT INTO pending_posts (text, image_url, source_url, image_query) VALUES (?, ?, ?, ?)",
                (text, image_url, source_url, image_query)
            )
            conn.commit()
            return cursor.lastrowid

    def get_pending_post(self, post_id: int) -> dict | None:
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute(
                "SELECT text, image_url, source_url, image_query FROM pending_posts WHERE id = ?",
                (post_id,)
            )
            row = cursor.fetchone()
            if row:
                return {
                    "text": row[0],
                    "image_url": row[1],
                    "source_url": row[2],
                    "image_query": row[3]
                }
            return None

    def save_pending_post(self, message_id: int, data: dict, publish_at: str):
        import json
        data_json = json.dumps(data)
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("INSERT OR REPLACE INTO scheduled_posts (message_id, data_json, publish_at) VALUES (?, ?, ?)",
                         (message_id, data_json, publish_at))
            conn.commit()

    def get_pending_post(self, message_id: int) -> dict | None:
        import json
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute("SELECT data_json FROM scheduled_posts WHERE message_id = ?", (message_id,))
            row = cursor.fetchone()
            return json.loads(row[0]) if row else None

    def remove_pending_post(self, message_id: int):
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("DELETE FROM scheduled_posts WHERE message_id = ?", (message_id,))
            conn.commit()

    def get_all_pending_posts(self) -> list[tuple[int, dict, str]]:
        import json
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute("SELECT message_id, data_json, publish_at FROM scheduled_posts")
            results = []
            for row in cursor.fetchall():
                try:
                    results.append((row[0], json.loads(row[1]), row[2]))
                except:
                    pass
            return results

    def get_all_sources(self) -> list[tuple[int, str]]:
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute("SELECT id, url FROM sources")
            return cursor.fetchall()
            
    def get_theme(self) -> str:
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute("SELECT value FROM settings WHERE key='theme'")
            row = cursor.fetchone()
            return row[0] if row else ""
            
    def set_theme(self, theme: str):
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("REPLACE INTO settings (key, value) VALUES ('theme', ?)", (theme,))
            conn.commit()

db = Database()
