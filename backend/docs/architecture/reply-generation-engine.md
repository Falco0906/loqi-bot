# Reply Generation Engine

## Architecture

```
Conversation Intelligence     Reasoning Result
         │                         │
         └─────────┬───────────────┘
                   ▼
         Generation Context
                   │
                   ▼
           Prompt Builder
                   │
          ┌────────┴────────┐
          ▼                 ▼
    System Prompt      User Prompt
          │                 │
          └────────┬────────┘
                   ▼
        Provider Registry
                   │
          ┌────────┴────────┐
          ▼                 ▼
    OpenAI    Anthropic   Gemini   DeepSeek
                   │
                   ▼
         Reply Draft(s)  ← ProviderResponse (text + model + usage)
                   │
                   ▼
           Validation
                   │
                   ▼
         Generation Result
         (drafts + metadata + timing + validation)
```

## Principles

1. **Separation of concerns** — Conversation Intelligence understands, Reasoning decides, Reply Generation communicates.
2. **Provider independence** — The generation engine never knows which LLM provider is active. Providers are interchangeable via registry.
3. **Prompt isolation** — Prompt construction is a separate concern from provider calls. Providers receive pre-built prompts.
4. **Template-driven** — Reply structure is governed by templates, not hardcoded logic.
5. **Style-driven** — Tone and structure are governed by style instructions, not business logic.
6. **Validation** — Every generated draft is validated before return.
7. **Versioned** — Every component exposes a version string in metadata.
8. **Observable** — Every generation has lifecycle timing.

## Components

### Generation Models (`generation_models.py`)

| Model | Purpose |
|-------|---------|
| `GenerationContext` | Normalized input for providers — never raw messages |
| `ReplyDraft` | Single generated reply with `original_content` preservation |
| `ReplyVariant` | Collection of drafts for one style |
| `GenerationMetadata` | Provider, model, latency, token usage, version fields |
| `GenerationResult` | Complete generation output with validation + timing |
| `ValidationIssue` | Structured validation feedback |

Version constants: `PROMPT_BUILDER_VERSION`, `TEMPLATE_LIBRARY_VERSION`, `STYLE_ENGINE_VERSION`, `CONTEXT_BUILDER_VERSION`, `PIPELINE_VERSION`

### Provider Abstraction (`provider_base.py`)

```python
class LLMProvider(ABC):
    def generate(system_prompt, user_prompt, model, temperature, max_tokens) -> ProviderResponse
    async def generate_async(...) -> ProviderResponse
    async def generate_stream(...) -> AsyncGenerator[str, None]
    def validate_connection() -> bool  # lightweight, no expensive API calls
```

`ProviderResponse` contains:
- `text` — the generated reply
- `model` — model identifier from API response
- `token_usage` — input/output token counts

### Provider Registry (`provider_registry.py`)

- `_auto_register()` — discovers all providers on import. No manual imports needed.
- `register_provider(name, class)` — add a provider at runtime
- `get_provider(name)` — get/create cached instance
- `get_default_provider()` — first available validated provider (deterministic order: openai, anthropic, gemini, deepseek)
- `validate_all()` — check all registered providers. Unavailable providers degrade gracefully.

### Supported Providers

| Provider | Env Key | Default Model | Status |
|----------|---------|---------------|--------|
| OpenAI | `OPENAI_API_KEY` | gpt-4o-mini | Full (Responses API) with retries + usage extraction |
| Anthropic | `ANTHROPIC_API_KEY` | claude-sonnet-4-20250514 | Full (Messages API) with retries + usage extraction |
| Gemini | `GEMINI_API_KEY` | gemini-2.0-flash-lite | Stub (structure ready) |
| DeepSeek | `DEEPSEEK_API_KEY` | deepseek-chat | Stub (structure ready) |

#### Provider Lifecycle

1. `_auto_register()` imports each module and registers the class
2. `get_provider(name)` instantiates the class on first access
3. `get_default_provider()` iterates registered providers, calls `validate_connection()`, returns first valid one
4. Unavailable providers (missing API key) are skipped, never raise errors
5. `validate_connection()` is lightweight — just checks for API key presence, no expensive API calls

#### Retry Behavior

- Both OpenAI and Anthropic providers implement 3 retries with exponential backoff (1s, 2s, 4s)
- Rate limiting (HTTP 429) triggers automatic retry
- Authentication errors (HTTP 401/403) are caught immediately — no retry wasted
- Timeout errors retry with backoff
- All errors produce structured `ProviderResponse` with error info in `token_usage`

### Prompt Builder (`prompt_builder.py`)

Responsible for constructing system and user prompts from `GenerationContext`.

- `build_system_prompt(context)` — industry context + style instructions + template instructions
- `build_user_prompt(context)` — conversation context + signals + reasoning summary + task

Providers never assemble prompts manually. All prompt construction is isolated here.

#### Prompt Lifecycle

