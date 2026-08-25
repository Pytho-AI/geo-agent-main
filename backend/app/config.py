from pydantic_settings import BaseSettings
from functools import lru_cache


class Settings(BaseSettings):
    # Database
    database_url: str = "postgresql+asyncpg://geoagent:geoagent@localhost:9846/geoagent"

    # AWS
    aws_s3_bucket: str = ""
    aws_region: str = "us-east-1"

    # LLM — gemma4 26B everywhere, per-deployment TRANSPORT only
    # (scratch/docs/agent/map-nl-chat-scope.md). Defaults are the cloud
    # shape (bedrock-mantle); the edge overrides base_url/model in .env:
    #   LLM_BASE_URL=http://172.17.0.1:18000/v1        (GB10 vllm)
    #   LLM_MODEL=nvidia/Gemma-4-26B-A4B-NVFP4
    #   LLM_ENABLE_THINKING=true                       (vllm-only knob)
    # Mantle auth is a bearer minted from ambient AWS credentials; a
    # static LLM_API_KEY overrides when set.
    llm_provider: str = "openai_compatible"
    llm_model: str = "google.gemma-4-26b-a4b"
    llm_base_url: str = "https://bedrock-mantle.us-east-1.api.aws/openai/v1"
    llm_api_key: str = ""
    # String, parsed in client.py: compose passes '' when unset, and an
    # empty string must mean "knob absent" (mantle rejects it), never a
    # boot-time bool validation error.
    llm_enable_thinking: str = ""
    # Gemma-4 image token budget (max_soft_tokens ∈ {70,140,280,560,1120}).
    # Default 0 = leave the serving default, which is 280 on BOTH paths —
    # Bedrock/mantle fixes it at ~280 and ignores the knob (verified:
    # prompt_tokens flat at ~282 across 70→1120 and 1148px→2600px), so we
    # keep vLLM at the same 280 for parity (no cloud/edge divergence).
    # Raise it (→ mm_processor_kwargs on vLLM only; inert on mantle) only
    # for a deliberate edge experiment with dense tables.
    llm_image_soft_tokens: int = 0
    ollama_base_url: str = "http://host.docker.internal:11434"
    owm_api_key: str = ""

    # The editor subprocess (in-container, loopback) — also the
    # office-doc converter for graph-ingest: DOCX/XLSX/PPTX POST to
    # {editor_url}/cool/convert-to/pdf, then
    # PyMuPDF renders the PDF to page images for the VLM. The same
    # pair drives the WOPI viewer proxy (api/v1/wopi.py) and the
    # entrypoint's service_root flag — ONE knob pair, they cannot
    # diverge. env EDITOR_URL.
    editor_url: str = "http://127.0.0.1:9980"

    # Per-deployment first-open camera for maps with no saved viewport:
    # "lng,lat,zoom" (env DEFAULT_VIEW). ONE image serves every
    # deployment, so an exercise AO belongs HERE (the deployment's env),
    # never hardcoded in the shared frontend — an edge box sets its
    # exercise AO; the cloud box can leave it unset and the frontend
    # falls back to a neutral world view. Served via /config defaultView.
    default_view: str = ""

    # Data root — the compose GEO_DATA_DIR host dir mounts here. Offline
    # assets live under <data_dir>/offline, persisted renders under
    # <data_dir>/renders. offline_data_dir derives; it is NOT a separate
    # deployment knob (the old OFFLINE_DATA_DIR compose env just restated
    # this default and was removed).
    data_dir: str = "/app/data"

    # Offline mode
    offline_mode: bool = False
    offline_data_dir: str = "/app/data/offline"

    class Config:
        env_file = ".env"


@lru_cache
def get_settings() -> Settings:
    return Settings()
