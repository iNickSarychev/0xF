import asyncio
import logging
import httpx
import ollama
from typing import Any, Dict, List, Optional
from config import config

logger = logging.getLogger(__name__)

class LLMGateway:
    """
    Централизованный шлюз для работы с Ollama.
    Обеспечивает последовательное выполнение запросов (Semaphore(1))
    и единые настройки стабильности (num_ctx, keep_alive).
    """
    _instance = None
    _semaphore = asyncio.Semaphore(1)

    def __new__(cls, *args, **kwargs):
        if not cls._instance:
            cls._instance = super(LLMGateway, cls).__new__(cls)
        return cls._instance

    def __init__(self, host: str = config.OLLAMA_BASE_URL, timeout: float = 300.0):
        if not hasattr(self, 'initialized'):
            self.client = ollama.AsyncClient(
                host=host,
                timeout=httpx.Timeout(timeout, connect=10.0)
            )
            self.initialized = True

    async def generate(
        self, 
        model: str, 
        prompt: str, 
        system: Optional[str] = None,
        images: Optional[List[str]] = None,
        format: str = "",
        options: Optional[Dict[str, Any]] = None,
        keep_alive: str = "5m"
    ) -> Dict[str, Any]:
        """
        Выполняет запрос к Ollama через семафор.
        """
        # Базовые опции стабильности
        base_options = {
            "num_ctx": 8192,
            "temperature": 0.7,
            "num_thread": 4, 
            "low_vram": True,
        }
        if options:
            base_options.update(options)

        async with self._semaphore:
            try:
                response = await self.client.generate(
                    model=model,
                    prompt=prompt,
                    system=system,
                    images=images,
                    format=format,
                    options=base_options,
                    keep_alive=keep_alive
                )
                return response
            except Exception as e:
                logger.error(f"LLMGateway Error: {e}")
                raise

    async def chat(
        self,
        model: str,
        messages: List[Dict[str, str]],
        format: str = "",
        options: Optional[Dict[str, Any]] = None,
        keep_alive: str = "5m"
    ) -> Dict[str, Any]:
        """
        Выполняет chat-запрос к Ollama через семафор.
        """
        base_options = {
            "num_ctx": 8192,
            "num_thread": 4,
            "low_vram": True,
        }
        if options:
            base_options.update(options)

        async with self._semaphore:
            try:
                response = await self.client.chat(
                    model=model,
                    messages=messages,
                    format=format,
                    options=base_options,
                    keep_alive=keep_alive
                )
                return response
            except Exception as e:
                logger.error(f"LLMGateway Chat Error: {e}")
                raise

llm_gateway = LLMGateway()
