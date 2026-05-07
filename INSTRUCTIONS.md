# CHI Instructions

This file is the practical companion to the main README.

It is not a full deployment guide. It is a short orientation note for running the current project locally and understanding its present limitations.

## What To Expect

CHI is a local Python/Tkinter GUI shell that discovers and loads tool packs from the repository folders.

It is still an in-progress project:

- some pages are more mature than others
- some packs are stronger than others
- layout and theme consistency are still being refined
- some pages include experimental or partially developed workflow ideas

## Environment

Current assumptions:

- Linux desktop environment
- Python 3
- Tkinter available in that Python environment

The project is low-dependency in spirit, but individual pages may still assume local tools, local files, or workstation-specific utilities depending on what that page is trying to control.

## Run

From the repository root:

```bash
python3 guichi.py
```

## How The Shell Loads Content

The shell discovers packs by reading folder-based metadata, primarily:

- `module_manifest.json`
- `pages.json`

Each pack can define one or more pages. The shell registry and loader then attempt to import the configured page classes and mount them through the supported GUI methods.

## Current Practical Caveats

- This is a prototype shell, not a packaged end-user application.
- Some modules are present mainly as useful drafts or experiments.
- Some workflow pages may reflect my local workstation habits more than a generalized user setup.
- Theme support and cross-page consistency are still being improved.
- The most representative current area is `chi_los`, which is closest to the present direction of the project.

## Suggested Reading Order

If you are evaluating the repo quickly:

1. read `README.md`
2. run `python3 guichi.py`
3. look at `chi_los` first
4. then inspect `chi_gui`, `chi_ain`, and `chitsheet`

If you want to understand the shell structure itself, start with:

- `guichi.py`
- `gui_files/shell_discovery.py`
- `gui_files/shell_loader.py`
- `gui_files/shell_gui.py`
