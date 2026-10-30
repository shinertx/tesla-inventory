# Design System: Carvana-Style Tesla Marketplace
**Project ID:** scratch/tesla_site_dist

## 1. Visual Theme & Atmosphere
- **Atmosphere Philosophy**: Architectural, clear, and trust-inducing digital automotive marketplace.
- **Synthesis**: Merges Carvana digital retail clarity with aerospace-grade Tesla telemetry.
- **Visual Tone**: Crisp light canvas, high-contrast navy typography, precise telemetry data, and clean photo stages.
- **The Core UX Formula**: Enforces "1 Big Number -> Visual Product Cards -> 1 Action".
  - **1 Big Number First**: Headlines display verified inventory proof ("12,757 Verified US Teslas", "$3,000+ Under Market").
  - **Visual Product Cards**: Pure white cards feature 16:10 vehicle photography, verified hardware badges, and split cash/monthly pricing.
  - **1 Action**: Primary buttons demand explicit verb + noun commitment ("Lock In VIN", "Reserve for $250").
- **Un-Gated Daily Research Workbench**:
  - Implements the "Come for the Tool, Stay for the Network" habit loop.
  - Operates with zero login wall or authentication gate before value delivery.
  - Delivers sub-50ms client-side filter and calculation feedback.
  - Stores investment via `localStorage` persistence for saved VINs, reservations, and custom search configurations.

## 2. Color Palette & Roles
The design system enforces a strict navy-tinted ink scale. Pure grays (Tailwind `gray-*`, `slate-*`, `zinc-*`, `#666`, `#999`) are strictly forbidden.

### 2.1 CSS Custom Properties
```css
:root {
  /* Canvas & Surface Tokens */
  --paper: #F4F8FC;                 /* Canvas background */
  --paper-2: #EBF2FA;               /* Inset fills and active pill backgrounds */
  --brand-white: #FFFFFF;           /* Card and modal surfaces */
  --line: #D8E3F2;                  /* Structural borders and card outlines */
  --line-2: #E6EEF8;                /* Subtle internal dividers */

  /* Carvana Brand Anchors */
  --cv-navy: #002855;               /* Carvana primary navy brand anchor */
  --cv-dark: #001635;               /* Deep navy ink for headings and dark surfaces */
  --cv-cyan: #00AED9;               /* Carvana electric cyan action accent */
  --brand-blue: #1DA4FF;            /* Electric accent for focus rings and mono eyebrows */
  --brand-light-blue: #DCF1FF;       /* Soft blue fill for dark surfaces and tags */

  /* Semantic Status & Accents */
  --emerald: #047857;               /* Great Deal text and free shipping (WCAG AA: 5.21:1 on mint, 5.48:1 on white) */
  --emerald-bg: #ECFDF5;            /* Great Deal badge fill */
  --emerald-border: #A7F3D0;        /* Great Deal badge border */
  --brand-red: #C2410C;             /* Dealer misbook alert and urgent warnings (WCAG AA: 4.70:1 on coral, 5.18:1 on white) */
  --brand-red-bg: #FFF1ED;          /* Misbook tag fill */
  --brand-red-border: #FFD4C7;      /* Misbook tag border */
  --saved-rose: #E11D48;            /* Saved vehicle heart active fill */

  /* Navy-Tinted Ink Scale (Zero Pure Grays) */
  --ink: #0E1A2F;                   /* Primary body copy (16:1 contrast on white) */
  --ink-2: #2A3654;                 /* Secondary headings and card metadata */
  --ink-3: #5B6786;                 /* Captions, subtitles, and form labels */
  --ink-4: #8B95B0;                 /* Placeholder text and disabled elements */
  --ink-5: #B8C1D4;                 /* Disabled borders and subtle indicators */

  /* Font Families */
  --font-sans: 'Figtree', system-ui, -apple-system, sans-serif;
  --font-mono: 'JetBrains Mono', monospace;

  /* Typography Scale Tokens (Table 3.3) */
  --text-hero-num: 800 52px/1.05 'Figtree', sans-serif;
  --text-display: 800 36px/1.12 'Figtree', sans-serif;
  --text-h1: 700 24px/1.22 'Figtree', sans-serif;
  --text-h2: 600 19px/1.26 'Figtree', sans-serif;
  --text-h3: 600 16px/1.32 'Figtree', sans-serif;
  --text-body: 400 14px/1.45 'Figtree', sans-serif;
  --text-caption: 500 12px/1.35 'Figtree', sans-serif;
  --text-mono-eyebrow: 600 11px/1.2 'JetBrains Mono', monospace;
  --text-mono-num: 700 15px/1.2 'JetBrains Mono', monospace;

  /* Additional Typography Scale Tokens */
  --text-sm: 600 12px/1.40 'Figtree', sans-serif;
  --text-xs: 700 11px/1.20 'Figtree', sans-serif;
  --text-mono-vin: 600 13px/1.25 'JetBrains Mono', monospace;
}
```

