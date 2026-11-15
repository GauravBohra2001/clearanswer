FROM python:3.13-slim

# Set environment variables
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV PORT=5050

# Set work directory
WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    git \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

# Install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy project files
COPY . .

# Fetch the required hackathon repository during build.
# We remove any local copy that might have been brought in by 'COPY . .'
# to ensure a clean, official version is used.
RUN if [ -d "oncosys-hackathon-challenge" ]; then rm -rf oncosys-hackathon-challenge; fi \
    && git clone https://github.com/disleveK/oncosys-hackathon-challenge.git oncosys-hackathon-challenge

# Create necessary directories
RUN mkdir -p outputs

# Expose the port the app runs on
EXPOSE 5050

# Run the application
CMD ["python", "app.py"]
