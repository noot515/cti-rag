"""Legacy application configuration with explicit, lazy runtime construction.

Importing this module does not load ``.env``, create log files, read application
configuration, validate provider credentials, or create backend clients. Those
operations happen only when ``Config`` is constructed or ``get_runtime_config`` is
called explicitly.
"""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from threading import RLock
from typing import Any

import yaml

logger = logging.getLogger("ThreatRAG.config")
DEFAULT_MOCK_API = "this_is_mock_api_key_in_frontend"

_runtime_config: "Config | None" = None
_runtime_config_lock = RLock()
_dotenv_loaded = False


def get_project_root() -> str:
    """Resolve the repository root without importing packages.utils."""
    current_path = Path(__file__).resolve()
    root_indicators = [".git", "requirements.txt", "pyproject.toml", "setup.py", "README.md", "readme.md"]
    for parent in current_path.parents:
        if any((parent / indicator).exists() for indicator in root_indicators):
            return str(parent)
    return str(current_path.parent.parent.parent)


def _load_dotenv_once() -> None:
    global _dotenv_loaded
    if _dotenv_loaded:
        return
    with _runtime_config_lock:
        if _dotenv_loaded:
            return
        env_path = Path(get_project_root()) / ".env"
        if env_path.exists():
            try:
                from dotenv import load_dotenv
            except ImportError as exc:
                raise RuntimeError(
                    "python-dotenv is required to load the legacy .env runtime configuration"
                ) from exc
            load_dotenv(env_path)
        _dotenv_loaded = True


class SimpleConfig(dict):
    def __key(self, key):
        return "" if key is None else key

    def __str__(self):
        return json.dumps(self)

    def __setattr__(self, key, value):
        self[self.__key(key)] = value

    def __getattr__(self, key):
        return self.get(self.__key(key))

    def __getitem__(self, key):
        return self.get(self.__key(key))

    def __setitem__(self, key, value):
        return super().__setitem__(self.__key(key), value)

    def __dict__(self):
        return {k: v for k, v in self.items()}


