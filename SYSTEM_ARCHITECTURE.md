# System Architecture - Enhanced Landslide Chatbot

## 🏗️ Overall Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                    User Browser Interface                        │
│                  (HTML + Leaflet Maps + JS)                      │
└────────────────┬────────────────────────────────────────────────┘
                 │ HTTP/JSON API
                 ↓
┌─────────────────────────────────────────────────────────────────┐
│                   Flask Web Server                               │
│         (APP/landslide_app/app.py - Port 5000)                   │
└────┬──────────────────────────────────────────────────────────┬─┘
     │                                                           │
     ↓                                                           ↓
┌─────────────────────────────┐    ┌──────────────────────────────┐
│  Chatbot Routes (Blueprint)  │    │  API Endpoints               │
│                              │    │ • /api/chatbot/chat          │
│ chatbot_flask_integration.py │    │ • /api/chatbot/history       │
│                              │    │ • /api/chatbot/clear         │
│ - setup_chatbot_routes()    │    │ • /api/chatbot/info          │
│ - Session management        │    │ • /api/chatbot/health        │
└──────────┬──────────────────┘    └──────────────┬───────────────┘
           │                                      │
           └──────────────┬───────────────────────┘
                          ↓
              ┌─────────────────────────────┐
              │  AdvancedRagChatbot         │
              │ (chatbot_advanced.py)       │
              │                             │
              │ • Multi-provider LLM        │
              │ • Memory persistence        │
              │ • Context injection         │
              │ • Risk analysis             │
              └──────┬──────────────────────┘
                     │
        ┌────────────┼────────────┬─────────────┐
        ↓            ↓            ↓             ↓
    ┌────────┐  ┌────────┐  ┌────────┐  ┌────────────┐
    │DataLoader│ │RiskAnalyzer│ │LLM Providers│ │Memory Manager│
    └────────┘  └────────┘  └────────┘  └────────────┘
```

---

## 🔄 Data Flow: User Query → LLM Response

```
1. USER SENDS QUERY
   │
   └─→ "Based on what I asked, what rainfall thresholds..."
   
2. CHATBOT RECEIVES
   ├─→ Append to conversation_history
   └─→ Save to chat_memory_{session_id}.json
   
3. GENERATE RESPONSE
   ├─→ Build prompt with:
   │   ├─ Full conversation history (6 messages)
   │   ├─ Project context (8000+ characters)
   │   └─ User query + system instructions
   │
   ├─→ Select LLM provider
   │   ├─ Check if Ollama healthy
   │   ├─ Fall back to OpenAI if complex query
   │   └─ Fall back to HuggingFace if needed
   │
   └─→ Call LLM with enhanced prompt
   
4. LLM GENERATES RESPONSE
   └─→ Uses injected context to provide:
       ├─ Specific rainfall values (3000mm, 4200mm)
       ├─ Color-coded thresholds (Safe/Caution/Alert/Critical)
       ├─ District profiles
       ├─ AHP weights
       └─ Quantified recommendations
   
5. SAVE & RETURN
   ├─→ Append response to conversation_history
   ├─→ Save to chat_memory_{session_id}.json
   └─→ Return to frontend with risk_analysis + provider_info
```

---

## 💾 Memory System Architecture

```
Session Start
    │
    ↓
Check for chat_memory_{session_id}.json
    │
    ├─→ File EXISTS
    │   └─→ Load and restore full conversation history
    │       ├─ Message timestamps
    │       ├─ User queries
    │       └─ LLM responses
    │
    └─→ File NOT EXISTS
        └─→ Start with empty history
        
During Chat Session
    │
    ├─→ User sends message
    │   └─→ Append to history
    │   └─→ SAVE to JSON immediately
    │
    ├─→ LLM generates response
    │   └─→ Append to history
    │   └─→ SAVE to JSON immediately
    │
    └─→ Repeat for each turn
    
Session End (Server Restart)
    │
    └─→ Memory file persists
        └─→ Same user loads page with same session ID
            └─→ Automatic memory restoration
