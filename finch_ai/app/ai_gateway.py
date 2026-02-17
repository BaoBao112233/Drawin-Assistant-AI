"""AI Gateway - Abstraction layer for multiple AI providers."""
import os
import logging
import time
from typing import Optional, Dict, Any, List
from enum import Enum

import httpx
from tenacity import retry, stop_after_attempt, wait_exponential

logger = logging.getLogger(__name__)


class AIProvider(str, Enum):
    """Supported AI providers."""
    OPENAI = "openai"
    GEMINI = "gemini"
    GROQ = "groq"
    LOCAL = "local"


class AIGateway:
    """
    Unified interface for multiple AI providers.
    Supports OpenAI, Google Gemini, and local models with fallback logic.
    """
    
    def __init__(self):
        self.openai_key = os.getenv("OPENAI_API_KEY")
        self.gemini_key = os.getenv("GOOGLE_API_KEY")
        self.anthropic_key = os.getenv("ANTHROPIC_API_KEY")
        self.groq_key = os.getenv("GROQ_API_KEY")
        self.default_model = os.getenv("DEFAULT_AI_MODEL", "groq")
        
        # Token usage tracking
        self.token_usage = {
            "total_requests": 0,
            "total_tokens": 0,
            "by_provider": {}
        }
        
    @retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=2, max=10))
    async def generate(
        self,
        prompt: str,
        model: Optional[str] = None,
        system_prompt: Optional[str] = None,
        temperature: float = 0.7,
        max_tokens: int = 2000,
        timeout: int = 30
    ) -> Dict[str, Any]:
        """
        Generate text using specified AI model with fallback.
        
        Args:
            prompt: User prompt
            model: Model provider (openai, gemini, local). Uses default if None.
            system_prompt: System/instructions prompt
            temperature: Randomness (0-1)
            max_tokens: Maximum response tokens
            timeout: Request timeout in seconds
            
        Returns:
            Dict with 'text', 'provider', 'model', 'tokens', 'duration'
        """
        start_time = time.time()
        model = model or self.default_model
        
        # Try primary model
        try:
            result = await self._generate_with_provider(
                provider=model,
                prompt=prompt,
                system_prompt=system_prompt,
                temperature=temperature,
                max_tokens=max_tokens,
                timeout=timeout
            )
            result["duration"] = time.time() - start_time
            self._track_usage(model, result.get("tokens", 0))
            return result
            
        except Exception as e:
            logger.error(f"Error with primary model {model}: {e}")
            
            # Fallback logic
            fallback_order = self._get_fallback_order(model)
            for fallback in fallback_order:
                try:
                    logger.info(f"Trying fallback: {fallback}")
                    result = await self._generate_with_provider(
                        provider=fallback,
                        prompt=prompt,
                        system_prompt=system_prompt,
                        temperature=temperature,
                        max_tokens=max_tokens,
                        timeout=timeout
                    )
                    result["duration"] = time.time() - start_time
                    result["fallback_used"] = True
                    self._track_usage(fallback, result.get("tokens", 0))
                    return result
                except Exception as fallback_error:
                    logger.error(f"Fallback {fallback} failed: {fallback_error}")
                    continue
            
            # All providers failed
            raise Exception(f"All AI providers failed. Last error: {e}")
    
    async def _generate_with_provider(
        self,
        provider: str,
        prompt: str,
        system_prompt: Optional[str],
        temperature: float,
        max_tokens: int,
        timeout: int
    ) -> Dict[str, Any]:
        """Generate with specific provider."""
        
        if provider == AIProvider.OPENAI:
            return await self._generate_openai(prompt, system_prompt, temperature, max_tokens, timeout)
        elif provider == AIProvider.GEMINI:
            return await self._generate_gemini(prompt, system_prompt, temperature, max_tokens, timeout)
        elif provider == AIProvider.GROQ:
            return await self._generate_groq(prompt, system_prompt, temperature, max_tokens, timeout)
        elif provider == AIProvider.LOCAL:
            return await self._generate_local(prompt, system_prompt, temperature, max_tokens, timeout)
        else:
            raise ValueError(f"Unknown provider: {provider}")
    
    async def _generate_openai(
        self,
        prompt: str,
        system_prompt: Optional[str],
        temperature: float,
        max_tokens: int,
        timeout: int
    ) -> Dict[str, Any]:
        """Generate using OpenAI API."""
        if not self.openai_key:
            raise ValueError("OpenAI API key not configured")
        
        try:
            from openai import AsyncOpenAI
            
            client = AsyncOpenAI(api_key=self.openai_key, timeout=timeout)
            
            messages = []
            if system_prompt:
                messages.append({"role": "system", "content": system_prompt})
            messages.append({"role": "user", "content": prompt})
            
            response = await client.chat.completions.create(
                model="gpt-4o-mini",  # Cost-effective but capable
                messages=messages,
                temperature=temperature,
                max_tokens=max_tokens
            )
            
            return {
                "text": response.choices[0].message.content,
                "provider": "openai",
                "model": response.model,
                "tokens": response.usage.total_tokens,
                "fallback_used": False
            }
            
        except Exception as e:
            logger.error(f"OpenAI error: {e}")
            raise
    
    async def _generate_gemini(
        self,
        prompt: str,
        system_prompt: Optional[str],
        temperature: float,
        max_tokens: int,
        timeout: int
    ) -> Dict[str, Any]:
        """Generate using Google Gemini API."""
        if not self.gemini_key:
            raise ValueError("Google API key not configured")
        
        try:
            import google.generativeai as genai
            
            genai.configure(api_key=self.gemini_key)
            
            # Combine system and user prompts
            full_prompt = prompt
            if system_prompt:
                full_prompt = f"{system_prompt}\n\n{prompt}"
            
            model = genai.GenerativeModel('gemini-1.5-flash')
            
            generation_config = genai.types.GenerationConfig(
                temperature=temperature,
                max_output_tokens=max_tokens,
            )
            
            response = model.generate_content(
                full_prompt,
                generation_config=generation_config
            )
            
            # Estimate tokens (Gemini doesn't always provide this)
            estimated_tokens = len(full_prompt.split()) + len(response.text.split())
            
            return {
                "text": response.text,
                "provider": "gemini",
                "model": "gemini-1.5-flash",
                "tokens": estimated_tokens,
                "fallback_used": False
            }
            
        except Exception as e:
            logger.error(f"Gemini error: {e}")
            raise
    
    async def _generate_groq(
        self,
        prompt: str,
        system_prompt: Optional[str],
        temperature: float,
        max_tokens: int,
        timeout: int
    ) -> Dict[str, Any]:
        """Generate using Groq API (fast inference for open-source models)."""
        if not self.groq_key:
            raise ValueError("Groq API key not configured")
        
        try:
            from groq import AsyncGroq
            
            client = AsyncGroq(api_key=self.groq_key, timeout=timeout)
            
            messages = []
            if system_prompt:
                messages.append({"role": "system", "content": system_prompt})
            messages.append({"role": "user", "content": prompt})
            
            # Groq models available:
            # - openai/gpt-oss-20b (GPT OSS 20B - fast and efficient)
            # - llama3-70b-8192 (best quality)
            # - llama3-8b-8192 (fast)
            # - mixtral-8x7b-32768 (long context)
            # - gemma-7b-it
            
            response = await client.chat.completions.create(
                model="openai/gpt-oss-20b",  # GPT OSS 20B - fast open-source model
                messages=messages,
                temperature=temperature,
                max_tokens=max_tokens
            )
            
            return {
                "text": response.choices[0].message.content,
                "provider": "groq",
                "model": response.model,
                "tokens": response.usage.total_tokens if response.usage else len(response.choices[0].message.content.split()),
                "fallback_used": False
            }
            
        except Exception as e:
            logger.error(f"Groq error: {e}")
            raise
    
    async def _generate_local(
        self,
        prompt: str,
        system_prompt: Optional[str],
        temperature: float,
        max_tokens: int,
        timeout: int
    ) -> Dict[str, Any]:
        """
        Generate using local model (stub/mock).
        In production, this would connect to Ollama, vLLM, or similar.
        """
        logger.info("Using local model (stub)")
        
        # Stub implementation - returns a template response
        # In production, replace with actual local model inference
        
        await self._simulate_inference_delay()
        
        response_text = self._generate_stub_response(prompt)
        
        return {
            "text": response_text,
            "provider": "local",
            "model": "local-stub",
            "tokens": len(response_text.split()),
            "fallback_used": False
        }
    
    async def _simulate_inference_delay(self):
        """Simulate local model inference time."""
        import asyncio
        await asyncio.sleep(0.5)  # Simulate processing
    
    def _generate_stub_response(self, prompt: str) -> str:
        """Generate a stub response for local model."""
        
        # Very basic SQL detection
        if "sql" in prompt.lower() or "query" in prompt.lower():
            return """```sql
SELECT COUNT(*) as total_count
FROM trips
WHERE status = 'completed';
```

This query counts all completed trips."""
        
        return "I am a local model stub. In production, I would generate a real response based on a local LLM."
    
    def _get_fallback_order(self, primary: str) -> List[str]:
        """Get fallback provider order."""
        all_providers = [AIProvider.GROQ, AIProvider.OPENAI, AIProvider.GEMINI, AIProvider.LOCAL]
        
        # Remove primary from list
        fallbacks = [p for p in all_providers if p != primary]
        
        return fallbacks
    
    def _track_usage(self, provider: str, tokens: int):
        """Track token usage statistics."""
        self.token_usage["total_requests"] += 1
        self.token_usage["total_tokens"] += tokens
        
        if provider not in self.token_usage["by_provider"]:
            self.token_usage["by_provider"][provider] = {
                "requests": 0,
                "tokens": 0
            }
        
        self.token_usage["by_provider"][provider]["requests"] += 1
        self.token_usage["by_provider"][provider]["tokens"] += tokens
    
    def get_usage_stats(self) -> Dict[str, Any]:
        """Get token usage statistics."""
        return self.token_usage.copy()


# Global instance
ai_gateway = AIGateway()


async def generate_text(
    prompt: str,
    model: Optional[str] = None,
    system_prompt: Optional[str] = None,
    temperature: float = 0.7,
    max_tokens: int = 2000
) -> str:
    """
    Convenience function to generate text.
    
    Returns just the text content.
    """
    result = await ai_gateway.generate(
        prompt=prompt,
        model=model,
        system_prompt=system_prompt,
        temperature=temperature,
        max_tokens=max_tokens
    )
    return result["text"]
