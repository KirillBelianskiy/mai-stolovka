# UI demonstration completion — 8 November 2026

The owner requested fixing the incomplete demonstration after finding missing menu photographs.
This delivery follows Penpot UI PR #57 and retains its palette, typography and supported flows.

## Corrections

- Six catalog dishes have local photographs. Original Penpot photographs cover buckwheat and
  syrniki; four additional illustrative demo photographs were generated with the built-in image
  tool. The complete optimized JPEG set is 528,903 bytes.
- `infra/demo-menu.json` is the single demonstration catalog. `infra/local_demo_menu.py` uses
  Menu's public APIs to create missing entries and repair missing/legacy photo URLs on existing
  entries. It reads every admin page, preserves custom image URLs and item fields, and repeated
  execution avoids additional category/item writes.
- The isolated launcher and Compose override are included for reproducibility. `.private` is
  excluded from Docker contexts. A partially completed setup resumes JWT generation when both
  keys are absent and reports an incomplete existing pair for explicit recovery.
- A shared `DishPhoto` component handles absent and failed images visibly. A replacement URL
  loads after an earlier failure. Menu, cart and dish dialog use the same behavior.
- Staff cancellation uses an accessible native HTML dialog with explicit keep/cancel actions,
  rather than a system confirm prompt. Versioned cancellation still uses the captured order.
- Staff queue responses are bound to the active token and latest request. Old success/401
  responses cannot reveal an old queue or log out a subsequent employee. The Admin callback
  observes the same session boundary. In-flight order actions ignore obsolete UI results and
  an immediate lock suppresses overlapping submissions before React updates disabled buttons.

## Reproduce

In a checkout of this branch with Docker Desktop running and Python/OpenSSL installed:

```sh
python3 infra/local-demo.py up --open
```

The isolated project is `mai-food-demo`, with customer/staff ports 8180/8181, PostgreSQL 5544,
and Kafka 9192. It generates local-only credentials and fake Telegram launch data, applies the
four owned migrations, provisions the development topic/workers and seeds synthetic data.
No real Telegram token is needed. A new launch URL is available through `login --open`.

After building the current frontend image, `python3 infra/local-demo.py seed` repairs photos in
the existing isolated menu. This also retains the previously documented demo balance top-up
and initial-order behavior. Use the photo-only Menu provisioning function for an audit that
must leave wallet/order fixtures untouched. The local correction used that photo-only path.

Credentials remain in ignored `.private/local-demo/access.json`. `status` inspects this project;
`down` stops it while preserving its volumes. The old project on 8080/8081 is separate.

## Verification

- Thirty Node domain/API tests and twenty-three DOM cases pass. New cases cover absent/broken
  photographs, replacing a failed URL, explicit/busy staff confirmation, two obsolete-admin
  response variants after cook login, and overlapping staff action submission.
- All twenty-seven contract/tool cases pass, including fresh/repeated menu provisioning,
  pagination, preserving an edited item/custom photo, bounded JPEG assets, and interrupted
  local key initialization.
- Both frontend typechecks/static builds and root Ruff checks pass. The existing Mini App DOM
  harness also executes the staff component regressions. Its Docker build stage copies the
  needed staff source; the runtime image remains a static Mini App export.
- In the isolated running demo, all six Menu API image URLs returned valid JPEGs, and all six
  rendered menu images loaded at 640 px natural width. Browser checks confirmed that keeping
  synthetic order MAI-000047 leaves it pending and explicit cancellation removes it from the
  queue. API checks then confirmed CANCELLED / DEMO_REFUNDED, the exact original wallet balance
  and release of the slot reservation. This used a separate synthetic customer; the owner's
  existing cart and demo balance were preserved.
- Full MVP release,
  Telegram dispatch, real Telegram/HTTPS, staff Kafka reconciliation and operational exercises
  remain tracked by their existing work items.
