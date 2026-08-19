FROM python:3.12-slim@sha256:229a2c5bfa27522db7815ea81f9bed70af17ccb9de9fc7ad142b1877b5830d36

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONHASHSEED=0 \
    PYTHONPATH=/subject/src:/opt/evaluator

COPY requirements.lock /opt/evaluator/requirements.lock
RUN python -m pip install \
      --disable-pip-version-check \
      --no-cache-dir \
      --require-hashes \
      --requirement /opt/evaluator/requirements.lock

COPY bridge.py /opt/evaluator/bridge.py
COPY interfaces.py /opt/evaluator/soa_experience/calculations/interfaces.py

USER 65532:65532
ENTRYPOINT ["python", "/opt/evaluator/bridge.py"]
