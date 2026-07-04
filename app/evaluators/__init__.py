"""Evaluator task, profile, and materialization utilities."""


def __getattr__(name: str):
    if name in {"EvaluationMaterializationResult", "EvaluatorOutputMaterializer"}:
        from app.evaluators.materialization import (
            EvaluationMaterializationResult,
            EvaluatorOutputMaterializer,
        )

        return {
            "EvaluationMaterializationResult": EvaluationMaterializationResult,
            "EvaluatorOutputMaterializer": EvaluatorOutputMaterializer,
        }[name]
    if name in {
        "EvaluatorProfile",
        "EvaluatorProfileError",
        "EvaluatorProfileRegistry",
        "create_default_evaluator_profile_registry",
    }:
        from app.evaluators.profiles import (
            EvaluatorProfile,
            EvaluatorProfileError,
            EvaluatorProfileRegistry,
            create_default_evaluator_profile_registry,
        )

        return {
            "EvaluatorProfile": EvaluatorProfile,
            "EvaluatorProfileError": EvaluatorProfileError,
            "EvaluatorProfileRegistry": EvaluatorProfileRegistry,
            "create_default_evaluator_profile_registry": create_default_evaluator_profile_registry,
        }[name]
    if name == "EvaluatorTaskFactory":
        from app.evaluators.tasks import EvaluatorTaskFactory

        return EvaluatorTaskFactory
    raise AttributeError(name)


__all__ = [
    "EvaluationMaterializationResult",
    "EvaluatorOutputMaterializer",
    "EvaluatorProfile",
    "EvaluatorProfileError",
    "EvaluatorProfileRegistry",
    "EvaluatorTaskFactory",
    "create_default_evaluator_profile_registry",
]