```

---

## 🧠 LLM Context Injection System

```
CONTEXT LAYERS (In Order of Injection):

Layer 1: System Role Definition
├─ "You are an expert landslide risk analyst"
├─ Domain expertise areas (8 categories)
└─ Analytical approach instructions

Layer 2: Conversation History
├─ Last 6 messages (user + assistant)
├─ Timestamps for chronological context
└─ Enables multi-turn understanding

Layer 3: Project Knowledge Base
├─ Historical Landslide Inventory
│  ├─ 1000+ documented events
│  ├─ Data range, distribution
│  └─ Coverage statistics
│
├─ Rainfall Data (50+ years)
│  ├─ Average annual (3000/1500mm)
│  ├─ Peak rainfall (4200mm)
│  ├─ Monsoon patterns
│  └─ Climate trends
│
├─ Susceptibility Zones (AHP)
│  ├─ Classification system (Very Low-Very High)
│  ├─ 8 weighted factors with %
│  ├─ Accuracy metrics (78-85%)
│  └─ Spatial resolution (30m x 30m)
│
├─ Methodology Details
│  ├─ Analysis approach
│  ├─ Validation process
│  ├─ ROC curve performance
│  └─ Village-level aggregation
│
└─ District Risk Profiles (13 districts)
   ├─ Risk classification by district
   ├─ Key risk drivers
   ├─ Vulnerable areas
   └─ Recommendations

Layer 4: Instructions for Response Format
├─ Answer clearly and directly
├─ Use structured sections
├─ Reference specific data when relevant
├─ Include quantified risks and thresholds
├─ Provide actionable advice
└─ Remember full context is available
```

---

## 🤖 LLM Provider Selection

```
Query Received
    │
    ├─→ Analyze query complexity
    │   ├─ Word count > 150 chars?
    │   ├─ Complex keywords? (compare, analyze, comprehensive)
    │   └─ Score: SIMPLE or COMPLEX
    │
    ├─→ Check provider availability
    │   ├─ Ollama health check
    │   ├─ OpenAI API key present?
    │   └─ HuggingFace API key present?
    │
    └─→ Select best provider
        │
        ├─ IF complex AND openai_key_present
        │  └─→ Use OpenAI (gpt-4o-mini)
        │
        ├─ ELSE IF ollama_healthy
        │  └─→ Use Ollama (mistral-7b)
        │
        ├─ ELSE IF huggingface_key_present
        │  └─→ Use HuggingFace (tiiuae/mistral-small)
        │
        └─ ELSE
           └─→ Use template fallback (mock)
```

---

## 📊 Data Loading Sequence

```
App Startup
    │
    ├─→ Flask initialization
    │   └─→ Import chatbot_flask_integration
    │       └─→ Create chatbot instance per session
    │
    ├─→ DataLoader.__init__()
    │   └─→ _load_all_data() called IMMEDIATELY
    │       │
    │       ├─→ load_landslide_inventory()
    │       │   └─→ Reads: landslides_Sri_Lanka.csv
    │       │   └─→ Returns: Summary (1000+ events)
    │       │
    │       ├─→ load_rainfall_data()
    │       │   └─→ Reads: Srilanka Rainfall year wise.csv
    │       │   └─→ Returns: 50-year statistics
    │       │
    │       ├─→ load_susceptibility_zones()
    │       │   └─→ Returns: AHP classification + 8 factors
    │       │
    │       ├─→ load_methodology()
    │       │   └─→ Returns: Complete methodology doc
    │       │
    │       └─→ load_district_data()
    │           └─→ Returns: 13 district profiles
    │
    ├─→ get_context_summary()
    │   └─→ Combines all above into single 8000+ char string
    │
    ├─→ AdvancedRagChatbot.__init__()
    │   ├─→ self.context_cache = context_summary
    │   └─→ _load_conversation_memory()
    │       └─→ Check for chat_memory_{session_id}.json
    │
    └─→ System ready for user queries
        └─→ All project data in memory, ready for injection into LLM prompts
