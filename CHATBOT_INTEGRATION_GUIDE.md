# Chatbot Integration Implementation Guide
# Step-by-step instructions to add the chatbot to your Flask app

## Overview

This guide shows exactly how to integrate the chatbot into your existing Flask application with minimal changes.

---

## Step 1: Update app.py

Add these lines to `APP/landslide_app/app.py`:

### At the top of the file (after imports):

```python
# Add these imports after existing imports
import sys
import os

# Add parent directory to path to access chatbot modules
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../..')))

from chatbot_flask_integration import setup_chatbot_routes, configure_chatbot
```

### After creating the Flask app instance (after `app = Flask(__name__)`):

```python
# ─────────────────────────────────────────────────────────────────────────
# CHATBOT SETUP
# ─────────────────────────────────────────────────────────────────────────

# Configure chatbot provider
# Options: "mock" (default), "ollama" (recommended), "huggingface"
configure_chatbot({
    "provider": "mock",  # Change to "ollama" if you have Ollama running
    "ollama_url": "http://localhost:11434",
    "ollama_model": "mistral-7b",
    "max_history_per_session": 20,
    "response_timeout": 30,
})

# Register chatbot routes
setup_chatbot_routes(app)

print("✓ Chatbot integration enabled")
```

### Complete modified section example:

```python
"""
Sri Lanka Landslide Risk — Web Application Backend
(Enhanced with Chatbot)
"""

import os, glob, json, subprocess, sys, threading, time
import pandas as pd
import geopandas as gpd
import matplotlib
matplotlib.use('Agg')
matplotlib.rcParams['figure.max_open_warning'] = 50
matplotlib.rcParams['agg.path.chunksize'] = 1000
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
from flask import Flask, request, jsonify, send_file, render_template, send_from_directory, Response
from flask_cors import CORS

# Add chatbot imports
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../..')))
from chatbot_flask_integration import setup_chatbot_routes, configure_chatbot

# Initialize Flask
app = Flask(__name__)
CORS(app)

# ═ CHATBOT SETUP ═
configure_chatbot({
    "provider": "mock",  # Change to "ollama" when ready
    "ollama_url": "http://localhost:11434",
    "ollama_model": "mistral-7b",
})
setup_chatbot_routes(app)
print("✓ Chatbot integration enabled")

# ═ REST OF YOUR EXISTING CODE ═
# ... (keep all existing code unchanged)
```

---

## Step 2: Update HTML Template

Add the chatbot widget to your main template.

### In `APP/landslide_app/templates/index.html` (or your main template):

Add this line before the closing `</body>` tag:

```html
    <!-- Chatbot Widget -->
    {% include 'chatbot_widget.html' %}
</body>
```

Or if you're using a base template, add it to `base.html`:

```html
<!DOCTYPE html>
<html>
<head>
    <!-- Your existing head content -->
</head>
<body>
    <!-- Your existing body content -->
    
    <!-- Chatbot Widget -->
    {% include 'chatbot_widget.html' %}
</body>
</html>
```

---

## Step 3: Verify File Structure

Ensure these files exist in the right locations:

```
Srilanka_Landslide_Prediction/
├── chatbot_engine.py                 ← New (created in root)
├── APP/
│   └── landslide_app/
│       ├── app.py                    ← Modified (add chatbot setup)
│       ├── chatbot_flask_integration.py ← New
│       └── templates/
│           ├── index.html            ← Modified (include widget)
│           └── chatbot_widget.html   ← New
```

---

## Step 4: Test the Integration

### Terminal 1: Start Ollama (if using local LLM)

```bash
# Optional: if using Ollama provider
ollama serve
```

### Terminal 2: Start Flask App

```bash
cd APP/landslide_app
python app.py

# Output should show:
# ✓ Chatbot integration enabled
# ✓ Chatbot routes registered
# * Running on http://localhost:5000
```

### Terminal 3: Test the API

```bash
# Test chatbot endpoint
curl -X POST http://localhost:5000/api/chatbot/chat \
  -H "Content-Type: application/json" \
  -d '{"message": "What is landslide risk?"}'

# Should return:
# {"status": "success", "response": "...", ...}
```

### In Browser

1. Open http://localhost:5000
2. Look for the chat bubble in the bottom-right corner
3. Click to open the chatbot widget
4. Type a question

---

## Step 5: Configure Provider (Optional)

