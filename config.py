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
        "https://huggingface.co/papers/rss.xml",  # HF Daily Papers (если blog не тянет)
        "https://blog.research.google/feeds/posts/default?alt=rss",  # Google Research (вкл. DeepMind)
        "https://openai.com/blog/rss.xml",
        "https://bair.berkeley.edu/blog/feed.xml",  # Berkeley AI Research
        "https://huyenchip.com/feed.xml",  # Chip Huyen (MLOps, LLM инжиниринг)

        # ================= 📰 AI-НОВОСТИ =================
        "https://techcrunch.com/category/artificial-intelligence/feed/",
        "https://www.wired.com/feed/category/artificial-intelligence/latest/rss",
        "https://feeds.feedburner.com/venturebeat/SZYF",
        "https://www.marktechpost.com/feed/",  # Краткие обзоры научных работ

        # ================= 💻 ТЕХНОЛОГИИ =================
        "https://feeds.arstechnica.com/arstechnica/technology-lab",
        "https://www.technologyreview.com/feed/",
        "https://www.theverge.com/ai-artificial-intelligence/rss/index.xml",  # Раздел AI на The Verge

        # ================= 🇷🇺 РУССКОЯЗЫЧНЫЕ ТОПОВЫЕ РЕСУРСЫ =================
        "https://habr.com/ru/rss/articles/?fl=ru",  # Хабр - все статьи (проверен RSS-валидатором) [citation:1]
        "https://tproger.ru/feed/",  # Tproger - новости и статьи для разработчиков [citation:3]
        "https://3dnews.ru/news/rss/",  # 3DNews - ведущее издание о цифровых технологиях [citation:5]
        "https://www.cnews.ru/inc/rss/news.xml",  # CNews - крупнейшее IT-издание для бизнеса [citation:4]
        "https://www.computerra.ru/feed/",  # Компьютерра - легендарный IT-журнал [citation:6]
        "https://overclockers.ru/rss/news",  # Overclockers - новости железа и IT [citation:10]
        "https://www.securitylab.ru/_services/export/rss/",  # SecurityLab - кибербезопасность и технологии [citation:9]

        # ================= 🧠 AI-ЛАБОРАТОРИИ И ФРЕЙМВОРКИ =================
        "https://blog.langchain.dev/rss/",  # Главный фреймворк для AI-агентов

        # ================= 🔬 СЫРЫЕ ИССЛЕДОВАНИЯ (arXiv) =================
        "https://export.arxiv.org/rss/cs.AI",  # Свежие пейперы по AI
        "https://export.arxiv.org/rss/cs.CL",  # Computation and Language (LLM появляются тут)

        # ================= 👨💻 КОМЬЮНИТИ РАЗРАБОТЧИКОВ =================
        "https://news.ycombinator.com/rss",  # HackerNews (фильтровать в ридере, т.к. HNRSS под блокировкой)
        "https://dev.to/feed/tag/ai",  # Практические статьи от разработчиков
    ]


config = Config()