### 2.2 Color Roles Table
| Color Role | Descriptive Name | Hex Code | Functional Role |
| :--- | :--- | :--- | :--- |
| **Primary Brand Anchor** | Carvana Deep Navy | `#002855` | Primary brand identity, header logo badge, active filter pills, primary buttons. |
| **Deep Ink Surface** | Dark Obsidian Navy | `#001635` | Major headlines, dark mode surfaces, high-contrast modal headers. |
| **Action Accent** | Energetic Cyan | `#00AED9` | Primary action buttons, active slider tracks, search icons, focus highlights. |
| **Electric Accent** | Electric Brand Blue | `#1DA4FF` | Interactive link hover, focus ring glow, live telemetry status dots. |
| **Soft Surface Tint** | Glacier Ice Blue | `#DCF1FF` | Subdued badge fills, dark mode secondary copy, selection highlights. |
| **Deal Success Accent** | Deal Emerald | `#047857` | Below-market Great Deal badges, confirmed shipping, positive deltas. |
| **Deal Success Fill** | Mint Wash | `#ECFDF5` | Background container fill for Great Deal status badges. |
| **Deal Success Border** | Pale Mint Outline | `#A7F3D0` | Border outline for Great Deal badges. |
| **Misbook Alert Accent** | High-Heat Coral Red | `#C2410C` | Dealer misbook badges, pricing error alerts, action-required tags. |
| **Misbook Alert Fill** | Coral Tint Wash | `#FFF1ED` | Background fill for dealer pricing error tags. |
| **Misbook Alert Border** | Soft Coral Outline | `#FFD4C7` | Border outline for dealer pricing error tags. |
| **Saved Item Accent** | Saved Rose | `#E11D48` | Filled state for active vehicle wishlist heart buttons. |
| **Canvas Background** | Clean Polar Paper | `#F4F8FC` | Global page viewport background canvas. |
| **Alt Surface Fills** | Inset Mist Paper | `#EBF2FA` | Secondary section breaks, payment block insets, inactive track fills. |
| **Card Surface** | Pure White | `#FFFFFF` | Vehicle cards, modal windows, search bar surface, dropdowns. |
| **Structural Border** | Navy-Tinted Line | `#D8E3F2` | Card perimeter borders, table dividers, input borders. |
| **Subtle Divider** | Faint Navy Hairline | `#E6EEF8` | Internal card dividers, footer separators, table row rules. |
| **Body Ink** | Deep Navy Ink | `#0E1A2F` | Main body paragraphs, table values, input text. |
| **Secondary Ink** | Slate Navy Ink | `#2A3654` | Card titles, subtitle values, secondary metadata. |
| **Muted Ink** | Steel Navy Ink | `#5B6786` | Field labels, mileage stats, timestamp notes. |
| **Faint Ink** | Faint Blue Mist | `#8B95B0` | Input placeholders, strikethrough MSRP values. |

