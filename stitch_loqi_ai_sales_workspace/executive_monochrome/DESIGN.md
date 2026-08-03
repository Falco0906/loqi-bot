---
name: Executive Monochrome
colors:
  surface: '#141313'
  surface-dim: '#141313'
  surface-bright: '#3a3939'
  surface-container-lowest: '#0f0e0e'
  surface-container-low: '#1c1b1b'
  surface-container: '#201f1f'
  surface-container-high: '#2b2a2a'
  surface-container-highest: '#363434'
  on-surface: '#e6e2e1'
  on-surface-variant: '#ccc4c9'
  inverse-surface: '#e6e2e1'
  inverse-on-surface: '#313030'
  outline: '#958f93'
  outline-variant: '#4a4549'
  surface-tint: '#cac5c6'
  primary: '#ffffff'
  on-primary: '#313030'
  primary-container: '#e6e1e1'
  on-primary-container: '#666464'
  inverse-primary: '#605e5e'
  secondary: '#c9c6c5'
  on-secondary: '#313030'
  secondary-container: '#484646'
  on-secondary-container: '#b8b4b3'
  tertiary: '#ffffff'
  on-tertiary: '#32302f'
  tertiary-container: '#e6e1e0'
  on-tertiary-container: '#666462'
  error: '#ffb4ab'
  on-error: '#690005'
  error-container: '#93000a'
  on-error-container: '#ffdad6'
  primary-fixed: '#e6e1e1'
  primary-fixed-dim: '#cac5c6'
  on-primary-fixed: '#1c1b1c'
  on-primary-fixed-variant: '#484647'
  secondary-fixed: '#e6e2e0'
  secondary-fixed-dim: '#c9c6c5'
  on-secondary-fixed: '#1c1b1b'
  on-secondary-fixed-variant: '#484646'
  tertiary-fixed: '#e6e1e0'
  tertiary-fixed-dim: '#cac6c4'
  on-tertiary-fixed: '#1c1b1a'
  on-tertiary-fixed-variant: '#484645'
  background: '#141313'
  on-background: '#e6e2e1'
  surface-variant: '#363434'
typography:
  display-lg:
    fontFamily: Libre Caslon Text
    fontSize: 56px
    fontWeight: '400'
    lineHeight: 64px
    letterSpacing: -0.02em
  headline-lg:
    fontFamily: Libre Caslon Text
    fontSize: 32px
    fontWeight: '400'
    lineHeight: 40px
  headline-lg-mobile:
    fontFamily: Libre Caslon Text
    fontSize: 28px
    fontWeight: '400'
    lineHeight: 36px
  title-md:
    fontFamily: Libre Caslon Text
    fontSize: 20px
    fontWeight: '600'
    lineHeight: 28px
  body-lg:
    fontFamily: Libre Caslon Text
    fontSize: 18px
    fontWeight: '400'
    lineHeight: 28px
  body-md:
    fontFamily: Libre Caslon Text
    fontSize: 16px
    fontWeight: '400'
    lineHeight: 24px
  label-sm:
    fontFamily: Inter
    fontSize: 12px
    fontWeight: '500'
    lineHeight: 16px
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
  xs: 4px
  sm: 12px
  md: 24px
  lg: 48px
  xl: 80px
  gutter: 24px
  margin-mobile: 16px
  margin-desktop: 64px
---

## Brand & Style
The design system embodies a high-contrast, executive aesthetic tailored for elite productivity and decision-making environments. It leverages a "Void-Chamber" philosophy: a deep, immersive dark workspace where content and typography act as the primary light sources. 

The style is a fusion of **Minimalism** and **High-Contrast Modern**, utilizing stark tonal shifts rather than color to establish hierarchy. The emotional response is one of absolute focus, authority, and refined clarity. Interaction is characterized by crisp transitions and precise geometry, ensuring the interface feels like a high-end physical tool crafted from obsidian and silver.

