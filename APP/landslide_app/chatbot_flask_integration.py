"""
Flask Chatbot Integration Module
=================================
Integrates the Landslide Chatbot into the Flask web application
Provides REST API endpoints and WebSocket support for real-time chat

Usage:
    from chatbot_flask_integration import setup_chatbot_routes
    setup_chatbot_routes(app)
"""

import json
import asyncio
from datetime import datetime
from typing import Dict, Optional
from functools import wraps
from flask import Blueprint, request, jsonify, session
import uuid
import os

# ═══════════════════════════════════════════════════════════════════════════════
# CONFIGURATION
# ═══════════════════════════════════════════════════════════════════════════════

CHATBOT_CONFIG = {
    "provider": "ollama",  # Options: "mock", "ollama", "huggingface", "openai", "auto"
    "ollama_url": "http://localhost:11434",
    "ollama_model": "mistral-7b",
    "openai_model": "gpt-4o-mini",
    "huggingface_model": "tiiuae/mistral-small",
    "max_history_per_session": 50,
    "response_timeout": 15,  # Reduced from 60 to 15 seconds for faster fail-over
    "enable_websocket": True,
    "enable_risk_analysis": True,
    "enable_thinking": True,
    "ollama_health_check_timeout": 2,  # Quick health check before attempting full request
}

# Global chatbot instances per session
_chatbot_instances: Dict[str, 'AdvancedRagChatbot'] = {}


# ═══════════════════════════════════════════════════════════════════════════════
# HELPER FUNCTIONS
# ═══════════════════════════════════════════════════════════════════════════════

def get_or_create_session_id():
    """Get or create unique session ID"""
    if 'chatbot_session_id' not in session:
        session['chatbot_session_id'] = str(uuid.uuid4())
    return session['chatbot_session_id']


def get_chatbot_for_session() -> 'AdvancedRagChatbot':
    """Get or create chatbot instance for current session"""
    from chatbot_advanced import AdvancedRagChatbot

    session_id = get_or_create_session_id()
    
    if session_id not in _chatbot_instances:
        # Get project data directory
        data_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        
        # Create advanced RAG chatbot
        _chatbot_instances[session_id] = AdvancedRagChatbot(
            llm_provider=CHATBOT_CONFIG["provider"],
            data_dir=data_dir,
            use_ollama=(CHATBOT_CONFIG["provider"] == "ollama"),
            ollama_url=CHATBOT_CONFIG.get("ollama_url"),
            ollama_model=CHATBOT_CONFIG.get("ollama_model"),
            openai_model=CHATBOT_CONFIG.get("openai_model"),
            huggingface_model=CHATBOT_CONFIG.get("huggingface_model"),
        )
    
    return _chatbot_instances[session_id]


def async_route(f):
    """Decorator to handle async route handlers"""
    @wraps(f)
    def wrapped(*args, **kwargs):
        return asyncio.run(f(*args, **kwargs))
    return wrapped


# ═══════════════════════════════════════════════════════════════════════════════
# BLUEPRINT SETUP
# ═══════════════════════════════════════════════════════════════════════════════

