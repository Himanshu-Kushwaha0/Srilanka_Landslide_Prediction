# API Documentation
# Sri Lanka Landslide Prediction System

## Overview

Comprehensive REST API for the Landslide Prediction System with chatbot integration.

**Base URL**: `/api/`  
**Version**: 1.0  
**Authentication**: None (session-based for chatbot)

---

## Chatbot API

### Base Path: `/api/chatbot/`

#### Send Message

Send a message to the AI chatbot and receive a response.

**Endpoint**: `POST /api/chatbot/chat`

**Request**:
```json
{
    "message": "What factors influence landslide risk?",
    "session_id": "optional-uuid"
}
```

**Parameters**:
- `message` (string, required): User's question or message (max 1000 chars)
- `session_id` (string, optional): Unique session identifier for conversation continuity

**Response** (200 OK):
```json
{
    "status": "success",
    "response": "Landslide risk is influenced by multiple factors including slope angle, rainfall, terrain wetness, soil properties, and proximity to geological faults. Our model weights slope most heavily (22%) as it's the primary factor determining instability...",
    "session_id": "550e8400-e29b-41d4-a716-446655440000",
    "timestamp": "2024-01-15T10:30:45.123456"
}
```

**Error Responses**:
- 400 Bad Request: Empty message
- 400 Bad Request: Message too long
- 504 Gateway Timeout: LLM response timeout
- 500 Internal Server Error: Unexpected error

**Example cURL**:
```bash
curl -X POST http://localhost:5000/api/chatbot/chat \
  -H "Content-Type: application/json" \
  -d '{"message": "What is the TWI index?"}'
```

**Example Python**:
```python
import requests

response = requests.post(
    'http://localhost:5000/api/chatbot/chat',
    json={'message': 'What is landslide risk?'}
)

print(response.json()['response'])
```

---

#### Get Conversation History

Retrieve all messages in the current conversation session.

**Endpoint**: `GET /api/chatbot/history`

**Parameters**: None

**Response** (200 OK):
```json
{
    "history": [
        {
            "role": "user",
            "content": "What is landslide susceptibility?",
            "timestamp": "2024-01-15T10:25:00.000000"
        },
        {
            "role": "assistant",
            "content": "Landslide susceptibility is...",
            "timestamp": "2024-01-15T10:25:02.000000"
        }
    ],
    "session_id": "550e8400-e29b-41d4-a716-446655440000",
    "count": 2
}
```

**Example**:
```bash
curl http://localhost:5000/api/chatbot/history
```

---

#### Clear Conversation History

Clear all messages for the current session.

**Endpoint**: `POST /api/chatbot/clear`

**Parameters**: None

**Request Body**: None

**Response** (200 OK):
```json
{
    "status": "success",
    "message": "History cleared"
}
```

**Example**:
```bash
curl -X POST http://localhost:5000/api/chatbot/clear
```

---

#### Get Example Questions

Get a list of suggested questions users can ask.

**Endpoint**: `GET /api/chatbot/examples`

**Parameters**: None

**Response** (200 OK):
```json
{
    "examples": [
        "What factors influence landslide susceptibility?",
        "How do you calculate the topographic wetness index?",
        "What are the risk classes and what do they mean?",
        "Which districts have the highest landslide risk?",
        "How does rainfall affect landslide prediction?",
        "What data sources are used in this system?",
        "Explain the AHP methodology",
        "How can I interpret the susceptibility maps?",
        "What mitigation measures are recommended for high-risk areas?",
        "How accurate is the prediction model?"
    ]
}
```

---

#### Get Chatbot Information

Get metadata about the chatbot system.

**Endpoint**: `GET /api/chatbot/info`

**Parameters**: None

**Response** (200 OK):
```json
{
    "name": "Landslide Prediction Expert",
    "description": "AI-powered chatbot for Sri Lanka Landslide Prediction System",
    "version": "1.0.0",
    "capabilities": [
        "Answer questions about landslide prediction",
        "Explain methodology and data sources",
        "Provide risk assessment insights",
        "Guide interpretation of maps and results",
        "Suggest mitigation measures",
        "Support conversation history"
    ],
    "provider": "ollama",
    "session_id": "550e8400-e29b-41d4-a716-446655440000"
}
```

---

#### Health Check

Check if the chatbot service is running and healthy.

**Endpoint**: `GET /api/chatbot/health`

**Parameters**: None

**Response** (200 OK):
```json
{
    "status": "healthy",
    "bot_active": true,
    "sessions_active": 3,
    "timestamp": "2024-01-15T10:30:45.000000"
}
```

**Response** (500 Error):
```json
{
    "status": "error",
    "message": "LLM service unavailable"
}
```

---

#### Streaming Chat Response

Get chatbot response as a stream of tokens (Server-Sent Events).

**Endpoint**: `POST /api/chatbot/chat-stream`