## 3. Typography Rules
The typography system pairs geometric readability with fixed-width telemetry precision.

### 3.1 Font Families
- **Primary Interface Family**: `'Figtree', -apple-system, BlinkMacSystemFont, 'Segoe UI', system-ui, sans-serif`.
  - Applied to all UI headers, body text, buttons, form controls, and retail pricing.
- **Monospace Telemetry Family**: `'JetBrains Mono', 'SF Mono', Consolas, monospace`.
  - Applied strictly to 17-character VINs, motor codes, hardware cutoffs, and tabular financial figures.
  - Tabular figure feature flag required: `font-feature-settings: 'tnum' 1, 'zero' 1;`.

### 3.2 Font Weights
- `400` (Regular): Long-form descriptions, tooltips, table body copy.
- `500` (Medium): Subtitles, filter labels, vehicle mileage details.
- `600` (Semibold): Filter group headings, delivery notices, input values.
- `700` (Bold): Section headers, badge labels, secondary buttons, monetary totals.
- `800` (Extrabold): Hero metrics, card titles, cash price figures, primary CTA buttons.

### 3.3 Type Hierarchy Scale
| Token | Size | Line Height | Tracking | Weight | Font Family | Usage |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| `--text-hero-num` | `3.25rem` (52px) | `1.05` | `-0.03em` | 800 | Figtree | Large cash prices, hero statistics. |
| `--text-display` | `2.25rem` (36px) | `1.12` | `-0.025em` | 800 | Figtree | Display headers, major vehicle titles. |
| `--text-h1` | `1.50rem` (24px) | `1.22` | `-0.022em` | 700 | Figtree | Page view headers, modal titles. |
| `--text-h2` | `1.1875rem` (19px) | `1.26` | `-0.015em` | 600 | Figtree | Section titles, sidebar header. |
| `--text-h3` | `1.00rem` (16px) | `1.32` | `-0.012em` | 600 | Figtree | Vehicle card title, modal tabs. |
| `--text-body` | `0.875rem` (14px) | `1.45` | `0` | 400 | Figtree | Default body text, filter options. |
| `--text-sm` | `0.75rem` (12px) | `1.40` | `0` | 600 | Figtree | Footers, delivery notices, subtitles. |
| `--text-xs` | `0.6875rem` (11px) | `1.20` | `0.06em` | 700 | Figtree / Mono | Status tags, hardware chips. |
| `--text-caption` | `0.75rem` (12px) | `1.35` | `0` | 500 | Figtree | Secondary captions, timestamps, disclaimers. |
| `--text-mono-eyebrow` | `0.6875rem` (11px) | `1.20` | `0.06em` | 600 | JetBrains Mono | Telemetry badges, hardware chips. |
| `--text-mono-vin` | `0.8125rem` (13px) | `1.25` | `0.05em` | 600 | JetBrains Mono | 17-character VIN strings, motor codes. |
| `--text-mono-num` | `0.9375rem` (15px) | `1.20` | `0` | 700 | JetBrains Mono | Dynamic loan amortization, payment figures. |

### 3.4 Iconography Standard
- Emojis are strictly prohibited as primary UI icons.
- All interface icons use crisp stroke-based SVGs with `1.5px` or `2.0px` stroke widths.

## 4. Component Stylings

### 4.1 Base Primitives
* **Buttons:**
  - Geometry: `border-radius: var(--radius-btn)` (10px). Height `42px` standard, `34px` compact.
  - Primary CTA (`.btn-primary`): `background: var(--cv-navy); color: #FFFFFF; font-weight: 800;`. Hover scales to `#003B7A`.
  - Cyan Accent CTA (`.btn-cyan`): `background: var(--cv-cyan); color: var(--cv-dark); font-weight: 800;`. Hover scales to `background: var(--cv-navy); color: #FFFFFF;`.
  - Secondary Outline (`.btn-outline`): `background: #FFFFFF; border: 1.5px solid var(--line); color: var(--ink);`.
  - Focus Ring: `outline: none; box-shadow: 0 0 0 3px rgba(0, 174, 217, 0.25);`.