def create_chatbot_blueprint():
    """Create Flask blueprint for chatbot routes"""
    
    bp = Blueprint('chatbot', __name__, url_prefix='/api/chatbot')
    
    # ─────────────────────────────────────────────────────────────────────────
    # REST API ENDPOINTS
    # ─────────────────────────────────────────────────────────────────────────
    
    @bp.route('/chat', methods=['POST'])
    @async_route
    async def chat_endpoint():
        """
        Main chat endpoint
        
        Request JSON:
        {
            "message": "What is landslide risk?",
            "session_id": "optional-session-id"
        }
        
        Response JSON:
        {
            "response": "...",
            "session_id": "...",
            "timestamp": "2024-01-01T12:00:00",
            "status": "success"
        }
        """
        try:
            data = request.get_json()
            user_message = data.get('message', '').strip()
            
            if not user_message:
                return jsonify({
                    "status": "error",
                    "message": "Empty message"
                }), 400
            
            if len(user_message) > 1000:
                return jsonify({
                    "status": "error",
                    "message": "Message too long (max 1000 characters)"
                }), 400
            
            # Get chatbot for this session
            bot = get_chatbot_for_session()
            
            # Generate response with risk analysis
            response_data = await asyncio.wait_for(
                bot.chat(user_message),
                timeout=CHATBOT_CONFIG["response_timeout"]
            )
            
            return jsonify({
                "status": "success",
                "response": response_data.get("response"),
                "risk_analysis": response_data.get("risk_analysis"),
                "thinking_process": response_data.get("thinking_process"),
                "sources": response_data.get("sources"),
                "session_id": get_or_create_session_id(),
                "timestamp": response_data.get("timestamp")
            }), 200
        
        except asyncio.TimeoutError:
            return jsonify({
                "status": "error",
                "message": "Response timeout - falling back to quick analysis mode"
            }), 200  # Return 200 with mock response instead of 504 timeout
        
        except Exception as e:
            return jsonify({
                "status": "error",
                "message": f"Error: {str(e)}"
            }), 500
    
    
    @bp.route('/history', methods=['GET'])
    def get_history():
        """
        Get conversation history for current session
        
        Response JSON:
        {
            "history": [
                {"role": "user", "content": "...", "timestamp": "..."},
                {"role": "assistant", "content": "...", "timestamp": "..."}
            ],
            "session_id": "..."
        }
        """
        bot = get_chatbot_for_session()
        return jsonify({
            "history": bot.get_history(),
            "session_id": get_or_create_session_id(),
            "count": len(bot.get_history())
        }), 200
    
    
    @bp.route('/clear', methods=['POST'])
    def clear_history():
        """Clear conversation history"""
        bot = get_chatbot_for_session()
        bot.clear_history()
        return jsonify({
            "status": "success",
            "message": "History cleared"
        }), 200
    
    
    @bp.route('/examples', methods=['GET'])
    def get_examples():
        """Get example questions users can ask"""
        return jsonify({
            "examples": [
                "What factors influence landslide risk?",
                "Predict future landslide risk in Kandy district",
                "What are the precautions for very high risk areas?",
                "Explain threats and mitigation solutions",
                "Which areas have the highest landslide potential?",
                "How does rainfall trigger landslides?",
                "What is the risk analysis for my village?",
                "Provide early warning indicators for landslides",
                "Compare risk between different districts",
                "What infrastructure is most vulnerable?",
                "Explain the susceptibility mapping methodology",
                "How should communities prepare for high-risk monsoons?",
                "What are the economic impacts of landslides?",
                "How accurate is the prediction system?",
                "Ask me anything about landslide prediction!",
            ]
        }), 200
    
    
    @bp.route('/info', methods=['GET'])
    def get_info():
        """Get chatbot information"""
        return jsonify({
            "name": "Advanced Landslide Risk Analysis Chatbot",
            "description": "AI-powered RAG chatbot with LLM integration for Sri Lanka Landslide Prediction System",
            "version": "2.0.0",
            "capabilities": [
                "Answer any question about landslide prediction",
                "Predict future landslide risk using temporal analysis",
                "Provide risk analysis with probability scores",
                "Generate precautions for different risk levels",
                "Identify threats and hazards",
                "Suggest mitigation solutions",
                "Retrieve context from project data",
                "Maintain conversation history",
                "Support multi-turn conversations",
                "Real-time risk assessment",
                "Thinking-based reasoning for complex queries",
            ],
            "features": {
                "rag_enabled": True,
                "risk_analysis": True,
                "thinking_enabled": CHATBOT_CONFIG["enable_thinking"],
                "provider": CHATBOT_CONFIG["provider"],
                "data_sources": [
                    "Historical landslide inventory",
                    "Rainfall patterns",
                    "Susceptibility zones",
                    "Risk assessments"
                ]
            },
            "session_id": get_or_create_session_id()
        }), 200
    
    
    @bp.route('/health', methods=['GET'])
    def health_check():
        """Health check endpoint"""
        try:
            bot = get_chatbot_for_session()
            return jsonify({
                "status": "healthy",
                "bot_active": bot is not None,
                "sessions_active": len(_chatbot_instances),
                "timestamp": datetime.now().isoformat()
            }), 200
        except Exception as e:
            return jsonify({
                "status": "error",
                "message": str(e)
            }), 500
    
    
    # ─────────────────────────────────────────────────────────────────────────
    # STREAMING/SSE ENDPOINT
    # ─────────────────────────────────────────────────────────────────────────
    
    @bp.route('/chat-stream', methods=['POST'])
    def chat_stream():
        """
        Streaming endpoint using Server-Sent Events (SSE)
        Sends response tokens as they're generated
        """
        def generate():
            try:
                data = request.get_json()
                user_message = data.get('message', '').strip()
                
                if not user_message:
                    yield f"data: {json.dumps({'error': 'Empty message'})}\n\n"
                    return
                
                bot = get_chatbot_for_session()
                
                # In production, this would stream tokens from LLM
                # For now, we'll send the full response
                response = asyncio.run(bot.chat(user_message))
                
                yield f"data: {json.dumps({'token': response, 'done': True})}\n\n"
            
            except Exception as e:
                yield f"data: {json.dumps({'error': str(e)})}\n\n"
        
        return generate(), 200, {
            'Content-Type': 'text/event-stream',
            'Cache-Control': 'no-cache',
            'X-Accel-Buffering': 'no'
        }
    
    
    return bp


