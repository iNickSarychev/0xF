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
        "https://ai.meta.com/blog/feed/",
        # AI-новости
        "https://techcrunch.com/category/artificial-intelligence/feed/",
        "https://www.wired.com/feed/tag/ai/latest/rss",
        "https://feeds.feedburner.com/venturebeat/SZYF",
        # Технологии
        "https://feeds.arstechnica.com/arstechnica/technology-lab",
        "https://www.technologyreview.com/feed/",
        "https://www.theverge.com/rss/index.xml",
        # 🧠 AI-лаборатории и профильные фреймворки (дополнение)
        "https://www.anthropic.com/feed.xml", # Claude сейчас часто обходит GPT в кодинге
        "https://blog.langchain.dev/rss/", # Главный фреймворк для сборки AI-агентов
    
        # 🔬 Хардкор и сырые исследования (arXiv)
         "https://export.arxiv.org/rss/cs.AI", # Свежие пейперы по искусственному интеллекту
        "https://export.arxiv.org/rss/cs.CL", # Computation and Language (все новые LLM появляются тут)
    
         # 👨‍💻 Комьюнити разработчиков (инсайты с полей)
        "https://hnrss.org/newest?q=AI", # Фильтр Hacker News по теме AI — абсолютный мастхэв
        "https://hnrss.org/newest?q=LLM", # Фильтр Hacker News по LLM
        "https://dev.to/feed/tag/ai", # Практические статьи от разработчиков
        "https://dev.to/feed/tag/prompt-engineering", # Трюки по промптингу
    ]


config = Config()