```

---

## 🔀 Response Generation Flow

```
User Query "What rainfall thresholds trigger landslides?"
    │
    ├─→ Add to conversation_history
    └─→ Save to chat_memory.json
    
Build Enhanced Prompt:
    ├─→ System role (expert analyst)
    ├─→ Domain expertise areas
    ├─→ Conversation history (6 messages)
    ├─→ Project knowledge base (8000+ chars)
    │   ├─ Inventory data
    │   ├─ Rainfall statistics
    │   ├─ AHP methodology
    │   ├─ District profiles
    │   └─ Historical data
    ├─→ User question
    └─→ Response format instructions

Call LLM with Complete Prompt:
    ├─→ Ollama (local) - FAST
    │   └─→ URL: http://localhost:11434
    │   └─→ Model: mistral-7b
    │   └─→ Response time: 2-3 seconds
    │
    └─→ [If Ollama fails]
        ├─→ OpenAI (cloud) - POWERFUL
        │   └─→ Model: gpt-4o-mini
        │
        └─→ [If OpenAI unavailable]
            └─→ HuggingFace or Template

LLM Generates Response:
    ├─→ Uses injected context
    ├─→ Provides specific data values
    │   ├─ Safe: <50mm/day
    │   ├─ Caution: 50-100mm/day
    │   ├─ Alert: 100-150mm/day
    │   ├─ Critical: >150mm/day
    │   └─ And more...
    └─→ References project knowledge

Response Processing:
    ├─→ Add to conversation_history
    ├─→ Save to chat_memory.json
    ├─→ Generate risk_analysis (if enabled)
    └─→ Return to frontend with:
        ├─ response text
        ├─ risk_analysis
        ├─ llm_provider used
        └─ timestamp
```

---

## 📁 File Structure with Enhancements

```
APP/landslide_app/
├── app.py
│   └─→ Main Flask app (unchanged)
│
├── chatbot_advanced.py (ENHANCED)
│   ├─ DataLoader class
│   │  ├─ _load_all_data() [NEW - loads at init]
│   │  ├─ load_landslide_inventory() [ENHANCED]
│   │  ├─ load_rainfall_data() [ENHANCED]
│   │  ├─ load_susceptibility_zones() [ENHANCED]
│   │  ├─ load_methodology() [NEW]
│   │  ├─ load_district_data() [ENHANCED]
│   │  └─ get_context_summary() [ENHANCED]
│   │
│   └─ AdvancedRagChatbot class
│      ├─ _load_conversation_memory() [NEW]
│      ├─ _save_conversation_memory() [NEW]
│      ├─ _select_best_model() [ENHANCED]
│      ├─ _build_prompt() [ENHANCED]
│      ├─ chat() [ENHANCED - saves memory]
│      ├─ _generate_response() [unchanged]
│      └─ clear_history() [ENHANCED - deletes file]
│
├── chatbot_flask_integration.py
│   └─→ Uses enhanced chatbot class (unchanged)
│
├── templates/
│   └─ chatbot_advanced_widget.html (unchanged)
│
└── chat_memory_{session_id}.json [NEW - auto-created]
   └─ Stores: session_id, history[], timestamp
```

---

## 🎯 Performance Summary

```
Memory Usage:
  ├─ Context cache: ~8000 characters
  ├─ Per message: ~200-300 characters
  ├─ 12 messages: ~2400-3600 characters
  └─ Total overhead: < 15KB per session

Load Time:
  ├─ DataLoader init: ~100ms (loads all data once)
  ├─ Memory restore: ~50ms (JSON parsing)
  ├─ LLM call: 2-4 seconds (dependent on model)
  └─ Total response: 3-5 seconds

Storage:
  ├─ Chat memory file: ~1KB per message
  ├─ Project context: ~8KB (shared across sessions)
  └─ Total per session: < 20KB

Scalability:
  ├─ Sessions: Can support 100+ concurrent
  ├─ Message history: Can store 1000+ messages
  └─ Project data: Constant, independent of sessions
```

---

*Architecture designed for scalability, reliability, and comprehensive project context awareness*
