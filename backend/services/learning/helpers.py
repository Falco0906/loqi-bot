"""Learning helpers — simple import surface for main.py integration.

Provides singleton access to FeedbackInterpreter so that main.py
can record user actions without importing the full learning pipeline.
"""

from services.learning.behavior_tracker import get_tracker
from services.learning.feedback_interpreter import FeedbackInterpreter


_interpreter: FeedbackInterpreter | None = None


def get_interpreter() -> FeedbackInterpreter:
    global _interpreter
    if _interpreter is None:
        _interpreter = FeedbackInterpreter(get_tracker())
    return _interpreter