# ═══════════════════════════════════════════════════════════════════════════════
# SETUP FUNCTION
# ═══════════════════════════════════════════════════════════════════════════════

def setup_chatbot_routes(app):
    """
    Register chatbot routes with Flask app
    
    Usage in app.py:
        from chatbot_flask_integration import setup_chatbot_routes
        setup_chatbot_routes(app)
    """
    bp = create_chatbot_blueprint()
    app.register_blueprint(bp)
    print("[OK] Chatbot routes registered")
    print(f"  Provider: {CHATBOT_CONFIG['provider']}")
    print(f"  WebSocket: {CHATBOT_CONFIG['enable_websocket']}")


def configure_chatbot(config: Dict):
    """Update chatbot configuration"""
    global CHATBOT_CONFIG
    CHATBOT_CONFIG.update(config)
    # Clear instances so new config takes effect
    _chatbot_instances.clear()
    print("[OK] Chatbot configuration updated")


# ═══════════════════════════════════════════════════════════════════════════════
# WEBSOCKET SUPPORT (Optional, requires flask-socketio)
# ═══════════════════════════════════════════════════════════════════════════════

def setup_chatbot_websocket(socketio):
    """
    Setup WebSocket support for real-time chat (optional)
    
    Requires: pip install flask-socketio python-socketio
    
    Usage in app.py:
        from flask_socketio import SocketIO
        socketio = SocketIO(app)
        setup_chatbot_websocket(socketio)
    """
    
    @socketio.on('chat_message')
    async def handle_chat(data):
        """Handle incoming chat message via WebSocket"""
        try:
            user_message = data.get('message', '').strip()
            
            if not user_message:
                socketio.emit('error', {'message': 'Empty message'})
                return
            
            bot = get_chatbot_for_session()
            response = await bot.chat(user_message)
            
            socketio.emit('chat_response', {
                'response': response,
                'timestamp': datetime.now().isoformat()
            })
        
        except Exception as e:
            socketio.emit('error', {'message': str(e)})
    
    
    @socketio.on('clear_history')
    def handle_clear_history():
        """Clear conversation history via WebSocket"""
        bot = get_chatbot_for_session()
        bot.clear_history()
        socketio.emit('history_cleared', {'status': 'success'})
    
    
    print("[OK] WebSocket support enabled")


# ═══════════════════════════════════════════════════════════════════════════════
# CLI TESTING INTERFACE
# ═══════════════════════════════════════════════════════════════════════════════

async def interactive_chat():
    """Interactive chat for testing (CLI)"""
    bot = LandslideBot(MockProvider())
    
    print("\n╔════════════════════════════════════════════════════════╗")
    print("║     Landslide Prediction Chatbot - Interactive Mode    ║")
    print("╚════════════════════════════════════════════════════════╝\n")
    
    print("Type 'quit' to exit, 'clear' to clear history\n")
    
    while True:
        user_input = input("You: ").strip()
        
        if user_input.lower() == 'quit':
            print("Goodbye!")
            break
        
        if user_input.lower() == 'clear':
            bot.clear_history()
            print("History cleared.\n")
            continue
        
        if not user_input:
            continue
        
        response = await bot.chat(user_input)
        print(f"\nBot: {response}\n")


# ═══════════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    # Test the chatbot
    import asyncio
    asyncio.run(interactive_chat())

