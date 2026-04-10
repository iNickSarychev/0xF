import os
from dotenv import load_dotenv

load_dotenv()


class Config:
    BOT_TOKEN = os.getenv("BOT_TOKEN")
    OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "0xf-writer")
    OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
    OLLAMA_KEEP_ALIVE = os.getenv("OLLAMA_KEEP_ALIVE", "1m")
    DB_PATH = os.getenv("DB_PATH", "news.db")
    CHANNEL_ID = os.getenv("CHANNEL_ID", "@AxFUTURE")
    ADMIN_CHAT_ID = int(os.getenv("ADMIN_CHAT_ID", "341481395"))

    # RSS-ленты: AI-модели (приоритет), технологии, AGI
    RSS_FEEDS = [
        "https://openai.com/blog/rss.xml",
        "https://bair.berkeley.edu/blog/feed.xml",
        "https://huyenchip.com/feed.xml",
        "https://blog.langchain.dev/rss/",
        "https://techcrunch.com/category/artificial-intelligence/feed/",
        "https://www.wired.com/feed/tag/ai/latest/rss",
        "https://www.marktechpost.com/feed/",
        "https://www.theverge.com/rss/index.xml",
        "https://feeds.arstechnica.com/arstechnica/technology-lab",
        "https://www.technologyreview.com/feed/",
        "https://habr.com/ru/rss/articles/?fl=ru",
        "https://tproger.ru/feed/",
        "https://3dnews.ru/news/rss/",
        "https://www.cnews.ru/inc/rss/news.xml",
        "https://www.computerra.ru/feed/",
        "https://www.securitylab.ru/_services/export/rss/news.php",
        "https://arxiv.org/rss/cs.AI",
        "https://dev.to/feed/tag/ai",
    ]


config = Config()
