import os
from dotenv import load_dotenv

load_dotenv()


class Config:
    BOT_TOKEN = os.getenv("BOT_TOKEN")
    OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "0xf-writer")
    OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
    DB_PATH = os.getenv("DB_PATH", "news.db")
    CHANNEL_ID = os.getenv("CHANNEL_ID", "@AxFUTURE")
    ADMIN_CHAT_ID = int(os.getenv("ADMIN_CHAT_ID", "341481395"))
    LLM_OPTIONS = {"num_predict": 4096}

    # RSS-ленты: AI-модели (приоритет), технологии, AGI
    RSS_FEEDS = [
        # 🔥 AI-модели и исследования (приоритет)
        "https://huggingface.co/blog/feed.xml",
        "https://blog.google/technology/ai/rss/",
        "https://openai.com/blog/rss.xml",
        "https://deepmind.google/blog/rss.xml",
        "https://ai.meta.com/blog/rss/",
        # AI-новости
        "https://techcrunch.com/category/artificial-intelligence/feed/",
        "https://www.wired.com/feed/tag/ai/latest/rss",
        "https://feeds.feedburner.com/venturebeat/SZYF",
        # Технологии
        "https://feeds.arstechnica.com/arstechnica/technology-lab",
        "https://www.technologyreview.com/feed/",
        "https://www.theverge.com/rss/index.xml",
    ]


config = Config()
