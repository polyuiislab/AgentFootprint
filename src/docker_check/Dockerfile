FROM python:3.12-slim
COPY requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir -r /tmp/requirements.txt
RUN useradd -m runner
USER runner
ENV HOME=/sandbox/home
WORKDIR /sandbox/workspace
ENTRYPOINT ["python", "/adapter/run_langgraph.py"]
