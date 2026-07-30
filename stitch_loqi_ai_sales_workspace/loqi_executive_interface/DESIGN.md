---
name: Loqi Executive Interface
colors:
  surface: '#fdf8f8'
  surface-dim: '#ddd9d8'
  surface-bright: '#fdf8f8'
  surface-container-lowest: '#ffffff'
  surface-container-low: '#f7f3f2'
  surface-container: '#f1edec'
  surface-container-high: '#ebe7e6'
  surface-container-highest: '#e5e2e1'
  on-surface: '#1c1b1b'
  on-surface-variant: '#444748'
  inverse-surface: '#313030'
  inverse-on-surface: '#f4f0ef'
  outline: '#747878'
  outline-variant: '#c4c7c7'
  surface-tint: '#5f5e5e'
  primary: '#000000'
  on-primary: '#ffffff'
  primary-container: '#1c1b1b'
  on-primary-container: '#858383'
  inverse-primary: '#c8c6c5'
  secondary: '#53625c'
  on-secondary: '#ffffff'
  secondary-container: '#d3e3dc'
  on-secondary-container: '#576660'
  tertiary: '#000000'
  on-tertiary: '#ffffff'
  tertiary-container: '#1c1b1a'
  on-tertiary-container: '#868382'
  error: '#ba1a1a'
  on-error: '#ffffff'
  error-container: '#ffdad6'
  on-error-container: '#93000a'
  primary-fixed: '#e5e2e1'
  primary-fixed-dim: '#c8c6c5'
  on-primary-fixed: '#1c1b1b'
  on-primary-fixed-variant: '#474746'
  secondary-fixed: '#d6e6df'
  secondary-fixed-dim: '#bacac3'
  on-secondary-fixed: '#111e1a'
  on-secondary-fixed-variant: '#3c4a44'
  tertiary-fixed: '#e6e2df'
  tertiary-fixed-dim: '#cac6c4'
  on-tertiary-fixed: '#1c1b1a'
  on-tertiary-fixed-variant: '#484645'
  background: '#fdf8f8'
  on-background: '#1c1b1b'
  surface-variant: '#e5e2e1'
typography:
  display-xl:
    fontFamily: Libre Caslon Text
    fontSize: 48px
    fontWeight: '400'
    lineHeight: '1.1'
    letterSpacing: -0.02em
  display-xl-mobile:
    fontFamily: Libre Caslon Text
    fontSize: 36px
    fontWeight: '400'
    lineHeight: '1.2'
  headline-lg:
    fontFamily: Libre Caslon Text
    fontSize: 32px
    fontWeight: '400'
    lineHeight: '1.3'
  headline-md:
    fontFamily: Libre Caslon Text
    fontSize: 24px
    fontWeight: '400'
    lineHeight: '1.4'
  body-lg:
    fontFamily: Inter
    fontSize: 18px
    fontWeight: '400'
    lineHeight: '1.6'
  body-md:
    fontFamily: Inter
    fontSize: 16px
    fontWeight: '400'
    lineHeight: '1.5'
  label-sm:
    fontFamily: Geist
    fontSize: 13px
    fontWeight: '500'
    lineHeight: '1.2'
    letterSpacing: 0.02em
  label-xs:
    fontFamily: Geist
    fontSize: 11px
    fontWeight: '600'
    lineHeight: '1.2'
    letterSpacing: 0.05em
rounded:
  sm: 0.25rem
  DEFAULT: 0.5rem
  md: 0.75rem
  lg: 1rem
  xl: 1.5rem
  full: 9999px
spacing:
  base: 8px
  container-max: 1200px
  reading-width: 720px
  gutter: 24px
  section-gap: 64px
  element-gap: 16px
---

## Brand & Style

The design system is anchored in the concept of "The Digital Consiglieri." It moves away from the frenetic energy of typical productivity tools toward a state of focused composure. The aesthetic is a synthesis of high-end editorial layouts and precision software engineering, drawing from the clarity of modern productivity pioneers.

**Design Style: Editorial Minimalism**
The system employs a "content-first" hierarchy where the AI's output is treated with the same reverence as a printed broadsheet. It prioritizes:
- **Quiet Authority:** Avoiding decorative flourishes in favor of intentional whitespace and structural integrity.
- **Precision:** Fine lines and microscopic attention to alignment.
- **Tactile Softness:** Subverting the "coldness" of tech with warm grays and subtle depth that mimics premium paper stock and milled aluminum.

