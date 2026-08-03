---
name: Obsidian Command
colors:
  surface: '#13121b'
  surface-dim: '#13121b'
  surface-bright: '#393842'
  surface-container-lowest: '#0e0d16'
  surface-container-low: '#1b1b24'
  surface-container: '#1f1f28'
  surface-container-high: '#2a2933'
  surface-container-highest: '#35343e'
  on-surface: '#e4e1ee'
  on-surface-variant: '#c7c4d8'
  inverse-surface: '#e4e1ee'
  inverse-on-surface: '#302f39'
  outline: '#918fa1'
  outline-variant: '#464555'
  surface-tint: '#c4c0ff'
  primary: '#c4c0ff'
  on-primary: '#2000a4'
  primary-container: '#8781ff'
  on-primary-container: '#1b0091'
  inverse-primary: '#4f44e2'
  secondary: '#4edea3'
  on-secondary: '#003824'
  secondary-container: '#00a572'
  on-secondary-container: '#00311f'
  tertiary: '#ffb95f'
  on-tertiary: '#472a00'
  tertiary-container: '#ca8100'
  on-tertiary-container: '#3e2400'
  error: '#ffb4ab'
  on-error: '#690005'
  error-container: '#93000a'
  on-error-container: '#ffdad6'
  primary-fixed: '#e3dfff'
  primary-fixed-dim: '#c4c0ff'
  on-primary-fixed: '#100069'
  on-primary-fixed-variant: '#3622ca'
  secondary-fixed: '#6ffbbe'
  secondary-fixed-dim: '#4edea3'
  on-secondary-fixed: '#002113'
  on-secondary-fixed-variant: '#005236'
  tertiary-fixed: '#ffddb8'
  tertiary-fixed-dim: '#ffb95f'
  on-tertiary-fixed: '#2a1700'
  on-tertiary-fixed-variant: '#653e00'
  background: '#13121b'
  on-background: '#e4e1ee'
  surface-variant: '#35343e'
typography:
  headline-xl:
    fontFamily: Geist
    fontSize: 40px
    fontWeight: '600'
    lineHeight: '1.1'
    letterSpacing: -0.04em
  headline-lg:
    fontFamily: Geist
    fontSize: 32px
    fontWeight: '600'
    lineHeight: '1.2'
    letterSpacing: -0.03em
  headline-md:
    fontFamily: Geist
    fontSize: 24px
    fontWeight: '500'
    lineHeight: '1.3'
    letterSpacing: -0.02em
  body-lg:
    fontFamily: Inter
    fontSize: 16px
    fontWeight: '400'
    lineHeight: '1.6'
    letterSpacing: '0'
  body-md:
    fontFamily: Inter
    fontSize: 14px
    fontWeight: '400'
    lineHeight: '1.5'
    letterSpacing: '0'
  label-md:
    fontFamily: Geist
    fontSize: 12px
    fontWeight: '500'
    lineHeight: '1'
    letterSpacing: 0.05em
  mono-sm:
    fontFamily: Geist
    fontSize: 12px
    fontWeight: '400'
    lineHeight: '1.4'
    letterSpacing: '0'
rounded:
  sm: 0.25rem
  DEFAULT: 0.5rem
  md: 0.75rem
  lg: 1rem
  xl: 1.5rem
  full: 9999px
spacing:
  unit: 4px
  container-padding: 24px
  gutter: 16px
  stack-sm: 8px
  stack-md: 16px
  stack-lg: 32px
---

## Brand & Style
The design system is engineered to feel like a high-performance operating system for outbound sales. It prioritizes speed, clarity, and deep focus by utilizing an **Obsidian Minimalism** aesthetic—blending the structural rigor of developer tools with the sophisticated finish of premium consumer software.

The emotional response should be one of "effortless control." By leveraging high-fidelity glassmorphism and subtle luminosity, the UI avoids the heaviness of traditional enterprise software. The "Command Center" philosophy dictates that every element has a clear purpose, utilizing generous whitespace and distinct visual hierarchies to manage complex sales data without cognitive overload.

## Colors
The palette is built on a foundation of deep, ink-like blacks to maximize contrast and reduce eye strain during long-form prospecting.

