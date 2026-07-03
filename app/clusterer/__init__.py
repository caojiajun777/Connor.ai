"""Clusterer task and materialization utilities."""


def __getattr__(name: str):
    if name in {"ClusterMaterializationResult", "ClusterOutputMaterializer"}:
        from app.clusterer.materialization import (
            ClusterMaterializationResult,
            ClusterOutputMaterializer,
        )

        return {
            "ClusterMaterializationResult": ClusterMaterializationResult,
            "ClusterOutputMaterializer": ClusterOutputMaterializer,
        }[name]
    if name == "ClusterTaskFactory":
        from app.clusterer.tasks import ClusterTaskFactory

        return ClusterTaskFactory
    raise AttributeError(name)


__all__ = [
    "ClusterMaterializationResult",
    "ClusterOutputMaterializer",
    "ClusterTaskFactory",
]
