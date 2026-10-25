# Aidemy: один образ закрывает всё разноверсионие Python.
#
# 3.12 — единственная ветка, которая устраивает и kokoro (requires_python <3.13),
# и kokoro-onnx (<3.14). Хостовые 3.14/3.15 для синтеза не годятся.
#
# DEVICE=gpu  -> torch из whl/cu126 + onnxruntime-gpu (по умолчанию)
# DEVICE=cpu  -> torch из whl/cpu  + onnxruntime   (фолбэк и машины без карты)
# Два onnxruntime в одно окружение не кладём: они конфликтуют.
FROM python:3.12-slim-bookworm

ARG DEVICE=gpu

RUN apt-get update \
 && apt-get install -y --no-install-recommends ffmpeg libgomp1 \
 && rm -rf /var/lib/apt/lists/*

RUN python -m pip install --no-cache-dir beautifulsoup4 piper-tts edge-tts

RUN if [ "$DEVICE" = "gpu" ]; then \
      python -m pip install --no-cache-dir --index-url https://download.pytorch.org/whl/cu126 torch torchaudio \
      && python -m pip install --no-cache-dir onnxruntime-gpu; \
    else \
      python -m pip install --no-cache-dir --index-url https://download.pytorch.org/whl/cpu torch torchaudio \
      && python -m pip install --no-cache-dir onnxruntime; \
    fi \
 && python -m pip install --no-cache-dir "kokoro==0.9.4" ruaccent silero omegaconf

# Код и проверки — последними лёгкими слоями: правка одного скрипта
# не должна сбрасывать заново скачанный torch.
COPY skills/aidemy /app/skills/aidemy
COPY tests /app/tests
COPY .claude-plugin /app/.claude-plugin
COPY docs /app/docs

WORKDIR /app
CMD ["sleep", "infinity"]
