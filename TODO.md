# SolarIQ

## To Do List

1. Investigate whether battery use during peak savings is taking into account the cost of charging

2. Investigate the feasability of applying the TOU strategy directly to the inverter
    * HTTP API vs modbus
    * Look at HA plugins
    * modbus proxy
    * scheduling, the TOU needs to start at midnight`

3. If 2 is implemented, look at implementing a TOU manager
    * Create TOU
    * Edit TOU
    * Delete TOU
    * Apply TOU

4. On strategy page highlight non-considered slots or don't show them.

5. On strategy page, provide some way of dismissing errors.

6. Not entirely sure about time alignment of the solar forecast, it does not look right comparing with the website, see (https://toolkit.solcast.com.au/home-pv-system/96f5-db62-fe5d-dd53/detail)

7. Dashlane / Edge password manager injection causes React hydration error #418 on the login page.
   - Dashlane injects DOM nodes into password inputs before React hydrates, triggering a server/client mismatch.
   - CSS audit showed no stylesheet conflicts from our side.
   - `autocomplete` token hints were added via `custom_attrs` (Reflex does not support string `auto_complete`).
   - Attempts so far: autocomplete hints, `auth_ready=False` SSR guard (caused spinning regression, reverted).
   - Next steps to investigate: render login/bootstrap forms client-side only (post-mount flag), or use a Reflex `rx.client_side_only` wrapper if available in a future version.