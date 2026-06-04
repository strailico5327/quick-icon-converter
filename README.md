# Quick Icon Converter

A small Qt desktop tool for converting PNG or SVG files into size-specific Windows `.ico` files.

## Requirements

The interface and SVG rendering use PySide6. Image resizing and ICO output use Pillow.

```powershell
python -m pip install -r requirements.txt
```

## Usage

Run the app:

```powershell
python main.py
```

Add files by:

- dragging PNG/SVG files into the window
- pasting copied file paths with `Ctrl+V`
- clicking `Browse...` and selecting multiple files

Queue behaviour:

- The first column checkbox controls whether a file participates in conversion.
- The checkbox in the table header selects or clears every queue item.
- Highlight one or more rows with normal platform shortcuts such as Ctrl/Shift selection.
- The size checkboxes only affect highlighted rows, so each file can have its own size set.
- `All sizes` selects every size for the highlighted rows; when all are selected it changes to `Clear sizes`.

Output behaviour:

- By default, output files are saved next to each source file in `ico_converted`.
- Choosing an output folder sends every queue output to that folder instead.
- Output files are named with the size suffix, for example `logo_16x.ico` and `logo_256x.ico`.

Conversion controls:

- Click `Start` after adding and configuring the queue.
- During conversion, `Start` becomes `Pause`.
- While paused, `Clear queue` becomes `Cancel`; cancelling keeps the queue.
- When not converting, `Clear queue` removes all queue items.

## Smoke test

Check that the required Qt and PNG/ICO dependencies are available:

```powershell
python main.py --self-test
```

## Licence

This source code is licensed under GNU GPLv3. See [LICENSE](LICENSE).

## Notes

This project was developed with assistance from OpenAI Codex. The code has been reviewed and tested before release.