1. Context is built from intelligence + reasoning
2. `build_system_prompt()` selects style instructions via `style_engine` and template instructions via `template_library`
3. `build_user_prompt()` formats conversation context, signals, objections, entities, memory, policies, reasoning summary
4. Providers receive `system_prompt` + `user_prompt` as flat strings

### Context Builder (`generation_context.py`)

Normalizes `ConversationIntelligence` + `ReasoningResult` into `GenerationContext`.

Filters: limits signals (5 max), objections (5 max), entities (8 max), memory facts (10 max), messages (3 max).

Fields populated:
- `executive_summary` — short summary from intelligence
- `conversation_stage` — from reasoning stage
- `primary_goal`, `alternative_goal` — from reasoning goal
- `decision_type`, `decision_priority`, `decision_confidence` — from reasoning decision
- `target_action` — human-readable decision type
- `style_name` — the style being generated (resolved to instructions in prompt builder)

No raw provider objects, no Gmail models, no conversation store references.

#### Context Lifecycle

1. Receive `ConversationIntelligence` + `ReasoningResult`
2. Extract and filter each field
3. Return `GenerationContext` — a plain dataclass with no references to source objects
4. Pipeline passes context to prompt builder

### Template Library (`template_library.py`)

10 reusable templates:
- Pricing Response
- Demo Confirmation
- Technical Question
- Follow-up
- Objection Handling
- Meeting Scheduling
- General Reply
- Re-engagement
- Thank You
- Clarification

#### Template Selection

Templates are selected based on `context.primary_goal`:
- `pricing`/`budget` → pricing_response
- `demo` → demo_confirmation
- `meeting`/`schedule` → meeting_scheduling
- `objection`/`overcome` → objection_handling
- `question`/`technical`/`information` → technical_question or clarification
- `engage`/`follow` → re_engagement
- `confirm`/`interest` → thank_you
- `wait`/`continue_nurturing` → follow_up
- fallback → general_reply

#### Template Lifecycle

1. `select_template(context)` picks the best template name
2. `get_template_instructions(context)` retrieves the template string and calls `_fill_template()`
3. `_fill_template()` replaces all placeholders (`{primary_goal}`, `{decision_confidence:.0%}`, etc.)
4. All placeholders are verified before reaching the LLM — no literal syntax escapes

### Style Engine (`style_engine.py`)

9 styles that only influence tone, verbosity, structure, and wording:

| Style | Tone | Structure |
|-------|------|-----------|
| Professional | Polished, formal | Greeting → message → CTA |
| Friendly | Warm, conversational | Friendly opening → message → soft next step |
| Executive | Direct, strategic | Bottom-line upfront → key points → ask |
| Technical | Precise, informative | Context → detail → next technical step |
| Consultative | Advisory, insightful | Insight → relevance → recommendation → next step |
| Short | Brief, efficient | 1-2 sentences |
| Detailed | Thorough, comprehensive | Full context → explanation → supporting points → next step |
| Persuasive | Confident, compelling | Hook → value → proof → CTA |
| Neutral | Balanced, objective | Neutral → balanced info → open next step |

Styles never change: reasoning, goals, policies, conversation strategy.

### Validation (`validation.py`)

Complete set of validation checks:

| Check | Code | Severity |
|-------|------|----------|
| Empty response | `empty_response` | ERROR |
| Excessively short/long | `too_short` / `too_long` | WARNING |
| Unresolved placeholders | `placeholder_remaining` | ERROR |
| Hallucinated prices | `hallucinated_price` | WARNING |
| Hallucinated dates/times | `hallucinated_date` | WARNING |
| Prohibited phrases | `prohibited_phrase` | WARNING |
| Markdown artifacts | `markdown_artifact` | WARNING |
| Excessive blank lines | `excessive_newlines` | WARNING |
| Repeated sentences | `repetition` | WARNING |
| Missing call-to-action | `missing_cta` | WARNING |
| Unsupported claims | `unsupported_claim` | WARNING |
| Unsolicited promises | `unsolicited_promise` | WARNING |
| HTML/script injection | `html_injection` | ERROR |

Validation returns structured `ValidationIssue` objects. Never silently modifies replies.

#### Validation Lifecycle

1. Each draft is validated after generation
2. Issues are collected into `GenerationResult.validation_results`
3. Draft content is never modified by validation
4. Frontend displays issues inline with severity-colored badges

### Generation Pipeline (`generation_pipeline.py`)

Orchestrates the full generation flow with observability:

```
Generation Requested
  ↓
Context Built          ← timing: context_built_{style}
  ↓
Template Selected
  ↓
Style Applied
  ↓
Prompt Built           ← timing: prompt_built_{style}
  ↓
Provider Selected
  ↓
Generation Started     ← timing: generation_{style}
  ↓  (with retries)
Generation Completed
  ↓
Validation Completed   ← timing: validation_{style}
  ↓
Generation Returned    ← timing: total
```

