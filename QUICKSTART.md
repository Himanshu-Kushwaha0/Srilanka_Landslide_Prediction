# 🚀 Quick Start - Enhanced Chatbot

## Start the System (2 Steps)

### Step 1: Open Terminal
```bash
cd APP/landslide_app
```

### Step 2: Run Flask
```bash
python app.py
```

### Expected Output:
```
[OK] Chatbot routes registered
  Provider: ollama
  WebSocket: True
[OK] All required files exist
============================================================
  Sri Lanka Landslide Risk — Web App
  Open:  http://localhost:5000
============================================================
```

**System is ready!** ✅

---

## Open in Browser

1. Go to: **http://localhost:5000**
2. Find the chatbot widget (bottom right, 💬 button)
3. Click to expand

---

## Try These Questions

### Q1: Rainfall & Landslides (Foundation)
```
"What is the relationship between rainfall and landslide risk in Sri Lanka?"
```
**Expected**: Explanation of rainfall triggers, monsoon patterns, soil saturation

### Q2: Specific Thresholds (Memory Test)
```
"Based on what I asked, what specific rainfall thresholds trigger landslides?"
```
**Expected**: Exact numbers (Safe<50, Caution 50-100, Alert 100-150, Critical>150)
**Why it's better**: References previous answer, shows memory working

### Q3: Monsoon Comparison (Context Test)
```
"How do these thresholds compare between Southwest and Northeast monsoons?"
```
**Expected**: Detailed comparison with seasonal data, climate trends
**Why it's better**: Full conversation history maintained

---

## Key Improvements You'll See

### 1. **Specific Numbers**
- ❌ Before: "Rainfall between 50-100mm triggers landslides"
- ✅ After: "Safe <50mm/day (Green), Caution 50-100mm/day (Yellow), Alert 100-150mm/day (Orange), Critical >150mm/day (Red)"

### 2. **Full Project Knowledge**
- ❌ Before: Generic responses
- ✅ After: Includes district profiles, AHP weights, historical data

### 3. **Multi-Turn Conversations**
- ❌ Before: Each query standalone
- ✅ After: Follow-up questions understand context from previous messages

### 4. **Memory Persistence**
- ❌ Before: Conversation lost on refresh/restart
- ✅ After: Automatic save to `chat_memory_{session_id}.json`

---

## What's Happening Behind the Scenes

```
1. Your Question
   ↓
2. Chatbot loads:
   ├─ Previous conversation (auto-restored from disk)
   ├─ 50+ years rainfall data
   ├─ 1000+ landslide events
   ├─ AHP methodology & weights
   └─ All 13 district profiles
   ↓
3. LLM builds enhanced prompt with:
   ├─ Your current question
   ├─ Last 6 messages (context)
   └─ All project data (8000+ characters)
   ↓
4. LLM generates response using:
   ├─ Local Ollama (fast)
   └─ Falls back to OpenAI if needed
   ↓
5. Response saved immediately:
   └─ To chat_memory_{session_id}.json
   ↓
6. You see detailed, data-aware answer
```

---

## Features Enabled

| Feature | How to Access |
|---------|---------------|
| **Memory** | Refresh page, ask follow-up questions - context maintained |
| **Project Data** | Ask any question - LLM has all data instantly |
| **Multi-turn** | Ask "Based on what I asked..." - previous context used |
| **Multiple Models** | System automatically picks best LLM |
| **Risk Analysis** | Every response includes threat/precaution/solution assessment |

---

## Check System Health

### In Browser Console (F12):
```javascript
// Check conversation history
fetch('/api/chatbot/history').then(r => r.json()).then(console.log)

// Check chatbot info
fetch('/api/chatbot/info').then(r => r.json()).then(console.log)

// Check health
fetch('/api/chatbot/health').then(r => r.json()).then(console.log)
```

### Expected Status:
```json
{
  "count": 3,                    // Messages in conversation
  "session_id": "1263469...",   // Your session ID
  "features": {
    "rag_enabled": true,
    "risk_analysis": true,
    "provider": "ollama"
  }
}
```

---

## Troubleshooting

### Q: Where are memory files saved?
```
App Directory: APP/landslide_app/
Files: chat_memory_{session_id}.json
Location: APP/chat_memory_*.json
```

