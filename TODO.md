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

4. Show solar forecast vs PV on historical graphs

5. On strategy page show soc as %

6. On strategy page highlight non-considered slots or don't show them.

7. On strategy page, provide some way of dismissing errors.

8. Not entirely sure about time alignment of the solar forecast, it does not look right comparing with the website, see (https://toolkit.solcast.com.au/home-pv-system/96f5-db62-fe5d-dd53/detail)