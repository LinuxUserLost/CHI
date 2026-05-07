# CHI

CHI is a Python/Tkinter GUI shell for organizing small tool packs into one desktop workspace.

The project started as a more manual Python control layer around CLI AI workflows, then grew into a modular shell as I learned more about GUI structure, local workflow design, and the hardware/runtime limits of different environments. Today its strongest area is Linux-side workflow control: terminal-oriented utilities, repeatable local tasks, and a shell structure that can load separate tool areas without folding everything into one file.

This is an active solo project and a working prototype, not a finished application.

## Current State

CHI already includes:

- a Tkinter shell with pack discovery, registry, and page loading
- modular pagepacks discovered through `module_manifest.json` and `pages.json`
- Linux workflow pages for terminal, network, audio, browser, and monitor-related utilities
- supporting tool areas for AI workflows, Git utilities, reading/TTS experiments, planning/log viewing, and hardware/device experiments
- shell-level theme and interaction work that is still being refined

The current code is usable in places, uneven in others, and still moving toward a more consistent layout and workflow feel across the whole shell.

## What CHI Is For

The main goal is to turn throwaway scripts and one-off workflow helpers into a reusable local platform.

Instead of keeping everything as separate experiments, CHI groups tools into packs and lets the shell discover and load them when the required manifest and page registry files are present. That keeps tool areas separated while still letting them live inside one interface.

The current project direction is practical rather than abstract:

- make local Linux tasks easier to repeat
- keep terminal-oriented workflows visible instead of hiding everything behind opaque automation
- preserve room for experiments without forcing the whole shell to be redesigned every time a new tool area appears

## Main Areas

### `chi_los`

The strongest current module. This pack is centered on Linux-side workflow control and includes pages related to terminal sessions, network control, audio routing, browser/bookmark utilities, and monitor management.

This area best represents the current direction of CHI: a GUI shell for reusing local system workflows while keeping the underlying command/task structure easier to inspect and grow over time.

### `chi_gui`

Shell-facing GUI support pages, currently focused on things like global page controls and theme organization. This area matters because the shell is usable now, but its visual consistency and overall layout are still being improved.

### `chi_ain`

AI-adjacent workflow pages, including prompt, markdown, terminal, and local model interface surfaces. This area reflects where the project started, but it is no longer the only identity of CHI.

### `chitsheet`

A newer support pack for viewing plans, logs, build-history material, and related project references from inside the shell. It is useful for the broader workflow idea behind CHI, but it is still early and less polished than the core shell/workflow surfaces.

### Secondary Areas

- `chi_git`: Git-oriented helper pages and workflow experiments
- `chi_reader`: reading and TTS experiments
- `chi_flippin0`: early hardware/device workflow pages related to Flipper Zero work
- `chiside_guide` and `chiside_jsondisplayer`: side windows that support shell navigation and inspection

These are real parts of the project, but they are not equally mature or equally central to the current direction.

## Structure

CHI keeps the shell small and uses folder-based discovery for packs and pages.

The shell looks for files such as:

- `module_manifest.json`
- `pages.json`

Those files tell the loader what a pack contains and which page classes should be imported. This keeps tool areas modular and makes it easier to add, remove, or revise packs without rewriting the whole shell entry point.

## In Progress

The current work is mostly about refinement rather than a ground-up rewrite:

- making the shell layout feel more intentional and consistent
- improving theme behavior across different pages
- tightening workflow pages so they feel less like isolated experiments and more like parts of one platform
- deciding which exploratory tools should stay lightweight and which should become more fully developed modules

## Running CHI

The current shell entry point is:

```bash
python3 guichi.py
```

CHI is currently designed around a local Linux Python environment with Tkinter available.

For practical run/setup notes, see [INSTRUCTIONS.md](/media/min/Claude/01_project_workshop/CHI_public_upload/INSTRUCTIONS.md:1).
