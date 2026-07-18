# Intelligence Knowledge Layer

## Philosophy

Reasoning engines should never know business facts.

**Reasoning engines** only know:
- how to analyze
- how to score
- how to normalize
- how to combine evidence

**Business knowledge** (technologies, titles, patterns, confidence values) belongs in a centralized Knowledge Layer.

This separation means:
- Adding a new technology requires zero analyzer changes
- Adding a new industry means extending knowledge modules only
- Confidence tuning is a single file change
- Regex pattern updates don't touch extraction logic

## Architecture

```
conversation_intelligence/
├── knowledge/                     # Knowledge Layer (data only, no logic)
│   ├── titles.py                  # Decision-maker titles + normalization
│   ├── technologies.py            # Technology names by category
│   ├── companies.py               # Company indicators + patterns
│   ├── budgets.py                 # Budget regex patterns
│   ├── timelines.py               # Timeline/date regex patterns
│   ├── meeting_patterns.py        # Meeting-related regex patterns
│   ├── patterns.py                # Generic extraction patterns
│   ├── buying_signals.py          # Buying signal definitions
│   ├── objections.py              # Objection definitions
│   ├── confidence.py              # Named confidence defaults
│   ├── scoring_config.py          # Scoring weights + thresholds
│   ├── normalization.py           # Normalization functions
│   └── registry.py                # Central KnowledgeRegistry
│
├── intent_extractor.py            # Reasoning only
├── entity_extractor.py            # Reasoning only
├── buying_signal_detector.py      # Reasoning only
├── objection_detector.py          # Reasoning only
├── conversation_summary.py        # Reasoning only
├── conversation_memory.py         # Reasoning only
├── conversation_scoring.py        # Reasoning only
├── intelligence_pipeline.py       # Orchestration only
└── __init__.py
```

## Registry Pattern

All reasoning engines depend **only** on `KnowledgeRegistry`.

```python
from services.conversation_intelligence.knowledge.registry import get_registry

registry = get_registry()
titles = registry.get_decision_maker_titles()
technologies = registry.get_technologies()
confidence = registry.get_confidence("PERSON_CONFIDENCE")
```

Never import individual knowledge files directly from analyzers.

## Knowledge Module Contracts

Each knowledge module exposes only constants. No functions, no classes, no extraction logic.

| Module | Exports | Consumer |
|--------|---------|----------|
| `titles.py` | `DECISION_MAKER_TITLES`, `TITLE_NORMALIZATIONS` | entity_extractor, memory |
| `technologies.py` | `TECHNOLOGIES`, `ALL_TECHNOLOGIES`, `TECHNOLOGY_NORMALIZATIONS` | entity_extractor |
| `companies.py` | `COMPANY_INDICATORS`, `COMPANY_PATTERNS`, `COMPANY_INDICATOR_EXCEPTIONS` | entity_extractor, memory |
| `budgets.py` | `BUDGET_PATTERNS`, `BUDGET_KEYWORDS` | entity_extractor |
| `timelines.py` | `TIMELINE_PATTERNS`, `TIMELINE_KEYWORDS` | entity_extractor |
| `meeting_patterns.py` | `MEETING_PATTERNS`, `MEETING_KEYWORDS` | entity_extractor |
| `patterns.py` | `PERSON_PATTERNS`, `PERSON_SELF_IDENTIFICATION`, `PRODUCT_PATTERNS`, `NEED_PATTERNS` | entity_extractor, memory |
| `buying_signals.py` | `BUYING_SIGNAL_DEFINITIONS` | buying_signal (legacy), buying_signal_detector |
| `objections.py` | `OBJECTION_DEFINITIONS` | objection_detector |
| `confidence.py` | Named confidence constants (e.g., `PERSON_CONFIDENCE = 0.6`) | All analyzers |
| `scoring_config.py` | `DEFAULT_SCORING_WEIGHTS`, `STRENGTH_SCORES`, `SEVERITY_PENALTIES` | conversation_scoring |
| `normalization.py` | `normalize_title()`, `normalize_technology()`, `normalize_budget_value()`, `normalize_company_suffix()`, `normalize_entity_type_label()` | Any consumer |

### Confidence Configuration

All numeric confidence values live in `confidence.py` as named constants:

```
PERSON_CONFIDENCE          → 0.6
COMPANY_CONFIDENCE         → 0.5
TITLE_CONFIDENCE           → 0.7
TECHNOLOGY_CONFIDENCE      → 0.8
BUDGET_EXPLICIT_CONFIDENCE → 0.8
BUDGET_IMPLICIT_CONFIDENCE → 0.6
TIMELINE_DATE_CONFIDENCE   → 0.7
TIMELINE_OTHER_CONFIDENCE  → 0.5
MEETING_CONFIDENCE         → 0.6
...
```

Analyzers access via `registry.get_confidence("PERSON_CONFIDENCE")`.

### Scoring Configuration

Scoring weights live in `scoring_config.py`:

```
buying_signal → 35
objection     → -25
engagement    → 20
velocity      → 15
sentiment     → 10
```

Strength scores and severity penalties are also configured there.

## Extensibility Strategy

### Adding a new technology

1. Add to `knowledge/technologies.py` under the appropriate category
2. Zero analyzer changes

### Adding a new industry

1. Add industry-specific terms, titles, technologies to knowledge modules
2. Registry can gain industry filters (`get_technologies(industry="healthcare")`)
3. Analyzers remain unchanged

### Adding a new language

1. Add translated patterns to knowledge modules
2. Registry gains language parameter (`get_objection_definitions(language="de")`)
3. Analyzers remain unchanged

### AI model integration

AI models can consume the same Knowledge Layer:
- Buying signal definitions can become AI prompt context
- Objection patterns can train AI classification
- Normalization rules can guide AI output formatting
- Confidence values can calibrate AI confidence scoring

## Future Externalization

The registry is designed so knowledge sources can move to external storage without changing analyzers.

### Phase 1 (current): Python modules
```python
# knowledge/technologies.py
TECHNOLOGIES = {"crm": ["salesforce", "hubspot"]}
```

### Phase 2: YAML/JSON files
```python
# registry loads from YAML instead of Python module
class KnowledgeRegistry:
    def __init__(self, source="yaml"):
        self._data = yaml.load("knowledge/technologies.yaml")
```

### Phase 3: Database
```python
class KnowledgeRegistry:
    def __init__(self, source="supabase"):
        self._data = supabase.table("knowledge").select("*").execute()
```

### Phase 4: Admin UI
```python
class KnowledgeRegistry:
    def get_technologies(self):
        return self._admin_api.get("/knowledge/technologies")
```

In every phase, the analyzer code stays the same:
```python
registry.get_technologies()   # works regardless of source
```

## Avoiding Circular Imports

The knowledge modules import only from:
- `services.conversation_models` (for `SignalStrength`)
- `services.conversation_intelligence.intelligence_models` (for `ObjectionCategory`, `ObjectionSeverity`)

No knowledge module imports from:
- Any analyzer module
- `services.conversation_intelligence.__init__`
- `services.buying_signal`

Existing services (like `buying_signal.py`) that need knowledge use **lazy imports** inside function scope to avoid circular dependency with the `conversation_intelligence` package init.

## Migration Guide

To add new entity types or extraction categories:

1. Add entity type to `intelligence_models.py` `EntityType` enum
2. Add patterns to appropriate knowledge module
3. Add confidence constant to `confidence.py`
4. Add registry getter method to `KnowledgeRegistry`
5. Add extraction function to the relevant analyzer
6. Expose new data in `ConversationIntelligence.to_dict()`

The knowledge layer grows, analyzers stay lean.
