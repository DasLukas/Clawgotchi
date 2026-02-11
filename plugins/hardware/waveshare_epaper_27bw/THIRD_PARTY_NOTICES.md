# Third-Party Notices

This plugin targets the public Waveshare Python driver interface from the `waveshare-epaper` package (`epaper` module).

- Package: `waveshare-epaper`
- Upstream: https://pypi.org/project/waveshare-epaper/
- Use in this plugin: Runtime driver import and configuration for SPI bus/device and GPIO pins.
- Package: `gpiozero`
- Upstream: https://pypi.org/project/gpiozero/
- Use in this plugin: Indirect runtime dependency of the Waveshare `epaper` compatibility API.
- Package: `lgpio`
- Upstream: https://pypi.org/project/lgpio/
- Use in this plugin: Preferred gpiozero pin backend on Raspberry Pi for stable edge detection.

No upstream source files are copied into this repository.
