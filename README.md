# Quick Icon Converter

Quick Icon Converter is a static H5 tool that converts PNG and SVG files into size-specific `.ico` or `.png` outputs in the browser.

## Usage

Open `index.html` directly in a modern browser, or deploy this directory to any static host. No server, Python runtime, or network access is required.

Supported source formats:

- PNG
- SVG

Supported output sizes:

- 16, 24, 32, 48, 64, 128, 180, 192, 256, and 512 pixels

Use the output mode toggle to choose PNG or ICO. Click `Start conversion` to generate outputs, then click `Download`. When one output is generated, the browser downloads that file directly. When multiple files or sizes are generated, the browser downloads `png_converted.zip` or `ico_converted.zip`. ZIP downloads group generated files into folders named after each source file.

Presets:

- `Desktop Mini`: ICO mode with 16, 24, 32, and 48 pixels.
- `Desktop Large`: PNG mode with 64, 128, 256, and 512 pixels.
- `Web Favicon`: PNG mode with 32, 128, 180, and 192 pixels.

## License

This project is licensed under GNU GPLv3. See [LICENSE](LICENSE).