**Parameters**: Same as `/chat`

**Response** (200 OK with SSE stream):
```
data: {"token": "Landslide", "done": false}
data: {"token": " risk", "done": false}
data: {"token": " is", "done": false}
...
data: {"token": ".", "done": true}
```

**Content-Type**: `text/event-stream`

**Example JavaScript**:
```javascript
const eventSource = new EventSource('/api/chatbot/chat-stream');

eventSource.addEventListener('message', (event) => {
    const data = JSON.parse(event.data);
    console.log(data.token);
    
    if (data.done) {
        eventSource.close();
    }
});
```

---

## Integration Examples

### JavaScript/Frontend

```javascript
// Basic chat function
async function askChatbot(message) {
    const response = await fetch('/api/chatbot/chat', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ message })
    });
    
    return response.json();
}

// Usage
const result = await askChatbot('What is landslide risk?');
console.log(result.response);
```

### Python

```python
import requests

# Send message
response = requests.post(
    'http://localhost:5000/api/chatbot/chat',
    json={'message': 'Explain susceptibility mapping'}
)

data = response.json()
print(f"Bot: {data['response']}")
print(f"Session: {data['session_id']}")

# Get history
history_response = requests.get('http://localhost:5000/api/chatbot/history')
history = history_response.json()['history']

for msg in history:
    print(f"{msg['role']}: {msg['content']}")
```

### cURL

```bash
# Ask question
curl -X POST http://localhost:5000/api/chatbot/chat \
  -H "Content-Type: application/json" \
  -d '{
    "message": "What is the AHP methodology?"
  }' | jq '.response'

# Get history
curl http://localhost:5000/api/chatbot/history | jq '.history'

# Clear history
curl -X POST http://localhost:5000/api/chatbot/clear
```

---

## Rate Limiting

Current limits (can be configured):
- 10 requests per minute per session
- 100 concurrent sessions
- 1000 character message limit
- 30 second response timeout

---

## Error Handling

### Standard Error Format

```json
{
    "status": "error",
    "message": "Descriptive error message",
    "error_code": "ERROR_CODE",
    "timestamp": "2024-01-15T10:30:45.000000"
}
```

### Common Error Codes

| Code | Status | Meaning |
|------|--------|---------|
| `EMPTY_MESSAGE` | 400 | Message is empty |
| `MESSAGE_TOO_LONG` | 400 | Message exceeds 1000 characters |
| `INVALID_SESSION` | 401 | Session ID is invalid |
| `LLM_TIMEOUT` | 504 | LLM response took too long |
| `LLM_ERROR` | 503 | LLM service error |
| `INTERNAL_ERROR` | 500 | Unexpected server error |

---

## Response Times

Typical response times by provider:

| Provider | Response Time | Availability |
|----------|---------------|--------------|
| Mock | <100ms | Always |
| Ollama (Local) | 1-3s | Requires setup |
| HuggingFace | 2-5s | Internet required |
| OpenAI | 1-5s | API key required |

---

## WebSocket Events (Optional)

If using `flask-socketio` for real-time chat:

**Connect**:
```javascript
const socket = io('/chatbot');
```

**Send Message**:
```javascript
socket.emit('chat_message', {
    message: 'What is risk assessment?'
});
```

**Receive Response**:
```javascript
socket.on('chat_response', (data) => {
    console.log(data.response);
});
```

**Clear History**:
```javascript
socket.emit('clear_history');
socket.on('history_cleared', (data) => {
    console.log('History cleared');
});
```

---

## Conversation Context

The chatbot maintains context through:
1. **Session History**: Last 10 messages stored in memory
2. **Knowledge Base**: Static project information
3. **Dynamic Context**: Relevant knowledge extracted per query

Example context flow:
```
User: "What factors influence risk?"
  ↓
Extract keywords: [factors, influence, risk]
  ↓
Retrieve from knowledge base: [slope, rainfall, terrain, etc.]
  ↓
Generate response with context
  ↓
Store in session history
```

---

## Best Practices

1. **Session Management**:
   - Store session_id client-side for conversation continuity
   - Don't create new sessions for each request
   - Clear history when starting new conversation

2. **Error Handling**:
   - Implement retry logic for timeout errors
   - Show user-friendly error messages
   - Log errors for debugging

3. **Performance**:
   - Use streaming endpoint for long responses
   - Batch multiple questions if possible
   - Cache responses for common questions

4. **Security**:
   - Validate input message length
   - Sanitize output in HTML context
   - Use HTTPS in production

---

## Version History

**v1.0.0** (2024-01-15)
- Initial API release
- Basic chatbot endpoints
- Multiple LLM provider support
- Conversation history

---

## Support

For issues or questions:
1. Check `/api/chatbot/health` endpoint
2. Review error messages and codes
3. Consult SETUP_AND_DEPLOYMENT_GUIDE.md
4. Check logs for detailed error information