* **Cards / Containers:**
  - Geometry: `border-radius: var(--radius-card)` (14px).
  - Surface: `background: var(--brand-white); border: 1px solid var(--line);`.
  - Elevation: Resting `var(--shadow-e1)`, hovered `var(--shadow-e2)`.
* **Inputs & Forms:**
  - Geometry: `border-radius: var(--radius-sm)` (8px). Height `40px`.
  - Surface: `background: #FFFFFF; border: 1.5px solid var(--line); padding: 0 14px; font-size: 14px;`.
  - Focus State: `border-color: var(--cv-cyan); box-shadow: 0 0 0 3px rgba(0, 174, 217, 0.20); outline: none;`.
  - Range Sliders: Track height `6px`, background `var(--paper-2)`, thumb `18px` circle with `background: var(--cv-cyan)`.

### 4.2 Sticky Top Header
- **Layout & Structure**:
  - `position: sticky; top: 0; z-index: 50; width: 100%; height: 70px; background: #FFFFFF; border-bottom: 1px solid var(--line); box-shadow: 0 2px 6px rgba(0, 40, 85, 0.05);`.
  - Centered inner wrapper constrained to `1480px` max-width with `24px` horizontal padding.
- **Brand Logo**:
  - Deep navy badge (`background: var(--cv-navy); padding: 8px 14px; border-radius: 8px; color: #FFFFFF; font-weight: 800;`).
  - Text: `⚡ TESLA` with electric cyan accent `DIRECT`.
- **Live Search Bar with Autocomplete Dropdown**:
  - Input: Pill-shaped (`border-radius: 999px; height: 44px; padding-left: 42px; background: var(--paper); border: 1.5px solid var(--line);`).
  - Search SVG icon anchored left at `14px`.
  - Instant autocomplete popover anchored beneath input (`box-shadow: var(--shadow-e3); border-radius: 14px; background: #FFFFFF; z-index: 60;`).
  - Dropdown renders categorized sections: Model groups, Trim matches, exact VIN queries, and Dealer cities.
- **Delivery ZIP Selector**:
  - Pill button: `padding: 8px 14px; border-radius: 999px; background: var(--paper-2); border: 1px solid var(--line); color: var(--cv-navy); font-weight: 600; font-size: 13px;`.
  - Displays: `📍 Delivery to: 78701 (TX)`.
  - Click opens ZIP entry flyout; recalculates real road miles and shipping tier ($0 Texas, $490, $690, $890, $1,090).
- **Saved Vehicles Drawer Trigger**:
  - Pill button: `padding: 8px 14px; border-radius: 999px; background: #FFFFFF; border: 1px solid var(--line); font-weight: 700; font-size: 13px;`.
  - Icon: SVG heart. Active badge counter: `background: var(--cv-navy); color: #FFFFFF; border-radius: 999px; padding: 2px 7px; font-size: 11px;`.
- **7-Day Guarantee Trigger**:
  - Link badge: `color: var(--emerald); font-weight: 700; font-size: 13px; display: inline-flex; align-items: center; gap: 6px;`.
  - Shield SVG icon. Triggers Carvana Trust Pillars modal.
- **Showroom vs Architecture Desk Toggle**:
  - Segmented pill switch: `background: var(--paper-2); padding: 4px; border-radius: 999px; border: 1px solid var(--line);`.
  - Active tab: `background: var(--cv-navy); color: #FFFFFF; border-radius: 999px; font-weight: 700; box-shadow: 0 2px 6px rgba(0, 40, 85, 0.15);`.
  - Toggles between `#showroom-view` and `#architecture-desk-view`.