## Colors

The palette is monochromatic and grounded, designed to reduce cognitive load and emphasize content importance through value rather than hue.

- **Foundational Neutrals:** The background uses a slightly warm "Paper White" (`#F9F9F8`) to reduce eye strain compared to pure hex white. 
- **The Ink:** Deep Charcoal (`#1A1A1A`) serves as the primary color for all high-emphasis text and iconography, ensuring peak legibility.
- **The Accent:** Forest Green (`#2D3B36`) is used with extreme restraint. It is reserved for active states, primary actions, or "Success" indicators, acting as a subtle nod to traditional executive stationery.
- **Tertiary Tones:** Soft grays are used exclusively for structural elements like dividers and secondary metadata.

## Typography

This system uses a tiered typographic strategy to balance "The Briefing" (Serif) with "The Tool" (Sans-Serif).

1.  **The Briefing (Libre Caslon Text):** Used for primary headlines and executive summaries. It evokes the feeling of a printed report. It should always have generous top margin to let headers breathe.
2.  **The Narrative (Inter):** Used for all long-form body copy. Inter’s tall x-height ensures clarity in complex AI responses and task descriptions.
3.  **The Utility (Geist):** A technical sans-serif used for labels, buttons, and data points. Its monospace-like tracking in "Geist" gives the UI a feeling of precision and "live" data.

**Scaling Rule:** Maintain a "comfortable reading width" (max-width: 720px) for all body text to ensure optimal scanning speeds.

## Layout & Spacing

The layout philosophy follows a **Fixed-Fluid Hybrid** model. While the overall container can expand, the content core is strictly bound to a "Reading Column."

- **Desktop:** A centered 12-column grid. The main "Briefing" content occupies the central 8 columns (720px), while supplementary meta-information or navigation sits in the outer margins.
- **Rhythm:** Spacing follows an 8px baseline. Use `section-gap` (64px) to separate distinct AI modules and `element-gap` (16px) for internal card padding.
- **Margins:** Large horizontal safe areas (minimum 40px on desktop) are mandatory to maintain the "premium" feel; content should never feel "trapped" by the screen edges.

## Elevation & Depth

Depth in this design system is communicated through **Tonal Layering** rather than heavy shadows.

- **The Canvas:** The base background is the lowest layer (`#F9F9F8`).
- **The Sheet:** Floating modules and cards use a pure white surface (`#FFFFFF`).
- **Shadows:** Use "Ambient Shadows"—extremely soft, low-opacity (2-4%) blurs with a slight vertical offset (Y: 4px, Blur: 12px). They should be nearly invisible, felt rather than seen.
- **Glassmorphism:** Reserved exclusively for global navigation bars and sticky headers. Use a `12px` backdrop blur with a `0.5` opacity white fill to allow content to peak through as the user scrolls.

## Shapes

The shape language is "Tailored." It avoids the hyper-roundness of casual apps and the sharp corners of legacy enterprise software.

- **Standard Elements:** Buttons and input fields use an `8px` (0.5rem) radius.
- **Containers:** Large cards and modular sections use a `16px` (1rem) radius.
- **Icons:** Use a consistent 1.5px stroke weight. Icons should be enclosed in "soft squares" (8px roundedness) when used as primary navigational triggers.

## Components

### Buttons
- **Primary:** Solid `#1A1A1A` with white text. No gradient. High-contrast and immediate.
- **Secondary:** Transparent background with a subtle `1px` border in `#E2E2E0`.
- **Tertiary:** Text-only with an underline that appears on hover.

### Cards & Containers
Cards should have no visible border. Use the "Ambient Shadow" defined in Elevation. This creates a "Paper on Table" effect where hierarchy is defined by light and shadow rather than strokes.

### Input Fields
Inputs are minimalist. A simple bottom border (`1px`) that transitions to a full-frame soft-gray border on focus. Labels should use `label-xs` (Geist) and sit 8px above the field.

### Chips & Tags
Use a "Pill" shape (32px radius) with a light gray background (`#F1F1EF`) and `label-sm` typography. These are for categorizing tasks or status (e.g., "High Priority," "In Review").

### The "Briefing" List
A custom list component for AI summaries. Items are separated by a `0.5px` hairline divider. Each item features a `libreCaslonText` sub-header and `inter` body text. This is the heart of the "Chief of Staff" experience.