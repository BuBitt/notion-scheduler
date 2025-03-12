import os
import json
import datetime
import hashlib
from typing import Dict, List, Tuple, Any, Optional  # Adicionado Optional aqui
from config import Config
from pathlib import Path


def serialize_time_slots(
    slots: List[Tuple[str, datetime.time, datetime.time, Optional[datetime.date]]]
) -> List[Tuple[str, str, str, Optional[str]]]:
    """Serializa slots de tempo para formato JSON.

    Args:
        slots: Lista de slots de tempo.

    Returns:
        Lista de tuplas serializadas.
    """
    return [
        (
            slot[0],
            slot[1].isoformat(),
            slot[2].isoformat(),
            slot[3].isoformat() if slot[3] else None,
        )
        for slot in slots
    ]


def load_cache(
    file_path: str, cache_name: str, logger
) -> Tuple[Dict[str, Any], Optional[str]]:
    """Carrega o cache de um arquivo se válido e configurado para uso.

    Args:
        file_path: Caminho do arquivo de cache.
        cache_name: Nome do cache ('topics_cache' ou 'time_slots_cache').
        logger: Objeto de log para registrar mensagens.

    Returns:
        Tupla com dados do cache e hash do conteúdo.
    """
    if not Config.USE_CACHE:
        logger.info(f"Cache '{cache_name}' desativado")
        return ({} if cache_name == "topics_cache" else {"slots": []}), None

    file_path = Path(file_path)
    if (
        file_path.exists()
        and (
            datetime.datetime.now()
            - datetime.datetime.fromtimestamp(file_path.stat().st_mtime)
        ).days
        <= Config.CACHE_MAX_AGE_DAYS
    ):
        try:
            with file_path.open("r") as f:
                content = f.read()
                cache = json.loads(content)
                cache_hash = hashlib.sha256(content.encode()).hexdigest()
            if cache_name == "time_slots_cache":
                cache["slots"] = [
                    (
                        slot[0],
                        datetime.time.fromisoformat(slot[1]),
                        datetime.time.fromisoformat(slot[2]),
                        datetime.date.fromisoformat(slot[3]) if slot[3] else None,
                    )
                    for slot in cache["slots"]
                ]
            logger.info(
                f"Cache '{cache_name}' carregado com {len(cache if cache_name == 'topics_cache' else cache['slots'])} itens"
            )
            return cache, cache_hash
        except Exception as e:
            logger.error(f"Erro ao carregar cache '{cache_name}': {e}")
    return ({} if cache_name == "topics_cache" else {"slots": []}), None


def save_cache(
    cache: Dict[str, Any],
    file_path: str,
    cache_name: str,
    logger,
    data_hash: Optional[str] = None,
) -> None:
    """Salva o cache em arquivo apenas se os dados mudaram.

    Args:
        cache: Dados a serem salvos no cache.
        file_path: Caminho do arquivo de cache.
        cache_name: Nome do cache ('topics_cache' ou 'time_slots_cache').
        logger: Objeto de log para registrar mensagens.
        data_hash: Hash dos dados existentes para comparação (opcional).
    """
    if not Config.USE_CACHE:
        logger.debug(f"Salvamento de cache '{cache_name}' desativado")
        return

    try:
        serializable_cache = (
            {"slots": serialize_time_slots(cache["slots"])}
            if cache_name == "time_slots_cache"
            else cache
        )
        content = json.dumps(serializable_cache)
        new_hash = hashlib.sha256(content.encode()).hexdigest()

        file_path = Path(file_path)
        if file_path.exists():
            _, existing_hash = load_cache(file_path, cache_name, logger)
            if existing_hash == new_hash:
                logger.debug(f"Cache '{cache_name}' não mudou, pulando salvamento")
                return

        with file_path.open("w") as f:
            json.dump(serializable_cache, f)
        logger.info(
            f"Cache '{cache_name}' salvo com {len(cache if cache_name == 'topics_cache' else cache['slots'])} itens"
        )
    except Exception as e:
        logger.error(f"Erro ao salvar cache '{cache_name}': {e}")
