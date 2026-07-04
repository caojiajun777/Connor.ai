"""Watchlist, archive, and intelligence thread utilities."""


def __getattr__(name: str):
    if name in {"WatchlistMaterializationResult", "WatchlistOutputMaterializer"}:
        from app.watchlist.materialization import (
            WatchlistMaterializationResult,
            WatchlistOutputMaterializer,
        )

        return {
            "WatchlistMaterializationResult": WatchlistMaterializationResult,
            "WatchlistOutputMaterializer": WatchlistOutputMaterializer,
        }[name]
    if name == "WatchlistLifecycleService":
        from app.watchlist.lifecycle import WatchlistLifecycleService

        return WatchlistLifecycleService
    if name == "WatchlistTaskFactory":
        from app.watchlist.tasks import WatchlistTaskFactory

        return WatchlistTaskFactory
    raise AttributeError(name)


__all__ = [
    "WatchlistLifecycleService",
    "WatchlistMaterializationResult",
    "WatchlistOutputMaterializer",
    "WatchlistTaskFactory",
]
