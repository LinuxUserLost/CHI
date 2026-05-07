# CHI

CHI is a low-dependency Python/Tkinter GUI shell for loading and organizing modular tool packs.

The project is built around a simple idea: keep the shell small, keep tools separated into folders, and let the GUI discover/load packs when it can find the correct manifest and page registry files.

This is a working prototype and portfolio checkpoint. It is not a finished application.

## Current Status

CHI is under active development.

The current version includes a GUI shell, page discovery, page loading, theme work, interaction helpers, Git workflow pages, Linux utility pages, AI/prompt pages, reading/TTS experiments, and hardware/device workflow drafts.

Many pages are usable drafts. Some pages include extra tabs for testing new workflow ideas or future features. Theme support is currently being updated so pages can work more consistently across the whole shell.

## Project Background

This is my first major program.

It began as a smaller Linux/Python workflow for AI chat capture, prompt presets, clipboard cleanup, terminal helpers, and local note organization. It later grew into a modular desktop GUI where separate tools can be loaded as page packs.

The repository history reflects the real development timeline, including breaks, lighter weeks, and checkpoint uploads.

## Design Goals

- Python-first
- low dependency
- local-first
- modular folders
- readable project structure
- easy checkpointing with Git
- tools that can be added, removed, or tested without rewriting the whole app
- useful on a normal Linux desktop, but organized with portable/mobile workflows in mind

## Why the Directory Structure Matters

CHI is organized around packs and pages because the shell is meant to load tools from folders instead of hardcoding every tool into one large file.

The GUI shell can load a pack when it can find the required discovery files, such as:

- `module_manifest.json`
- `pages.json`

The page registry tells the shell what page files and page classes exist. The loader then imports the page and tries the supported GUI mount methods.

This makes it possible to keep different tool areas separated, such as Linux tools, Git tools, AI tools, reading tools, theme tools, and hardware/device tools.

## Core Shell

The main shell entry point is:

```bash
python guichi.py
