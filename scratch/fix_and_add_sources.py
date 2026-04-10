import sqlite3
import os

DB_PATH = "bot_database.db"

new_sources = [
    ("The Verge (AI)", "https://www.theverge.com/ai-artificial-intelligence/rss/index.xml"),
    ("TechCrunch (AI)", "https://techcrunch.com/category/artificial-intelligence/feed/"),
    ("MIT Tech Review", "https://www.technologyreview.com/feed/"),
    ("Wired (AI)", "https://www.wired.com/category/science/ai/feed/"),
    ("Arxiv AI", "https://rss.arxiv.org/rss/cs.AI"),
    ("NVIDIA Blog", "https://blogs.nvidia.com/feed/"),
    ("AWS Machine Learning", "https://aws.amazon.com/blogs/machine-learning/feed/"),
]

def update_db():
    if not os.path.exists(DB_PATH):
        print(f"Database {DB_PATH} not found!")
        return

    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    # 1. Исправляем Meta AI
    cursor.execute(
        "UPDATE sources SET url = ? WHERE url LIKE ?", 
        ("https://ai.meta.com/blog/feed/", "%ai.meta.com/blog/rss/%")
    )
    print("Meta AI URL updated.")

    # 2. Добавляем новые
    for name, url in new_sources:
        try:
            cursor.execute("INSERT OR IGNORE INTO sources (name, url) VALUES (?, ?)", (name, url))
            print(f"Added: {name}")
        except Exception as e:
            print(f"Error adding {name}: {e}")

    conn.commit()
    conn.close()
    print("Update complete.")

if __name__ == "__main__":
    update_db()
