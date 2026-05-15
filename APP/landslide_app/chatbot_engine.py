"""
Landslide Prediction Chatbot Engine
====================================
AI-powered chatbot with domain knowledge about Sri Lanka landslide prediction.
Supports multiple LLM providers: Mock, Ollama, HuggingFace, OpenAI.
"""

import asyncio
import os
import logging
import requests
from typing import Optional, List, Dict
from datetime import datetime

# Configure logging
logger = logging.getLogger(__name__)

# Set up reasonable request timeouts
REQUEST_TIMEOUT = 30
OLLAMA_HEALTH_CHECK_TIMEOUT = 2


class LandslideKnowledgeBase:
    """Static knowledge about the landslide prediction system."""
    
    KNOWLEDGE = {
        "methodology": """
        The Sri Lanka Landslide Prediction System uses the Analytical Hierarchy Process (AHP) 
        with the following weight distribution:
        - Slope: 22%
        - Topographic Wetness Index (TWI): 16%
        - Distance to Faults: 14%
        - Soil Type: 12%
        - LULC (Land Use/Land Cover): 11%
        - Rainfall: 10%
        - Curvature: 8%
        - Elevation: 7%
        
        The system generates susceptibility and risk maps at village level resolution.
        """,
        
        "risk_classes": """
        Risk is classified into four levels:
        - Low (Green): < 25% probability
        - Moderate (Orange): 25-50% probability
        - High (Red): 50-75% probability
        - Very High (Dark Red): > 75% probability
        """,
        
        "data_sources": """
        The system uses multiple data sources:
        - Landslide Inventory: Historical landslide records for Sri Lanka
        - Digital Elevation Model (DEM): 30m resolution
        - Rainfall Data: Year-wise rainfall records
        - Land Use/Land Cover (LULC): Satellite-based classification
        - Soil Data: Soil type and properties
        - Geological Faults: Fault line locations
        - Road and Education Facilities: For exposure assessment
        """,
        
        "factors": """
        Key factors influencing landslide risk:
        - Slope: Steeper slopes increase landslide probability
        - Rainfall: Heavy rainfall triggers slope failures
        - Soil Properties: Weak soils are more susceptible
        - Geology: Fault proximity and rock type matter
        - Land Use: Deforestation increases risk
        - Elevation: Higher elevations often have steeper slopes
        - Drainage: Poor drainage increases water saturation
        """,
        
        "output": """
        Model outputs include:
        - Susceptibility Maps: Show inherent landslide potential (static)
        - Risk Maps: Combine susceptibility with rainfall and temporal factors (year-wise)
        - Risk Data Tables: CSV exports with risk metrics per village
        - Risk Statistics: High-risk village identification
        """,
    }
    
    @staticmethod
    def get_context(query: str) -> str:
        """Extract relevant knowledge based on query keywords."""
        query_lower = query.lower()
        
        # Keyword matching
        keywords = {
            "methodology|weight|ahp|factor": "methodology",
            "risk|class|level|probability": "risk_classes",
            "data|source|rainfall|dem|lulc": "data_sources",
            "slope|rainfall|soil|factor|influence": "factors",
            "output|map|result|csv|village": "output",
        }
        
        for keywords_str, key in keywords.items():
            for kw in keywords_str.split("|"):
                if kw in query_lower:
                    return LandslideKnowledgeBase.KNOWLEDGE.get(key, "")
        
        return ""


class LLMProvider:
    """Abstract base class for LLM providers."""
    
    async def generate(self, prompt: str, context: str = "") -> str:
        """Generate response from LLM."""
        raise NotImplementedError


class MockProvider(LLMProvider):
    """Mock provider for testing without external LLMs."""
    
    RESPONSES = {
        "what factors": "The main factors affecting landslide risk include slope (22%), rainfall (10%), soil type (12%), and land use changes. Steeper slopes and areas with heavy rainfall are at higher risk.",
        "how does rainfall": "Rainfall is a key trigger for landslides. Intense rainfall increases water infiltration into soil, reducing shear strength and triggering failures. Our model weights rainfall at 10% in the AHP framework.",
        "which districts": "The system covers all districts in Sri Lanka. Based on susceptibility analysis, central highlands including Kandy, Nuwara Eliya, and Badulla typically show higher risk due to steep terrain and high rainfall.",
        "explain susceptibility": "Susceptibility represents the inherent potential for landslides based on terrain and geological factors. Risk combines susceptibility with triggering factors like rainfall.",
        "what data sources": "We use DEM, rainfall records, soil data, LULC, geological faults, and historical landslide inventory. Data is integrated through the AHP methodology.",
    }
    
    async def generate(self, prompt: str, context: str = "") -> str:
        """Return mock response based on keywords."""
        prompt_lower = prompt.lower()
        for keywords, response in self.RESPONSES.items():
            if any(kw in prompt_lower for kw in keywords.split("|")):
                return response
        return "Based on the Sri Lanka Landslide Prediction System methodology, the model combines multiple factors to assess risk. For specific details, please refer to the system documentation."