### 4.3 Left Facet Filter Rail
- **Sidebar Container**:
  - Width: `280px` desktop. `position: sticky; top: 90px; max-height: calc(100vh - 110px); overflow-y: auto;`.
  - Surface: `background: #FFFFFF; border: 1px solid var(--line); border-radius: 14px; padding: 20px; box-shadow: var(--shadow-e1);`.
- **Model Pills with Live Inventory Counts**:
  - Vertical pill stack: `All Tesla Models`, `Model Y`, `Model 3`, `Cybertruck`, `Model X`, `Model S`.
  - Resting Pill: `background: #FFFFFF; border: 1px solid var(--line); color: var(--ink-2); font-weight: 600; padding: 8px 12px; border-radius: 8px;`.
  - Active Pill: `background: var(--cv-navy); border-color: var(--cv-navy); color: #FFFFFF; font-weight: 700;`.
  - Dynamic count badge: Resting `background: var(--paper-2); color: var(--ink-2);`. Active `background: rgba(255, 255, 255, 0.22); color: #FFFFFF;`.
- **Cash vs Monthly Payment Toggle**:
  - Segmented control switching financial calculation mode across all listing cards.
  - Down Payment Slider: Interactive range `$0` to `$15,000` in `$500` steps. Shows real-time formatted label.
  - 4 Credit Score Profile Buttons:
    1. Excellent (`750+` · `5.9% APR`)
    2. Great (`700–749` · `6.9% APR`)
    3. Fair (`640–699` · `8.9% APR`)
    4. Building (`<640` · `12.9% APR`)
- **Dual Year & Mileage Inputs**:
  - Year selection dropdowns: Min Year (`2016`–`2026`) and Max Year (`2016`–`2026`).
  - Max Mileage options: `<20k mi`, `<40k mi`, `<60k mi`, `<80k mi`, `Any Mileage`.
- **Autopilot Hardware Filter**:
  - Radio pills: `All Hardware`, `HW4 / AI4 Only (5MP Cameras)`, `HW3 (FSD Capable)`.
- **Position-8 Motor / Drivetrain Filter**:
  - Checkboxes for NHTSA VIN Position-8 codes:
    - Dual Motor AWD (Codes: `B`, `D`, `2`, `4`)
    - Performance AWD (Codes: `E`, `F`, `6`)
    - Single Motor RWD (Codes: `A`, `C`, `1`, `5`)
    - Cyberbeast Tri-Motor (Code: `T`)
- **Shipping & Certification Toggles**:
  - Free Delivery switch (`$0 Local Shipping`).
  - Verified Franchise Partner switch (`150-Point Certified Guarantee`).

### 4.4 Vehicle Cards (Card Anatomy)
- **Card Geometry**:
  - Fixed flex column: `border-radius: 14px; border: 1px solid var(--line); background: #FFFFFF; box-shadow: var(--shadow-e1); overflow: hidden; cursor: pointer;`.
  - Hover Interaction: Lift `translateY(-3px)` with transition `240ms cubic-bezier(0.16, 1, 0.3, 1)` and shadow `var(--shadow-e2)`.
- **Photo Stage (16:10 Ratio)**:
  - Container: `position: relative; width: 100%; aspect-ratio: 16 / 10; background: linear-gradient(135deg, #EBF3FA, #D8E6F5); overflow: hidden;`.
  - Image: `width: 100%; height: 100%; object-fit: cover; transition: transform 0.28s ease;`. Hover scales image `1.035`.
  - Fallback: Crisp SVG silhouette placeholder if CDN photo fails.