#### Variant Generation

Variants differ by more than temperature:
- Different temperature per variant: 0.5, 0.6, 0.8, 0.9
- Different structural instructions per variant (concise, question-driven, value-first, story-driven)
- Same reasoning and context preserved across variants

## Generation Metadata

Every generated reply exposes:

| Field | Description |
|-------|-------------|
| `generation_id` | UUID hex (12 chars) |
| `provider` | Provider name (e.g. "openai") |
| `model` | Model identifier from API response |
| `latency_ms` | Total generation time in milliseconds |
| `token_usage` | Input/output token counts |
| `generated_at` | ISO 8601 timestamp |
| `template_used` | Template name |
| `style_used` | Style name |
| `prompt_builder_version` | Version string |
| `template_library_version` | Version string |
| `style_engine_version` | Version string |
| `context_builder_version` | Version string |
| `pipeline_version` | Version string |
| `reasoning_version` | Version from reasoning result |

## Security

- API keys: validated by presence check in `validate_connection()`, never logged
- Prompts: never contain secrets, API keys only in `_headers()` methods
- Prompt injection: HTML/script content filtered by validation layer before generation
- Internal reasoning: never exposed to recipients — stays in metadata and context
- Provider errors: sanitized — `get_provider()` returns `None` instead of raising exceptions
- Malformed responses: providers return empty `ProviderResponse` on failure, pipeline handles gracefully

## Frontend Integration

The `ReplyDraftPanel` component sits in the conversation detail sidebar.

Features:
- **Style selector** — toggle one or more styles
- **Variant count** — 1, 2, or 3 variants per style
- **Generate** — triggers the API
- **Draft display** — read-only preview with variant tabs
- **Edit** — human editing with original AI draft preserved
- **Restore original** — revert to AI-generated version at any time
- **Edited indicator** — amber banner shows when draft differs from original
- **Copy** — clipboard
- **Refresh** — cycle through variants and styles
- **Approve** — disabled (future phase)
- **Variant counter** — navigate variants with prev/next buttons
- **Issues** — validation warnings displayed inline
- **Generation info** — expandable details (generation ID, provider, model, template, all versions, latency)

## Versioning Strategy

Each component has an independent version string:

- `PROMPT_BUILDER_VERSION` — bump when prompt construction logic changes
- `TEMPLATE_LIBRARY_VERSION` — bump when template content changes
- `STYLE_ENGINE_VERSION` — bump when style instructions change
- `CONTEXT_BUILDER_VERSION` — bump when context normalization changes
- `PIPELINE_VERSION` — bump when pipeline orchestration changes
- `reasoning_version` — propagated from reasoning result

Future prompt improvements can be traced to which version of each component was active.

## Extension Points

| Feature | How to add |
|---------|-----------|
| New LLM provider | Implement `LLMProvider`, add to `_auto_register()` |
| New style | Add to `GenerationStyle` enum + `STYLE_INSTRUCTIONS` |
| New template | Call `register_template()` with name + instructions |
| New validation check | Add `_check_*` function to `validation.py`, call in `validate_draft()` |
| Autonomous sending | Consume `ReplyDraft.content` in outbound pipeline |
| A/B testing | Track `variant_index` per draft |
| Multilingual | Add language parameter to style engine |
| RAG | Add retrieval results to `GenerationContext` |
| Custom prompt packs | Hot-reload `TEMPLATE_REGISTRY` from config |

## Technical Debt & Future Improvements

### 1. Placeholder Replacement (`_fill_template`)
Current: `template.replace(key, value)` — works but doesn't scale.
Future: Migrate to `string.Formatter` (SafeFormatter), Jinja2, or a typed template engine. String replacement becomes brittle as templates grow.

### 2. Timing Precision
Status: `time.perf_counter()` in use (resolved in 3.6.2).

### 3. Version Constants
Status: Semantic `1.0.0` format in use (resolved in 3.6.2).

### 4. Conversation Stage Ownership
Current: `conversation_stage` read from `reasoning.stage`.
Architectural concern: Conversation stage (New Lead → Contacted → Replied → Qualified → Demo Booked) is a property of Conversation Intelligence, not Reasoning. Reasoning consumes it but shouldn't define it. Move stage tracking to intelligence layer when the boundary is revisited.

### 5. HTML Normalization
Current: Regex-based detection for `<script>`, `<iframe>`, `javascript:`.
Concern: Emails are messy. Regex misses edge cases. Future phase should add proper HTML normalization before prompt construction (e.g., strip tags, decode entities, sanitize) rather than relying on post-generation regex detection.

## Constraints

- Never makes reasoning decisions
- Never modifies Conversation Intelligence
- Never modifies the Reasoning Engine
- Never auto-sends replies
- Never bypasses policy evaluation
- Never hardcodes provider-specific prompts into the engine
- Never couples generation to a specific communication channel
- Never modifies the design system
