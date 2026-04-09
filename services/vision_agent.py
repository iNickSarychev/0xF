import ollama
import httpx
import base64
import logging
from typing import Optional
from config import config
from services.prompts import VISION_PROMPT

logger = logging.getLogger(__name__)

class VisionAgent:
    def __init__(self, model: str = "llava:7b"):
        self.model = model
        self.client = ollama.AsyncClient(
            host=config.OLLAMA_BASE_URL,
            timeout=httpx.Timeout(300.0, connect=10.0)
        )

    async def check_image(self, post_text: str, image_url: str) -> bool:
        """Проверяет релевантность картинки через LLaVA."""
        if not await self.is_available():
            logger.warning("VisionAgent: Ollama is offline. Skipping image.")
            return False
            
        try:
            # Скачивание картинки
            async with httpx.AsyncClient() as client:
                resp = await client.get(image_url, timeout=10)
                if resp.status_code != 200:
                    return False
                image_bytes = resp.content
                image_b64 = base64.b64encode(image_bytes).decode('utf-8')

            prompt = VISION_PROMPT.format(post_text=post_text)
            
            response = await self.client.generate(
                model=self.model,
                prompt=prompt,
                images=[image_b64],
                stream=False,
                options={"num_predict": 10, "temperature": 0.5}
            )
            
            answer = response['response'].strip().upper()
            logger.info(f"Vision verdict for {image_url}: {answer}")
            return "YES" in answer

        except Exception as e:
            logger.error(f"VisionAgent error: {e}")
            return False

    async def is_available(self) -> bool:
        try:
            await self.client.list()
            return True
        except Exception:
            return False

vision_agent = VisionAgent()