- **Top Badge Stack (Photo Stage Overlay)**:
  - Position: `position: absolute; top: 12px; left: 12px; z-index: 10; display: flex; flex-direction: column; gap: 6px;`.
  - Great Deal Badge: `background: var(--emerald-bg); color: var(--emerald); border: 1px solid var(--emerald-border); font-size: 11px; font-weight: 700; padding: 4px 8px; border-radius: 6px;`. Text: `★ Great Deal · $X,XXX under market`.
  - HW4 Badge: `background: var(--cv-dark); color: #FFFFFF; border: 1px solid var(--cv-cyan); font-family: var(--font-mono); font-size: 10.5px; font-weight: 800; padding: 3px 7px; border-radius: 6px;`. Includes cyan live dot.
  - Dealer Misbook Alert: `background: var(--brand-red-bg); color: var(--brand-red); border: 1px solid var(--brand-red-border); font-size: 10.5px; font-weight: 800; padding: 3px 7px; border-radius: 6px; text-transform: uppercase;`. Text: `⚡ Misbook: Performance Motor`.
- **Circular Save Button**:
  - Position: `position: absolute; top: 12px; right: 12px; z-index: 10; width: 36px; height: 36px; border-radius: 999px;`.
  - Backdrop: `background: rgba(255, 255, 255, 0.90); backdrop-filter: blur(8px); border: 1px solid rgba(0, 40, 85, 0.10); box-shadow: 0 2px 6px rgba(0, 22, 53, 0.12);`.
  - Heart icon: Outline on unsaved, filled `--saved-rose` on saved.
- **Card Body**:
  - Padding: `16px 18px 14px 18px;`.
  - Telemetry Eyebrow: `font-family: var(--font-mono); font-size: 10.5px; font-weight: 700; text-transform: uppercase; color: var(--ink-3); letter-spacing: 0.05em;`. Example: `GIGA TEXAS · POSITION-8 "E"`.
  - Vehicle Title: `font-size: 1.10rem; font-weight: 800; color: var(--ink); line-height: 1.25; margin: 4px 0;`.
  - Trim & Mileage: `font-size: 0.88rem; color: var(--ink-2); font-weight: 500; margin-bottom: 14px;`.
- **Split Cash / Monthly Payment Block**:
  - Container: `display: flex; align-items: center; justify-content: space-between; padding: 12px 14px; background: var(--paper-2); border: 1px solid var(--line-2); border-radius: 8px; margin-top: auto;`.
  - Left Section (Cash): Large Cash figure (`font-size: 1.25rem; font-weight: 800; color: var(--cv-navy);`) and market comparison strike.
  - Divider: `width: 1px; height: 36px; background: var(--line); margin: 0 10px;`.
  - Right Section (Monthly): Monthly amortization figure (`font-size: 1.10rem; font-weight: 800; color: var(--cv-dark); font-family: var(--font-mono);`) and down-payment term note.
  - Payment Mode Toggle Reaction: Active mode elevates font size and color prominence.
- **Card Footer**:
  - Surface: `background: #FAFDFE; border-top: 1px solid var(--line-2); padding: 10px 18px; font-size: 0.78rem; font-weight: 600; color: var(--ink-2); display: flex; align-items: center; justify-content: space-between;`.
  - Delivery Note: Van SVG icon + delivery date estimate based on active ZIP.
  - Inspection Mark: `✓ 150-Pt Inspected · View Deal →`.

### 4.5 Multi-Tab VDP Modal
- **Dialog Geometry**:
  - Full-screen takeover: `max-width: 1100px; width: 95vw; max-height: 90vh; border-radius: 22px; background: #FFFFFF; border: 1px solid var(--line); box-shadow: var(--shadow-e4); overflow-y: auto;`.
  - Backdrop: `background: rgba(0, 22, 53, 0.65); backdrop-filter: blur(6px);`.
