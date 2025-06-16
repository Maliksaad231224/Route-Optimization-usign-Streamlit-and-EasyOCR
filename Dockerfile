FROM python:3.12.3

# Create a non-root user
RUN useradd -m -u 1000 user
USER user
ENV PATH="/home/user/.local/bin:$PATH"

# Set working directory
WORKDIR /app

# Copy requirements and install
COPY --chown=user ./requirements.txt requirements.txt
RUN pip install --no-cache-dir --upgrade -r requirements.txt

# Copy the app code
COPY --chown=user . /app

# Run the Streamlit app
CMD ["streamlit", "run", "stream.py", "--server.port=7860", "--server.address=0.0.0.0"]