## Colors
The palette is strictly monochromatic, optimized for high legibility in low-light environments. 

- **Primary & On-Surface (#FDF8F8):** Used for primary text, active icons, and high-emphasis action buttons. This off-white reduces eye strain compared to pure #FFFFFF while maintaining maximum contrast against the dark background.
- **Surface-Dim (#121212):** The foundation layer, used for global backgrounds to create depth behind floating elements.
- **Surface (#1A1A1A):** The standard layer for content areas and primary containers.
- **Surface-Bright (#242424):** Used for hover states, elevated cards, and highlighted sections to provide subtle visual separation without relying on borders.
- **On-Surface-Variant (#DDD9D8):** Reserved for secondary metadata, placeholder text, and inactive iconography.

## Typography
This design system utilizes **Libre Caslon Text** for both display and body roles to convey a sense of editorial authority and timelessness. The serif's high contrast is emphasized by the dark mode setting, making every character feel etched into the screen.

- **Headlines:** Use generous leading to maintain a spacious, premium feel. 
- **Body Text:** Scaled for readability; use `body-lg` for primary narrative content.
- **Labels:** System labels and small UI markers switch to **Inter** (Utility Font) to provide a clean, functional counterpoint to the decorative serif, ensuring clarity at small scales.

## Layout & Spacing
The layout follows a **Fixed Grid** philosophy on desktop to maintain an executive, composed look, transitioning to a fluid model on mobile devices.

- **Desktop:** 12-column grid, 1200px max-width, 24px gutters. Content is centered with wide 64px margins to create a "focus letter" effect.
- **Mobile:** Single column with 16px side margins. 
- **Rhythm:** All spacing must be a multiple of 8px. Use `lg` (48px) spacing between major sections to maintain the minimalist breathability of the brand.

## Elevation & Depth
Depth is achieved through **Tonal Layering** rather than traditional drop shadows. In this high-contrast dark environment, shadows are replaced by subtle value shifts:

- **Level 0 (Floor):** `surface-dim` (#121212) for the canvas.
- **Level 1 (Card):** `surface` (#1A1A1A) with a 1px solid border of `surface-bright` (#242424) to define edges.
- **Level 2 (Overlay/Menu):** `surface-bright` (#242424) with a sharp, high-contrast 1px border using `on-surface-variant` at 20% opacity.
- **Interactive States:** Hovering over an element should shift its background from `surface` to `surface-bright` instantaneously, providing tactile feedback through value change.

## Shapes
The design system employs a **Rounded (8px)** corner strategy to soften the high-contrast aesthetic, making the professional environment feel sophisticated rather than aggressive.

- **Standard Elements:** Buttons, input fields, and small cards use the `0.5rem` (8px) base radius.
- **Large Containers:** Main content areas use `1.5rem` (24px) to create a distinct structural framing.
- **Icons:** Should be contained within circular or 8px rounded bounding boxes for consistency.

## Components
Consistent component execution is vital for the executive feel:

- **Buttons:** 
  - *Primary:* Solid `on-surface` (#FDF8F8) background with `surface-dim` (#121212) text.
  - *Secondary:* `surface-bright` (#242424) background with `on-surface` text.
- **Input Fields:** Background set to `surface-dim`, with a 1px border of `surface-bright`. On focus, the border becomes `on-surface` (#FDF8F8). Text is always `on-surface`.
- **Cards:** Use `surface` background. For high-priority cards, use a 1px top-border of `primary` to denote importance.
- **Lists:** Separated by 1px rules of `surface-bright`. Use `body-md` for list items and `label-sm` for category headers.
- **Navigation:** Top-tier navigation uses `label-sm` (Inter) for precision. Active links are underlined with a 2px stroke of `primary`.
- **Selection (Checkboxes/Radios):** When active, these are filled with `primary` and use `surface-dim` for the checkmark/indicator to maintain the inverted high-contrast look.