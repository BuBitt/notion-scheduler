import os
import json
import datetime
import hashlib
from config import Config


def load_cache(file_path, cache_name, logger):
    """
    Carrega o cache de um arquivo se válido e configurado para uso.

    Args:
        file_path (str): Caminho do arquivo de cache.
        cache_name (str): Nome do cache (e.g., 'topics_cache').
        logger: Objeto de logging.

    Returns:
        tuple: (dados do cache, hash do conteúdo) ou ({}, None) se inválido.
    """
    if not Config.USE_CACHE:
        logger.info(f"Cache '{cache_name}' desativado")
        return {} if cache_name == "topics_cache" else {"slots": []}, None

    if os.path.exists(file_path):
        mod_time = datetime.datetime.fromtimestamp(os.path.getmtime(file_path))
        if (datetime.datetime.now() - mod_time).days <= Config.CACHE_MAX_AGE_DAYS:
            try:
                with open(file_path, "r") as f:
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
    return {} if cache_name == "topics_cache" else {"slots": []}, None


def save_cache(cache, file_path, cache_name, logger, data_hash=None):
    """
    Salva o cache em arquivo apenas se os dados mudaram.

    Args:
        cache: Dados a serem salvos.
        file_path (str): Caminho do arquivo de cache.
        cache_name (str): Nome do cache.
        logger: Objeto de logging.
        data_hash (str, optional): Hash dos dados atuais para comparação.
    """
    if not Config.USE_CACHE:
        logger.debug(f"Salvamento de cache '{cache_name}' desativado")
        return

    try:
        if cache_name == "time_slots_cache":
            serializable_cache = {
                "slots": [
                    (
                        slot[0],
                        slot[1].isoformat(),
                        slot[2].isoformat(),
                        slot[3].isoformat() if slot[3] else None,
                    )
                    for slot in cache["slots"]
                ]
            }
        else:
            serializable_cache = cache

        content = json.dumps(serializable_cache)
        new_hash = hashlib.sha256(content.encode()).hexdigest()

        if os.path.exists(file_path):
            _, existing_hash = load_cache(file_path, cache_name, logger)
            if existing_hash == new_hash:
                logger.debug(f"Cache '{cache_name}' não mudou, pulando salvamento")
                return

        with open(file_path, "w") as f:
            json.dump(serializable_cache, f)
        logger.info(
            f"Cache '{cache_name}' salvo com {len(cache if cache_name == 'topics_cache' else cache['slots'])} itens"
        )
    except Exception as e:
        logger.error(f"Erro ao salvar cache '{cache_name}': {e}")
