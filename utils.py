import os
import json
import datetime
from config import Config


def load_cache(file_path, cache_name, logger):  # Adicionado logger como parâmetro
    if not Config.USE_CACHE:
        logger.info(f"Cache {cache_name} desativado")
        return {} if cache_name == "topics_cache" else {"slots": []}
    if os.path.exists(file_path):
        mod_time = datetime.datetime.fromtimestamp(os.path.getmtime(file_path))
        if (datetime.datetime.now() - mod_time).days <= Config.CACHE_MAX_AGE_DAYS:
            try:
                with open(file_path, "r") as f:
                    cache = json.load(f)
                if cache_name == "time_slots_cache":
                    cache["slots"] = [
                        (
                            slot[0],
                            datetime.time.fromisoformat(slot[1]),
                            datetime.time.fromisoformat(slot[2]),
                            (datetime.date.fromisoformat(slot[3]) if slot[3] else None),
                        )
                        for slot in cache["slots"]
                    ]
                logger.info(
                    f"Cache {cache_name} carregado de {file_path} com {len(cache if cache_name == 'topics_cache' else cache['slots'])} itens"
                )
                return cache
            except Exception as e:
                logger.error(f"Erro ao carregar cache {cache_name}: {e}")
    return {} if cache_name == "topics_cache" else {"slots": []}


def save_cache(
    cache, file_path, cache_name, logger
):  # Adicionado logger como parâmetro
    if not Config.USE_CACHE:
        logger.debug(f"Salvamento de cache {cache_name} desativado")
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
        with open(file_path, "w") as f:
            json.dump(serializable_cache, f)
        logger.info(
            f"Cache {cache_name} salvo em {file_path} com {len(cache if cache_name == 'topics_cache' else cache['slots'])} itens"
        )
    except Exception as e:
        logger.error(f"Erro ao salvar cache {cache_name}: {e}")
