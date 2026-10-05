FROM python:3.11-slim
WORKDIR /app

RUN adduser --disabled-password --gecos "" myuser
USER myuser
ENV PATH="/home/myuser/.local/bin:$PATH"

COPY --chown=myuser:myuser . /app/agents/running_coach/

# requirements.txt references ./agents/running_coach/tp_mcp-*.whl relative to /app
RUN pip install --no-cache-dir -r /app/agents/running_coach/requirements.txt

EXPOSE 8080

CMD exec adk api_server --port=8080 --host=0.0.0.0 \
    --session_service_uri="${SESSION_SERVICE_URI:?SESSION_SERVICE_URI must be set}" \
    --otel_to_cloud --a2a --gemini_enterprise_app_name=running_coach /app/agents