- **Foundational Neutrals:** The base layer uses `#09090B` (Obsidian), while floating panels and workspace containers use `#0B0B0F` (Charcoal) to create depth.
- **Primary Accent (Premium Purple):** Used exclusively for high-intent actions, primary buttons, and active AI processing states.
- **Semantic Accents:** 
  - **Emerald Green:** Reserved for successful conversions, positive sentiment analysis, and "Live" status indicators.
  - **Amber:** Used for high-value opportunities, urgent follow-ups, and "Warm" lead indicators.
- **Luminosity:** Use a 5% opacity tint of the Primary Accent for subtle glows behind AI-driven components to indicate "intelligence" without disrupting the dark aesthetic.

## Typography
The typography system balances the technical precision of **Geist** for UI controls and headings with the supreme readability of **Inter** for long-form communication and CRM data.

- **Headlines:** Utilize tight tracking (`-0.02em` to `-0.04em`) to create a dense, "locked-in" editorial feel.
- **Body Text:** Use generous line heights (`1.5` to `1.6`) to ensure sales scripts and email drafts are highly legible.
- **Labels:** Use Geist in all-caps with increased letter spacing for small metadata, ensuring a structured, "instrument-panel" look.
- **Scale:** On mobile devices, `headline-xl` should scale down to `28px` to maintain visual balance within the narrower viewport.

## Layout & Spacing
This design system utilizes a **Fixed-Fluid Hybrid** layout. The primary sidebar and auxiliary utility panels (AI assistants, lead details) are fixed-width to maintain muscle memory, while the central "Stage" is fluid to accommodate varying data densities.

- **Grid:** A 12-column grid is used for the central workspace.
- **Rhythm:** All spacing is based on a 4px baseline. Use `16px` (stack-md) as the default internal padding for cards and containers.
- **Breakpoints:**
  - **Desktop (1440px+):** Full three-pane layout (Navigation | Stage | Context).
  - **Tablet (768px - 1439px):** Context panel becomes a collapsible drawer.
  - **Mobile (<767px):** Single-pane "Stage" view with a bottom navigation bar for core sales actions.

## Elevation & Depth
Depth is achieved through **Tonal Layering** and **Glassmorphism** rather than traditional heavy shadows.

1.  **Base (Level 0):** `#09090B`. The background "canvas."
2.  **Surface (Level 1):** `#0B0B0F`. Main cards and work areas. Subtle `1px` border using `#1F1F23`.
3.  **Floating (Level 2):** Semi-transparent surfaces (80% opacity) with a `20px` backdrop blur. Used for modals, dropdowns, and AI chat overlays.
4.  **AI State:** For active AI processing or "Smart" suggestions, apply a `0px 0px 20px` outer glow using the Primary Accent color at 15% opacity to create a "pulsing" depth effect.

## Shapes
The shape language is sophisticated and approachable, utilizing a "Large-Soft" corner logic. 

- **Primary Containers:** Cards, modals, and main workspace areas use a `12px` (rounded-lg) corner radius.
- **Interactive Elements:** Buttons and input fields use an `8px` radius to feel precise.
- **AI Components:** Elements that are AI-generated or "smart" use a `16px` (rounded-xl) radius to visually distinguish them from standard system data.

## Components
- **Buttons:** 
  - *Primary:* Solid `#6C63FF` with white text. High-gloss finish.
  - *Ghost:* No fill, `#1F1F23` border. Subtle hover state with 5% white overlay.
- **Input Fields:** Darker than the surface (`#050507`), `1px` border. On focus, the border transitions to the Primary Accent with a subtle `2px` outer glow.
- **Cards:** Background `#0B0B0F`, `1px` border `#1F1F23`. No shadows, unless floating.
- **AI Chips:** Small, pill-shaped badges with a gradient border (Primary to Secondary) to indicate AI-driven insights like "High Intent" or "Optimal Time to Send."
- **Lists:** Data rows should have a `1px` bottom border. Hovering over a row should trigger a subtle background shift to `#14141A`.
- **Command Bar:** A floating, glassmorphic input (centered) with a `24px` backdrop blur, mimicking the "Command + K" pattern for rapid navigation.