class OllamaProvider(LLMProvider):
    """Provider for local Ollama LLM with health checking."""
    
    def __init__(self, host: str = "http://localhost:11434", model: str = "mistral"):
        self.host = host.rstrip('/')
        self.model = model
        self._health_checked = False
        self._is_healthy = False
    
    async def _check_health(self) -> bool:
        """Check if Ollama service is running."""
        if self._health_checked:
            return self._is_healthy
        
        try:
            response = requests.get(f"{self.host}/api/tags", timeout=OLLAMA_HEALTH_CHECK_TIMEOUT)
            self._is_healthy = response.status_code == 200
            self._health_checked = True
            logger.debug(f"Ollama health check: {'OK' if self._is_healthy else 'FAILED'}")
            return self._is_healthy
        except Exception as e:
            logger.debug(f"Ollama health check failed: {e}")
            self._is_healthy = False
            self._health_checked = True
            return False
    
    async def generate(self, prompt: str, context: str = "") -> str:
        """Generate response using Ollama API with health checking."""
        try:
            # Quick health check before attempting full request
            if not await self._check_health():
                return "Error: Ollama is not running. Please start Ollama with: ollama serve"
            
            full_prompt = f"{context}\n\nQuestion: {prompt}" if context else prompt
            
            logger.debug(f"Requesting from Ollama model: {self.model}")
            response = requests.post(
                f"{self.host}/api/generate",
                json={
                    "model": self.model,
                    "prompt": full_prompt,
                    "stream": False,
                },
                timeout=REQUEST_TIMEOUT,
            )
            response.raise_for_status()
            result = response.json().get("response", "Sorry, I couldn't generate a response.")
            logger.debug(f"Ollama response: {result[:50]}...")
            return result
        
        except requests.exceptions.ConnectionError as e:
            logger.error(f"Connection error to Ollama: {e}")
            return "Error: Ollama is not running. Please start Ollama with: ollama serve"
        except requests.exceptions.Timeout as e:
            logger.error(f"Ollama request timeout: {e}")
            return "Error: Ollama request timed out. The service may be slow."
        except Exception as e:
            logger.error(f"Error communicating with Ollama: {e}", exc_info=True)
            return f"Error: {str(e)}"


class HuggingFaceProvider(LLMProvider):
    """Provider for HuggingFace Inference API with better error handling."""
    
    def __init__(self):
        self.api_key = os.getenv("HF_API_KEY")
        if not self.api_key:
            logger.error("HF_API_KEY environment variable not set")
            raise ValueError("HF_API_KEY environment variable not set")
        self.model = "mistralai/Mistral-7B-Instruct-v0.1"
        logger.info(f"Initialized HuggingFace provider with model: {self.model}")
    
    async def generate(self, prompt: str, context: str = "") -> str:
        """Generate response using HuggingFace API with proper error handling."""
        try:
            full_prompt = f"{context}\n\nQuestion: {prompt}" if context else prompt
            
            logger.debug("Requesting from HuggingFace API")
            response = requests.post(
                f"https://api-inference.huggingface.co/models/{self.model}",
                headers={"Authorization": f"Bearer {self.api_key}"},
                json={"inputs": full_prompt},
                timeout=REQUEST_TIMEOUT,
            )
            response.raise_for_status()
            result = response.json()
            
            if isinstance(result, list) and len(result) > 0:
                text = result[0].get("generated_text", "No response generated")
                logger.debug(f"HuggingFace response: {text[:50]}...")
                return text
            
            logger.warning(f"Unexpected HuggingFace response format: {result}")
            return str(result)
        
        except requests.exceptions.Timeout as e:
            logger.error(f"HuggingFace request timeout: {e}")
            return "Error: HuggingFace request timed out. The service may be slow."
        except requests.exceptions.HTTPError as e:
            logger.error(f"HuggingFace API error: {e}")
            return f"Error: HuggingFace API returned {e.response.status_code}"
        except Exception as e:
            logger.error(f"Error communicating with HuggingFace: {e}", exc_info=True)
            return f"Error: {str(e)}"


