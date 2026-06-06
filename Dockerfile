FROM python:3.11-slim

# Prevent Python from writing pyc files to disc and buffering stdout/stderr
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

# Set the working directory inside the container
WORKDIR /app

# Install system dependencies AND dos2unix
RUN apt-get update && apt-get install -y curl dos2unix && rm -rf /var/lib/apt/lists/*

# Copy only the requirements first to leverage Docker layer caching
COPY requirements-api.txt .

# Install Python dependencies for the backend, PLUS the Streamlit frontend
RUN pip install --no-cache-dir -r requirements-api.txt
RUN pip install --no-cache-dir streamlit pandas requests

# Copy the ENTIRE repository
COPY . /app

# Convert Windows line endings to Linux, THEN make executable
RUN dos2unix /app/run.sh && chmod +x /app/run.sh

# Start both the FastAPI server and Streamlit dashboard
CMD ["./run.sh"]