class Config(SimpleConfig):
    def __init__(self):
        _load_dotenv_once()
        super().__init__()
        self._config_items = {}
        project_root = get_project_root()
        self.save_dir = os.path.join(project_root, "saves")

        root_config = os.path.join(project_root, "config.yaml")
        fallback_config = str(Path(self.save_dir) / "config" / "base.yaml")

        if os.path.exists(root_config):
            self.filename = root_config
        else:
            self.filename = fallback_config
            os.makedirs(os.path.dirname(self.filename), exist_ok=True)

        self._update_models_from_file()

        self.add_item("enable_reranker", default=False, des="enable reranking")
        self.add_item("enable_knowledge_base", default=False, des="enable knowledge base")
        self.add_item("enable_knowledge_graph", default=False, des="enable knowledge graph")
        self.add_item("enable_web_search", default=False, des="enable web search")
        self.add_item(
            "model_provider",
            default="siliconflow",
            des="model provider",
            choices=list(self.model_names.keys()),
        )
        self.add_item("model_name", default="Qwen/Qwen2.5-7B-Instruct", des="model name")
        self.add_item(
            "embed_model",
            default="siliconflow/BAAI/bge-m3",
            des="embedding model",
            choices=list(self.embed_model_names.keys()),
        )
        self.add_item(
            "reranker",
            default="siliconflow/BAAI/bge-reranker-v2-m3",
            des="reranker model",
            choices=list(self.reranker_names.keys()),
        )
        self.add_item("model_local_paths", default={}, des="local model paths")
        self.add_item("use_rewrite_query", default="off", des="query rewrite", choices=["off", "on", "hyde"])
        self.add_item("device", default="cuda", des="local model device", choices=["cpu", "cuda"])
        self.add_item("RERANK_TOP_K", default=5, des="reranker result count")
        self.add_item(
            "rl_base_model_path",
            default="models/reasoning_model/Qwen2.5-3B-Instruct",
            des="RL base model path",
        )
        self.add_item(
            "rl_lora_path",
            default="models/reasoning_model/final_lora",
            des="RL LoRA path",
        )
        self.add_item(
            "rl_policy_checkpoint_path",
            default="models/reasoning_model/rl_policy_path_match/best_policy.pt",
            des="RL policy checkpoint",
        )
        self.add_item(
            "rl_adjacency_path",
            default="RL/cache/adjacency.json",
            des="RL graph adjacency cache",
        )
        self.add_item("rl_device", default="cuda", des="RL device", choices=["cpu", "cuda"])
        self.add_item("rl_max_steps", default=4, des="RL maximum steps")
        self.add_item("rl_candidate_top_k", default=3, des="RL start entity candidates")

        self.load()
        try:
            def _normalize_path(p: str) -> str:
                if not isinstance(p, str):
                    return p
                q = p.replace("\\", "/")
                if q.startswith("models/"):
                    q = "/app/" + q
                return q

            if isinstance(self.model_local_paths, dict):
                for key, value in list(self.model_local_paths.items()):
                    self.model_local_paths[key] = _normalize_path(value)

            for table in (
                getattr(self, "embed_model_names", {}),
                getattr(self, "reranker_names", {}),
            ):
                if isinstance(table, dict):
                    for value in table.values():
                        if isinstance(value, dict) and "local_path" in value:
                            value["local_path"] = _normalize_path(value["local_path"])
        except Exception:
            pass

        self.handle_self()

    def add_item(self, key, default, des=None, choices=None):
        self.__setattr__(key, default)
        self._config_items[key] = {"default": default, "des": des, "choices": choices}

    def __dict__(self):
        blocklist = [
            "_config_items",
            "model_names",
            "model_provider_status",
            "embed_model_names",
            "reranker_names",
        ]
        return {k: v for k, v in self.items() if k not in blocklist}

    def _update_models_from_file(self):
        project_root = get_project_root()
        static_dir = os.path.join(project_root, "packages", "static")

        with open(os.path.join(static_dir, "models.yaml"), "r", encoding="utf-8") as file:
            models = yaml.safe_load(file)

        try:
            with open(os.path.join(static_dir, "models.yml"), "r", encoding="utf-8") as file:
                private_models = yaml.safe_load(file) or {}
        except FileNotFoundError:
            private_models = {}

        filtered_models = {
            "MODEL_NAMES": {
                key: value
                for key, value in models["MODEL_NAMES"].items()
                if key in ["deepseek", "zhipu"]
            },
            "EMBED_MODEL_INFO": {
                key: value
                for key, value in models["EMBED_MODEL_INFO"].items()
                if key.startswith(("deepseek/", "zhipu/", "local/", "dashscope/"))
                or key in ["deepseek", "zhipu", "local", "dashscope"]
            },
            "RERANKER_LIST": {
                key: value
                for key, value in models["RERANKER_LIST"].items()
                if key.startswith(("deepseek/", "zhipu/", "local/"))
                or key in ["deepseek", "zhipu", "local"]
            },
        }

        self.model_names = {
            **filtered_models["MODEL_NAMES"],
            **private_models.get("MODEL_NAMES", {}),
        }
        self.embed_model_names = {
            **filtered_models["EMBED_MODEL_INFO"],
            **private_models.get("EMBED_MODEL_INFO", {}),
        }
        self.reranker_names = {
            **filtered_models["RERANKER_LIST"],
            **private_models.get("RERANKER_LIST", {}),
        }

    def _save_models_to_file(self):
        models = {
            "MODEL_NAMES": self.model_names,
            "EMBED_MODEL_INFO": self.embed_model_names,
            "RERANKER_LIST": self.reranker_names,
        }
        project_root = get_project_root()
        static_dir = os.path.join(project_root, "packages", "static")
        with open(os.path.join(static_dir, "models.yml"), "w", encoding="utf-8") as file:
            yaml.dump(models, file, indent=2, allow_unicode=True)

    def handle_self(self):
        model_provider_info = self.model_names.get(self.model_provider, {})
        self.model_dir = os.environ.get("MODEL_DIR", "")

        if self.model_dir:
            if os.path.exists(self.model_dir):
                logger.info("MODEL_DIR (%s) entries: %s", self.model_dir, os.listdir(self.model_dir))
            else:
                logger.warning("MODEL_DIR (%s) does not exist", self.model_dir)

        if self.model_provider not in ["deepseek"]:
            logger.warning(
                "Model provider %s not supported, using default model provider",
                self.model_provider,
            )
            self.model_provider = "deepseek"
            model_provider_info = self.model_names.get(self.model_provider, {})

        if self.model_name not in model_provider_info.get("models", []):
            logger.warning(
                "Model name %s not in %s, using default model name",
                self.model_name,
                self.model_provider,
            )
            self.model_name = model_provider_info.get("default", "deepseek-chat")

        conds = {}
        self.model_provider_status = {}
        for provider in ["deepseek"]:
            conds[provider] = self.model_names[provider]["env"]
            conds_bool = [bool(os.getenv(key)) for key in conds[provider]]
            self.model_provider_status[provider] = all(conds_bool)

        if os.getenv("TAVILY_API_KEY"):
            self.enable_web_search = True

        self.valuable_model_provider = [
            key for key, value in self.model_provider_status.items() if value
        ]
        assert self.valuable_model_provider, (
            "No model provider available, please check your `.env` file. "
            f"API_KEY_LIST: {conds}"
        )

    def load(self):
        logger.info("Loading config from %s", self.filename)
        if self.filename is not None and os.path.exists(self.filename):
            if self.filename.endswith(".json"):
                with open(self.filename, "r", encoding="utf-8") as file:
                    content = file.read()
                    if content:
                        self.update(json.loads(content))
            elif self.filename.endswith(".yaml"):
                with open(self.filename, "r", encoding="utf-8") as file:
                    content = file.read()
                    if content:
                        self.update(yaml.safe_load(content))
            else:
                logger.warning("Unknown config file type %s", self.filename)
        else:
            logger.warning("Config file not found: %s", self.filename)

    def save(self):
        logger.info("Saving config to %s", self.filename)
        if self.filename is None:
            self.filename = os.path.join(self.save_dir, "config", "base.yaml")
            os.makedirs(os.path.dirname(self.filename), exist_ok=True)

        if self.filename.endswith(".json"):
            with open(self.filename, "w+", encoding="utf-8") as file:
                json.dump(self.__dict__(), file, indent=4, ensure_ascii=False)
        elif self.filename.endswith(".yaml"):
            with open(self.filename, "w+", encoding="utf-8") as file:
                yaml.dump(self.__dict__(), file, indent=2, allow_unicode=True)
        else:
            logger.warning("Unknown config file type %s, saving as json", self.filename)
            with open(self.filename, "w+", encoding="utf-8") as file:
                json.dump(self, file, indent=4)

        logger.info("Config file %s saved", self.filename)

    def get_safe_config(self):
        config = json.loads(str(self))
        for model in config.get("custom_models", []):
            model["api_key"] = DEFAULT_MOCK_API if model.get("api_key") else ""
        return config

    def compare_custom_models(self, value):
        current_models_dict = {
            model["custom_id"]: model.get("api_key")
            for model in self.get("custom_models", [])
        }
        for index, model in enumerate(value):
            input_custom_id = model.get("custom_id")
            input_api_key = model.get("api_key")
            if input_custom_id in current_models_dict:
                current_api_key = current_models_dict[input_custom_id]
                if input_api_key == DEFAULT_MOCK_API or input_api_key == current_api_key:
                    value[index]["api_key"] = current_api_key
        return value


def get_runtime_config() -> Config:
    """Construct and cache the legacy configuration on explicit runtime access."""
    global _runtime_config
    if _runtime_config is None:
        with _runtime_config_lock:
            if _runtime_config is None:
                _runtime_config = Config()
    return _runtime_config


def __getattr__(name: str) -> Any:
    """Keep ``packages.config.<legacy field>`` compatible after submodule import."""
    if name.startswith("__"):
        raise AttributeError(name)
    return getattr(get_runtime_config(), name)


def __dir__() -> list[str]:
    public = {"Config", "SimpleConfig", "DEFAULT_MOCK_API", "get_runtime_config"}
    if _runtime_config is not None:
        public.update(_runtime_config.keys())
    return sorted(set(globals()) | public)