class ConversationManager:
    """Manages conversation history with thread safety."""
    
    def __init__(self, max_messages: int = 10):
        self.max_messages = max_messages
        self.messages: List[Dict] = []
    
    def add_message(self, role: str, content: str):
        """Add message to history, maintaining size limit."""
        try:
            self.messages.append({
                "role": role,
                "content": content[:500],  # Limit message length
                "timestamp": datetime.now().isoformat(),
            })
            
            # Keep only last N messages
            if len(self.messages) > self.max_messages:
                removed = len(self.messages) - self.max_messages
                self.messages = self.messages[-self.max_messages:]
                logger.debug(f"Conversation history trimmed ({removed} messages removed)")
        
        except Exception as e:
            logger.error(f"Error adding message to conversation: {e}")
    
    def get_context(self) -> str:
        """Get formatted conversation history for context."""
        if not self.messages:
            return ""
        
        try:
            lines = ["Recent conversation:"]
            for msg in self.messages[-5:]:  # Last 5 messages
                role = "User" if msg["role"] == "user" else "Assistant"
                content = msg.get("content", "")[:80]
                lines.append(f"{role}: {content}...")
            return "\n".join(lines)
        
        except Exception as e:
            logger.error(f"Error getting conversation context: {e}")
            return ""
    
    def clear(self):
        """Clear conversation history."""
        self.messages = []
        logger.debug("Conversation history cleared")
    
    def get_all(self) -> List[Dict]:
        """Get all messages in history."""
        return self.messages.copy()


class LandslideBot:
    """Main chatbot class combining knowledge base and LLM with proper error handling."""
    
    def __init__(self, provider: LLMProvider = None):
        """Initialize with LLM provider."""
        try:
            self.provider = provider or MockProvider()
            self.knowledge_base = LandslideKnowledgeBase()
            self.conversation = ConversationManager()
            logger.info(f"LandslideBot initialized with provider: {self.provider.__class__.__name__}")
        except Exception as e:
            logger.error(f"Error initializing LandslideBot: {e}", exc_info=True)
            # Fallback to mock provider
            self.provider = MockProvider()
            self.knowledge_base = LandslideKnowledgeBase()
            self.conversation = ConversationManager()
    
    async def chat(self, user_message: str) -> str:
        """Generate chatbot response with error handling."""
        try:
            if not user_message or not user_message.strip():
                logger.warning("Empty user message received")
                return "Please provide a question or message."
            
            # Limit message length
            if len(user_message) > 1000:
                logger.warning(f"Message too long ({len(user_message)} chars)")
                user_message = user_message[:1000]
            
            # Add user message to history
            self.conversation.add_message("user", user_message)
            
            # Get context from knowledge base
            kb_context = self.knowledge_base.get_context(user_message)
            conv_context = self.conversation.get_context()
            
            # Build context
            full_context = "You are an expert on Sri Lanka landslide prediction systems. "
            if kb_context:
                full_context += f"\nRelevant knowledge: {kb_context}"
            if conv_context:
                full_context += f"\n{conv_context}"
            
            # Generate response
            logger.debug(f"Requesting response from provider: {self.provider.__class__.__name__}")
            response = await self.provider.generate(user_message, full_context)
            
            # Add bot response to history
            self.conversation.add_message("assistant", response)
            
            logger.debug(f"Response generated: {response[:50]}...")
            return response
        
        except asyncio.TimeoutError:
            logger.error("Chat request timed out")
            return "Response took too long. Please try again."
        except Exception as e:
            logger.error(f"Error generating chat response: {e}", exc_info=True)
            return f"An error occurred: {str(e)[:100]}"
    
    def get_history(self) -> List[Dict]:
        """Return conversation history."""
        return self.conversation.get_all()
    
    def clear_history(self):
        """Clear conversation history."""
        self.conversation.clear()
        logger.info("Conversation history cleared")
    
    @staticmethod
    def example_questions() -> List[str]:
        """Return suggested questions users can ask."""
        return [
            "What factors influence landslide risk?",
            "Explain the susceptibility mapping methodology",
            "Which districts have the highest risk?",
            "How does rainfall affect predictions?",
            "What data sources are used?",
            "What are the risk classes?",
            "How is AHP methodology applied?",
            "What is the difference between susceptibility and risk?",
            "How do I interpret the maps?",
            "What is the model's accuracy?",
        ]
