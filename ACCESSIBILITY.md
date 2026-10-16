# Accessibility Statement for DocScout

DocScout is committed to ensuring digital accessibility for all users, including compliance officers, financial analysts, auditors, and developers with disabilities. We continually improve the user experience for everyone and apply relevant accessibility standards.

---

## Conformance Status

DocScout aims to conform to the **Web Content Accessibility Guidelines (WCAG) 2.2 Level AA** standards across all user interfaces, interactive consoles, and public documentation.

---

## Accessibility Measures & Design Standards

We implement the following accessibility measures across DocScout:

### 1. Semantic HTML and Landmark Structure
- All web surfaces in the React console (`ui/src/App.tsx`) use semantic HTML5 elements (`<header>`, `<main>`, `<nav>`, `<section>`, `<footer>`) to ensure consistent document outline navigation.
- Headings follow a strict logical hierarchy (single `<h1>` per view, nested `<h2>` and `<h3>` tags).

### 2. Keyboard Navigation and Focus Management
- Every interactive element (search input, facet filters, citation links, playbook triggers, and tab selectors) is accessible via standard keyboard navigation (`Tab`, `Shift+Tab`, `Enter`, `Space`).
- Focus rings are visibly indicated with high-contrast outlines that meet the WCAG 2.4.11 focus appearance requirement.
- Modal dialogs and popups trap focus appropriately and can be dismissed using the `Escape` key.

### 3. Screen Reader Compatibility & ARIA Live Regions
- Asynchronous retrieval operations and search status changes employ ARIA live regions (`aria-live="polite"`, `role="status"`) to communicate search execution, progress, and result counts to screen reader users without interrupting flow.
- All iconography and decorative elements carry `aria-hidden="true"`, while meaningful visual indicators provide descriptive `aria-label` or visually hidden text.
- Accessible statutory definition tooltips (FEAT-007) are fully keyboard-navigable and programmatically linked using `aria-describedby`.

### 4. Color Contrast and Visual Presentation
- All text and interactive components maintain a color contrast ratio of at least 4.5:1 against their background for standard text, and 3.0:1 for large text and graphical user interface components.
- The interface does not convey regulatory status, risk levels, or validation outcomes through color alone. Text badges, explicit labels, and distinct shapes accompany all color cues.
- The console supports operating system preferences for light, dark, and high-contrast modes (`prefers-color-scheme`, `prefers-contrast`).

### 5. API and CLI Output Accessibility
- CLI tools and REST API responses provide structured, clean JSON or unformatted plain text.
- Output does not rely on ASCII art or color escape codes to convey essential compliance data.

---

## Supported Environments & Assistive Technologies

DocScout is tested for compatibility with:
- **Browsers:** Current versions of Google Chrome, Mozilla Firefox, Apple Safari, and Microsoft Edge.
- **Screen Readers:**
  - NVDA and JAWS on Windows.
  - VoiceOver on macOS and iOS.
  - Orca on Linux.
- **Alternative Input:** Standard keyboard-only navigation and speech recognition software.

---

## Known Limitations and Workarounds

While DocScout strives for comprehensive accessibility, external source constraints exist:
- **Scanned Historical Circulars:** Certain archival circulars and gazette annexures published by external regulatory bodies (RBI and SEBI) are legacy scanned raster PDFs lacking native PDF/UA tagging. DocScout mitigates this barrier by running deep OCR extraction pipelines, restoring text linearity, and surfacing clean, selectable, and screen-reader-accessible text blocks alongside source citations.

---

## Feedback and Barrier Reporting

We welcome your feedback on the accessibility of DocScout. If you encounter accessibility barriers, or need content in an alternative format, please let us know:

- **Email:** compliance-alerts@docscout.gov.in
- **GitHub Issues:** Open an issue on GitHub with the `accessibility` label.
- **Response Timeline:** We aim to respond to accessibility reports within 2 business days and provide an actionable remediation timeline.