- **Tab 1: Build Sheet & NHTSA Telemetry**:
  - 17-Position NHTSA Part 565 Decode Visual Bar: Interactive 17-character segmented strip highlighting WMI, Model, Restraint, Motor, Check Digit, Model Year, Assembly Plant, and Serial Number.
  - Decoded Specifications Table:
    - Motor Horsepower & Configuration (true motor capability)
    - Battery Chemistry (NMC / NCA / LFP)
    - Assembly Factory (Fremont, CA / Giga Texas / Giga Berlin / Giga Shanghai)
    - Autopilot Computer Version (HW4 vs HW3)
    - 150-Point Certified Inspection Checklist and checklist item verifications.
- **Tab 2: 3-Step Online Checkout Wizard**:
  - Step 1: Financing and Trade-In estimator (interactive down payment slider, term selector, credit tier selection, trade-in VIN lookup).
  - Step 2: Delivery address, carrier dispatch scheduling, delivery date confirmation.
  - Step 3: $250 refundable VIN reservation hold. Persists reservation record to `localStorage.getItem('tesla_reservations')`.
  - Official Buyer's Order Deal Sheet: Downloadable and printable DMV-compliant contract layout with itemized tax, title, license, registration, delivery fees, and deposit credit.

### 4.6 Saved Vehicles Drawer
- **Drawer Geometry**:
  - Slideout panel: `width: 420px; max-width: 90vw; height: 100vh; position: fixed; top: 0; right: 0; z-index: 100; background: #FFFFFF; box-shadow: -8px 0 32px rgba(0, 22, 53, 0.18); display: flex; flex-direction: column;`.
- **Drawer Content**:
  - Header: Title `Saved Vehicles` with dynamic total count and close button.
  - Vehicle List: Saved vehicle row items with thumbnail, model/trim title, price, monthly payment, and quick remove button.
  - Portfolio Summary: Aggregate cash value, estimated combined monthly payment.
  - Primary Action CTA: `Proceed to Reservation` button.

### 4.7 7-Day Guarantee Modal
- **Trust Pillars Modal**:
  - Dialog window: `max-width: 680px; border-radius: 20px; padding: 32px; background: #FFFFFF; box-shadow: var(--shadow-e4);`.
  - 4 Pillars Grid:
    1. **7-Day Money-Back Guarantee**: Full refund within 7 calendar days or 400 miles.
    2. **150-Point Certified Inspection**: Comprehensive mechanical, battery, and telemetry inspection.
    3. **100-Day / 4,189-Mile Limited Warranty**: Bumper-to-bumper powertrain and hardware protection.
    4. **$0 Hidden Fees**: Transparent pricing guarantee; no dealer markup or prep fees.

## 5. Layout Principles

### 5.1 Spacing Scale (8-Step Grid)
The layout adheres strictly to an 8-step spacing system.

```css
:root {
  --space-1: 4px;      /* Micro gap, badge vertical padding */
  --space-2: 8px;      /* Icon gaps, badge padding, chip spacing */
  --space-3: 12px;     /* Button padding, card footer spacing */
  --space-4: 16px;     /* Card inner padding, table cell padding */
  --space-5: 20px;     /* Card body padding, sidebar inner padding */
  --space-6: 24px;     /* Modal header padding, section spacing */
  --space-7: 32px;     /* Card grid row gap, hero vertical padding */
  --space-8: 48px;     /* Macro section breathing room */
}
```

### 5.2 Geometry Tokens
```css
:root {
  --radius-xs: 6px;    /* Micro status tags */
  --radius-sm: 8px;    /* Form inputs, select dropdowns, badges */
  --radius-btn: 10px;  /* Interactive action buttons, toggle tabs */
  --radius-card: 14px; /* Vehicle cards, sidebar container */
  --radius-lg: 22px;   /* VDP dialog modal, drawer panels, contract sheets */
  --radius-pill: 999px;/* Search bar, quick filter chips, circular heart button */
}
```

### 5.3 Elevation & Navy-Tinted Shadows
All shadows are derived from Carvana Navy (`#002855`) and Dark Navy (`#001635`). Black or pure gray shadows are forbidden.

