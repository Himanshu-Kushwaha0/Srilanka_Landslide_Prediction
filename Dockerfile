# Dockerfile for Sri Lanka Landslide Prediction System
# Production-ready containerization

FROM python:3.11-slim

# Set working directory
WORKDIR /app

# Set environment variables
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    CHATBOT_PROVIDER=mock

# Install system dependencies for GIS packages
RUN apt-get update && apt-get install -y \
    gdal-bin \
    libgdal-dev \
    libgeos-dev \
    libproj-dev \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

# Set GDAL environment
ENV GDAL_CONFIG=/usr/bin/gdal-config

# Copy requirements
COPY requirements_enhanced.txt .

# Install Python dependencies
RUN pip install --upgrade pip setuptools wheel && \
    pip install --no-cache-dir -r requirements_enhanced.txt

# Copy application code
COPY . .

# Create data directories
RUN mkdir -p /app/data /app/output /app/cache

# Expose port
EXPOSE 5000

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=40s --retries=3 \
    CMD curl -f http://localhost:5000/api/chatbot/health || exit 1

# Run the application
CMD ["python", "APP/landslide_app/app.py"]