### To use Ollama (Recommended for Privacy):

```python
# In app.py, change:
configure_chatbot({
    "provider": "ollama",  # ← Changed
    "ollama_url": "http://localhost:11434",
    "ollama_model": "mistral-7b",
})

# Make sure Ollama is running:
# ollama serve
```

### To use HuggingFace (Cloud-based):

```python
# Set environment variable first:
# export HF_API_KEY="hf_your_token_here"

# In app.py, change:
configure_chatbot({
    "provider": "huggingface",  # ← Changed
    "hf_model": "mistralai/Mistral-7B-Instruct-v0.1"
})
```

---

## Step 6: Customize Chatbot Behavior

### Change System Prompt

In `chatbot_engine.py`, modify the `SYSTEM_PROMPT`:

```python
class LandslideBot:
    SYSTEM_PROMPT = """You are an expert geotechnical engineer...
    [Customize this to your needs]
    """
```

### Add Custom Knowledge

In `LandslideKnowledgeBase.__init__()`:

```python
self.knowledge = {
    "project": {...},
    "your_custom_section": {
        "key": "value",
        "details": "..."
    }
}
```

### Change Response Timeout

```python
configure_chatbot({
    "response_timeout": 60,  # Increase to 60 seconds
})
```

---

## Step 7: Deploy (Optional)

### Using Docker

Create `Dockerfile`:

```dockerfile
FROM python:3.11-slim

WORKDIR /app

# Install dependencies
RUN apt-get update && apt-get install -y \
    gdal-bin libgdal-dev libgeos-dev libproj-dev \
    && rm -rf /var/lib/apt/lists/*

COPY requirements_enhanced.txt .
RUN pip install -r requirements_enhanced.txt

COPY . .

EXPOSE 5000
ENV CHATBOT_PROVIDER=mock
CMD ["python", "APP/landslide_app/app.py"]
```

Build and run:

```bash
docker build -t landslide-app .
docker run -p 5000:5000 landslide-app
```

### Using Gunicorn (Production)

```bash
pip install gunicorn
cd APP/landslide_app
gunicorn -w 4 -b 0.0.0.0:5000 app:app
```

---

## Step 8: Troubleshooting

### Chatbot widget not appearing?

1. Check browser console for errors (F12)
2. Verify `chatbot_widget.html` is in `templates/` directory
3. Check that Flask template includes the widget

### "Module not found" error?

1. Verify `chatbot_engine.py` is in project root
2. Check that `sys.path.insert(0, ...)` line is in app.py
3. Verify file paths are correct for your system

### Chatbot returns errors?

1. Check `/api/chatbot/health` endpoint
2. If using Ollama, verify it's running: `ollama serve`
3. If using HuggingFace, verify `HF_API_KEY` is set
4. Check Flask console output for error messages

### Slow responses?

1. Check which provider is configured
2. If using Ollama, verify model is loaded
3. Consider switching to faster model: `mistral-lite`
4. Check network latency if using cloud provider

---

## Complete Code Changes Summary

### File: `APP/landslide_app/app.py`

**Add imports:**
```python
import sys
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../..')))
from chatbot_flask_integration import setup_chatbot_routes, configure_chatbot
```

**After `app = Flask(__name__)`:**
```python
configure_chatbot({"provider": "mock"})
setup_chatbot_routes(app)
```

### File: `APP/landslide_app/templates/index.html`

**Add before `</body>`:**
```html
{% include 'chatbot_widget.html' %}
```

---

## Testing Checklist

- [ ] App starts without errors
- [ ] Chatbot widget appears in browser
- [ ] Can click to open/close chat
- [ ] Can send a message
- [ ] Receive a response
- [ ] `/api/chatbot/health` returns healthy
- [ ] `/api/chatbot/info` shows correct provider
- [ ] Can view conversation history
- [ ] Can clear history

---

## Next Steps

1. ✅ Integrate chatbot into Flask app (this guide)
2. Customize knowledge base for your domain
3. Deploy to production
4. Monitor chatbot responses and adjust prompts
5. Collect user feedback for improvements

---

## Need Help?

1. Check `SETUP_AND_DEPLOYMENT_GUIDE.md` for general setup
2. Check `API_DOCUMENTATION.md` for API endpoints
3. Review `chatbot_engine.py` for customization options
4. Check Flask console output for error messages

