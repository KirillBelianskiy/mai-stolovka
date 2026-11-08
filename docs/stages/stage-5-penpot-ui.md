# Penpot UI implementation — 8 November 2026

The owner requested replacing the independently styled application with the connected Penpot
design. This visual implementation is based on integration PR #56 at `a9b693e`.

## Design sources

Read the live Penpot project through its MCP plugin. Use the current presentation groups,
excluding the explicitly archived screens and components.

| Reference | Penpot shape ID | Dimensions |
| --- | --- | --- |
| Visitor presentation | `fd331433-1f4b-80bd-8008-d9954e1c57db` | Eight mobile screens |
| Menu | `743010df-21c5-8099-8008-d4732bfae346` | 390 × 844 |
| Dish details | `743010df-21c5-8099-8008-d4732c10e9dc` | 390 × 844 |
| Cart | `fd331433-1f4b-80bd-8008-d9936aebab81` | 390 × 844 |
| Ready ticket | `fd331433-1f4b-80bd-8008-d9936aebac62` | 390 × 844 |
| Staff overview | `fd331433-1f4b-80bd-8008-d9932168b2b0` | 1024 × 768 |
| Original food image | `743010df-21c5-8099-8008-d4732bfae367` | Original PNG fill |

Read the `MAI Food v1.0` token set. Applied values include ivory `#F8F5EC`, navy `#102A56`,
action `#0057D9`, brand `#0271FF`, soft `#EAF1FD`, muted `#526279`, line `#C2CBD6`,
lime `#D6F36B`, and focus `#8A3FFC`. The source wing path is reproduced as an inline SVG.
Mobile gutters are 24px, controls 48px, cards 24px radius, and staff navigation 184px wide.

Manrope and IBM Plex Mono are vendored from Google Fonts with their OFL licenses. Local CSS
includes Cyrillic and Latin subsets and font weights. Builds and page rendering use local files.
Font sources are `https://fonts.googleapis.com/` and `https://github.com/google/fonts`.

## Implemented screens

- Visitor shell has the Penpot header, bottom navigation, separate menu/cart/history/profile views,
  search among loaded dishes, horizontal categories, photographic dish rows and native accessible
  dish-detail dialog. Missing API photos retain a neutral image area.
- Cart uses rounded item cards, quantities and a separated total. Existing authenticated wallet,
  price confirmation, uncertain-request recovery and cancellation remain connected to the API.
- Current order details use a navy boarding pass, monospace order number/time, server payment
  evidence and preparation progress. History and a selected ticket occupy separate screens.
  Order composition remains available in a disclosure below the pass.
- Staff has the navy navigation rail, white shift summary, selectable queue and inline working
  ticket with current composition, amount, payment evidence and permitted next action. Kitchen
  and pickup filters use existing role permissions. Admin forms retain their working API actions
  within the same palette and typography. Narrow layouts stack the workspace.
- Screen changes keep checkout mounted. Hidden account screens leave the accessibility tree;
  existing authentication-generation and account-cache isolation continue to apply.

## Product-data adaptations

The current API provides a single cafeteria without campus coordinates, opening hours, portion
weights, nutrients or accessibility instructions. The venue view identifies that cafeteria.
The application displays actual menu descriptions and image URLs. The original photograph is
available at `/design/food-buckwheat.png` for operator-configured menu data.

The approved payment mode uses the demonstration wallet. The payment surface explains that mode
and uses server evidence. Card/SBP/cash-provider controls from the prototype require their own
future product implementation. Staff account/navigation follows the roles the backend grants.

The local demo received one explicitly synthetic reference dish with the original photograph and
three new synthetic orders to show PENDING, PREPARING and READY. Existing cart data was preserved.

## Verification

- Thirty Node domain/API tests and sixteen React component tests pass. Two navigation regressions
  cover a signed Telegram launch hash and preserving mounted checkout state across screen changes.
- Both workspace typechecks and static builds pass with Node 22.22.2. Docker builds use the pinned
  project Node image. The initial host build used an incompatible Node in child processes and
  failed before the component cases ran. Explicit PATH selection resolved that environment issue.
- Live browser against the isolated demo verified menu/cart/history navigation, persistent session
  restore, own order/payment reads, selected-ticket view, staff login and selectable working card.
  The original design and rendered pages were visually inspected. Screenshots are local artifacts.
- No horizontal overflow was observed in the measured mobile menu or desktop ticket. Browser
  viewport overrides were used for comparison with the mobile and staff references.

Full Telegram webview/HTTPS acceptance and the remaining MVP event-delivery work continue under
their existing issues. Visual delivery does not close the complete stage or pilot acceptance.