### Q: Can I see the project data?
```python
# It's loaded in code at startup:
# - 50+ years rainfall data
# - 1000+ landslide events
# - AHP methodology (8 factors)
# - 13 district profiles
# Check: AdvancedRagChatbot.context_cache (8000+ chars)
```

### Q: How do I clear conversation?
```
Click: Clear History button in chatbot widget
Result: Memory file deleted, new session starts
```

### Q: What if Ollama isn't running?
```
System falls back automatically:
1. Local Ollama (if available)
2. OpenAI (if API key set)
3. HuggingFace (if API key set)
4. Template responses (always available)
```

### Q: Can I use a different LLM?
```python
# In APP/landslide_app/chatbot_advanced.py:
# Modify in __init__:
self.llm_provider = "openai"  # or "ollama", "huggingface", "auto"
```

---

## Environment Variables (Optional)

### For OpenAI fallback:
```bash
set OPENAI_API_KEY=sk-your-key-here
```

### For HuggingFace fallback:
```bash
set HUGGINGFACE_API_KEY=hf_your-key-here
```

---

## API Reference

### Main Endpoint:
```bash
POST /api/chatbot/chat
Content-Type: application/json

{
  "message": "Your question here"
}

Response:
{
  "response": "LLM answer",
  "risk_analysis": {...},
  "llm_provider": "ollama",
  "session_id": "..."
}
```

### Get History:
```bash
GET /api/chatbot/history

Response:
{
  "count": 3,
  "history": [
    {
      "role": "user",
      "content": "...",
      "timestamp": "2026-05-12T..."
    },
    ...
  ],
  "session_id": "..."
}
```

### Clear History:
```bash
POST /api/chatbot/clear

Response:
{
  "status": "cleared",
  "session_id": "..."
}
```

---

## Examples of Enhanced Responses

### Example 1: Rainfall Thresholds
```
Q: "What rainfall thresholds trigger landslides?"

A: "RAINFALL THRESHOLDS FOR LANDSLIDES:
   Safe: < 50mm/day (Green)
   Caution: 50-100mm/day (Yellow)
   Alert: 100-150mm/day or sustained >48 hours (Orange)
   Critical: > 150mm/day or >500mm in 5 days (Red)
   
   HISTORICAL DATA:
   Average annual: 3000mm (highlands), 1500mm (lowlands)
   Record rainfall: 4200mm per year (Kandy region)
   Wettest months: June, July, August"
```

### Example 2: District-Specific
```
Q: "Risk in Kandy district?"

A: "KANDY DISTRICT - VERY HIGH RISK
   Characteristics:
   - Central highlands with steep terrain
   - Elevation: 500-2000m
   - Annual rainfall: 3000-3500mm
   - High population in valleys
   
   Key Risk Factors:
   - Steep slopes (>35°)
   - High rainfall during monsoons
   - Vulnerable settlements in valleys
   - Limited drainage in some areas"
```

### Example 3: Multi-Turn Context
```
Q1: "What factors influence landslide risk?"
A1: [Comprehensive answer with AHP weights]

Q2: "Based on what I asked, which district has highest risk?"
A2: [Uses previous answer + adds district-specific data]

Q3: "How can we mitigate that?"
A3: [References both previous answers + provides solutions]
```

---

## Performance Tips

### For Faster Responses:
1. **Ensure Ollama is running** (fastest local option)
2. **Keep queries under 200 characters** when possible
3. **Avoid extremely complex multi-part questions** in single query

### For Better Answers:
1. **Ask follow-up questions** - Memory helps provide context
2. **Reference previous answers** - Improves context awareness
3. **Be specific about districts** - More accurate responses

### For Reliability:
1. **System has automatic fallback** - Even if one provider fails
2. **Memory auto-saves** - Never lose conversation
3. **Error handling included** - Graceful degradation

---

## Next Steps

1. ✅ Start the system: `python app.py`
2. ✅ Open browser: http://localhost:5000
3. ✅ Ask a question in the chatbot widget
4. ✅ Notice the detailed responses with specific data
5. ✅ Ask a follow-up question - context is maintained
6. ✅ Refresh the page - conversation is restored!

---

## That's It! 🎉

You now have:
- ✅ Persistent conversation memory
- ✅ Full project data instantly available
- ✅ Better LLM responses with specific values
- ✅ Multi-turn conversations with context
- ✅ Intelligent model selection & fallback

**Happy landslide analyzing!** 🏔️⚠️
