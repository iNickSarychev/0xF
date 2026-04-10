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
        # ================= 🔥 AI-МОДЕЛИ И ИССЛЕДОВАНИЯ =================
        "https://blog.research.google/feeds/posts/default?alt=rss",  # Google Research
        "https://openai.com/blog/rss.xml",  # OpenAI Official
        "https://bair.berkeley.edu/blog/feed.xml",  # Berkeley AI Research
        "https://huyenchip.com/feed.xml",  # Chip Huyen (MLOps, LLM engineering)
        "https://blog.langchain.dev/rss/",  # LangChain Blog

        # ================= 📰 AI-НОВОСТИ & TECH =================
        "https://techcrunch.com/category/artificial-intelligence/feed/",
        "https://www.wired.com/feed/tag/ai/latest/rss",  # Wired AI
        "https://feeds.feedburner.com/venturebeat/SZYF",  # VentureBeat AI
        "https://www.marktechpost.com/feed/",  # Research summaries
        "https://www.theverge.com/ai-artificial-intelligence/rss/index.xml",  # The Verge (исправлено)
        "https://feeds.arstechnica.com/arstechnica/technology-lab",
        "https://www.technologyreview.com/feed/",

        # ================= 🇷🇺 РЕСУРСЫ (RU) =================
        "https://habr.com/ru/rss/articles/?fl=ru",  # Habr
        "https://tproger.ru/feed/",  # Tproger
        "https://3dnews.ru/news/rss/",  # 3DNews
        "https://www.cnews.ru/inc/rss/news.xml",  # CNews
        "https://www.computerra.ru/feed/",  # Computerra
        "https://overclockers.ru/rss/news",  # Overclockers (исправлено)
        "https://www.securitylab.ru/_services/export/rss/news.php",  # SecurityLab (исправлено)

        # ================= 🔬 ArXiv & DEV =================
        "https://arxiv.org/rss/cs.AI",  # Мягче защита, чем на export.arxiv.org
        "https://arxiv.org/rss/cs.CL",
        "https://news.ycombinator.com/rss",  # HackerNews
        "https://dev.to/feed/tag/ai",  # Dev.to AI tag
    ]


config = Config()
