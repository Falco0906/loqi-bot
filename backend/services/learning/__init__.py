"""Learning Layer — deterministic learned preferences from user behavior.

Architectural role (per ARCHITECTURE_RFC.md and IMPLEMENTATION_RULES.md):

  Intelligence Layer
      ↓ signals
  Reasoning Layer
      ↓ structured data
  Narrative Engine
      ↓ natural language
  Experience Layer

  Learning Layer (part of Intelligence Layer)
      ↓ typed workspace preferences
  Durable preference store
      ↓ preferences
  Reasoning Layer — consumes preferences for personalization
  Narrative Engine — may mention learned preferences

Design rules:
  - Learning is deterministic.  No LLM.
  - Learning is conservative.  MIN_EVIDENCE = 5.
  - Learning writes typed preferences only with canonical workspace scope.
  - Learning is idempotent.  Same evidence → same result.
  - Preferences are typed.  No natural language blobs.

Modules:
  models               — PreferenceKey enum, LearnedPreference dataclass
  behavior_tracker     — counts user actions, provides evidence
  preference_learner   — evaluates evidence, produces typed preferences
  pattern_detector     — detects temporal patterns (working hours, etc.)
  feedback_interpreter — translates user feedback into evidence
  preference_store     — typed access to durable workspace preferences
  learner              — orchestrator, idempotent pipeline runner
"""

from services.learning.learner import Learner
from services.learning.models import LearnedPreference, PreferenceKey
from services.learning.preference_store import PreferenceStore