```css
:root {
  --shadow-e0: none;
  --shadow-e1: 0 2px 8px rgba(0, 40, 85, 0.07), 0 1px 2px rgba(0, 40, 85, 0.04);
  --shadow-e2: 0 12px 28px rgba(0, 40, 85, 0.14), 0 2px 6px rgba(0, 40, 85, 0.06);
  --shadow-e3: 0 8px 24px rgba(0, 40, 85, 0.12), 0 2px 8px rgba(0, 40, 85, 0.06);
  --shadow-e4: 0 24px 64px rgba(0, 40, 85, 0.22), 0 4px 16px rgba(0, 40, 85, 0.08);
  --shadow-focus: 0 0 0 3px rgba(0, 174, 217, 0.25);
}
```

### 5.4 Responsive Breakpoints & Grid Alignment
The viewport adapts across 4 standardized breakpoints.

| Breakpoint | Viewport Width | Sidebar Behavior | Card Grid Layout | Modal Behavior |
| :--- | :--- | :--- | :--- | :--- |
| **Mobile** | `375px` to `767px` | Hidden in off-canvas drawer | Single column (`1fr`) | Full-screen takeover (100vw, 100vh) |
| **Tablet** | `768px` to `1023px` | Collapsible `240px` rail | 2 columns (`minmax(260px, 1fr)`) | Center dialog (`90vw`, `85vh`) |
| **Desktop** | `1024px` to `1439px` | Sticky `280px` rail | 3 columns (`minmax(305px, 1fr)`) | Full dialog (`1100px` max-width) |
| **Wide** | `1440px` and above | Sticky `300px` rail | 3 to 4 columns (`minmax(320px, 1fr)`) | Full dialog with dual inspection split |

```css
/* Responsive Grid Media Queries */
@media (max-width: 767px) {
  .cv-layout {
    grid-template-columns: 1fr;
    padding: var(--space-3) var(--space-4) var(--space-6);
  }
  .cv-sidebar {
    display: none; /* Triggered via floating mobile filter pill */
  }
  .cv-grid {
    grid-template-columns: 1fr;
    gap: var(--space-4);
  }
}

@media (min-width: 768px) and (max-width: 1023px) {
  .cv-layout {
    grid-template-columns: 240px 1fr;
    gap: var(--space-4);
  }
  .cv-grid {
    grid-template-columns: repeat(auto-fill, minmax(260px, 1fr));
    gap: var(--space-4);
  }
}

@media (min-width: 1024px) {
  .cv-layout {
    grid-template-columns: 280px 1fr;
    gap: var(--space-5);
    max-width: 1480px;
    margin: 0 auto;
    padding: var(--space-5) var(--space-6);
  }
  .cv-grid {
    grid-template-columns: repeat(auto-fill, minmax(305px, 1fr));
    gap: var(--space-5);
  }
}

@media (min-width: 1440px) {
  .cv-layout {
    grid-template-columns: 300px 1fr;
  }
  .cv-grid {
    grid-template-columns: repeat(auto-fill, minmax(320px, 1fr));
    gap: var(--space-6);
  }
}
```

### 5.5 Motion & Accessibility Principles
- **Transitions**:
  - `80ms` (Instant feedback for checkbox / radio selections)
  - `160ms` (Quick hover states and button presses)
  - `240ms` (Workhorse card hover lift and modal dialog fades)
  - `400ms` (Deliberate drawer slideout animations)
- **Easing Curve**:
  - `--ease-smooth: cubic-bezier(0.16, 1, 0.3, 1)`.
- **Accessibility & Contrast**:
  - Body text (`--ink: #0E1A2F`) on canvas (`#F4F8FC`) provides a 16:1 contrast ratio, exceeding WCAG AAA standards.
  - Interactive elements enforce visible focus indicators (`--shadow-focus`).
- **Motion Reduction**:
  - Mandatory `@media (prefers-reduced-motion: reduce)` resets transitions and transforms to `0ms`.
