import ollama
import httpx
import base64
import logging
import io
from PIL import Image
from config import config
from services.prompts import VISION_PROMPT
from services.llm_gateway import llm_gateway

logger = logging.getLogger(__name__)

class VisionAgent:
    def __init__(self, model: str = "llava:7b"):
        self.model = model

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

            # Сжимаем картинку до 512x512 для экономии ресурсов Ollama (защита от OOM)
            with Image.open(io.BytesIO(image_bytes)) as img:
                img.thumbnail((512, 512))
                output = io.BytesIO()
                # Используем JPEG для уменьшения объема данных
                img.save(output, format="JPEG", quality=85)
                image_b64 = base64.b64encode(output.getvalue()).decode('utf-8')

            prompt = VISION_PROMPT.format(post_text=post_text)
            
            response = await llm_gateway.generate(
                model=self.model,
                prompt=prompt,
                images=[image_b64],
                options={"num_predict": 10, "temperature": 0.5},
                keep_alive="5m"
            )
            
            answer = response['response'].strip().upper()
            logger.info(f"Vision verdict for {image_url}: {answer}")
            return "YES" in answer

        except Exception as e:
            logger.error(f"VisionAgent error: {e}")
            return False

    async def is_available(self) -> bool:
        try:
            await llm_gateway.client.list()
            return True
        except Exception:
            return False

vision_agent = VisionAgent()
