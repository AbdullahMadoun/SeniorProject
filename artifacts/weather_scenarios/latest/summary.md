# Weather Gate Scenario Summary

- scenario count: `4`
- passed count: `4`

| Scenario | Passed | Effective Wind (m/s) | Launch | Mission Continue | Dock | Safety Action | Final Mode |
| --- | --- | --- | --- | --- | --- | --- | --- |
| nominal_weather_ready | yes | 4.5 | yes | yes | yes | continue | hold |
| gust_abort_launch | yes | 8.2 | no | no | no | abort_launch | hold |
| inflight_wind_excursion_rtl | yes | 8.0 | no | no | no | return_to_launch | return_to_launch |
| nominal_dock_weather_ready | yes | 5.0 | yes | yes | yes | continue | return_to_launch |
