# AgentFootprint 复现镜像：7 个公开框架各一 venv（锁定版本，Linux 过滤 mac-only 包）。
# InfiAgent 依赖私有 SDK，不在镜像内（见 BENCHMARK_CARD.md）。
FROM python:3.11-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
      git zstd build-essential && rm -rf /var/lib/apt/lists/*

WORKDIR /bench
COPY envlocks/ envlocks/

RUN set -e; \
    for fw in langgraph autogen crewai smolagents openai_agents llamaindex agno; do \
      python -m venv /opt/venvs/$fw; \
      grep -viE '^(appnope|pyobjc|macholib|applaunchservices)' envlocks/$fw.txt \
        | grep -v '^#' > /tmp/req-$fw.txt; \
      /opt/venvs/$fw/bin/pip install --no-cache-dir --upgrade pip >/dev/null; \
      /opt/venvs/$fw/bin/pip install --no-cache-dir -r /tmp/req-$fw.txt; \
    done

COPY . .

ENV FOOTPRINT_PY_LANGGRAPH=/opt/venvs/langgraph/bin/python \
    FOOTPRINT_PY_AUTOGEN=/opt/venvs/autogen/bin/python \
    FOOTPRINT_PY_CREWAI=/opt/venvs/crewai/bin/python \
    FOOTPRINT_PY_SMOLAGENTS=/opt/venvs/smolagents/bin/python \
    FOOTPRINT_PY_OPENAI_AGENTS=/opt/venvs/openai_agents/bin/python \
    FOOTPRINT_PY_LLAMAINDEX=/opt/venvs/llamaindex/bin/python \
    FOOTPRINT_PY_AGNO=/opt/venvs/agno/bin/python

RUN pip install --no-cache-dir zstandard fastcdc numpy

# 冒烟：离线 fixed-trace（零 API）
CMD ["python", "src/fixed_trace.py"]
